from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from adapters.openclaw import live_conformance as live


class OpenClawLiveHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.scratch = Path(self.temporary.name)
        self.repo = self.scratch / "repo"
        self.state = self.scratch / "state"
        self.workspace = self.scratch / "workspace"
        self.evidence = self.scratch / "evidence" / "result.json"
        self.claude = self.scratch / "claude.exe"
        self.bash = self.scratch / "bash.exe"
        self.claude.write_bytes(b"fixture")
        self.bash.write_bytes(b"fixture")
        self.repo.mkdir()
        (self.repo / live.DISPOSABLE_MARKER).write_text("disposable\n", encoding="utf-8")

    def harness(self, **overrides: object) -> live.LiveHarness:
        kwargs: dict[str, object] = {
            "binary": "openclaw", "expected_version": "OpenClaw fixture",
            "repo": self.repo, "state": self.state, "workspace": self.workspace,
            "evidence_path": self.evidence, "port": 18789,
            "claude_binary": self.claude, "bash_path": self.bash,
        }
        kwargs.update(overrides)
        return live.LiveHarness(**kwargs)  # type: ignore[arg-type]

    def test_parser_requires_risk_acknowledgements_and_external_bash(self) -> None:
        parser = live.build_parser()
        common = [
            "--expected-version", "OpenClaw fixture", "--repo", str(self.repo),
            "--state-dir", str(self.state), "--private-workspace", str(self.workspace),
            "--evidence", str(self.evidence), "--port", "18789",
            "--claude-binary", str(self.claude), "--bash-path", str(self.bash),
        ]
        with self.assertRaises(SystemExit):
            parser.parse_args(common)
        parsed = parser.parse_args(common + [
            "--acknowledge-external-model-egress", "--acknowledge-disposable-repo",
        ])
        self.assertTrue(parsed.acknowledge_external_model_egress)
        self.assertEqual(self.bash, parsed.bash_path)

    def test_paths_require_exact_disposable_marker(self) -> None:
        (self.repo / live.DISPOSABLE_MARKER).write_text("not enough", encoding="utf-8")
        with self.assertRaisesRegex(live.HarnessError, "sanitized disposable"):
            live.validate_paths(self.repo, self.state, self.workspace, self.evidence)

    def test_paths_reject_nested_private_state(self) -> None:
        with self.assertRaisesRegex(live.HarnessError, "separate, non-nested"):
            live.validate_paths(self.repo, self.repo / "state", self.workspace, self.evidence)

    def test_harness_requires_unused_state_and_private_workspace(self) -> None:
        self.state.mkdir()
        with self.assertRaisesRegex(live.HarnessError, "state directory must not exist"):
            self.harness()

    def test_linked_path_is_rejected_when_supported(self) -> None:
        target = self.scratch / "actual"
        target.mkdir()
        link = self.scratch / "linked"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("symbolic links are unavailable")
        with self.assertRaisesRegex(live.HarnessError, "symbolic-link or reparse-point"):
            live.reject_linked_path(link / "child", "fixture")

    def test_config_binds_plugin_alias_to_exact_paths(self) -> None:
        target = live.write_openclaw_config(
            self.state, self.workspace, 18789, self.claude, self.repo, self.bash, "fixture-token",
        )
        config = json.loads(target.read_text(encoding="utf-8"))
        defaults = config["agents"]["defaults"]
        plugin = config["plugins"]["entries"]["context-os"]
        self.assertEqual(list(live.LIFECYCLE_SKILLS), defaults["skills"])
        self.assertEqual(live.MODEL_ROUTE, defaults["model"]["primary"])
        self.assertEqual(str(self.claude), defaults["cliBackends"]["claude-cli"]["command"])
        self.assertEqual(["--safe-mode"], defaults["cliBackends"]["claude-cli"]["args"])
        self.assertEqual(
            {"root": str(self.repo), "bashPath": str(self.bash)},
            plugin["config"]["projects"][live.PROJECT_ALIAS],
        )
        self.assertTrue(plugin["enabled"])
        self.assertEqual({"mode": "token", "token": "fixture-token"}, config["gateway"]["auth"])
        self.assertEqual(["context-os"], config["plugins"]["allow"])
        self.assertFalse(config["hooks"]["internal"]["enabled"])
        with self.assertRaisesRegex(live.HarnessError, "refusing to overwrite"):
            live.write_openclaw_config(
                self.state, self.workspace, 18789, self.claude, self.repo, self.bash, "fixture-token",
            )

    def test_plugin_install_command_uses_local_package(self) -> None:
        self.assertEqual(
            ["node", "openclaw.mjs", "plugins", "install", "C:\\fixture\\plugin"],
            live.plugin_install_command(
                ("node", "openclaw.mjs"), Path("C:\\fixture\\plugin"),
            ),
        )

    def test_gateway_call_command_is_exact_and_closed(self) -> None:
        command = live.gateway_call_command(
            ("node", "openclaw.mjs"), 18789, "contextos.run",
            {"scenario": live.CONFORMANCE_SCENARIO, "action": "setup", "alias": "fixture"},
            10000, "fixture-token",
        )
        self.assertEqual(["node", "openclaw.mjs", "gateway", "call", "contextos.run"], command[:5])
        self.assertEqual(
            '{"action":"setup","alias":"fixture","scenario":"synthetic-conformance-v1"}',
            command[command.index("--params") + 1],
        )
        self.assertEqual("ws://127.0.0.1:18789", command[command.index("--url") + 1])
        self.assertEqual("fixture-token", command[command.index("--token") + 1])
        self.assertEqual("--json", command[-1])
        with self.assertRaisesRegex(live.HarnessError, r"only contextos\.\*"):
            live.gateway_call_command(("openclaw",), 18789, "agent", {}, 1000, "fixture-token")

    def test_gateway_result_requires_successful_json_object(self) -> None:
        result = live.CommandResult(["openclaw"], 0, '{"runId":"r1"}', "")
        self.assertEqual({"runId": "r1"}, live.parse_gateway_result(result, "contextos.run"))
        with self.assertRaisesRegex(live.HarnessError, "did not return JSON"):
            live.parse_gateway_result(live.CommandResult([], 0, "no", ""), "contextos.run")
        with self.assertRaisesRegex(live.HarnessError, "failed"):
            live.parse_gateway_result(live.CommandResult([], 1, "", "denied"), "contextos.run")

    def test_lifecycle_uses_only_owned_gateway_methods_and_fixed_scenario(self) -> None:
        harness = self.harness()
        calls: list[tuple[str, dict[str, object], int]] = []
        responses = iter([
            {"runId": "run-1", "sessionKey": "session-1"},
            {"status": "ok"},
            {"text": 'CONTEXTOS_LIVE_RESULT={"status":"started"}'},
        ])

        def fake_call(method: str, params: dict[str, object], timeout_ms: int = 10000) -> dict[str, object]:
            calls.append((method, params, timeout_ms))
            return next(responses)

        harness.gateway_call = fake_call  # type: ignore[method-assign]
        self.assertEqual({"status": "started"}, harness.lifecycle("start"))
        self.assertEqual(
            ("contextos.run", {
                "alias": "fixture", "action": "start",
                "scenario": "synthetic-conformance-v1",
            }, 10000),
            calls[0],
        )
        self.assertEqual(("contextos.wait", {"runId": "run-1", "timeoutMs": 700000}, 710000), calls[1])
        self.assertEqual(("contextos.result", {"sessionKey": "session-1"}, 10000), calls[2])

    def test_lifecycle_rejects_failed_wait(self) -> None:
        harness = self.harness()
        harness.gateway_call = mock.Mock(side_effect=[
            {"runId": "run-1", "sessionKey": "session-1"}, {"status": "error"},
        ])
        with self.assertRaisesRegex(live.HarnessError, "status 'error'"):
            harness.lifecycle("setup")

    def test_source_contains_no_acp_lifecycle_execution(self) -> None:
        source = Path(live.__file__).read_text(encoding="utf-8")
        self.assertNotIn("session/prompt", source)
        self.assertNotIn("acp_server_command", source)
        self.assertIn("contextos.apply", source)

    def test_model_route_is_authenticated_claude_cli(self) -> None:
        config = live.openclaw_config(
            self.workspace, 18789, self.claude, self.repo, self.bash, "fixture-token",
        )
        self.assertEqual("claude-cli/claude-sonnet-5", live.MODEL_ROUTE)
        self.assertTrue(config["plugins"]["entries"]["anthropic"]["enabled"])

    def test_execution_policy_transitions(self) -> None:
        target = live.write_openclaw_config(
            self.state, self.workspace, 18789, self.claude, self.repo, self.bash, "fixture-token",
        )
        live.set_execution_policy(target, "deny")
        self.assertEqual(
            {"host": "gateway", "security": "deny"},
            json.loads(target.read_text(encoding="utf-8"))["tools"]["exec"],
        )
        live.set_execution_policy(target, "full", "off")
        self.assertEqual(
            {"host": "gateway", "security": "full", "ask": "off"},
            json.loads(target.read_text(encoding="utf-8"))["tools"]["exec"],
        )

    def test_exec_policy_preset_commands_are_closed(self) -> None:
        self.assertEqual(
            ["openclaw", "exec-policy", "preset", "yolo", "--json"],
            live.exec_policy_preset_command(("openclaw",), "yolo"),
        )
        with self.assertRaisesRegex(live.HarnessError, "unsupported"):
            live.exec_policy_preset_command(("openclaw",), "custom")

    def test_execute_always_stops_gateway(self) -> None:
        harness = self.harness()
        harness._execute_unprotected = mock.Mock(side_effect=live.HarnessError("fixture"))
        harness.stop_gateway = mock.Mock()
        with self.assertRaisesRegex(live.HarnessError, "fixture"):
            harness.execute()
        harness.stop_gateway.assert_called_once_with()

    def test_parse_result_requires_one_explicit_marker(self) -> None:
        self.assertEqual(
            {"status": "started"},
            live.parse_lifecycle_result({"text": 'CONTEXTOS_LIVE_RESULT={"status":"started"}'}),
        )
        with self.assertRaisesRegex(live.HarnessError, "exactly one"):
            live.parse_lifecycle_result("ordinary agent prose")

    def test_wrong_digest_control_requires_kernel_diagnostic(self) -> None:
        expected = live.CommandResult([], 1, "", "--confirm must exactly match the proposal_digest\n")
        self.assertTrue(live.is_wrong_digest_rejection(expected))
        self.assertFalse(live.is_wrong_digest_rejection(live.CommandResult([], 127, "", "not found")))
        self.assertFalse(live.is_wrong_digest_rejection(live.CommandResult([], 0, expected.stderr, "")))

    def test_source_commit_binding_requires_a_clean_worktree(self) -> None:
        live.require_clean_source(live.CommandResult([], 0, "", ""))
        with self.assertRaisesRegex(live.HarnessError, "one exact commit"):
            live.require_clean_source(live.CommandResult([], 0, " M adapters/openclaw/plugin/lib.js\n", ""))
        with self.assertRaisesRegex(live.HarnessError, "could not verify"):
            live.require_clean_source(live.CommandResult([], 1, "", "fatal"))

    def test_deny_control_accepts_only_an_explicit_non_success_result(self) -> None:
        self.assertTrue(live.is_explicit_lifecycle_denial(
            'exec policy denied tool use\nCONTEXTOS_LIVE_RESULT={"status":"blocked"}'
        ))
        self.assertTrue(live.is_explicit_lifecycle_denial("permission denied"))
        self.assertFalse(live.is_explicit_lifecycle_denial(
            'blocked was mentioned\nCONTEXTOS_LIVE_RESULT={"status":"started"}'
        ))
        self.assertFalse(live.is_explicit_lifecycle_denial("ordinary response"))

    def test_proposal_rejects_escape_and_invalid_digest(self) -> None:
        with self.assertRaisesRegex(live.HarnessError, "lowercase SHA-256"):
            live.require_proposal({"proposal": "p.json", "digest": "ABC"})
        with self.assertRaisesRegex(live.HarnessError, "unsafe proposal"):
            live.require_proposal({"proposal": "../p.json", "digest": "a" * 64})

    def test_operator_must_type_exact_digest(self) -> None:
        live.require_operator_digest("a" * 64, "setup", lambda _: "a" * 64)
        with self.assertRaisesRegex(live.HarnessError, "not approved"):
            live.require_operator_digest("a" * 64, "setup", lambda _: "b" * 64)

    def test_redaction_removes_sensitive_fields_and_paths(self) -> None:
        value = {"apiToken": "secret", "workspace": str(self.workspace), "nested": {"message": "prompt", "ok": True}}
        cleaned = live.redact(value, (self.workspace,))
        serialized = json.dumps(cleaned)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("prompt", serialized)
        self.assertNotIn(str(self.workspace), serialized)
        self.assertTrue(cleaned["nested"]["ok"])

    def test_missing_sync_helper_fails_clearly(self) -> None:
        with mock.patch.object(live.importlib.util, "spec_from_file_location", return_value=None):
            with self.assertRaisesRegex(live.HarnessError, r"sync\(workspace\)"):
                live.load_sync_helper()

    def test_repository_snapshot_ignores_bytecode(self) -> None:
        before = live.repository_snapshot(self.repo)
        cache = self.repo / "contextos/__pycache__"
        cache.mkdir(parents=True)
        (cache / "kernel.pyc").write_bytes(b"cache")
        self.assertEqual(before, live.repository_snapshot(self.repo))


if __name__ == "__main__":
    unittest.main()
