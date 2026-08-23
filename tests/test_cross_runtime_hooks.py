from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/context-os-hook.py"


class CrossRuntimeHookTest(unittest.TestCase):
    def run_hook(self, runtime: str, event: str, payload: dict) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(WRAPPER), runtime, event],
            cwd=ROOT,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_codex_adapter_declares_session_and_pre_write_events(self) -> None:
        config = json.loads((ROOT / ".codex/hooks.json").read_text(encoding="utf-8"))
        self.assertEqual({"SessionStart", "PreToolUse"}, set(config["hooks"]))
        serialized = json.dumps(config)
        self.assertIn("context-os-hook.py", serialized)
        self.assertIn("commandWindows", serialized)
        self.assertIn("powershell.exe", serialized)
        pre_tool = config["hooks"]["PreToolUse"][0]
        self.assertEqual("^apply_patch$", pre_tool["matcher"])

    def test_codex_pre_write_must_fire_control(self) -> None:
        result = self.run_hook(
            "codex", "pre-write", {"tool_input": {"file_path": str(ROOT / "state/current.md")}}
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("proposal/apply", json.loads(result.stdout)["systemMessage"])

    def test_codex_pre_write_must_not_fire_control(self) -> None:
        result = self.run_hook(
            "codex", "pre-write", {"tool_input": {"file_path": str(ROOT / "README.md")}}
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)

    def test_codex_real_apply_patch_payload_and_relative_path_fire(self) -> None:
        patch = "*** Begin Patch\n*** Update File: state/current.md\n@@\n-old\n+new\n*** End Patch"
        result = self.run_hook("codex", "pre-write", {"tool_input": {"command": patch}})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("proposal/apply", json.loads(result.stdout)["systemMessage"])

    def test_hermes_adapter_allows_with_advisory(self) -> None:
        result = self.run_hook(
            "hermes", "pre-write", {"args": {"path": str(ROOT / "state/decisions.md")}}
        )
        output = json.loads(result.stdout)
        self.assertEqual("allow", output["action"])
        self.assertIn("append-only", output["message"])

    def test_malformed_input_is_visible_and_advisory(self) -> None:
        result = subprocess.run(
            [sys.executable, str(WRAPPER), "codex", "pre-write"],
            cwd=ROOT,
            input="not-json",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode)
        self.assertIn("could not run", json.loads(result.stdout)["systemMessage"])


if __name__ == "__main__":
    unittest.main()
