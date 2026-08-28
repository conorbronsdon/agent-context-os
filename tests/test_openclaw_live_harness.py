from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from adapters.openclaw import live_conformance as live

ROOT = Path(__file__).resolve().parents[1]


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
        self.claude.write_bytes(b"fixture")
        self.repo.mkdir()
        (self.repo / live.DISPOSABLE_MARKER).write_text("disposable\n", encoding="utf-8")

    def test_parser_requires_both_risk_acknowledgements(self) -> None:
        parser = live.build_parser()
        common = [
            "--expected-version", "OpenClaw fixture", "--repo", str(self.repo),
            "--state-dir", str(self.state), "--private-workspace", str(self.workspace),
            "--evidence", str(self.evidence), "--port", "18789",
            "--claude-binary", str(self.claude),
        ]
        with self.assertRaises(SystemExit):
            parser.parse_args(common)
        parsed = parser.parse_args(common + [
            "--acknowledge-external-model-egress", "--acknowledge-disposable-repo",
        ])
        self.assertTrue(parsed.acknowledge_external_model_egress)
        self.assertTrue(parsed.acknowledge_disposable_repo)

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
            live.LiveHarness(
                binary="openclaw", expected_version="OpenClaw fixture",
                repo=self.repo, state=self.state, workspace=self.workspace,
                evidence_path=self.evidence, port=18789, claude_binary=self.claude,
            )

    def test_harness_accepts_an_injected_acp_runner(self) -> None:
        fake = mock.Mock()
        harness = live.LiveHarness(
            binary="openclaw", expected_version="OpenClaw fixture",
            repo=self.repo, state=self.state, workspace=self.workspace,
            evidence_path=self.evidence, port=18789, claude_binary=self.claude,
            acp_runner=fake,
        )
        self.assertIs(fake, harness.acp_runner)
        self.assertEqual("1", harness.env["OPENCLAW_NO_RESPAWN"])
        self.assertEqual("1", harness.env["PYTHONDONTWRITEBYTECODE"])

    def test_rpc_prepends_the_execution_root_boundary(self) -> None:
        fake = mock.Mock(return_value=live.CommandResult(
            ["openclaw", "acp"], 0,
            'CONTEXTOS_LIVE_RESULT={"status":"started"}', "",
        ))
        harness = live.LiveHarness(
            binary="openclaw", expected_version="OpenClaw fixture",
            repo=self.repo, state=self.state, workspace=self.workspace,
            evidence_path=self.evidence, port=18789,
            claude_binary=self.claude, acp_runner=fake,
        )
        self.assertEqual({"status": "started"}, harness.rpc("fixture", "start"))
        sent_prompt = fake.call_args.args[3]
        self.assertTrue(sent_prompt.startswith(live.EXECUTION_ROOT_BOUNDARY))
        self.assertTrue(sent_prompt.endswith("\n\nfixture"))

    def test_rpc_can_run_a_non_repository_policy_control_without_boundary(self) -> None:
        fake = mock.Mock(return_value=live.CommandResult(
            ["openclaw", "acp"], 0,
            'CONTEXTOS_LIVE_RESULT={"status":"rejected"}', "",
        ))
        harness = live.LiveHarness(
            binary="openclaw", expected_version="OpenClaw fixture",
            repo=self.repo, state=self.state, workspace=self.workspace,
            evidence_path=self.evidence, port=18789,
            claude_binary=self.claude, acp_runner=fake,
        )
        self.assertEqual(
            {"status": "rejected"},
            harness.rpc(
                "policy fixture", "deny", enforce_execution_root=False,
            ),
        )
        self.assertEqual("policy fixture", fake.call_args.args[3])

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

    def test_config_disables_hooks_and_allows_exact_eight_skills(self) -> None:
        target = live.write_openclaw_config(self.state, self.workspace, 18789, self.claude)
        config = json.loads(target.read_text(encoding="utf-8"))
        self.assertFalse(config["hooks"]["internal"]["enabled"])
        self.assertEqual(list(live.LIFECYCLE_SKILLS), config["agents"]["defaults"]["skills"])
        self.assertEqual(live.MODEL_ROUTE, config["agents"]["defaults"]["model"]["primary"])
        self.assertEqual(str(self.claude), config["agents"]["defaults"]["cliBackends"]["claude-cli"]["command"])
        self.assertEqual("none", config["gateway"]["auth"]["mode"])
        self.assertEqual("loopback", config["gateway"]["bind"])
        with self.assertRaisesRegex(live.HarnessError, "refusing to overwrite"):
            live.write_openclaw_config(self.state, self.workspace, 18789, self.claude)

    def test_acp_server_command_avoids_reserved_gateway_rpc(self) -> None:
        command = live.acp_server_command(("openclaw",))
        self.assertEqual(["openclaw", "acp"], command)
        self.assertNotIn("gateway", command)

    def test_acp_command_supports_node_entrypoint_prefix(self) -> None:
        command = live.acp_server_command(("node", "C:/fixture/openclaw.mjs"))
        self.assertEqual(
            ["node", "C:/fixture/openclaw.mjs", "acp"], command,
        )

    def test_model_route_is_the_authenticated_claude_cli_route(self) -> None:
        config = live.openclaw_config(self.workspace, 18789, self.claude)
        self.assertEqual("claude-cli/claude-sonnet-5", live.MODEL_ROUTE)
        self.assertTrue(config["plugins"]["entries"]["anthropic"]["enabled"])
        self.assertEqual(
            str(self.claude),
            config["agents"]["defaults"]["cliBackends"]["claude-cli"]["command"],
        )

    def test_execution_policy_transitions_from_deny_to_explicit_must_fire(self) -> None:
        target = live.write_openclaw_config(
            self.state, self.workspace, 18789, self.claude,
        )
        live.set_execution_policy(target, "deny")
        denied = json.loads(target.read_text(encoding="utf-8"))["tools"]["exec"]
        self.assertEqual({"host": "gateway", "security": "deny"}, denied)
        live.set_execution_policy(target, "full", "off")
        allowed = json.loads(target.read_text(encoding="utf-8"))["tools"]["exec"]
        self.assertEqual(
            {"host": "gateway", "security": "full", "ask": "off"}, allowed,
        )

    def test_exec_policy_preset_commands_are_exact_and_closed(self) -> None:
        self.assertEqual(
            ["node", "openclaw.mjs", "exec-policy", "preset", "deny-all", "--json"],
            live.exec_policy_preset_command(("node", "openclaw.mjs"), "deny-all"),
        )
        self.assertEqual(
            ["openclaw", "exec-policy", "preset", "yolo", "--json"],
            live.exec_policy_preset_command(("openclaw",), "yolo"),
        )
        with self.assertRaisesRegex(live.HarnessError, "unsupported"):
            live.exec_policy_preset_command(("openclaw",), "custom")

    def test_execute_always_stops_gateway_for_direct_callers(self) -> None:
        harness = live.LiveHarness(
            binary="openclaw", expected_version="OpenClaw fixture",
            repo=self.repo, state=self.state, workspace=self.workspace,
            evidence_path=self.evidence, port=18789, claude_binary=self.claude,
        )
        harness._execute_unprotected = mock.Mock(side_effect=live.HarnessError("fixture"))
        harness.stop_gateway = mock.Mock()
        with self.assertRaisesRegex(live.HarnessError, "fixture"):
            harness.execute()
        harness.stop_gateway.assert_called_once_with()

    def test_acp_runner_drives_json_rpc_and_denies_client_requests(self) -> None:
        script = (
            "import json, os, sys\n"
            "def read(): return json.loads(sys.stdin.readline())\n"
            "def send(value): print(json.dumps(value, separators=(',', ':')), flush=True)\n"
            "assert os.environ['OPENCLAW_NO_RESPAWN']=='1'\n"
            "message=read()\n"
            "assert message['method']=='initialize' and message['params']['protocolVersion']==1\n"
            "assert message['params']['clientCapabilities']['terminal'] is False\n"
            "send({'jsonrpc':'2.0','id':message['id'],'result':{'protocolVersion':1}})\n"
            "message=read()\n"
            "assert message['method']=='session/new'\n"
            "assert message['params']['cwd']==sys.argv[1] and message['params']['mcpServers']==[]\n"
            "send({'jsonrpc':'2.0','id':message['id'],'result':{'sessionId':'fixture-session'}})\n"
            "message=read()\n"
            "assert message['method']=='session/prompt' and message['params']['sessionId']=='fixture-session'\n"
            "assert message['params']['prompt']==[{'type':'text','text':'synthetic\\nprompt'}]\n"
            "send({'jsonrpc':'2.0','method':'session/update','params':{'sessionId':'fixture-session','update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'CONTEXTOS_LIVE_RESULT={\\\"status\\\":\\\"started\\\"}'}}}})\n"
            "send({'jsonrpc':'2.0','method':'session/update','params':{'sessionId':'fixture-session','update':{'sessionUpdate':'tool_call','title':'Bash','status':'pending'}}})\n"
            "send({'jsonrpc':'2.0','id':98,'method':'fs/read_text_file','params':{'path':'secret'}})\n"
            "response=read(); assert response['id']==98 and response['error']['code']==-32601\n"
            "send({'jsonrpc':'2.0','id':99,'method':'session/request_permission','params':{'options':[]}})\n"
            "response=read(); assert response=={'jsonrpc':'2.0','id':99,'result':{'outcome':{'outcome':'cancelled'}}}\n"
            "send({'jsonrpc':'2.0','method':'session/update','params':{'sessionId':'fixture-session','update':{'sessionUpdate':'tool_call_update','toolCallId':'tool-1','status':'failed'}}})\n"
            "send({'jsonrpc':'2.0','id':message['id'],'result':{'stopReason':'end_turn'}})\n"
        )
        result = live.default_acp_runner(
            [sys.executable, "-c", script, str(self.repo)], self.repo, os.environ,
            "synthetic\nprompt", 10,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("[tool] Bash (pending)", result.stdout)
        self.assertIn("[tool update] tool-1: failed", result.stdout)
        self.assertIn("[end_turn]", result.stdout)
        self.assertEqual(
            {"status": "started"}, live.parse_lifecycle_result(result.stdout),
        )

    def test_parse_result_requires_one_explicit_marker(self) -> None:
        response = json.dumps({"result": "CONTEXTOS_LIVE_RESULT={\"status\":\"started\"}"})
        self.assertEqual({"status": "started"}, live.parse_lifecycle_result(response))
        with self.assertRaisesRegex(live.HarnessError, "exactly one"):
            live.parse_lifecycle_result("ordinary agent prose")

    def test_wrong_digest_control_requires_the_kernel_diagnostic(self) -> None:
        expected = live.CommandResult(
            ["bash"], 1, "", "--confirm must exactly match the proposal_digest\n",
        )
        unrelated = live.CommandResult(["bash"], 127, "", "bash: not found\n")
        false_success = live.CommandResult(
            ["bash"], 0, "--confirm must exactly match the proposal_digest\n", "",
        )
        self.assertTrue(live.is_wrong_digest_rejection(expected))
        self.assertFalse(live.is_wrong_digest_rejection(unrelated))
        self.assertFalse(live.is_wrong_digest_rejection(false_success))

    def test_apply_prompt_requires_independent_proposal_verification(self) -> None:
        source = Path(live.__file__).read_text(encoding="utf-8")
        self.assertIn("Independently read that", source)
        self.assertIn("verify its proposal_digest", source)
        self.assertIn("every target path stays inside", source)
        self.assertNotIn("The operator approved exact digest", source)

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
        value = {
            "apiToken": "secret", "workspace": str(self.workspace),
            "nested": {"message": "personal prompt", "ok": True},
        }
        cleaned = live.redact(value, (self.workspace,))
        serialized = json.dumps(cleaned)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("personal prompt", serialized)
        self.assertNotIn(str(self.workspace), serialized)
        self.assertTrue(cleaned["nested"]["ok"])

    def test_missing_sync_helper_fails_clearly(self) -> None:
        with mock.patch.object(live.importlib.util, "spec_from_file_location", return_value=None):
            with self.assertRaisesRegex(live.HarnessError, r"sync\(workspace\)"):
                live.load_sync_helper()

    def test_sync_helper_loads_for_direct_script_execution(self) -> None:
        self.assertTrue(callable(live.load_sync_helper()))

    def test_native_memory_snapshot_covers_host_files_and_directory(self) -> None:
        (self.repo / "MEMORY.md").write_text("must stay private", encoding="utf-8")
        snapshot = live.native_memory_snapshot(self.repo)
        self.assertTrue(snapshot["MEMORY.md"])
        self.assertEqual(set(live.NATIVE_MEMORY_NAMES), set(snapshot))

    def test_repository_snapshot_detects_content_changes(self) -> None:
        fixture = self.repo / "state.md"
        fixture.write_text("before", encoding="utf-8")
        before = live.repository_snapshot(self.repo)
        fixture.write_text("after", encoding="utf-8")
        self.assertNotEqual(before, live.repository_snapshot(self.repo))

    def test_repository_snapshot_ignores_python_bytecode_cache(self) -> None:
        before = live.repository_snapshot(self.repo)
        cache = self.repo / "contextos/__pycache__"
        cache.mkdir(parents=True)
        (cache / "kernel.cpython-313.pyc").write_bytes(b"interpreter cache")
        self.assertEqual(before, live.repository_snapshot(self.repo))


if __name__ == "__main__":
    unittest.main()
