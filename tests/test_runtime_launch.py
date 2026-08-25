from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeLaunchTest(unittest.TestCase):
    """Opt-in, read-only smoke tests against installed runtime processes."""

    def run_runtime(self, runtime: str) -> str:
        if os.environ.get("CONTEXT_OS_RUNTIME_TESTS") != "1":
            self.skipTest("set CONTEXT_OS_RUNTIME_TESTS=1 to launch authenticated runtimes")
        binary = shutil.which(runtime)
        if not binary:
            self.skipTest(f"{runtime} is not installed")
        prompt = (
            f"Read AGENTS.md and runtimes/{runtime}.json in this public fixture. "
            f"Do not write files or use external data. If the {runtime} manifest's cli surface declares "
            "setup, start, update, and end invocations and AGENTS.md requires proposal/apply, "
            f"reply with exactly CONTEXT_OS_RUNTIME={runtime}. Otherwise explain the mismatch."
        )
        if runtime == "claude":
            command = [
                binary, "-p", prompt, "--allowedTools", "Read,Glob,Grep",
                "--permission-mode", "plan", "--no-session-persistence", "--max-budget-usd", "0.50",
            ]
        elif runtime == "codex":
            command = [binary, "exec", "--sandbox", "read-only", prompt]
        else:
            command = [
                binary, "chat", "-q", prompt, "-Q", "--ignore-user-config",
                "--max-turns", "20", "--run-budget", "120", "--source", "tool",
            ]
        completed = subprocess.run(
            command, cwd=ROOT, text=True, capture_output=True, timeout=180, check=False
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        return completed.stdout

    def test_claude_discovers_contract(self) -> None:
        self.assertIn("CONTEXT_OS_RUNTIME=claude", self.run_runtime("claude"))

    def test_codex_discovers_contract(self) -> None:
        self.assertIn("CONTEXT_OS_RUNTIME=codex", self.run_runtime("codex"))

    def test_hermes_discovers_contract(self) -> None:
        self.assertIn("CONTEXT_OS_RUNTIME=hermes", self.run_runtime("hermes"))


if __name__ == "__main__":
    unittest.main()
