from __future__ import annotations

import json
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

    def test_gateway_agent_command_has_repo_cwd_and_unique_idempotency(self) -> None:
        first = live.gateway_agent_command("openclaw", self.repo, "synthetic", "start", 18789)
        second = live.gateway_agent_command("openclaw", self.repo, "synthetic", "start", 18789)
        self.assertEqual(["openclaw", "gateway", "call", "agent"], first[:4])
        self.assertIn("--expect-final", first)
        self.assertIn("--json", first)
        self.assertEqual("ws://127.0.0.1:18789", first[first.index("--url") + 1])
        self.assertEqual("650000", first[first.index("--timeout") + 1])
        params = json.loads(first[first.index("--params") + 1])
        other = json.loads(second[second.index("--params") + 1])
        self.assertEqual(str(self.repo), params["cwd"])
        self.assertEqual("main", params["agentId"])
        self.assertEqual(live.MODEL_ROUTE, params["model"])
        self.assertIn("sessionKey", params)
        self.assertNotEqual(params["idempotencyKey"], other["idempotencyKey"])

    def test_model_route_is_the_authenticated_claude_cli_route(self) -> None:
        config = live.openclaw_config(self.workspace, 18789, self.claude)
        self.assertEqual("anthropic/claude-sonnet-5", live.MODEL_ROUTE)
        self.assertTrue(config["plugins"]["entries"]["anthropic"]["enabled"])
        self.assertEqual(
            str(self.claude),
            config["agents"]["defaults"]["cliBackends"]["claude-cli"]["command"],
        )

    def test_parse_result_requires_one_explicit_marker(self) -> None:
        response = json.dumps({"result": "CONTEXTOS_LIVE_RESULT={\"status\":\"started\"}"})
        self.assertEqual({"status": "started"}, live.parse_lifecycle_result(response))
        with self.assertRaisesRegex(live.HarnessError, "exactly one"):
            live.parse_lifecycle_result("ordinary agent prose")

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


if __name__ == "__main__":
    unittest.main()
