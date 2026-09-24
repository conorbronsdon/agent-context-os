from __future__ import annotations

import os
import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def hermes_start_contract(evidence: dict, manifest: dict) -> str:
    if evidence["source_sha"] != manifest["source_sha"] or evidence["fixture_commit"] != manifest["fixture_commit"]:
        raise AssertionError("Hermes evidence does not match fixture source and commit")
    return "/context-start"


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
        if os.environ.get("CONTEXT_OS_RUNTIME_TESTS") != "1":
            self.skipTest("set CONTEXT_OS_RUNTIME_TESTS=1 for installed-client launch")
        fixture_name = os.environ.get("CONTEXTOS_HERMES_FIXTURE")
        home_name = os.environ.get("CONTEXTOS_HERMES_HOME")
        evidence_name = os.environ.get("CONTEXTOS_HERMES_EVIDENCE")
        if not all((fixture_name, home_name, evidence_name)):
            self.skipTest("set CONTEXTOS_HERMES_FIXTURE, CONTEXTOS_HERMES_HOME, and CONTEXTOS_HERMES_EVIDENCE")
        binary = shutil.which("hermes")
        if not binary:
            self.skipTest("hermes is not installed")
        fixture = Path(fixture_name)
        evidence = json.loads(Path(evidence_name).read_text(encoding="utf-8"))
        manifest_name = os.environ.get("CONTEXTOS_HERMES_MANIFEST")
        if not manifest_name:
            self.skipTest("set CONTEXTOS_HERMES_MANIFEST")
        manifest = json.loads(Path(manifest_name).read_text(encoding="utf-8"))
        prompt = hermes_start_contract(evidence, manifest)
        self.assertEqual("passed", evidence["controls"]["run"])
        environment = os.environ.copy()
        environment["HERMES_HOME"] = home_name
        version = subprocess.run([binary, "--version"], cwd=fixture, env=environment,
                                 text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(0, version.returncode, version.stderr)
        self.assertEqual(evidence["version"], version.stdout.splitlines()[0])
        command = [binary, "chat", "-Q", "--source", "tool", "-m", evidence["model"],
                   "--provider", evidence["provider"], "--run-budget", "120", "--max-turns", "20", "-q", prompt]
        result = subprocess.run(command, cwd=fixture, env=environment, text=True,
                                capture_output=True, timeout=150, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        for name in ("agents", "context-start"):
            self.assertIn(manifest["canaries"][name], result.stdout)

    def test_hermes_start_contract_uses_source_bound_bare_command(self) -> None:
        evidence = {"source_sha": "a" * 40, "fixture_commit": "b" * 40}
        self.assertEqual("/context-start", hermes_start_contract(evidence, evidence))
        with self.assertRaisesRegex(AssertionError, "does not match"):
            hermes_start_contract(evidence, {"source_sha": "c" * 40, "fixture_commit": "b" * 40})


if __name__ == "__main__":
    unittest.main()
