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


DENY_STREAM = ROOT / "tests/fixtures/cursor/deny-stream-2026.09.23-86fc751.jsonl"


def observed_deny_stream(path: str) -> list[dict]:
    """Return the recorded Cursor CLI deny stream with its write aimed at path."""
    events = [json.loads(line) for line in DENY_STREAM.read_text(encoding="utf-8").splitlines()]
    for event in events:
        edit = event.get("tool_call", {}).get("editToolCall", {})
        if event.get("subtype") == "started" and "args" in edit:
            edit["args"]["path"] = path
    return events


class CursorLiveHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        environment = mock.patch.dict(os.environ, {"CURSOR_CONFIG_DIR": "", "XDG_CONFIG_HOME": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.temporary = tempfile.TemporaryDirectory()
        # Windows CI may return an 8.3 alias; the harness resolves its paths.
        self.root = Path(self.temporary.name).resolve()
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
            runner=lambda *_: next(responses), user_cli_config=self.root / "missing" / "cli-config.json",
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
            runner=lambda *_: next(responses), user_cli_config=self.root / "missing" / "cli-config.json",
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
            runner=lambda *_: next(responses), user_cli_config=self.root / "missing" / "cli-config.json",
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

    def test_preflight_rejects_user_allowances_before_running_cursor(self) -> None:
        config = self.root / "cli-config.json"
        for allowance in (["Write(*)"], ["Shell(ls)"], "Shell(*)", [None]):
            with self.subTest(allowance=allowance):
                config.write_text(json.dumps({"permissions": {"allow": allowance}}))
                runner = mock.Mock(side_effect=[
                    live.CommandResult([], 0, "v1", ""),
                    live.CommandResult([], 0, " ".join(live.REQUIRED_FLAGS), ""),
                    live.CommandResult([], 0, "Logged in", ""),
                ])
                harness = live.CursorHarness(
                    self.binary, "v1", "a" * 40, runner=runner, user_cli_config=config,
                )
                with self.assertRaisesRegex(live.HarnessError, "confound"):
                    harness.preflight(self.root)
                runner.assert_not_called()

    def test_preflight_accepts_empty_permissions(self) -> None:
        config = self.root / "cli-config.json"
        config.write_text('{"permissions": {"allow": [], "deny": []}}')
        responses = iter([
            live.CommandResult([], 0, "v1", ""),
            live.CommandResult([], 0, " ".join(live.REQUIRED_FLAGS), ""),
            live.CommandResult([], 0, "Logged in", ""),
        ])
        harness = live.CursorHarness(
            self.binary, "v1", "a" * 40,
            runner=lambda *_: next(responses), user_cli_config=config,
        )
        harness.preflight(self.root)
        self.assertTrue(harness.evidence.controls["authenticated"])

    def test_cleanup_lock_preserves_evidence_and_original_failures(self) -> None:
        harness = live.CursorHarness(self.binary, "v1", "a" * 40)
        temporary = mock.Mock(name=str(self.root))
        temporary.name = str(self.root)
        temporary.cleanup.side_effect = PermissionError("Windows file lock")
        diagnostic = io.StringIO()
        with mock.patch.object(live.tempfile, "TemporaryDirectory", return_value=temporary), redirect_stderr(diagnostic):
            with harness.disposable_workspace() as path:
                self.assertEqual(self.root, path)
                harness.evidence.controls["completed"] = True
            target = self.root / "completed.json"
            live.write_evidence(target, harness.evidence)
            result = json.loads(target.read_text())
            self.assertTrue(result["controls"]["completed"])
            self.assertEqual("retained-cleanup-error", result["workspace_cleanup"])
            with self.assertRaisesRegex(live.HarnessError, "original control failed"):
                with harness.disposable_workspace():
                    raise live.HarnessError("original control failed")
        self.assertIn(str(self.root), diagnostic.getvalue())

    def test_cleanup_success_is_recorded(self) -> None:
        harness = live.CursorHarness(self.binary, "v1", "a" * 40)
        with harness.disposable_workspace() as path:
            self.assertTrue(path.is_dir())
        self.assertFalse(path.exists())
        self.assertEqual("completed", harness.evidence.workspace_cleanup)

    def test_evidence_identifies_cursor_binary_instead_of_batch_bridge(self) -> None:
        def runner(argv, *_):
            if os.name == "nt":
                self.assertEqual("cmd.exe", Path(argv[0]).name.lower())
            else:
                self.assertEqual(str(self.binary), argv[0])
            return live.CommandResult(list(argv), 0, "v1", "")
        harness = live.CursorHarness(self.binary, "v1", "a" * 40, runner=runner)
        harness.run(self.root, "--version")
        target = self.root / "identity.json"
        live.write_evidence(target, harness.evidence)
        result = json.loads(target.read_text())
        self.assertEqual(self.binary.name, result["binary_name"])
        self.assertEqual(live.hashlib.sha256(b"fixture").hexdigest(), result["binary_sha256"])

    def test_binary_drift_is_rejected(self) -> None:
        runner = mock.Mock()
        harness = live.CursorHarness(self.binary, "v1", "a" * 40, runner=runner)
        self.binary.write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(live.HarnessError, "binary changed"):
            harness.run(self.root, "--version")
        runner.assert_not_called()

    def test_default_config_directory_is_pinned_for_child(self) -> None:
        harness = live.CursorHarness(self.binary, "v1", "a" * 40)
        self.assertEqual(str(Path.home() / ".cursor"), harness.env["CURSOR_CONFIG_DIR"])

    def test_non_object_config_is_rejected_before_cursor_runs(self) -> None:
        config = self.root / "cli-config.json"
        config.write_text("[]", encoding="utf-8")
        runner = mock.Mock()
        harness = live.CursorHarness(self.binary, "v1", "a" * 40, runner=runner, user_cli_config=config)
        with self.assertRaisesRegex(live.HarnessError, "JSON object"):
            harness.preflight(self.root)
        runner.assert_not_called()

    def test_effective_config_follows_cursor_directory_override(self) -> None:
        override = self.root / "override"
        with mock.patch.dict(os.environ, {"CURSOR_CONFIG_DIR": str(override)}):
            harness = live.CursorHarness(self.binary, "v1", "a" * 40)
        self.assertEqual(override / "cli-config.json", harness.user_cli_config)
        self.assertEqual(str(override), harness.env["CURSOR_CONFIG_DIR"])
        with self.assertRaisesRegex(live.HarnessError, "absolute"):
            live.effective_cli_config({"CURSOR_CONFIG_DIR": "relative"})

    def test_explicit_config_is_also_used_by_child(self) -> None:
        config = self.root / "explicit" / "cli-config.json"
        harness = live.CursorHarness(self.binary, "v1", "a" * 40, user_cli_config=config)
        self.assertEqual(config, harness.user_cli_config)
        self.assertEqual(str(config.parent), harness.env["CURSOR_CONFIG_DIR"])
        with self.assertRaisesRegex(live.HarnessError, "must name"):
            live.CursorHarness(self.binary, "v1", "a" * 40, user_cli_config=self.root / "other.json")

    def test_xdg_override_applies_on_every_platform(self) -> None:
        directory = self.root / "xdg"
        expected = directory / "cursor/cli-config.json"
        self.assertEqual(expected, live.effective_cli_config({"XDG_CONFIG_HOME": str(directory)}))
        self.assertEqual(expected, live.effective_cli_config({
            "CURSOR_CONFIG_DIR": "  ", "XDG_CONFIG_HOME": str(directory),
        }))
        self.assertEqual(Path.home() / ".cursor/cli-config.json", live.effective_cli_config({
            "CURSOR_CONFIG_DIR": "\t", "XDG_CONFIG_HOME": "  ",
        }))

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

    def test_deny_precedence_accepts_the_observed_cursor_denial_stream(self) -> None:
        stream = "\n".join(json.dumps(item) for item in observed_deny_stream(str(self.root / "denied.txt")))
        live.require_denied_write_attempt(
            live.CommandResult([], 0, stream, ""), self.root, "denied.txt", "deny"
        )

    def assert_deny_stream_rejected(self, events: list[dict], message: str) -> None:
        stream = "\n".join(json.dumps(item) for item in events)
        with self.assertRaisesRegex(live.HarnessError, message):
            live.require_denied_write_attempt(
                live.CommandResult([], 0, stream, ""), self.root, "denied.txt", "deny"
            )

    def test_deny_precedence_validates_the_denial_payload(self) -> None:
        def denial(events: list[dict]) -> dict:
            completed = next(e for e in events if e.get("subtype") == "completed" and "editToolCall" in e["tool_call"])
            return completed["tool_call"]["editToolCall"]["result"]

        for name, change in {
            "null payload": lambda result: result.update({"writePermissionDenied": None}),
            "other reported path": lambda result: result["writePermissionDenied"].update({"path": "other.txt"}),
            "non-string reported path": lambda result: result["writePermissionDenied"].update({"path": None}),
            "error names another file": lambda result: result["writePermissionDenied"].update(
                {"error": "Write permission denied: other.txt: Blocked by permissions configuration"}
            ),
        }.items():
            with self.subTest(name=name):
                events = observed_deny_stream(str(self.root / "denied.txt"))
                change(denial(events))
                self.assert_deny_stream_rejected(events, "other than policy")

    def test_deny_precedence_checks_the_whole_stream(self) -> None:
        events = observed_deny_stream(str(self.root / "denied.txt"))
        result_index = next(i for i, e in enumerate(events) if e.get("type") == "result")
        later = [
            {"type": "tool_call", "subtype": "started", "call_id": "call-2", "tool_call": {"editToolCall": {"args": {"path": str(self.root / "denied.txt")}}}},
            {"type": "tool_call", "subtype": "completed", "call_id": "call-2", "tool_call": {"editToolCall": {"result": {"success": {}}}}},
        ]
        self.assert_deny_stream_rejected(events[:result_index] + later + events[result_index:], "other than policy")
        outside = [
            {"type": "tool_call", "subtype": "started", "call_id": "call-3", "tool_call": {"editToolCall": {"args": {"path": str(self.root.parent / "elsewhere.txt")}}}},
        ]
        self.assert_deny_stream_rejected(events[:result_index] + outside + events[result_index:], "outside")
        ambiguous = [
            {"type": "tool_call", "subtype": "started", "call_id": "call-4", "tool_call": {
                "editToolCall": {"args": {"path": "denied.txt"}}, "writeToolCall": {"args": {"path": "denied.txt"}}}},
        ]
        self.assert_deny_stream_rejected(events[:result_index] + ambiguous + events[result_index:], "ambiguous")

    def test_deny_precedence_matches_full_paths_and_every_completion(self) -> None:
        subdirectory = observed_deny_stream(str(self.root / "sub" / "denied.txt"))
        self.assert_deny_stream_rejected(subdirectory, "rejected denied write")
        events = observed_deny_stream(str(self.root / "denied.txt"))
        completed = next(e for e in events if e.get("subtype") == "completed" and "editToolCall" in e["tool_call"])
        completed["tool_call"]["editToolCall"]["result"]["writePermissionDenied"]["path"] = str(self.root / "sub" / "denied.txt")
        self.assert_deny_stream_rejected(events, "other than policy")
        events = observed_deny_stream(str(self.root / "denied.txt"))
        result_index = next(i for i, e in enumerate(events) if e.get("type") == "result")
        other_success = [
            {"type": "tool_call", "subtype": "started", "call_id": "call-5", "tool_call": {"editToolCall": {"args": {"path": str(self.root / "other.txt")}}}},
            {"type": "tool_call", "subtype": "completed", "call_id": "call-5", "tool_call": {"editToolCall": {"result": {"success": {}}}}},
        ]
        self.assert_deny_stream_rejected(events[:result_index] + other_success + events[result_index:], "other than policy")
        events = observed_deny_stream(str(self.root / "denied.txt"))
        for event in events:
            if event.get("subtype") == "completed" and "editToolCall" in event["tool_call"]:
                event["tool_call"] = {"writeToolCall": event["tool_call"].pop("editToolCall")}
        self.assert_deny_stream_rejected(events, "ambiguous")

    def test_write_completion_kind_switch_is_ambiguous(self) -> None:
        events = observed_deny_stream(str(self.root / "denied.txt"))
        for event in events:
            tool_call = event.get("tool_call")
            if (
                event.get("subtype") == "completed"
                and isinstance(tool_call, dict)
                and "editToolCall" in tool_call
            ):
                del tool_call["editToolCall"]
                tool_call["shellToolCall"] = {"result": {"success": {"stdout": "DENIED_CONTROL"}}}
                break
        self.assert_deny_stream_rejected(events, "ambiguous write event")

    def test_other_write_completed_as_non_write_is_ambiguous(self) -> None:
        events = observed_deny_stream(str(self.root / "denied.txt"))
        started = next(
            event for event in events
            if event.get("subtype") == "started"
            and "editToolCall" in (event.get("tool_call") or {})
        )
        completed = next(
            event for event in events
            if event.get("subtype") == "completed"
            and "editToolCall" in (event.get("tool_call") or {})
        )
        switched_id = "tool_switched_write"
        switched_start = json.loads(json.dumps(started))
        switched_start["call_id"] = switched_id
        switched_start["tool_call"]["editToolCall"]["args"]["path"] = str(self.root / "other.txt")
        switched_done = json.loads(json.dumps(completed))
        switched_done["call_id"] = switched_id
        del switched_done["tool_call"]["editToolCall"]
        switched_done["tool_call"]["shellToolCall"] = {"result": {"success": {"stdout": "DENIED_CONTROL"}}}
        index = events.index(completed) + 1
        events[index:index] = [switched_start, switched_done]
        self.assert_deny_stream_rejected(events, "ambiguous write event")

    def test_started_write_without_completion_is_rejected(self) -> None:
        events = [
            event for event in observed_deny_stream(str(self.root / "denied.txt"))
            if not (
                event.get("subtype") == "completed"
                and "editToolCall" in (event.get("tool_call") or {})
            )
        ]
        self.assert_deny_stream_rejected(events, "left a write attempt without a denial")

    def test_unfinished_extra_write_is_rejected(self) -> None:
        events = observed_deny_stream(str(self.root / "denied.txt"))
        started = next(
            event for event in events
            if event.get("subtype") == "started"
            and "editToolCall" in (event.get("tool_call") or {})
        )
        unfinished = json.loads(json.dumps(started))
        unfinished["call_id"] = "tool_unfinished"
        unfinished["tool_call"]["editToolCall"]["args"]["path"] = str(self.root / "other.txt")
        events.insert(events.index(started), unfinished)
        self.assert_deny_stream_rejected(events, "left a write attempt without a denial")

    def test_reused_write_call_id_is_ambiguous(self) -> None:
        events = observed_deny_stream(str(self.root / "denied.txt"))
        started = next(
            event for event in events
            if event.get("subtype") == "started"
            and "editToolCall" in (event.get("tool_call") or {})
        )
        forgotten = json.loads(json.dumps(started))
        forgotten["tool_call"]["editToolCall"]["args"]["path"] = str(self.root / "other.txt")
        events.insert(events.index(started), forgotten)
        self.assert_deny_stream_rejected(events, "ambiguous write event")

    def test_duplicate_write_completion_is_ambiguous(self) -> None:
        events = observed_deny_stream(str(self.root / "denied.txt"))
        completed = next(
            event for event in events
            if event.get("subtype") == "completed"
            and "editToolCall" in (event.get("tool_call") or {})
        )
        events.insert(events.index(completed) + 1, json.loads(json.dumps(completed)))
        self.assert_deny_stream_rejected(events, "ambiguous write event")

    def test_deny_precedence_requires_every_shell_call_to_be_denied(self) -> None:
        def shell_events(events: list[dict], subtype: str) -> list[dict]:
            return [e for e in events if e.get("subtype") == subtype and "shellToolCall" in e.get("tool_call", {})]

        events = observed_deny_stream(str(self.root / "denied.txt"))
        self.assertEqual(1, len(shell_events(events, "completed")))
        shell_events(events, "completed")[0]["tool_call"]["shellToolCall"]["result"] = {"success": {"exitCode": 0}}
        self.assert_deny_stream_rejected(events, "ran a shell command despite the project deny")
        events = observed_deny_stream(str(self.root / "denied.txt"))
        events.remove(shell_events(events, "completed")[0])
        self.assert_deny_stream_rejected(events, "left a shell command without a denial")
        events = observed_deny_stream(str(self.root / "denied.txt"))
        duplicate = json.loads(json.dumps(shell_events(events, "started")[0]))
        events.insert(events.index(shell_events(events, "started")[0]), duplicate)
        self.assert_deny_stream_rejected(events, "ambiguous shell event")

    def test_deny_precedence_rejects_events_naming_several_tools(self) -> None:
        events = observed_deny_stream(str(self.root / "denied.txt"))
        completed = next(e for e in events if e.get("subtype") == "completed" and "editToolCall" in e["tool_call"])
        completed["tool_call"]["shellToolCall"] = {"result": {"success": {"exitCode": 0}}}
        self.assert_deny_stream_rejected(events, "ambiguous write event")
        events = observed_deny_stream(str(self.root / "denied.txt"))
        started = next(e for e in events if e.get("subtype") == "started" and "editToolCall" in e["tool_call"])
        started["tool_call"]["shellToolCall"] = {"args": {"command": "echo"}}
        self.assert_deny_stream_rejected(events, "ambiguous")

    def test_deny_precedence_rejects_other_completions_and_unmatched_calls(self) -> None:
        cases = {
            "success": {"success": {"path": "denied.txt"}},
            "denial plus success": {"writePermissionDenied": {}, "success": {}},
            "legacy invented key": {"denied": {"reason": "policy"}},
        }
        for name, outcome in cases.items():
            with self.subTest(name=name):
                events = observed_deny_stream(str(self.root / "denied.txt"))
                completed = next(e for e in events if e.get("subtype") == "completed" and "editToolCall" in e.get("tool_call", {}))
                completed["tool_call"]["editToolCall"]["result"] = outcome
                stream = "\n".join(json.dumps(item) for item in events)
                with self.assertRaisesRegex(live.HarnessError, "other than policy"):
                    live.require_denied_write_attempt(
                        live.CommandResult([], 0, stream, ""), self.root, "denied.txt", "deny"
                    )
        events = observed_deny_stream(str(self.root / "denied.txt"))
        for event in events:
            if event.get("subtype") == "completed" and "editToolCall" in event.get("tool_call", {}):
                event["call_id"] = "unmatched"
        stream = "\n".join(json.dumps(item) for item in events)
        with self.assertRaisesRegex(live.HarnessError, "ambiguous"):
            live.require_denied_write_attempt(
                live.CommandResult([], 0, stream, ""), self.root, "denied.txt", "deny"
            )
        events = observed_deny_stream(str(self.root / "other.txt"))
        stream = "\n".join(json.dumps(item) for item in events)
        with self.assertRaisesRegex(live.HarnessError, "other than policy"):
            live.require_denied_write_attempt(
                live.CommandResult([], 0, stream, ""), self.root, "denied.txt", "deny"
            )

    def test_deny_precedence_rejects_an_outside_workspace_attempt(self) -> None:
        stream = "\n".join(json.dumps(item) for item in [
            *observed_deny_stream(str(self.root.parent / "denied.txt")),
        ])
        with self.assertRaisesRegex(live.HarnessError, "outside"):
            live.require_denied_write_attempt(
                live.CommandResult([], 0, stream, ""), self.root, "denied.txt", "deny"
            )

    def test_deny_precedence_rejects_non_policy_tool_errors(self) -> None:
        stream = "\n".join(json.dumps(item) for item in [
            {"type": "tool_call", "subtype": "started", "call_id": "call-1", "tool_call": {"editToolCall": {"args": {"path": "denied.txt"}}}},
            {"type": "tool_call", "subtype": "completed", "call_id": "call-1", "tool_call": {"editToolCall": {"result": {"error": {"error": "disk full"}}}}},
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
                stream = observed_deny_stream(str(workspace / "denied.txt"))
                return live.CommandResult([], 0, "\n".join(json.dumps(item) for item in stream), "")
            if "allowed.txt" in prompt:
                (workspace / "allowed.txt").write_text("ALLOWED_CONTROL\n", encoding="utf-8")
                return live.CommandResult([], 0, json_result("written"), "")
            return live.CommandResult([], 0, json_result("ok"), "")

        harness = live.CursorHarness(
            self.binary, "v1", "a" * 40, runner=runner,
            user_cli_config=self.root / "missing" / "cli-config.json",
        )
        evidence = harness.execute()
        self.assertEqual("completed", evidence.workspace_cleanup)
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
