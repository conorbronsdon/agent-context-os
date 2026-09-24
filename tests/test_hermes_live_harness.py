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
phase = next(name for name in ('setup', 'start', 'update', 'end') if prompt.startswith('/context-' + name))
mode = os.environ.get('FAKE_HERMES_MODE', '')
if sys.argv[sys.argv.index('--format') + 1] != 'stream-json':
    sys.exit(3)
def emit(event):
    print(json.dumps(event))
emit({'type': 'tool_use', 'id': 'skill-1', 'name': 'skill_view', 'input': {'name': 'context-' + phase}})
emit({'type': 'tool_result', 'id': 'skill-1', 'name': 'skill_view', 'content': 'loaded'})
if mode == 'invalid-stream-env':
    print('FIXTURE_PRIVATE=veryprivate')
    sys.exit(0)
if mode in ('self-read-agents', 'self-read-skill', 'self-read-terminal', 'self-read-search'):
    target = 'AGENTS.md' if mode == 'self-read-agents' else '.agents/skills/context-' + phase + '/SKILL.md'
    tool = 'terminal' if mode == 'self-read-terminal' else 'search_files' if mode == 'self-read-search' else 'read_file'
    emit({'type': 'tool_use', 'name': tool,
          'input': {'command' if tool == 'terminal' else 'path': target}})
if phase == 'start' and mode == 'mutate-start':
    (root / 'state' / 'current.md').write_text('changed')
if phase == 'setup' and mode == 'premature-apply':
    (root / 'state' / 'current.md').write_text('changed before approval')
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
    emit({'type': 'assistant', 'content': 'I found the lifecycle instructions.'})
else:
    values = [canaries['agents'], canaries['context-' + phase]]
    if mode == 'omit-agents':
        values = values[1:]
    if mode == 'asks-approval':
        values.append('Please approve the kernel proposal.')
    if mode == 'tool-result-canaries':
        emit({'type': 'tool_result', 'content': ' '.join(values)})
        values = ['No canaries in assistant text.']
    emit({'type': 'assistant', 'content': ' '.join(values)})
    if mode == 'echo-secret':
        emit({'type': 'assistant', 'content': 'token=' + os.environ.get('OPENROUTER_API_KEY', '')})
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
        memory_canaries = {name: uuid.uuid4().hex for name in ("MEMORY.md", "USER.md")}
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

    def test_cli_accepts_approval_dir(self) -> None:
        approval_dir = self.base / "approval-cli"
        with mock.patch.object(live, "record", return_value={"controls": {"run": "passed"}}) as record:
            with contextlib.redirect_stdout(io.StringIO()):
                code = live.main(["record", "--fixture", "fixture", "--home", "home",
                                  "--evidence", "evidence", "--binary", "hermes",
                                  "--model", "model", "--provider", "provider",
                                  "--expected-version", "Hermes Agent v0.21.4",
                                  "--approval-dir", str(approval_dir)])
        self.assertEqual(0, code)
        self.assertEqual(approval_dir, record.call_args.kwargs["approval_dir"])

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

    def run_record(self, mode: str = "", input_fn=None, approval_dir=None,
                   approval_timeout=900) -> dict:
        original_command = live.command
        def kernel_command(argv, cwd, env=None, timeout=120, raw_output=False):
            if mode == "accept-wrong" and argv[:2] == ["bash", "scripts/contextos.sh"] and "0" * 64 in argv:
                return {"argv": list(argv), "exit_code": 0, "stdout": "accepted", "stderr": "", "duration_seconds": 0, "at": live.now()}
            if mode == "no-receipt" and argv[:2] == ["bash", "scripts/contextos.sh"] and "apply" in argv and "0" * 64 not in argv:
                return {"argv": list(argv), "exit_code": 0, "stdout": "accepted", "stderr": "", "duration_seconds": 0, "at": live.now()}
            if argv[:2] == ["bash", "scripts/contextos.sh"]:
                result = original_command([sys.executable, "-m", "contextos", *argv[2:]], cwd, env, timeout)
                if mode == "mutate-sentinel" and "-end-" in argv[3] and "0" * 64 not in argv:
                    (self.fixture / "unrelated-sentinel.txt").write_text("changed", encoding="utf-8")
                return result
            return original_command(argv, cwd, env, timeout, raw_output=raw_output)
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
                                   expected_version="Hermes Agent v0.21.4",
                                   approval_dir=approval_dir, approval_timeout=approval_timeout)

    def test_generic_text_fails_canary(self) -> None:
        report = self.run_record("generic")
        self.assertEqual("failed", report["controls"]["run"])
        self.assertIn("canary not reported", report["failure"])

    def test_prompts_are_bare_commands_without_file_names(self) -> None:
        for phase in live.PHASES:
            prompt = live.prompt_for(phase)
            self.assertTrue(prompt.startswith(f"/context-{phase}"))
            self.assertNotIn("AGENTS.md", prompt)
            self.assertNotIn("SKILL.md", prompt)
            self.assertNotIn(".agents/skills", prompt)

    def test_self_read_blocks_discovery(self) -> None:
        for mode in ("self-read-agents", "self-read-skill", "self-read-terminal", "self-read-search"):
            with self.subTest(mode=mode):
                self.evidence.unlink(missing_ok=True)
                report = self.run_record(mode)
                self.assertEqual("failed", report["controls"]["setup_discovery"])
                self.assertEqual("self-read: discovery not shown", report["failure"])
                self.assertEqual(["context-setup"], report["commands"][1]["skill_view_names"])

    def test_only_assistant_canaries_count(self) -> None:
        report = self.run_record("tool-result-canaries")
        self.assertEqual("failed", report["controls"]["setup_discovery"])
        self.assertIn("canary not reported", report["failure"])

    def test_agents_canary_required(self) -> None:
        report = self.run_record("omit-agents")
        self.assertEqual("failed", report["controls"]["setup_discovery"])
        self.assertEqual("canary not reported: agents", report["failure"])

    def test_approval_dir_exact_digest_passes(self) -> None:
        approval_dir = self.base / "approval"
        approval_dir.mkdir()
        def approve(_seconds):
            for review in approval_dir.glob("*.review.txt"):
                approve_path = review.with_name(review.name.replace(".review.txt", ".approve"))
                if not approve_path.exists():
                    digest = review.read_text(encoding="utf-8").split("Digest: ")[1].splitlines()[0]
                    approve_path.write_text(digest, encoding="utf-8")
        with mock.patch.object(live.time, "sleep", side_effect=approve):
            report = self.run_record(approval_dir=approval_dir)
        self.assertEqual("passed", report["controls"]["run"], report.get("failure"))
        self.assertEqual("approval-dir", report["operator_mode"])
        review = (approval_dir / "setup.review.txt").read_text(encoding="utf-8")
        self.assertIn("Proposal: .context-os/proposals/", review.replace("\\", "/"))
        self.assertIn("Digest: ", review)
        self.assertIn("# Synthetic fixture identity", review)

    def test_approval_dir_wrong_digest_fails(self) -> None:
        approval_dir = self.base / "approval"
        approval_dir.mkdir()
        def deny(_seconds):
            (approval_dir / "setup.approve").write_text("wrong", encoding="utf-8")
        with mock.patch.object(live.time, "sleep", side_effect=deny):
            report = self.run_record(approval_dir=approval_dir)
        self.assertEqual("failed", report["controls"]["setup_proposal_apply"])
        self.assertIn("exact proposal digest", report["failure"])

    def test_approval_digest_guard_direct(self) -> None:
        approval_dir = self.base / "approval-direct"
        approval_dir.mkdir()
        proposal = {"changes": [{"path": "state/current.md", "diff": "reviewed"}]}
        def deny(_seconds):
            (approval_dir / "setup.approve").write_text("wrong", encoding="utf-8")
        with mock.patch.object(live.time, "sleep", side_effect=deny):
            with self.assertRaisesRegex(live.HarnessError, "exact proposal digest"):
                live.operator_approval("setup", Path("proposal.json"), proposal, "a" * 64,
                                       None, approval_dir, timeout=3)

    def test_approval_dir_timeout_fails(self) -> None:
        approval_dir = self.base / "approval"
        approval_dir.mkdir()
        report = self.run_record(approval_dir=approval_dir, approval_timeout=0)
        self.assertEqual("failed", report["controls"]["setup_proposal_apply"])
        self.assertIn("timed out", report["failure"])

    def test_approval_dir_cannot_be_inside_hermes_home(self) -> None:
        approval_dir = self.home / "approval"
        approval_dir.mkdir()
        with self.assertRaisesRegex(live.HarnessError, "separate from HERMES_HOME"):
            self.run_record(approval_dir=approval_dir, approval_timeout=0)

    def test_approval_timeout_guard_direct(self) -> None:
        approval_dir = self.base / "approval-direct"
        approval_dir.mkdir()
        proposal = {"changes": [{"path": "state/current.md", "diff": "reviewed"}]}
        with self.assertRaisesRegex(live.HarnessError, "timed out"):
            live.operator_approval("setup", Path("proposal.json"), proposal, "a" * 64,
                                   None, approval_dir, timeout=0)

    def test_redaction_covers_token_shapes(self) -> None:
        secrets = ("sk-or-abcdefghijklmnop", "sk-abc", "Bearer abc",
                   "a" * 64, "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/==")
        for secret in secrets:
            self.assertNotIn(secret, live.clean(secret))
        self.assertNotIn("FIXTURE_VAR", live.clean("FIXTURE_VAR=fixture-value"))
        self.assertNotIn("fixture-value", live.clean("FIXTURE_VAR=fixture-value"))
        self.assertIn("b" * 64, live.clean("b" * 64, ("b" * 64,)))

    def test_tool_results_do_not_record_environment(self) -> None:
        raw = json.dumps({"type": "tool_result", "content": "FIXTURE_VAR=fixture-value"})
        events, assistant, skills, self_read = live.stream_evidence(raw, ())
        self.assertEqual("[REDACTED TOOL RESULT]", events[0]["content"])
        self.assertEqual("", assistant)
        self.assertEqual([], skills)
        self.assertFalse(self_read)

    def test_skill_view_name_is_redacted(self) -> None:
        raw = json.dumps({"type": "tool_use", "name": "skill_view", "input": {"name": "sk-abc"}})
        events, assistant, skills, self_read = live.stream_evidence(raw, ())
        self.assertEqual(["[REDACTED]"], skills)
        self.assertEqual("[REDACTED]", events[0]["input"]["name"])

    def test_invalid_stream_does_not_record_raw_output(self) -> None:
        report = self.run_record("invalid-stream-env")
        self.assertEqual("failed", report["controls"]["setup_discovery"])
        evidence = self.evidence.read_text(encoding="utf-8")
        self.assertNotIn("FIXTURE_PRIVATE", evidence)
        self.assertNotIn("veryprivate", evidence)

    def test_start_mutation_detected(self) -> None:
        report = self.run_record("mutate-start")
        self.assertEqual("failed", report["controls"]["run"])
        self.assertIn("start changed", report["failure"])

    def test_model_cannot_change_files_before_apply(self) -> None:
        report = self.run_record("premature-apply")
        self.assertEqual("failed", report["controls"]["setup_proposal_apply"])
        self.assertIn("before operator apply", report["failure"])

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
        self.assertEqual("Hermes Agent v0.21.4 (fake build)", report["version"])
        self.assertTrue(report["os"])
        self.assertTrue(report["fresh_hermes_home"])
        self.assertEqual("interactive", report["operator_mode"])
        self.assertIn("skill_view", [event.get("name") for event in report["commands"][1]["events"]])
        self.assertEqual(["context-setup"], report["commands"][1]["skill_view_names"])
        self.assertTrue(report["commands"][1]["argv"][-1].startswith("/context-setup"))
        self.assertEqual("passed", report["controls"]["stale_digest_rejected"])
        self.assertEqual("passed", report["controls"]["update_proposal_apply"])
        self.assertEqual("passed", report["controls"]["end_proposal_apply"])
        self.assertEqual("passed", report["controls"]["memory_separation"])
        self.assertEqual("unsupported", report["controls"]["hook_example"])

    def test_model_can_ask_approval_after_one_proposal(self) -> None:
        report = self.run_record("asks-approval")
        self.assertEqual("passed", report["controls"]["run"], report.get("failure"))

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
        secret = "test-secret-" + uuid.uuid4().hex
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": secret, "FAKE_HERMES_MODE": "generic"}):
            self.run_record("generic")
        self.assertNotIn(secret, self.evidence.read_text(encoding="utf-8"))
        leaked = [p.relative_to(self.fixture).as_posix() for p in self.fixture.rglob("*")
                  if p.is_file() and ".git" not in p.parts
                  and secret in p.read_text(encoding="utf-8", errors="ignore")]
        self.assertFalse(leaked, leaked)

    def test_output_token_redacted(self) -> None:
        secret = "test-secret-" + uuid.uuid4().hex
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": secret}):
            self.run_record("echo-secret")
        self.assertNotIn(secret, self.evidence.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
