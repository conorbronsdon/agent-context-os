from __future__ import annotations

import os
import json
import shutil
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest import mock

from adapters.hermes import live_conformance as live


ROOT = Path(__file__).resolve().parents[1]


def hermes_start_contract(evidence: dict, manifest: dict) -> str:
    if evidence["source_sha"] != manifest["source_sha"] or evidence["fixture_commit"] != manifest["fixture_commit"]:
        raise AssertionError("Hermes evidence does not match fixture source and commit")
    return live.prompt_for("start")


def hermes_start_stream(output: str, canaries: dict[str, str]) -> None:
    _events, assistant, _skills, self_read = live.stream_evidence(output, canaries, "start")
    if self_read:
        raise AssertionError("self-read: discovery not shown")
    for name in ("agents", "context-start"):
        if canaries[name] not in assistant:
            raise AssertionError(f"canary not reported: {name}")


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
        environment = live.hermes_environment(Path(home_name), evidence["provider"])
        version = subprocess.run([binary, "--version"], cwd=fixture, env=environment,
                                 text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(0, version.returncode, version.stderr)
        self.assertEqual(evidence["version"], version.stdout.splitlines()[0])
        command = [binary, "chat", "--format", "stream-json", "-Q", "--source", "tool", "-m", evidence["model"],
                   "--provider", evidence["provider"], "--run-budget", "120", "--max-turns", "20", "-q", prompt]
        result = subprocess.run(command, cwd=fixture, env=environment, text=True,
                                capture_output=True, timeout=150, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        stream_canaries = {**manifest["canaries"], **{f"native-{name}": marker
                                                   for name, marker in manifest.get("native_memory_canaries", {}).items()}}
        hermes_start_stream(result.stdout, stream_canaries)

    def test_hermes_start_contract_uses_source_bound_prompt(self) -> None:
        evidence = {"source_sha": "a" * 40, "fixture_commit": "b" * 40}
        self.assertEqual(live.prompt_for("start"), hermes_start_contract(evidence, evidence))
        with self.assertRaisesRegex(AssertionError, "does not match"):
            hermes_start_contract(evidence, {"source_sha": "c" * 40, "fixture_commit": "b" * 40})

    def test_hermes_start_stream_rejects_self_read(self) -> None:
        canaries = {"agents": "agents-canary", "context-start": "start-canary", "native-USER.md": "memory-canary"}
        events = [
            {"type": "tool_use", "name": "skill_view", "input": {"name": "context-start"}},
            {"type": "tool_result", "name": "skill_view", "output": "start-canary"},
            {"type": "result", "text": "agents-canary start-canary"},
        ]
        raw = "\n".join(json.dumps(event) for event in events)
        hermes_start_stream(raw, canaries)
        events.insert(2, {"type": "tool_use", "name": "terminal", "input": {"command": "cat AGENTS.md"}})
        with self.assertRaisesRegex(AssertionError, "self-read"):
            hermes_start_stream("\n".join(json.dumps(event) for event in events), canaries)
        events = events[:2] + [{"type": "tool_result", "name": "terminal", "output": "memory-canary"}, events[-1]]
        with self.assertRaisesRegex(AssertionError, "self-read"):
            hermes_start_stream("\n".join(json.dumps(event) for event in events), canaries)

    def test_hermes_launch_uses_filtered_environment_and_stream(self) -> None:
        base = ROOT / ".hermes-test-root" / uuid.uuid4().hex
        base.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        evidence = {"source_sha": "a" * 40, "fixture_commit": "b" * 40,
                    "controls": {"run": "passed"}, "version": "Hermes Agent v0.21.4",
                    "model": "fixture/model", "provider": "openrouter"}
        manifest = {"source_sha": evidence["source_sha"], "fixture_commit": evidence["fixture_commit"],
                    "canaries": {"agents": "agents-canary", "context-start": "start-canary"},
                    "native_memory_canaries": {"USER.md": "memory-canary"}}
        (base / "evidence.json").write_text(json.dumps(evidence))
        (base / "manifest.json").write_text(json.dumps(manifest))
        variables = {"CONTEXT_OS_RUNTIME_TESTS": "1", "CONTEXTOS_HERMES_FIXTURE": str(base),
                     "CONTEXTOS_HERMES_HOME": str(base / "home"),
                     "CONTEXTOS_HERMES_EVIDENCE": str(base / "evidence.json"),
                     "CONTEXTOS_HERMES_MANIFEST": str(base / "manifest.json"),
                     "OPENROUTER_API_KEY": "fixture-provider", "UNRELATED_API_KEY": "fixture-unrelated"}
        events = [
            {"type": "tool_use", "name": "skill_view", "input": {"name": "context-start"}},
            {"type": "tool_result", "name": "skill_view", "output": "start-canary"},
            {"type": "result", "text": "agents-canary start-canary"},
        ]
        def fake_run(argv, **kwargs):
            self.assertNotIn("UNRELATED_API_KEY", kwargs["env"])
            self.assertEqual("fixture-provider", kwargs["env"]["OPENROUTER_API_KEY"])
            if "chat" in argv:
                self.assertIn("--format", argv)
                self.assertEqual(live.prompt_for("start"), argv[-1])
                return subprocess.CompletedProcess(argv, 0, "\n".join(json.dumps(e) for e in events), "")
            return subprocess.CompletedProcess(argv, 0, evidence["version"] + "\n", "")
        with mock.patch.dict(os.environ, variables), mock.patch.object(shutil, "which", return_value="hermes"), mock.patch.object(subprocess, "run", side_effect=fake_run):
            self.test_hermes_discovers_contract()
            events.insert(2, {"type": "tool_result", "name": "terminal", "output": "memory-canary"})
            with self.assertRaisesRegex(AssertionError, "self-read"):
                self.test_hermes_discovers_contract()


if __name__ == "__main__":
    unittest.main()
