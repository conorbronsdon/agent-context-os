from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import uuid
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from adapters.hermes import live_conformance as live
from adapters.opencode.live_conformance import copy_tracked_fixture
from contextos.primitives import canonical_json


ROOT = Path(__file__).resolve().parents[1]

FAKE = r'''
import json, os, pathlib, subprocess, sys
root = pathlib.Path.cwd()
if '--version' in sys.argv:
    print('Hermes Agent v0.20.5 (fake build)' if os.environ.get('FAKE_HERMES_MODE') == 'wrong-version' else 'Hermes Agent v0.21.4 (fake build)')
    sys.exit(0)
prompt = sys.argv[sys.argv.index('-q') + 1]
manifest = json.loads((root / '.context-os-live-manifest.json').read_text())
canaries = manifest['canaries']
phase = next(name for name in ('setup', 'start', 'update', 'end') if '/' + name in prompt)
mode = os.environ.get('FAKE_HERMES_MODE', '')
if phase == 'start' and mode == 'mutate-start':
    (root / 'state' / 'current.md').write_text('changed')
if phase == 'end' and mode == 'mutate-sentinel':
    (root / 'unrelated-sentinel.txt').write_text('changed')
if phase == 'setup' and mode == 'memory':
    (root / 'MEMORY.md').write_text('native memory leak')
if phase == 'setup' and mode == 'mirror-memory':
    (root / 'identity' / 'memory-leak.md').write_text((pathlib.Path(os.environ['HERMES_HOME']) / 'memories' / 'MEMORY.md').read_text())
if phase in ('setup', 'update', 'end'):
    folder = root / '.context-os' / 'inputs'
    folder.mkdir(parents=True, exist_ok=True)
    payload = ({'files': {'identity/hermes-fixture.md': '# Synthetic fixture identity'}} if phase == 'setup'
               else {'progress': ['Synthetic checkpoint']} if phase == 'update'
               else {'what_happened': ['Synthetic close']})
    path = folder / (phase + '.json')
    path.write_text(json.dumps(payload))
    made = subprocess.run([sys.executable, '-m', 'contextos', 'propose', phase, '--input', str(path)], cwd=root, capture_output=True, text=True)
    if made.returncode:
        print(made.stderr, file=sys.stderr)
        sys.exit(2)
if mode == 'generic':
    print('I found the lifecycle instructions.')
else:
    values = [canaries[phase], canaries['context-' + phase]]
    if phase == 'setup':
        values.append(canaries['agents'])
    print(' '.join(values))
    if mode == 'echo-secret':
        print('token=' + os.environ.get('OPENROUTER_API_KEY', ''))
'''


class HermesLiveHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = ROOT / ".hermes-test-root" / uuid.uuid4().hex
        self.base.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.fixture = self.base / "fixture"
        source_sha = live.git(ROOT, "rev-parse", "HEAD")
        copy_tracked_fixture(ROOT, self.fixture, source_sha)
        self.home = self.base / "hermes-home"
        self.home.mkdir()
        (self.home / "memories").mkdir()
        memory_canaries = {"MEMORY.md": "unique-native-memory-canary", "USER.md": "unique-native-user-canary"}
        for name, marker in memory_canaries.items():
            (self.home / "memories" / name).write_text(f"Fixture native memory canary: {marker}\n", encoding="utf-8")
        self.evidence = self.base / "evidence.json"
        self.fake = self.base / "fake_hermes.py"
        self.fake.write_text(FAKE, encoding="utf-8")
        (self.fixture / live.MARKER).write_text("disposable\n", encoding="utf-8")
        (self.fixture / "unrelated-sentinel.txt").write_bytes(b"sentinel")
        canaries = {name: f"unique-{name}-canary" for name in ("agents", *live.SKILLS)}
        digests = {}
        for name in live.SKILLS:
            path = self.fixture / ".agents/skills" / name / "SKILL.md"
            digests[name] = live.sha(path)
            path.write_bytes(path.read_bytes() + f"\nHermes fixture canary: {canaries[name]}\n".encode())
        (self.fixture / "AGENTS.md").write_bytes((self.fixture / "AGENTS.md").read_bytes() +
                                                  f"\nHermes fixture canary: {canaries['agents']}\n".encode())
        manifest = {"source_sha": source_sha,
                    "fixture_commit": source_sha,
                    "skill_source_sha256": digests, "canaries": canaries,
                    "prompts": {phase: live.prompt_for(phase) for phase in live.PHASES},
                    "native_memory_canaries": memory_canaries}
        (self.fixture / ".context-os-live-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_prepare_records_source_and_all_eight_skill_digests(self) -> None:
        source_sha = live.git(ROOT, "rev-parse", "HEAD")
        new_fixture, new_home = self.base / "prepared", self.base / "prepared-home"
        def clean_git(cwd, *args):
            return "" if args[:1] == ("status",) else source_sha
        def clone(argv, cwd, env=None, timeout=120):
            copy_tracked_fixture(ROOT, new_fixture, source_sha)
            return {"exit_code": 0}
        with mock.patch.object(live, "git", side_effect=clean_git), mock.patch.object(live, "command", side_effect=clone), mock.patch.object(live, "outside_checkouts"):
            prepared = live.prepare(ROOT, new_fixture, new_home, source_sha)
        manifest = prepared["manifest"]
        self.assertEqual(source_sha, manifest["source_sha"])
        self.assertEqual(set(live.SKILLS), set(manifest["skill_source_sha256"]))
        self.assertEqual(set(live.PHASES), set(manifest["prompts"]))
        self.assertTrue(new_home.is_dir())

    def test_prepare_rejects_checkout_path(self) -> None:
        with self.assertRaisesRegex(live.HarnessError, "separate, non-nested"):
            live.outside_checkouts(ROOT / "fixture", ROOT)

    def test_status_warning_cannot_prove_clean_source(self) -> None:
        fake = subprocess.CompletedProcess(["git", "status"], 0, "", "warning: unreadable")
        with mock.patch.object(live.subprocess, "run", return_value=fake):
            with self.assertRaisesRegex(live.HarnessError, "unreadable paths"):
                live.git(ROOT, "status", "--porcelain")

    def test_prepare_rejects_wrong_source_commit(self) -> None:
        with mock.patch.object(live, "outside_checkouts"):
            with self.assertRaisesRegex(live.HarnessError, "exact expected HEAD"):
                live.prepare(ROOT, self.base / "wrong-fixture", self.base / "wrong-home", "0" * 40)

    def test_proposal_rejects_duplicate_json_key(self) -> None:
        import hashlib
        folder = self.fixture / ".context-os/proposals"
        folder.mkdir(parents=True)
        document = {"workflow": "update", "changes": [{"path": "state/current.md", "diff": "reviewed"}]}
        document["proposal_digest"] = hashlib.sha256(canonical_json(document).encode()).hexdigest()
        raw = json.dumps(document).replace('"workflow": "update"', '"workflow": "update", "workflow": "update"')
        (folder / "duplicate.json").write_text(raw, encoding="utf-8")
        with self.assertRaises(ValueError):
            live.new_proposal(self.fixture, set(), "update")

    def run_record(self, mode: str = "", input_fn=None) -> dict:
        original_command = live.command
        def kernel_command(argv, cwd, env=None, timeout=120):
            if mode == "accept-wrong" and argv[:2] == ["bash", "scripts/contextos.sh"] and "0" * 64 in argv:
                return {"argv": list(argv), "exit_code": 0, "stdout": "accepted", "stderr": "", "duration_seconds": 0, "at": live.now()}
            if mode == "no-receipt" and argv[:2] == ["bash", "scripts/contextos.sh"] and "apply" in argv and "0" * 64 not in argv:
                return {"argv": list(argv), "exit_code": 0, "stdout": "accepted", "stderr": "", "duration_seconds": 0, "at": live.now()}
            if argv[:2] == ["bash", "scripts/contextos.sh"]:
                return original_command([sys.executable, "-m", "contextos", *argv[2:]], cwd, env, timeout)
            return original_command(argv, cwd, env, timeout)
        def fixture_git(cwd, *args):
            if args == ("rev-parse", "HEAD"):
                return json.loads((self.fixture / ".context-os-live-manifest.json").read_text())["source_sha"]
            if args[:1] == ("status",):
                return ""
            return live.git(cwd, *args)
        with mock.patch.dict(os.environ, {"FAKE_HERMES_MODE": mode}), mock.patch.object(live, "git", side_effect=fixture_git), mock.patch.object(live, "command", side_effect=kernel_command), mock.patch.object(live, "outside_checkouts"):
            with contextlib.redirect_stdout(io.StringIO()):
                return live.record(self.fixture, self.home, self.evidence,
                                   [sys.executable, str(self.fake)], "fake/free", "fake", 30, 10,
                                   input_fn=input_fn or (lambda prompt: prompt.split("digest ")[1].split()[0]),
                                   expected_version="Hermes Agent v0.21.4")

    def test_generic_text_fails_canary(self) -> None:
        report = self.run_record("generic")
        self.assertEqual("failed", report["controls"]["run"])
        self.assertIn("canary", report["failure"])

    def test_start_mutation_detected(self) -> None:
        report = self.run_record("mutate-start")
        self.assertEqual("failed", report["controls"]["run"])
        self.assertIn("start changed", report["failure"])

    def test_unrelated_sentinel_mutation_detected(self) -> None:
        report = self.run_record("mutate-sentinel")
        self.assertEqual("failed", report["controls"]["unrelated_sentinel"])
        self.assertIn("sentinel changed", report["failure"])

    def test_operator_must_type_exact_digest(self) -> None:
        report = self.run_record(input_fn=lambda prompt: "wrong")
        self.assertEqual("failed", report["controls"]["setup_proposal_apply"])
        self.assertIn("operator did not type", report["failure"])

    def test_proposal_change_after_review_rejected(self) -> None:
        def alter(prompt):
            proposal = next((self.fixture / ".context-os/proposals").glob("*.json"))
            proposal.write_bytes(proposal.read_bytes() + b" ")
            return prompt.split("digest ")[1].split()[0]
        report = self.run_record(input_fn=alter)
        self.assertEqual("failed", report["controls"]["setup_proposal_apply"])
        self.assertIn("changed after review", report["failure"])

    def test_apply_requires_receipt(self) -> None:
        report = self.run_record("no-receipt")
        self.assertEqual("failed", report["controls"]["setup_proposal_apply"])
        self.assertIn("did not issue exactly one receipt", report["failure"])

    def test_memory_file_creation_detected(self) -> None:
        report = self.run_record("memory")
        self.assertEqual("failed", report["controls"]["run"])
        self.assertIn("native MEMORY.md", report["failure"])

    def test_native_memory_mirror_detected(self) -> None:
        report = self.run_record("mirror-memory")
        self.assertEqual("failed", report["controls"]["memory_separation"])
        self.assertIn("native memory canary", report["failure"])

    def test_wrong_digest_rejected_and_receipt_bound(self) -> None:
        report = self.run_record()
        self.assertEqual("passed", report["controls"]["run"], report.get("failure"))
        self.assertEqual("passed", report["controls"]["stale_digest_rejected"])
        self.assertEqual("passed", report["controls"]["update_proposal_apply"])
        self.assertEqual("passed", report["controls"]["end_proposal_apply"])
        self.assertEqual("passed", report["controls"]["memory_separation"])
        self.assertEqual("unsupported", report["controls"]["hook_example"])

    def test_stale_digest_guard_must_fire(self) -> None:
        report = self.run_record("accept-wrong")
        self.assertEqual("failed", report["controls"]["run"])
        self.assertIn("did not reject stale digest", report["failure"])

    def test_version_mismatch_fails(self) -> None:
        report = self.run_record("wrong-version")
        self.assertEqual("failed", report["controls"]["run"])
        self.assertIn("version was not verified", report["failure"])

    def test_evidence_refuses_overwrite(self) -> None:
        self.evidence.write_text("original", encoding="utf-8")
        with self.assertRaisesRegex(live.HarnessError, "evidence must be new"):
            self.run_record()
        self.assertEqual("original", self.evidence.read_text(encoding="utf-8"))

    def test_skill_revision_drift_rejected(self) -> None:
        skill = self.fixture / ".agents/skills/start/SKILL.md"
        skill.write_bytes(skill.read_bytes().replace(b"Read and follow", b"Ignore and follow"))
        with self.assertRaisesRegex(live.HarnessError, "skill drift"):
            self.run_record()

    def test_partial_skill_manifest_rejected(self) -> None:
        path = self.fixture / ".context-os-live-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        del manifest["skill_source_sha256"]["context-end"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(live.HarnessError, "incomplete"):
            self.run_record()

    def test_credentials_never_written(self) -> None:
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-secret-token-123", "FAKE_HERMES_MODE": "generic"}):
            self.run_record("generic")
        self.assertNotIn("test-secret-token-123", self.evidence.read_text(encoding="utf-8"))
        self.assertFalse(any("test-secret-token-123" in p.read_text(encoding="utf-8", errors="ignore")
                             for p in self.fixture.rglob("*") if p.is_file() and ".git" not in p.parts))

    def test_output_token_redacted(self) -> None:
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-secret-token-123"}):
            self.run_record("echo-secret")
        self.assertNotIn("test-secret-token-123", self.evidence.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
