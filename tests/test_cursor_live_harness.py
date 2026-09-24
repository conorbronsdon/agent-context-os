from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "adapters/cursor/live_conformance.py"
SPEC = importlib.util.spec_from_file_location("contextos_cursor_live", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
live = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = live
SPEC.loader.exec_module(live)


class CursorLiveHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.binary = self.root / ("agent.cmd" if os.name == "nt" else "agent")
        self.binary.write_text("fixture", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_fixture_has_explicit_skill_and_deny_precedence(self) -> None:
        workspace = self.root / "workspace"
        workspace.mkdir()
        canaries = {"root": "ROOT", "nested": "NESTED", "skill": "SKILL"}
        live.write_fixture(workspace, canaries)
        live.write_permissions(
            workspace,
            allow=["Write(*)"],
            deny=["Write(*)", "Shell(*)"],
        )
        skill = (workspace / ".agents/skills/contextos-live-explicit/SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("disable-model-invocation: true", skill)
        config = json.loads((workspace / ".cursor/cli.json").read_text(encoding="utf-8"))
        self.assertEqual(["Write(*)"], config["permissions"]["allow"])
        self.assertEqual(
            ["Write(*)", "Shell(*)"], config["permissions"]["deny"]
        )
        self.assertEqual("disposable\n", (workspace / live.DISPOSABLE_MARKER).read_text())
        self.assertEqual("nested fixture\n", (workspace / "nested/control.txt").read_text())

    def test_snapshot_reports_only_real_mutations(self) -> None:
        workspace = self.root / "workspace"
        live.write_fixture(workspace, {"root": "R", "nested": "N", "skill": "S"})
        before = live.snapshot(workspace)
        (workspace / "allowed.txt").write_text("ALLOWED_CONTROL\n", encoding="utf-8")
        self.assertEqual({"allowed.txt"}, live.changed_paths(before, live.snapshot(workspace)))

    def test_preflight_requires_exact_version_flags_and_authentication(self) -> None:
        responses = iter([
            live.CommandResult([], 0, "2026.08.31-4057e58\n", ""),
            live.CommandResult([], 0, "--print --force --workspace --trust --mode --output-format", ""),
            live.CommandResult([], 0, "Logged in", ""),
        ])
        harness = live.CursorHarness(
            self.binary, "2026.08.31-4057e58", "a" * 40,
            runner=lambda *_: next(responses), user_cli_config=self.root / "no-user-config.json",
        )
        harness.preflight(self.root)
        self.assertTrue(harness.evidence.controls["authenticated"])

    def test_nested_control_keeps_the_workspace_root(self) -> None:
        workspace = self.root / "workspace"
        nested = workspace / "nested"
        calls = []
        harness = live.CursorHarness(
            self.binary, "v1", "a" * 40,
            runner=lambda argv, cwd, *_: calls.append((list(argv), cwd)) or live.CommandResult([], 0, "", ""),
        )
        harness.agent(workspace, "@nested/control.txt prompt", "--mode", "ask", cwd=nested)
        self.assertEqual(nested, calls[0][1])
        self.assertIn(str(workspace), " ".join(calls[0][0]))
        self.assertIn("@nested/control.txt", " ".join(calls[0][0]))

    def test_preflight_rejects_unauthenticated_cli(self) -> None:
        responses = iter([
            live.CommandResult([], 0, "2026.08.31-4057e58\n", ""),
            live.CommandResult([], 0, "--print --force --workspace --trust --mode --output-format", ""),
            live.CommandResult([], 0, "Not logged in", ""),
        ])
        harness = live.CursorHarness(
            self.binary, "2026.08.31-4057e58", "a" * 40,
            runner=lambda *_: next(responses), user_cli_config=self.root / "no-user-config.json",
        )
        with self.assertRaisesRegex(live.HarnessError, "not authenticated"):
            harness.preflight(self.root)

    def test_preflight_requires_positive_authentication_marker(self) -> None:
        responses = iter([
            live.CommandResult([], 0, "2026.08.31-4057e58\n", ""),
            live.CommandResult([], 0, "--print --force --workspace --trust --mode --output-format", ""),
            live.CommandResult([], 0, "Authentication status unavailable", ""),
        ])
        harness = live.CursorHarness(
            self.binary, "2026.08.31-4057e58", "a" * 40,
            runner=lambda *_: next(responses), user_cli_config=self.root / "no-user-config.json",
        )
        with self.assertRaisesRegex(live.HarnessError, "positively confirm"):
            harness.preflight(self.root)

    def test_preflight_rejects_user_cli_permissions(self) -> None:
        config = self.root / "cli-config.json"
        config.write_text('{"permissions": {"deny": ["Write(*)"]}}', encoding="utf-8")
        harness = live.CursorHarness(
            self.binary, "v1", "a" * 40, user_cli_config=config,
        )
        with self.assertRaisesRegex(live.HarnessError, "confound"):
            harness.preflight(self.root)

        config.write_text('{"permissions": {"deny": ["Read(.agents/**)"]}}', encoding="utf-8")
        with self.assertRaisesRegex(live.HarnessError, "confound"):
            harness.preflight(self.root)

    def test_require_canary_rejects_benign_success_without_evidence(self) -> None:
        result = live.CommandResult(
            [], 0, json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ordinary"}), ""
        )
        with self.assertRaisesRegex(live.HarnessError, "did not return"):
            live.require_canary(result, "CANARY", "root")

    def test_require_canary_rejects_substring_and_non_json_output(self) -> None:
        substring = live.CommandResult(
            [], 0, json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "CANARY extra"}), ""
        )
        with self.assertRaisesRegex(live.HarnessError, "only"):
            live.require_canary(substring, "CANARY", "root")
        with self.assertRaisesRegex(live.HarnessError, "JSON"):
            live.require_canary(live.CommandResult([], 0, "CANARY", ""), "CANARY", "root")

    def test_deny_precedence_requires_observed_stream_write_attempt(self) -> None:
        terminal = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "Denied"})
        with self.assertRaisesRegex(live.HarnessError, "rejected denied write"):
            live.require_denied_write_attempt(
                live.CommandResult([], 0, terminal, ""), self.root, "denied.txt", "deny"
            )

    def test_deny_precedence_rejects_an_outside_workspace_attempt(self) -> None:
        stream = "\n".join(json.dumps(item) for item in [
            {"type": "tool_call", "subtype": "started", "call_id": "call-1", "tool_call": {"writeToolCall": {"args": {"path": str(self.root.parent / "denied.txt")}}}},
            {"type": "tool_call", "subtype": "completed", "call_id": "call-1", "tool_call": {"writeToolCall": {"args": {"path": str(self.root.parent / "denied.txt")}, "result": {"denied": {"reason": "policy"}}}}},
            {"type": "result", "subtype": "success", "is_error": False, "result": "Denied"},
        ])
        with self.assertRaisesRegex(live.HarnessError, "outside"):
            live.require_denied_write_attempt(
                live.CommandResult([], 0, stream, ""), self.root, "denied.txt", "deny"
            )

    def test_deny_precedence_rejects_non_policy_tool_errors(self) -> None:
        stream = "\n".join(json.dumps(item) for item in [
            {"type": "tool_call", "subtype": "started", "call_id": "call-1", "tool_call": {"writeToolCall": {"args": {"path": "denied.txt"}}}},
            {"type": "tool_call", "subtype": "completed", "call_id": "call-1", "tool_call": {"writeToolCall": {"args": {"path": "denied.txt"}, "result": {"error": {"reason": "disk full"}}}}},
            {"type": "result", "subtype": "success", "is_error": False, "result": "Write failed"},
        ])
        with self.assertRaisesRegex(live.HarnessError, "other than policy"):
            live.require_denied_write_attempt(
                live.CommandResult([], 0, stream, ""), self.root, "denied.txt", "deny"
            )

    def test_execute_requires_exact_json_controls_and_observed_denial(self) -> None:
        def json_result(value: str) -> str:
            return json.dumps({
                "type": "result", "subtype": "success", "is_error": False,
                "result": value,
            })

        def runner(argv, _cwd, _env, _timeout):
            command = " ".join(argv)
            if "--version" in command:
                return live.CommandResult([], 0, "v1\n", "")
            if "--help" in command:
                return live.CommandResult([], 0, "--print --force --workspace --trust --mode --output-format", "")
            if command.endswith(" status"):
                return live.CommandResult([], 0, "Logged in", "")
            if Path(argv[0]).name.lower() in {"cmd", "cmd.exe"}:
                # The Windows batch bridge folds every argument into one quoted string.
                workspace = Path(command.split("--workspace ", 1)[1].split(" --", 1)[0].strip('"'))
                prompt = command.rsplit('"', 2)[1] if command.count('"') >= 2 else command.rsplit(" ", 1)[-1]
            else:
                workspace = Path(argv[list(argv).index("--workspace") + 1])
                prompt = argv[-1]
            if "ROOT_INSTRUCTION_CANARY in the repository" in prompt:
                value = (workspace / "AGENTS.md").read_text().split("=", 1)[1].splitlines()[0]
                return live.CommandResult([], 0, json_result(value), "")
            if "@nested/control.txt" in prompt:
                value = (workspace / "nested/AGENTS.md").read_text().split("=", 1)[1].splitlines()[0]
                return live.CommandResult([], 0, json_result(value), "")
            if prompt.startswith("Use the available Context OS control"):
                return live.CommandResult([], 0, json_result("ordinary implicit answer"), "")
            if prompt.startswith("/contextos-live-explicit"):
                config = json.loads((workspace / ".cursor/cli.json").read_text(encoding="utf-8"))
                self.assertEqual(["Read(.agents/**)", "Shell(*)"], config["permissions"]["deny"])
                value = (workspace / ".agents/skills/contextos-live-explicit/SKILL.md").read_text().split("Return only ", 1)[1].split(".", 1)[0]
                return live.CommandResult([], 0, json_result(value), "")
            if "proposed.txt" in prompt:
                return live.CommandResult([], 0, json_result("PROPOSED_ONLY"), "")
            if "denied.txt" in prompt:
                stream = [
                    {"type": "tool_call", "subtype": "started", "call_id": "call-denied", "tool_call": {"writeToolCall": {"args": {"path": "denied.txt"}}}},
                    {"type": "tool_call", "subtype": "completed", "call_id": "call-denied", "tool_call": {"writeToolCall": {"args": {"path": "denied.txt"}, "result": {"denied": {"reason": "policy"}}}}},
                    {"type": "result", "subtype": "success", "is_error": False, "result": "Write denied"},
                ]
                return live.CommandResult([], 0, "\n".join(json.dumps(item) for item in stream), "")
            if "allowed.txt" in prompt:
                (workspace / "allowed.txt").write_text("ALLOWED_CONTROL\n", encoding="utf-8")
                return live.CommandResult([], 0, json_result("written"), "")
            return live.CommandResult([], 0, json_result("ok"), "")

        harness = live.CursorHarness(
            self.binary, "v1", "a" * 40, runner=runner,
            user_cli_config=self.root / "no-user-config.json",
        )
        evidence = harness.execute()
        self.assertTrue(evidence.controls["project_deny_rejected_a_write_attempt"])
        self.assertTrue(evidence.controls["forced_write_is_scoped"])

    def test_write_evidence_is_create_only(self) -> None:
        target = self.root / "evidence.json"
        evidence = live.Evidence(
            expected_version="v1", source_sha="a" * 40,
            binary_version="v1", controls={"control": True},
        )
        live.write_evidence(target, evidence)
        self.assertEqual("cursor", json.loads(target.read_text())["runtime"])
        with self.assertRaisesRegex(live.HarnessError, "refusing to overwrite"):
            live.write_evidence(target, evidence)

    def test_evidence_must_be_outside_the_source_repository(self) -> None:
        with self.assertRaisesRegex(live.HarnessError, "outside the source"):
            live.require_outside_source(live.REPOSITORY_ROOT / "evidence.json")

    def test_main_requires_explicit_model_traffic_opt_in(self) -> None:
        with mock.patch.object(live, "repository_source_sha") as source:
            with redirect_stderr(io.StringIO()):
                status = live.main([
                    "--binary", str(self.binary),
                    "--expected-version", "v1",
                    "--source-sha", "a" * 40,
                    "--evidence", str(self.root / "evidence.json"),
                ])
        self.assertEqual(1, status)
        source.assert_not_called()

    def test_main_rechecks_source_before_writing_evidence(self) -> None:
        target = self.root / "evidence.json"
        evidence = live.Evidence(
            expected_version="v1", source_sha="a" * 40, binary_version="v1"
        )
        with mock.patch.object(
            live, "repository_source_sha", side_effect=["a" * 40, "b" * 40]
        ):
            with mock.patch.object(live.CursorHarness, "execute", return_value=evidence):
                with mock.patch.object(live, "write_evidence") as write:
                    with redirect_stderr(io.StringIO()):
                        status = live.main([
                            "--binary", str(self.binary),
                            "--expected-version", "v1",
                            "--source-sha", "a" * 40,
                            "--evidence", str(target),
                            "--allow-model-traffic",
                        ])
        self.assertEqual(1, status)
        write.assert_not_called()

    def test_source_sha_requires_clean_worktree(self) -> None:
        responses = iter([
            live.CommandResult([], 0, " M file\n", ""),
        ])
        with self.assertRaisesRegex(live.HarnessError, "clean source commit"):
            live.repository_source_sha(lambda *_: next(responses))

    def test_source_does_not_invoke_built_in_update(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn('"/update"', source)
        self.assertIn('"short_update_alias_not_invoked": True', source)
        self.assertIn('"headless_ask_mode_preserves_files": True', source)
        self.assertIn('self.evidence.controls["headless_without_force_is_write_capable"] =', source)


if __name__ == "__main__":
    unittest.main()
