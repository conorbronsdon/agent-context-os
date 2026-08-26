from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/context-os-hook.py"
WINDOWS_WRAPPER = ROOT / "scripts/context-os-hook.ps1"


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
        self.assertIn("context-os-hook.sh", serialized)
        self.assertIn("context-os-hook.ps1", serialized)
        self.assertIn("commandWindows", serialized)
        self.assertIn("powershell.exe", serialized)
        self.assertNotIn("; python ", serialized)
        hermes_readme = (ROOT / "adapters/hermes/README.md").read_text(encoding="utf-8")
        self.assertIn("context-os-hook.ps1", hermes_readme)
        self.assertNotIn("; python ", hermes_readme)
        pre_tool = config["hooks"]["PreToolUse"][0]
        self.assertEqual("^apply_patch$", pre_tool["matcher"])

    @unittest.skipUnless(sys.platform == "win32", "native PowerShell adapter test")
    def test_windows_wrapper_honors_override_and_hook_controls(self) -> None:
        environment = os.environ.copy()
        environment.pop("CONTEXTOS_PYTHON", None)
        config = json.loads((ROOT / ".codex/hooks.json").read_text(encoding="utf-8"))
        production_pre_write = config["hooks"]["PreToolUse"][0]["hooks"][0]["commandWindows"]
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WINDOWS_WRAPPER),
            "codex",
            "pre-write",
        ]

        # Native Windows CI exercises the exact production command. When the
        # Python suite itself is launched below MSYS, use -File because the
        # parent shell changes stdin-handle behavior before PowerShell starts.
        must_fire_command = command if os.environ.get("MSYSTEM") else production_pre_write

        must_fire = subprocess.run(
            must_fire_command,
            cwd=ROOT,
            env=environment,
            input=json.dumps({"tool_input": {"file_path": str(ROOT / "state/current.md")}}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, must_fire.returncode, must_fire.stderr)
        self.assertIn("proposal/apply", json.loads(must_fire.stdout)["systemMessage"])

        with tempfile.TemporaryDirectory() as temporary_directory:
            fake_python = Path(temporary_directory) / "python.cmd"
            fake_python.write_text(
                '@echo off\nif "%~1"=="-c" exit /b 0\n'
                'echo {"systemMessage":"%~3 forwarded"}\n',
                encoding="utf-8",
            )
            environment["CONTEXTOS_PYTHON"] = str(fake_python)
            session_start = subprocess.run(
                [*command[:-1], "session-start"],
                cwd=ROOT,
                env=environment,
                input="{}",
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, session_start.returncode, session_start.stderr)
            self.assertEqual(
                "session-start forwarded",
                json.loads(session_start.stdout)["systemMessage"],
            )

            chatty_python = Path(temporary_directory) / "chatty-python.cmd"
            chatty_python.write_text(
                '@echo off\necho not-a-working-interpreter\nexit /b 1\n',
                encoding="utf-8",
            )
            environment["CONTEXTOS_PYTHON"] = str(chatty_python)
            rejected_chatty_override = subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                input="{}",
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, rejected_chatty_override.returncode)
            self.assertEqual("", rejected_chatty_override.stdout)
            self.assertIn("never silently replaced", rejected_chatty_override.stderr)

            stderr_python = Path(temporary_directory) / "stderr-python.cmd"
            stderr_python.write_text(
                '@echo off\nif "%~1"=="-c" (echo harmless-probe-warning 1>&2 & exit /b 0)\n'
                'echo {"systemMessage":"%~3 forwarded"}\n',
                encoding="utf-8",
            )
            environment["CONTEXTOS_PYTHON"] = str(stderr_python)
            accepted_stderr_override = subprocess.run(
                [*command[:-1], "session-start"],
                cwd=ROOT,
                env=environment,
                input="{}",
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, accepted_stderr_override.returncode, accepted_stderr_override.stderr)
            self.assertEqual(
                "session-start forwarded",
                json.loads(accepted_stderr_override.stdout)["systemMessage"],
            )

        environment["CONTEXTOS_PYTHON"] = sys.executable
        must_not_fire = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            input=json.dumps({"tool_input": {"file_path": str(ROOT / "README.md")}}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, must_not_fire.returncode, must_not_fire.stderr)
        self.assertEqual("", must_not_fire.stdout)

        environment["CONTEXTOS_PYTHON"] = str(ROOT / "no-such-python")
        invalid_override = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            input="{}",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(0, invalid_override.returncode)
        self.assertIn(str(ROOT / "no-such-python"), invalid_override.stderr)
        self.assertIn("never silently replaced", invalid_override.stderr)

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

    def test_cli_malformed_hermes_input_preserves_allow_envelope(self) -> None:
        result = subprocess.run(
            [
                sys.executable, "-m", "contextos", "--root", str(ROOT), "hook",
                "pre-write", "--runtime", "hermes",
            ],
            cwd=ROOT,
            input="not-json",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual("allow", output["action"])
        self.assertIn("could not run", output["message"])

    def test_cli_invalid_surface_remains_advisory(self) -> None:
        result = subprocess.run(
            [
                sys.executable, "-m", "contextos", "--root", str(ROOT), "hook",
                "pre-write", "--runtime", "hermes", "--surface", "bogus",
            ],
            cwd=ROOT,
            input="not-json",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual("allow", output["action"])
        self.assertIn("no surface 'bogus'", output["message"])


if __name__ == "__main__":
    unittest.main()
