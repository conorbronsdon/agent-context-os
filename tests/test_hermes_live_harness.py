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
import hashlib, json, os, pathlib, subprocess, sys
root = pathlib.Path.cwd()
if '--version' in sys.argv:
    print('Hermes Agent v0.20.5 (fake build)' if os.environ.get('FAKE_HERMES_MODE') == 'wrong-version' else 'Hermes Agent v0.21.4 (fake build)')
    sys.exit(0)
prompt = sys.argv[sys.argv.index('-q') + 1]
manifest = json.loads(pathlib.Path(os.environ['HERMES_LIVE_MANIFEST']).read_text())
canaries = manifest['canaries']
phase = next(name for name in ('setup', 'start', 'update', 'end') if prompt.startswith('/context-' + name))
mode = os.environ.get('FAKE_HERMES_MODE', '')
if sys.argv[sys.argv.index('--format') + 1] != 'stream-json':
    sys.exit(3)
def emit(event):
    print(json.dumps(event))
emit({'type': 'tool_use', 'id': 'skill-1', 'name': 'skill_view', 'input': {'name': 'context-' + phase}})
skill = (root / '.agents' / 'skills' / ('context-' + phase) / 'SKILL.md').read_text()
if mode == 'skill-view-other-phase':
    skill += (root / '.agents' / 'skills' / 'context-start' / 'SKILL.md').read_text()
if mode == 'skill-view-native-memory':
    skill += (pathlib.Path(os.environ['HERMES_HOME']) / 'memories' / 'USER.md').read_text()
emit({'type': 'tool_result', 'id': 'skill-1', 'name': 'skill_view', 'output': skill})
if mode == 'write-agents-word':
    emit({'type': 'tool_use', 'name': 'write_file', 'input': {'path': 'identity/hermes-fixture.md',
          'content': 'The agents loaded .agents/skills/context-setup/SKILL.md'}})
if mode == 'cat-agents':
    emit({'type': 'tool_use', 'name': 'terminal', 'input': {'command': 'cat AGENTS.md'}})
if mode == 'invalid-stream-env':
    print('FIXTURE_PRIVATE=veryprivate')
    sys.exit(0)
if mode in ('self-read-agents', 'self-read-skill', 'self-read-terminal', 'self-read-search'):
    target = 'AGENTS.md' if mode == 'self-read-agents' else '.agents/skills/context-' + phase + '/SKILL.md'
    tool = 'terminal' if mode == 'self-read-terminal' else 'search_files' if mode == 'self-read-search' else 'read_file'
    emit({'type': 'tool_use', 'name': tool,
          'input': {'command' if tool == 'terminal' else 'path': target}})
if mode.startswith('evasion-'):
    attacks = {'grep': 'grep -rn "Hermes fixture canary:" .', 'manifest': 'cat .context-os-live-manifest.json',
               'diff': 'git diff', 'skill-glob': 'cat .agents/skills/context-setup/*',
               'agents-glob': 'cat AGENT*', 'show': 'git show', 'log': 'git log -p',
               'rg': 'rg "Hermes fixture canary:"', 'findstr': 'findstr "Hermes fixture canary:"',
               'select-string': 'Select-String "Hermes fixture canary:"'}
    emit({'type': 'tool_use', 'name': 'execute_code' if mode == 'evasion-execute-code' else 'terminal',
          'input': {'code' if mode == 'evasion-execute-code' else 'command':
                    'cat AGENT*' if mode == 'evasion-execute-code' else attacks[mode[8:]]}})
if mode == 'result-leak':
    emit({'type': 'tool_result', 'content': canaries['agents']})
if phase == 'start' and mode == 'mutate-kernel':
    (root / '.context-os' / 'hosts.json').write_text('changed')
if mode == 'mutate-native-memory':
    (pathlib.Path(os.environ['HERMES_HOME']) / 'memories' / 'USER.md').write_text('changed')
if mode == 'add-native-memory':
    (pathlib.Path(os.environ['HERMES_HOME']) / 'memories' / 'extra.md').write_text('added')
if mode == 'remove-native-memory':
    (pathlib.Path(os.environ['HERMES_HOME']) / 'memories' / 'USER.md').unlink()
if phase == 'start' and mode == 'mutate-start':
    (root / 'state' / 'current.md').write_text('changed')
if phase == 'setup' and mode == 'premature-apply':
    (root / 'state' / 'current.md').write_text('changed before approval')
if phase == 'setup' and mode == 'memory':
    (root / 'MEMORY.md').write_text('native memory leak')
if phase == 'setup' and mode == 'mirror-memory':
    (root / 'identity' / 'memory-leak.md').write_text((pathlib.Path(os.environ['HERMES_HOME']) / 'memories' / 'MEMORY.md').read_text())
if phase == 'setup' and mode == 'mirror-kernel':
    (root / '.context-os').mkdir(exist_ok=True)
    (root / '.context-os' / 'memory-leak.txt').write_text((pathlib.Path(os.environ['HERMES_HOME']) / 'memories' / 'MEMORY.md').read_text())
if phase in ('setup', 'update', 'end'):
    folder = root / '.context-os' / 'inputs'
    folder.mkdir(parents=True, exist_ok=True)
    payload = ({'files': {'identity/hermes-fixture.md': '# Synthetic fixture identity'}} if phase == 'setup'
               else {'progress': ['Synthetic checkpoint']} if phase == 'update'
               else {'what_happened': ['Synthetic close']})
    if phase == 'setup' and mode == 'propose-memory':
        memory = (pathlib.Path(os.environ['HERMES_HOME']) / 'memories' / 'USER.md').read_text()
        payload = {'files': {'identity/hermes-fixture.md': '# Synthetic fixture identity\n' + memory}}
    if phase == 'setup' and mode in ('propose-memory-obfuscated', 'propose-memory-punctuated'):
        marker = manifest['native_memory_canaries']['USER.md'].upper()
        separator = ' _:\n' if mode == 'propose-memory-punctuated' else ' -\n'
        payload = {'files': {'identity/hermes-fixture.md': '# Synthetic fixture identity\n' + separator.join(marker[i:i+4] for i in range(0, len(marker), 4))}}
    path = folder / (phase + '.json')
    path.write_text(json.dumps(payload))
    made = subprocess.run([sys.executable, '-m', 'contextos', 'propose', phase, '--input', str(path)], cwd=root, capture_output=True, text=True)
    if made.returncode:
        print(made.stderr, file=sys.stderr)
        sys.exit(2)
    if phase == 'setup' and mode == 'bad-diff':
        sys.path.insert(0, str(root))
        from contextos.primitives import canonical_json
        proposal = next((root / '.context-os' / 'proposals').glob('*.json'))
        document = json.loads(proposal.read_text())
        document['changes'][0]['diff'] = ['invalid']
        document.pop('proposal_digest')
        document['proposal_digest'] = hashlib.sha256(canonical_json(document).encode()).hexdigest()
        proposal.write_text(json.dumps(document))
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
    text = ' '.join(values)
    # Real Hermes stream-json sends small text deltas that can split a token, then a result event.
    for start in range(0, len(text), 7):
        emit({'type': 'text', 'text': text[start:start + 7]})
    emit({'type': 'result', 'exit_code': 0, 'text': text})
    if mode == 'echo-secret':
        emit({'type': 'tool_result', 'content': 'token=' + os.environ.get('OPENROUTER_API_KEY', '')})
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
        self.manifest_path = self.base / "fixture-manifest.json"
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
        subprocess.run(["git", "init", "--quiet"], cwd=self.fixture, check=True)
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=self.fixture, check=True)
        subprocess.run(["git", "-c", "core.autocrlf=false", "add", "--", "AGENTS.md", *(f".agents/skills/{name}/SKILL.md" for name in live.SKILLS)], cwd=self.fixture, check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "commit", "--quiet", "-m", "Fixture canaries"], cwd=self.fixture, check=True)
        fixture_commit = live.git(self.fixture, "rev-parse", "HEAD")
        manifest = {"source_sha": source_sha,
                    "fixture_commit": fixture_commit,
                    "skill_source_sha256": digests, "canaries": canaries,
                    "prompts": {phase: live.prompt_for(phase) for phase in live.PHASES},
                    "native_memory_canaries": memory_canaries}
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_prepare_records_source_and_all_eight_skill_digests(self) -> None:
        source_sha = live.git(ROOT, "rev-parse", "HEAD")
        new_fixture, new_home = self.base / "prepared", self.base / "prepared-home"
        real_git = live.git
        def clean_git(cwd, *args):
            if cwd == ROOT and args[:1] == ("status",):
                return ""
            if cwd == new_fixture and args == ("rev-parse", "HEAD"):
                try:
                    return real_git(cwd, *args)
                except live.HarnessError:
                    return source_sha
            return real_git(cwd, *args)
        def clone(argv, cwd, env=None, timeout=120, raw_output=False):
            copy_tracked_fixture(ROOT, new_fixture, source_sha)
            subprocess.run(["git", "init", "--quiet"], cwd=new_fixture, check=True)
            subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=new_fixture, check=True)
            return {"exit_code": 0}
        with mock.patch.object(live, "git", side_effect=clean_git), mock.patch.object(live, "command", side_effect=clone), mock.patch.object(live, "outside_checkouts"):
            prepared = live.prepare(ROOT, new_fixture, new_home, source_sha)
        manifest = prepared["manifest"]
        self.assertEqual(source_sha, manifest["source_sha"])
        self.assertEqual(set(live.SKILLS), set(manifest["skill_source_sha256"]))
        self.assertEqual(set(live.PHASES), set(manifest["prompts"]))
        self.assertTrue(new_home.is_dir())
        self.assertEqual(manifest["fixture_commit"], real_git(new_fixture, "rev-parse", "HEAD"))
        self.assertNotEqual(source_sha, manifest["fixture_commit"])
        self.assertFalse((new_fixture / ".context-os-live-manifest.json").exists())
        self.assertEqual("", real_git(new_fixture, "diff", "--", "AGENTS.md", ".agents/skills"))
        self.assertIn(manifest["canaries"]["agents"], real_git(new_fixture, "show", "--format=", "HEAD", "--", "AGENTS.md"))

    def test_cli_accepts_approval_dir(self) -> None:
        approval_dir = self.base / "approval-cli"
        with mock.patch.object(live, "record", return_value={"controls": {"run": "passed"}}) as record:
            with contextlib.redirect_stdout(io.StringIO()):
                code = live.main(["record", "--fixture", "fixture", "--home", "home", "--manifest", "manifest",
                                  "--evidence", "evidence", "--binary", "hermes",
                                  "--model", "model", "--provider", "provider",
                                  "--expected-version", "Hermes Agent v0.21.4",
                                  "--approval-dir", str(approval_dir), "--env-allow", "PRIVATE_TEST"])
        self.assertEqual(0, code)
        self.assertEqual(approval_dir, record.call_args.kwargs["approval_dir"])
        self.assertEqual(["PRIVATE_TEST"], record.call_args.kwargs["env_allow"])

    def test_prepare_rejects_checkout_path(self) -> None:
        with self.assertRaisesRegex(live.HarnessError, "separate, non-nested"):
            live.outside_checkouts(ROOT / "fixture", ROOT)

    def test_manifest_inside_fixture_rejected(self) -> None:
        with mock.patch.object(live, "outside_checkouts"):
            with self.assertRaisesRegex(live.HarnessError, "manifest must be outside"):
                live.record(self.fixture, self.home, self.base / "unused.json", ["hermes"],
                            "fake/free", "fake", 1, 1, manifest_path=self.fixture / "manifest.json")

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

    def test_nonstring_proposal_diff_rejected(self) -> None:
        import hashlib
        folder = self.fixture / ".context-os/proposals"
        folder.mkdir(parents=True)
        document = {"workflow": "update", "changes": [{"path": "state/current.md", "diff": ["bad"]}]}
        document["proposal_digest"] = hashlib.sha256(canonical_json(document).encode()).hexdigest()
        (folder / "bad.json").write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(TypeError):
            live.new_proposal(self.fixture, set(), "update")

    def run_record(self, mode: str = "", input_fn=None, approval_dir=None,
                   approval_timeout=900, provider="fake") -> dict:
        original_command = live.command
        def kernel_command(argv, cwd, env=None, timeout=120, raw_output=False):
            if mode == "accept-wrong" and argv[:2] == ["bash", "scripts/contextos.sh"] and "0" * 64 in argv:
                return {"argv": list(argv), "exit_code": 0, "stdout": "accepted", "stderr": "", "duration_seconds": 0, "at": live.now()}
            if mode == "no-receipt" and argv[:2] == ["bash", "scripts/contextos.sh"] and "apply" in argv and "0" * 64 not in argv:
                return {"argv": list(argv), "exit_code": 0, "stdout": "accepted", "stderr": "", "duration_seconds": 0, "at": live.now()}
            if (mode == "accept-stale" and argv[:2] == ["bash", "scripts/contextos.sh"]
                    and "apply" in argv and (self.fixture / ".context-os/receipts" / Path(argv[3]).name).exists()):
                return {"argv": list(argv), "exit_code": 0, "stdout": "accepted", "stderr": "", "duration_seconds": 0, "at": live.now()}
            if argv[:2] == ["bash", "scripts/contextos.sh"]:
                result = original_command([sys.executable, "-m", "contextos", *argv[2:]], cwd, env, timeout)
                if mode == "bad-receipt" and "apply" in argv and result["exit_code"] == 0:
                    for receipt in (self.fixture / ".context-os/receipts").glob("*.json"):
                        receipt.write_text("[]", encoding="utf-8")
                if mode == "mutate-sentinel" and "-end-" in argv[3] and "0" * 64 not in argv:
                    (self.fixture / "unrelated-sentinel.txt").write_text("changed", encoding="utf-8")
                return result
            return original_command(argv, cwd, env, timeout, raw_output=raw_output)
        def fixture_git(cwd, *args):
            if args == ("rev-parse", "HEAD"):
                return json.loads(self.manifest_path.read_text())["fixture_commit"]
            if args[:1] == ("status",):
                return ""
            return live.git(cwd, *args)
        with mock.patch.dict(os.environ, {"FAKE_HERMES_MODE": mode, "HERMES_LIVE_MANIFEST": str(self.manifest_path)}), mock.patch.object(live, "git", side_effect=fixture_git), mock.patch.object(live, "command", side_effect=kernel_command), mock.patch.object(live, "outside_checkouts"):
            with contextlib.redirect_stdout(io.StringIO()):
                return live.record(self.fixture, self.home, self.evidence,
                                   [sys.executable, str(self.fake)], "fake/free", provider, 30, 10,
                                   input_fn=input_fn or (lambda prompt: prompt.split("digest ")[1].split()[0]),
                                   expected_version="Hermes Agent v0.21.4",
                                   approval_dir=approval_dir, approval_timeout=approval_timeout,
                                   manifest_path=self.manifest_path, env_allow=("FAKE_HERMES_MODE",))

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
        for mode in ("self-read-agents", "self-read-skill", "self-read-terminal", "self-read-search",
                     "evasion-grep", "evasion-manifest", "evasion-diff", "evasion-skill-glob",
                     "evasion-agents-glob", "evasion-show", "evasion-log", "evasion-rg",
                     "evasion-findstr", "evasion-select-string", "evasion-execute-code", "result-leak",
                     "skill-view-other-phase", "skill-view-native-memory", "cat-agents"):
            with self.subTest(mode=mode):
                self.evidence.unlink(missing_ok=True)
                report = self.run_record(mode)
                self.assertEqual("failed", report["controls"]["setup_discovery"])
                self.assertEqual("HarnessError: self-read: discovery not shown", report["failure"])
                self.assertEqual(["context-setup"], report["commands"][1]["skill_view_names"])
                if mode == "result-leak":
                    self.assertIn("[REDACTED TOOL RESULT]", self.evidence.read_text(encoding="utf-8"))

    def test_skill_view_result_is_not_self_read(self) -> None:
        report = self.run_record("skill-view-valid")
        self.assertEqual("passed", report["controls"]["run"], report.get("failure"))

    def test_skill_view_native_memory_is_self_read(self) -> None:
        report = self.run_record("skill-view-native-memory")
        self.assertEqual("failed", report["controls"]["setup_discovery"])
        self.assertIn("self-read", report["failure"])

    def test_write_payload_is_not_self_read(self) -> None:
        report = self.run_record("write-agents-word")
        self.assertEqual("passed", report["controls"]["run"], report.get("failure"))

    def test_skill_view_alias_and_result_id(self) -> None:
        canaries = {"agents": "agent-marker", "setup": "alias-marker",
                    "context-setup": "core-marker", "context-start": "other-marker",
                    "native-USER.md": "memory-marker"}
        use = {"type": "tool_use", "id": "skill-1", "name": "skill_view", "input": {"name": "setup"}}
        result = {"type": "tool_result", "id": "skill-1", "name": "skill_view", "output": "alias-marker"}
        raw = "\n".join(json.dumps(event) for event in (use, result))
        self.assertFalse(live.stream_evidence(raw, canaries, "setup")[3])
        result["output"] = "alias-marker other-marker"
        self.assertTrue(live.stream_evidence("\n".join(json.dumps(event) for event in (use, result)), canaries, "setup")[3])
        result["output"] = "alias-marker memory-marker"
        self.assertTrue(live.stream_evidence("\n".join(json.dumps(event) for event in (use, result)), canaries, "setup")[3])
        result["output"] = "alias-marker"
        result["id"] = "skill-2"
        self.assertTrue(live.stream_evidence("\n".join(json.dumps(event) for event in (use, result)), canaries, "setup")[3])

    def test_fake_skill_view_returns_fixture_skill_text(self) -> None:
        env = os.environ.copy()
        env["HERMES_LIVE_MANIFEST"] = str(self.manifest_path)
        env["HERMES_HOME"] = str(self.home)
        result = subprocess.run([sys.executable, str(self.fake), "chat", "--format", "stream-json",
                                 "-q", live.prompt_for("setup")], cwd=self.fixture, env=env,
                                capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        skill = next(event for event in events if event.get("name") == "skill_view" and event["type"] == "tool_result")
        self.assertEqual((self.fixture / ".agents/skills/context-setup/SKILL.md").read_text(), skill["output"])

    def test_only_assistant_canaries_count(self) -> None:
        report = self.run_record("tool-result-canaries")
        self.assertEqual("failed", report["controls"]["setup_discovery"])
        self.assertIn("self-read", report["failure"])

    def test_agents_canary_required(self) -> None:
        report = self.run_record("omit-agents")
        self.assertEqual("failed", report["controls"]["setup_discovery"])
        self.assertEqual("HarnessError: canary not reported: agents", report["failure"])

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
        self.assertIn("docs/x.md", live.clean("docs/x.md"))
        self.assertIn("docs/" + "q" * 40 + ".md", live.clean("docs/" + "q" * 40 + ".md"))
        self.assertIn("docs/" + "q" * 40, live.clean("docs/" + "q" * 40))
        self.assertNotIn("k" * 40, live.clean("k" * 40))
        raw = json.dumps({"type": "tool_use", "name": "read_file", "input": {"path": "docs/x.md"}})
        events, _assistant, _skills, _self_read = live.stream_evidence(raw, ())
        self.assertEqual("docs/x.md", events[0]["input"]["path"])
        raw = json.dumps({"type": "tool_use", "name": "execute_code", "input": {"key": "k" * 40}})
        events, _assistant, _skills, _self_read = live.stream_evidence(raw, ())
        self.assertEqual("[REDACTED]", events[0]["input"]["key"])

    def test_environment_names_are_filtered(self) -> None:
        provider_value = "fixture-provider-" + uuid.uuid4().hex
        with mock.patch.dict(os.environ, {"PRIVATE_UNRELATED": "private", "OPENROUTER_API_KEY": provider_value}):
            env = live.hermes_environment(self.home, "openrouter")
            self.assertNotIn("PRIVATE_UNRELATED", env)
            self.assertEqual(provider_value, env["OPENROUTER_API_KEY"])
            self.assertIn("PRIVATE_UNRELATED", live.hermes_environment(self.home, "openrouter", ("PRIVATE_UNRELATED",)))
            report = self.run_record(provider="openrouter")
        self.assertNotIn("PRIVATE_UNRELATED", report["environment_names"])
        self.assertIn("OPENROUTER_API_KEY", report["environment_names"])
        self.assertEqual(["OPENROUTER_API_KEY"], report["api_key_names"])
        self.assertNotIn(provider_value, self.evidence.read_text(encoding="utf-8"))

    def test_environment_only_passes_selected_provider_key_and_network_settings(self) -> None:
        values = {"OPENROUTER_API_KEY": "fixture-openrouter", "OTHER_API_KEY": "fixture-other",
                  "HERMES_OTHER_API_KEY": "fixture-hermes-other",
                  "HTTP_PROXY": "http://proxy.invalid", "https_proxy": "http://proxy.invalid",
                  "SSL_CERT_FILE": "fixture-ca.pem", "REQUESTS_CA_BUNDLE": "fixture-bundle.pem"}
        with mock.patch.dict(os.environ, values):
            env = live.hermes_environment(self.home, "openrouter")
            self.assertIn("OPENROUTER_API_KEY", env)
            self.assertNotIn("OTHER_API_KEY", env)
            self.assertNotIn("HERMES_OTHER_API_KEY", env)
            for name in ("HTTP_PROXY", "https_proxy", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
                self.assertEqual(values[name], {key.upper(): value for key, value in env.items()}[name.upper()])
            self.assertNotIn("OPENROUTER_API_KEY", live.hermes_environment(self.home, "fake"))
            self.assertIn("OTHER_API_KEY", live.hermes_environment(self.home, "fake", ("OTHER_API_KEY",)))
            report = self.run_record()
        self.assertNotIn("OTHER_API_KEY", report["api_key_names"])
        self.assertIn("api_key_names", report)

    def test_tool_results_do_not_record_environment(self) -> None:
        raw = json.dumps({"type": "tool_result", "content": "FIXTURE_VAR=fixture-value"})
        events, assistant, skills, self_read = live.stream_evidence(raw, ())
        self.assertEqual("[REDACTED TOOL RESULT]", events[0]["content"])
        self.assertEqual("", assistant)
        self.assertEqual([], skills)
        self.assertFalse(self_read)

    def test_delegate_task_input_counts_as_self_read(self) -> None:
        raw = json.dumps({"type": "tool_use", "name": "delegate_task", "input": {"task": "cat AGENT*"}})
        _events, _assistant, _skills, self_read = live.stream_evidence(raw, ())
        self.assertTrue(self_read)
        split = json.dumps({"type": "tool_use", "name": "execute_code",
                            "input": {"command": "grep", "pattern": "Hermes fixture canary:"}})
        _events, _assistant, _skills, self_read = live.stream_evidence(split, ())
        self.assertTrue(self_read)
        reversed_fields = json.dumps({"type": "tool_use", "name": "execute_code",
                                      "input": {"pattern": "Hermes fixture canary:", "command": "grep"}})
        _events, _assistant, _skills, self_read = live.stream_evidence(reversed_fields, ())
        self.assertTrue(self_read)

    def test_instruction_file_globs_count_as_self_read(self) -> None:
        for command in ("cat AGENTS.md", "cat agents.MD", "cat AGENTS.?d", "cat *.md",
                        "cat .agents/skills/context-setup/*"):
            with self.subTest(command=command):
                raw = json.dumps({"type": "tool_use", "name": "terminal", "input": {"command": command}})
                self.assertTrue(live.stream_evidence(raw, ())[3])

    def test_write_file_payload_does_not_trigger_self_read(self) -> None:
        raw = json.dumps({"type": "tool_use", "name": "write_file",
                          "input": {"path": "identity/hermes-fixture.md",
                                    "content": "The agents read .agents/skills/context-setup/SKILL.md"}})
        self.assertFalse(live.stream_evidence(raw, ())[3])

    def test_split_text_deltas_rejoin_canaries(self) -> None:
        canary = "c" * 16 + "d" * 16
        raw = "\n".join(json.dumps({"type": "text", "text": canary[i:i + 5]}) for i in range(0, 32, 5))
        _events, assistant, _skills, _self_read = live.stream_evidence(raw, (canary,))
        self.assertIn(canary, assistant)
        raw = json.dumps({"type": "result", "exit_code": 0, "text": "final " + canary})
        _events, assistant, _skills, _self_read = live.stream_evidence(raw, (canary,))
        self.assertIn(canary, assistant)

    def test_route_identifiers_are_recorded_verbatim(self) -> None:
        for model in ("thinkingmachines/inkling:free", "nvidia/nemotron-3-ultra-550b-a55b:free"):
            self.assertEqual(model, live.route_id(model, "model"))
        for bad in ("sk-or-v1-" + "a" * 40, "openrouter:sk-or-v1-" + "a" * 40,
                    "provider:" + "b" * 40, "openrouter:sk-or-v1-short1", "model with spaces", "../../etc"):
            with self.assertRaises(live.HarnessError):
                live.route_id(bad, "model")
        report = self.run_record()
        self.assertEqual("fake/free", report["model"])
        self.assertEqual("fake", report["provider"])

    def test_split_secret_is_redacted_in_recorded_events(self) -> None:
        secret = "sk-or-v1-" + "e" * 40
        raw = "\n".join(json.dumps({"type": "text", "text": secret[i:i + 6]}) for i in range(0, len(secret), 6))
        events, _assistant, _skills, _self_read = live.stream_evidence(raw, ())
        recorded = json.dumps(events)
        self.assertNotIn("e" * 12, recorded)
        self.assertNotIn("sk-or", recorded)
        self.assertEqual([{"type": "text", "text": "[REDACTED]", "joined_deltas": True}], events)

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

    def test_start_kernel_state_mutation_detected(self) -> None:
        report = self.run_record("mutate-kernel")
        self.assertEqual("failed", report["controls"]["start_read_only"])

    def test_native_memory_mutation_and_addition_detected(self) -> None:
        for mode in ("mutate-native-memory", "add-native-memory", "remove-native-memory"):
            with self.subTest(mode=mode):
                self.evidence.unlink(missing_ok=True)
                report = self.run_record(mode)
                self.assertEqual("failed", report["controls"]["memory_separation"])
                self.assertIn("native memory changed", report["failure"])
                self.assertTrue(report["native_memory_changes"])
                changed = report["native_memory_changes"][0]
                self.assertIn(changed["path"], ("USER.md", "extra.md"))
                self.assertIn("--- before/", changed["diff"])
                self.assertLessEqual(len(changed["diff"]), 2000)
                (self.home / "memories" / "extra.md").unlink(missing_ok=True)
                if mode in ("mutate-native-memory", "remove-native-memory"):
                    manifest = json.loads(self.manifest_path.read_text())
                    marker = manifest["native_memory_canaries"]["USER.md"]
                    (self.home / "memories" / "USER.md").write_text(f"Fixture native memory canary: {marker}\n")

    def test_obfuscated_memory_in_proposal_detected(self) -> None:
        for mode in ("propose-memory-obfuscated", "propose-memory-punctuated"):
            with self.subTest(mode=mode):
                self.evidence.unlink(missing_ok=True)
                report = self.run_record(mode)
                self.assertEqual("failed", report["controls"]["memory_separation"])

    def test_memory_normalization_catches_punctuation_in_fixture(self) -> None:
        marker = json.loads(self.manifest_path.read_text())["native_memory_canaries"]["USER.md"]
        obfuscated = "Fixture: " + " :\n_".join(marker.upper()[i:i + 4] for i in range(0, 32, 4))
        path = self.fixture / "identity" / "memory-leak.md"
        path.write_text(obfuscated, encoding="utf-8")
        self.assertTrue(live.mirrors_memory(obfuscated, (marker,)))
        with self.assertRaisesRegex(live.HarnessError, "native memory canary"):
            live.check_memory(self.fixture, self.home, {"USER.md": marker})

    def test_native_memory_diff_is_cleaned_and_capped(self) -> None:
        before = live.native_memory_state(self.home)
        contents = live.native_memory_contents(self.home)
        (self.home / "memories" / "USER.md").write_text("token=fixture-secret\n" + "x" * 3000)
        report = {}
        with self.assertRaisesRegex(live.HarnessError, "native memory changed"):
            live.check_native_memory(self.home, before, contents, report, ())
        change = report["native_memory_changes"][0]
        self.assertEqual("USER.md", change["path"])
        self.assertNotIn("fixture-secret", change["diff"])
        self.assertIn("[REDACTED]", change["diff"])
        self.assertLessEqual(len(change["diff"]), 2000)

    def test_unexpected_control_exception_writes_evidence(self) -> None:
        with mock.patch.object(live, "stream_evidence", side_effect=AttributeError("synthetic bad event")):
            report = self.run_record()
        self.assertEqual("failed", report["controls"]["setup_discovery"])
        self.assertIn("AttributeError: synthetic bad event", self.evidence.read_text(encoding="utf-8"))

    def test_nondict_receipt_writes_evidence(self) -> None:
        report = self.run_record("bad-receipt")
        self.assertEqual("failed", report["controls"]["setup_proposal_apply"])
        self.assertIn("AttributeError", self.evidence.read_text(encoding="utf-8"))

    def test_nonstring_diff_writes_evidence(self) -> None:
        report = self.run_record("bad-diff")
        self.assertEqual("failed", report["controls"]["setup_proposal_apply"])
        self.assertIn("TypeError", self.evidence.read_text(encoding="utf-8"))

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

    def test_native_memory_mirror_in_kernel_state_detected(self) -> None:
        report = self.run_record("mirror-kernel")
        self.assertEqual("failed", report["controls"]["memory_separation"])
        self.assertIn("native memory canary", report["failure"])

    def test_proposal_mirroring_native_memory_fails_before_approval(self) -> None:
        approval_dir = self.base / "approval-memory"
        approval_dir.mkdir()
        report = self.run_record("propose-memory", approval_dir=approval_dir)
        self.assertEqual("failed", report["controls"]["memory_separation"])
        self.assertIn("native memory canary appeared in fixture state", report["failure"])
        self.assertFalse((approval_dir / "setup.review.txt").exists())

    def test_wrong_digest_rejected_and_receipt_bound(self) -> None:
        report = self.run_record()
        self.assertEqual("passed", report["controls"]["run"], report.get("failure"))
        self.assertEqual("Hermes Agent v0.21.4 (fake build)", report["version"])
        self.assertTrue(report["os"])
        self.assertTrue(report["fresh_hermes_home"])
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_sha"], report["source_sha"])
        self.assertEqual(manifest["fixture_commit"], report["fixture_commit"])
        self.assertEqual("interactive", report["operator_mode"])
        self.assertIn("skill_view", [event.get("name") for event in report["commands"][1]["events"]])
        self.assertEqual(["context-setup"], report["commands"][1]["skill_view_names"])
        self.assertTrue(report["commands"][1]["argv"][-1].startswith("/context-setup"))
        self.assertEqual("passed", report["controls"]["wrong_digest_rejected"])
        self.assertEqual("passed", report["controls"]["stale_target_rejected"])
        self.assertEqual("passed", report["controls"]["update_proposal_apply"])
        self.assertEqual("passed", report["controls"]["end_proposal_apply"])
        self.assertEqual("passed", report["controls"]["memory_separation"])
        self.assertEqual("unsupported", report["controls"]["hook_example"])

    def test_model_can_ask_approval_after_one_proposal(self) -> None:
        report = self.run_record("asks-approval")
        self.assertEqual("passed", report["controls"]["run"], report.get("failure"))

    def test_wrong_digest_guard_must_fire(self) -> None:
        report = self.run_record("accept-wrong")
        self.assertEqual("failed", report["controls"]["run"])
        self.assertIn("did not reject wrong digest", report["failure"])

    def test_stale_target_guard_must_fire(self) -> None:
        report = self.run_record("accept-stale")
        self.assertEqual("failed", report["controls"]["stale_target_rejected"])
        self.assertIn("already-applied proposal", report["failure"])

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
        path = self.manifest_path
        manifest = json.loads(path.read_text(encoding="utf-8"))
        del manifest["skill_source_sha256"]["context-end"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(live.HarnessError, "incomplete"):
            self.run_record()

    def test_credentials_never_written(self) -> None:
        secret = "test-secret-" + uuid.uuid4().hex
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": secret}):
            self.run_record("echo-secret", provider="openrouter")
        self.assertNotIn(secret, self.evidence.read_text(encoding="utf-8"))
        leaked = [p.relative_to(self.fixture).as_posix() for p in self.fixture.rglob("*")
                  if p.is_file() and ".git" not in p.parts
                  and secret in p.read_text(encoding="utf-8", errors="ignore")]
        self.assertFalse(leaked, leaked)

    def test_output_token_redacted(self) -> None:
        secret = "test-secret-" + uuid.uuid4().hex
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": secret}):
            self.run_record("echo-secret", provider="openrouter")
        self.assertNotIn(secret, self.evidence.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
