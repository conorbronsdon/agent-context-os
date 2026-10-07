from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODULE_PATH = ROOT / "adapters/devin/cli_hook_conformance.py"
SPEC = importlib.util.spec_from_file_location("contextos_devin_cli_hooks", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
hooks = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = hooks
SPEC.loader.exec_module(hooks)


@unittest.skipIf(os.name == "nt", "the probe command is POSIX; the harness refuses native Windows")
class HookProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.log, self.command = hooks.write_probe(self.base)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_probe(self, payload: object, *, project_dir: bool = True) -> subprocess.CompletedProcess[str]:
        environment = {"PATH": "/usr/bin:/bin"}
        if project_dir:
            environment["DEVIN_PROJECT_DIR"] = str(self.base)
        return subprocess.run(
            self.command, shell=True, input=json.dumps(payload), text=True,
            capture_output=True, check=False, env=environment,
        )

    def test_probe_logs_only_event_tool_and_target(self) -> None:
        result = self.run_probe({
            "hook_event_name": "PreToolUse", "tool_name": "write", "session_id": "secret-session",
            "tool_input": {"file_path": "state/current.md", "content": "raw content"},
        })
        self.assertEqual(0, result.returncode, result.stderr)
        entries = hooks.read_hook_log(self.log)
        self.assertEqual(
            [{"event": "PreToolUse", "tool": "write", "target": "state/current.md", "project_dir_set": True}],
            entries,
        )
        self.assertNotIn("raw content", self.log.read_text(encoding="utf-8"))
        self.assertNotIn("secret-session", self.log.read_text(encoding="utf-8"))
        hooks.require_hook_event(entries, "PreToolUse", tool="write", target="state/current.md")

    def test_probe_blocks_only_the_synthetic_target_with_exit_two(self) -> None:
        blocked = self.run_probe({"hook_event_name": "PreToolUse", "tool_name": "write",
                                  "tool_input": {"file_path": hooks.BLOCKED_TARGET}})
        self.assertEqual(2, blocked.returncode)
        allowed = self.run_probe({"hook_event_name": "PreToolUse", "tool_name": "write",
                                  "tool_input": {"file_path": "allowed/probe.txt"}})
        self.assertEqual(0, allowed.returncode)
        session = self.run_probe({"hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual(0, session.returncode)
        self.assertEqual(["PreToolUse", "PreToolUse", "SessionStart"],
                         [entry["event"] for entry in hooks.read_hook_log(self.log)])

    def test_malformed_payload_is_logged_without_blocking(self) -> None:
        result = subprocess.run(self.command, shell=True, input="not-json", text=True,
                                capture_output=True, check=False)
        self.assertEqual(0, result.returncode)
        self.assertEqual(None, hooks.read_hook_log(self.log)[0]["event"])

    def test_hook_event_requires_devin_project_dir_and_matching_action(self) -> None:
        self.run_probe({"hook_event_name": "SessionStart"}, project_dir=False)
        entries = hooks.read_hook_log(self.log)
        with self.assertRaises(hooks.HarnessError):
            hooks.require_hook_event(entries, "SessionStart")
        with self.assertRaises(hooks.HarnessError):
            hooks.require_hook_event([], "PreToolUse")
        with self.assertRaises(hooks.HarnessError):
            hooks.require_hook_event(
                [{"event": "PreToolUse", "tool": "edit", "target": "a.txt", "project_dir_set": True}],
                "PreToolUse", tool="write",
            )


class InjectedNoticeTest(unittest.TestCase):
    def trajectory(self, *steps: dict) -> object:
        numbered = [dict(step, step_id=index + 1) for index, step in enumerate(steps)]
        return hooks.Trajectory({"schema_version": "ATIF-v1.7",
                                 "agent": {"name": "devin", "version": "1"}, "steps": numbered}, "1")

    def test_notice_must_be_a_system_step_after_the_tool_call(self) -> None:
        write = {"source": "agent", "message": "", "observation": {"results": []},
                 "tool_calls": [{"tool_call_id": "c1", "function_name": "write", "arguments": {}}]}
        notice = {"source": "system", "message": hooks.WRITE_NOTICE + " so invariants hold."}
        user = {"source": "user", "message": hooks.WRITE_NOTICE}
        self.assertTrue(hooks.injected_notice(self.trajectory(user, write, notice), hooks.WRITE_NOTICE,
                                              after_tool="write"))
        self.assertFalse(hooks.injected_notice(self.trajectory(notice, write, user), hooks.WRITE_NOTICE,
                                               after_tool="write"))
        self.assertFalse(hooks.injected_notice(self.trajectory(user, notice), hooks.WRITE_NOTICE,
                                               after_tool="write"))
        self.assertTrue(hooks.injected_notice(self.trajectory(notice, user), hooks.WRITE_NOTICE))

    def call(self, name: str, arguments: dict, observation: str, call_id: str = "c1") -> dict:
        return {"source": "agent", "message": "",
                "tool_calls": [{"tool_call_id": call_id, "function_name": name, "arguments": arguments}],
                "observation": {"results": [{"source_call_id": call_id, "content": observation}]}}

    def test_blocking_control_requires_the_probe_rejection(self) -> None:
        self.assertIn(hooks.PROBE_BLOCK_MESSAGE, hooks.PROBE_SOURCE)
        arguments = {"file_path": hooks.BLOCKED_TARGET, "content": "x"}
        hooks.require_probe_blocked(self.trajectory(
            self.call("write", arguments, "Tool rejected: " + hooks.PROBE_BLOCK_MESSAGE)))
        for trajectory in (
            self.trajectory(self.call("write", arguments, "Tool execution was rejected by the user")),
            self.trajectory(self.call("write", {"file_path": "other.txt"}, hooks.PROBE_BLOCK_MESSAGE)),
        ):
            with self.assertRaises(hooks.HarnessError):
                hooks.require_probe_blocked(trajectory)

    def test_allowlist_control_requires_expansion_and_the_exact_command(self) -> None:
        expanded = {"source": "user", "message": hooks.ALLOWLIST_BODY}
        command = {"command": f"bash {hooks.MARKER_SCRIPT}"}
        hooks.require_allowlisted_exec(self.trajectory(
            expanded, self.call("exec", command, "Output\n\nExit code: 0")))
        for trajectory in (
            self.trajectory({"source": "user", "message": "/skill"},
                            self.call("exec", command, "Exit code: 0")),
            self.trajectory(expanded, self.call("exec", {"command": f"cat x; bash {hooks.MARKER_SCRIPT}"},
                                                "Exit code: 0")),
            self.trajectory(expanded, self.call("exec", command, "Exit code: 1")),
            self.trajectory(expanded, self.call("exec", command, "Exit code: 0"),
                            self.call("exec", command, "Exit code: 0", call_id="c2")),
        ):
            with self.assertRaises(hooks.HarnessError):
                hooks.require_allowlisted_exec(trajectory)


class FixtureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_probe_hooks_use_the_shipped_write_matcher(self) -> None:
        shipped = json.loads(hooks.SHIPPED_HOOKS.read_text(encoding="utf-8"))
        probe = hooks.probe_hooks("probe")
        self.assertLessEqual(set(shipped), set(probe))
        self.assertEqual(shipped["PostToolUse"][0]["matcher"], probe["PostToolUse"][0]["matcher"])
        self.assertEqual(shipped["PostToolUse"][0]["matcher"], probe["PreToolUse"][0]["matcher"])

    def test_local_config_never_touches_shipped_files(self) -> None:
        hooks.write_local_config(self.root, {"deny": ["exec"]}, hooks.probe_hooks("probe"))
        local = json.loads((self.root / ".devin/config.local.json").read_text(encoding="utf-8"))
        self.assertEqual({"deny": ["exec"]}, local["permissions"])
        self.assertEqual({"SessionStart", "PreToolUse", "PostToolUse"}, set(local["hooks"]))
        self.assertFalse((self.root / ".devin/config.json").exists())
        self.assertFalse((self.root / ".devin/hooks.v1.json").exists())

    def test_shipped_hooks_check_requires_exact_bytes(self) -> None:
        (self.root / ".devin").mkdir()
        for name in ("config.json", "hooks.v1.json"):
            (self.root / ".devin" / name).write_bytes((ROOT / ".devin" / name).read_bytes())
        hooks.require_shipped_hooks(self.root)
        (self.root / ".devin/hooks.v1.json").write_text("{}\n", encoding="utf-8")
        with self.assertRaises(hooks.HarnessError):
            hooks.require_shipped_hooks(self.root)

    def test_allowlist_fixture_differs_only_by_allowed_tools(self) -> None:
        hooks.write_allowlist_fixture(self.root, "TOKEN")
        allowed = (self.root / ".agents/skills" / hooks.ALLOWED_SKILL / "SKILL.md").read_text(encoding="utf-8")
        unlisted = (self.root / ".agents/skills" / hooks.UNLISTED_SKILL / "SKILL.md").read_text(encoding="utf-8")
        for text in (allowed, unlisted):
            self.assertIn('triggers: ["user"]', text)
            self.assertIn(f"bash {hooks.MARKER_SCRIPT}", text)
        self.assertIn("allowed-tools:\n  - exec\n", allowed)
        self.assertNotIn("allowed-tools", unlisted)
        self.assertNotIn(b"\r", (self.root / hooks.MARKER_SCRIPT).read_bytes())
        if os.name == "nt":
            return
        subprocess.run(["bash", hooks.MARKER_SCRIPT], cwd=self.root, check=True)
        self.assertEqual(["TOKEN"], (self.root / hooks.MARKER_FILE).read_text(encoding="utf-8").splitlines())

    def test_shipped_hooks_are_owned_by_the_devin_component(self) -> None:
        manifest = json.loads((ROOT / "components/manifest.json").read_text(encoding="utf-8"))
        component = next(item for item in manifest["components"] if item["id"] == "devin-adapter")
        self.assertIn({"path": ".devin/hooks.v1.json", "policy": "managed"}, component["paths"])
        self.assertIn({"path": "adapters/devin/cli_hook_conformance.py", "policy": "managed"},
                      component["paths"])


if __name__ == "__main__":
    unittest.main()
