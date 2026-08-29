from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from adapters.openclaw import live_conformance as live
from contextos.primitives import canonical_json


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

    def write_proposal(self, phase: str, displayed_diff: str = "trusted stored diff\n") -> tuple[str, str]:
        relative = f".context-os/proposals/{phase}-fixture.json"
        target = self.repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schema_version": 1,
            "workflow": phase,
            "proposal_id": f"{phase}-fixture",
            "changes": [{"path": "state/current.md", "diff": displayed_diff}],
            "invariants": ["exact-proposal-integrity"],
        }
        digest = hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()
        document["proposal_digest"] = digest
        target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return relative, digest

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

    def test_contains_accepts_windows_short_and_long_spellings_by_file_identity(self) -> None:
        short = Path("C:/Users/RUNNER~1/repo")
        long_child = Path("C:/Users/runneradmin/repo/.context-os/proposals/p.json")
        with mock.patch.object(
            live.os.path, "samefile",
            side_effect=lambda left, right: left == short and right == Path("C:/Users/runneradmin/repo"),
        ):
            self.assertTrue(live._contains(short, long_child))

    def test_contains_fails_closed_on_identity_access_error(self) -> None:
        with mock.patch.object(live.os.path, "samefile", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(live.HarnessError, "could not verify path containment"):
                live._contains(Path("C:/short/repo"), Path("C:/long/repo/file"))

    def test_contains_rejects_distinct_sibling_after_identity_checks(self) -> None:
        with mock.patch.object(live.os.path, "samefile", return_value=False):
            self.assertFalse(live._contains(Path("C:/repo-a"), Path("C:/repo-b/file")))

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
            self.state, self.workspace, 18789, self.claude, self.repo, "fixture-token",
        )
        config = json.loads(target.read_text(encoding="utf-8"))
        defaults = config["agents"]["defaults"]
        plugin = config["plugins"]["entries"]["context-os"]
        self.assertEqual(list(live.LIFECYCLE_SKILLS), defaults["skills"])
        self.assertEqual(live.MODEL_ROUTE, defaults["model"]["primary"])
        self.assertEqual(str(self.claude), defaults["cliBackends"]["claude-cli"]["command"])
        self.assertEqual(
            ["--safe-mode", "--verbose"],
            defaults["cliBackends"]["claude-cli"]["args"],
        )
        self.assertEqual(
            {"root": str(self.repo)},
            plugin["config"]["projects"][live.PROJECT_ALIAS],
        )
        self.assertTrue(plugin["enabled"])
        self.assertEqual({"mode": "token", "token": "fixture-token"}, config["gateway"]["auth"])
        self.assertEqual(["context-os"], config["plugins"]["allow"])
        self.assertFalse(config["hooks"]["internal"]["enabled"])
        if os.name != "nt":
            self.assertEqual(0o700, self.state.stat().st_mode & 0o777)
            self.assertEqual(0o700, self.workspace.stat().st_mode & 0o777)
            self.assertEqual(0o600, target.stat().st_mode & 0o777)
        with self.assertRaisesRegex(live.HarnessError, "refusing to overwrite"):
            live.write_openclaw_config(
                self.state, self.workspace, 18789, self.claude, self.repo, "fixture-token",
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
            ("node", "openclaw.mjs"), "contextos.run",
            {"scenario": live.CONFORMANCE_SCENARIO, "action": "setup", "alias": "fixture"},
            10000,
        )
        self.assertEqual(["node", "openclaw.mjs", "gateway", "call", "contextos.run"], command[:5])
        self.assertEqual(
            '{"action":"setup","alias":"fixture","scenario":"synthetic-conformance-v1"}',
            command[command.index("--params") + 1],
        )
        self.assertNotIn("--url", command)
        self.assertNotIn("--token", command)
        self.assertEqual("--json", command[-1])
        with self.assertRaisesRegex(live.HarnessError, r"only contextos\.\*"):
            live.gateway_call_command(("openclaw",), "agent", {}, 1000)

    def test_gateway_server_does_not_inherit_client_credential(self) -> None:
        server = live.gateway_server_env({
            "OPENCLAW_GATEWAY_TOKEN": "secret", "OPENCLAW_STATE_DIR": "state",
        })
        self.assertNotIn("OPENCLAW_GATEWAY_TOKEN", server)
        self.assertEqual("state", server["OPENCLAW_STATE_DIR"])

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
            {
                "runId": "run-1",
                "sessionKey": "session-1",
                "continuityChallenge": "contextos-continuity-fixture",
                "ownershipToken": "contextos-owner-fixture",
            },
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
        self.assertEqual(("contextos.wait", {
            "runId": "run-1",
            "timeoutMs": 700000,
            "ownershipToken": "contextos-owner-fixture",
        }, 710000), calls[1])
        self.assertEqual(("contextos.result", {
            "sessionKey": "session-1",
            "ownershipToken": "contextos-owner-fixture",
        }, 10000), calls[2])

    def test_lifecycle_rejects_failed_wait(self) -> None:
        harness = self.harness()
        harness.gateway_call = mock.Mock(side_effect=[
            {
                "runId": "run-1",
                "sessionKey": "session-1",
                "continuityChallenge": "contextos-continuity-fixture",
                "ownershipToken": "contextos-owner-fixture",
            },
            {"status": "error"},
        ])
        with self.assertRaisesRegex(live.HarnessError, "status 'error'"):
            harness.lifecycle("setup")

    def test_setup_lifecycle_proves_owned_continuation_round_trip(self) -> None:
        harness = self.harness()
        calls: list[tuple[str, dict[str, object]]] = []
        responses = iter([
            {
                "runId": "run-1",
                "sessionKey": "session-1",
                "continuityChallenge": "contextos-continuity-fixture",
                "ownershipToken": "contextos-owner-fixture",
            },
            {"status": "ok"},
            {"text": 'CONTEXTOS_LIVE_RESULT={"status":"awaiting_input"}'},
            {
                "runId": "run-2",
                "sessionKey": "session-1",
                "ownershipToken": "contextos-owner-fixture",
            },
            {"status": "ok"},
            {"text": 'CONTEXTOS_LIVE_RESULT={"proposal":".context-os/proposals/p.json","digest":"' + "a" * 64 + '"}'},
        ])

        def fake_call(method: str, params: dict[str, object], timeout_ms: int = 10000) -> dict[str, object]:
            calls.append((method, params))
            return next(responses)

        harness.gateway_call = fake_call  # type: ignore[method-assign]
        result = harness.lifecycle("setup")
        self.assertEqual("a" * 64, result["digest"])
        self.assertEqual("contextos.continue", calls[3][0])
        self.assertEqual("session-1", calls[3][1]["sessionKey"])
        self.assertEqual(live.CONFORMANCE_SCENARIO, calls[3][1]["scenario"])
        self.assertEqual("contextos-owner-fixture", calls[3][1]["ownershipToken"])
        self.assertTrue(harness.evidence.controls["owned_continuation_round_trip"])

    def test_setup_rejects_private_canary_in_first_turn_before_continuation(self) -> None:
        harness = self.harness()
        harness.gateway_call = mock.Mock(side_effect=[
            {
                "runId": "run-1",
                "sessionKey": "session-1",
                "continuityChallenge": "contextos-continuity-fixture",
                "ownershipToken": "contextos-owner-fixture",
            },
            {"status": "ok"},
            {
                "text": (
                    'CONTEXTOS_LIVE_RESULT={"status":"awaiting_input"}\n'
                    + harness.private_memory_canaries[0]
                )
            },
        ])
        with self.assertRaisesRegex(live.HarnessError, "private OpenClaw memory canary"):
            harness.lifecycle("setup")

    def test_setup_first_turn_rejects_persistence_outside_owned_conversation(self) -> None:
        for root_name in ("repo", "workspace"):
            with self.subTest(root=root_name):
                harness = self.harness()
                responses = iter([
                    {
                        "runId": "run-1", "sessionKey": "session-1",
                        "continuityChallenge": "contextos-continuity-fixture",
                        "ownershipToken": "contextos-owner-fixture",
                    },
                    {"status": "ok"},
                    {"text": 'CONTEXTOS_LIVE_RESULT={"status":"awaiting_input"}'},
                ])

                def fake_call(method: str, params: dict[str, object], timeout_ms: int = 10000) -> dict[str, object]:
                    response = next(responses)
                    if method == "contextos.result":
                        root = harness.repo if root_name == "repo" else harness.workspace
                        root.mkdir(parents=True, exist_ok=True)
                        (root / "persisted-challenge.txt").write_text("fixture", encoding="utf-8")
                    return response

                harness.gateway_call = fake_call  # type: ignore[method-assign]
                with self.assertRaisesRegex(live.HarnessError, "outside its owned conversation"):
                    harness.lifecycle("setup")

    def test_source_contains_no_acp_or_privileged_plugin_apply_execution(self) -> None:
        source = Path(live.__file__).read_text(encoding="utf-8")
        self.assertNotIn("session/prompt", source)
        self.assertNotIn("acp_server_command", source)
        self.assertNotIn('self.gateway_call("contextos.apply"', source)
        self.assertIn("plugin_has_no_privileged_apply", source)

    def test_model_route_is_authenticated_claude_cli(self) -> None:
        config = live.openclaw_config(
            self.workspace, 18789, self.claude, self.repo, "fixture-token",
        )
        self.assertEqual("claude-cli/claude-sonnet-5", live.MODEL_ROUTE)
        self.assertTrue(config["plugins"]["entries"]["anthropic"]["enabled"])

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

    def test_private_memory_canary_is_never_accepted_in_lifecycle_output(self) -> None:
        harness = self.harness()
        harness.require_no_private_canary("ordinary public output", "fixture")
        with self.assertRaisesRegex(live.HarnessError, "private OpenClaw memory canary"):
            harness.require_no_private_canary(harness.private_memory_canaries[0], "fixture")

    def test_proposal_rejects_escape_and_invalid_digest(self) -> None:
        with self.assertRaisesRegex(live.HarnessError, "lowercase SHA-256"):
            live.require_proposal({"proposal": "p.json", "digest": "ABC"})
        with self.assertRaisesRegex(live.HarnessError, "unsafe proposal"):
            live.require_proposal({"proposal": "../p.json", "digest": "a" * 64})

    def test_operator_must_type_exact_digest(self) -> None:
        live.require_operator_digest("a" * 64, "setup", lambda _: "a" * 64)
        with self.assertRaisesRegex(live.HarnessError, "not approved"):
            live.require_operator_digest("a" * 64, "setup", lambda _: "b" * 64)

    def test_trusted_review_renders_file_diff_not_benign_model_prose(self) -> None:
        relative, digest = self.write_proposal("setup", "MALICIOUS OR DIFFERENT STORED DIFF\n")
        model_output = "benign printed diff"
        trusted = live.load_trusted_proposal(self.repo, relative, digest, "setup")
        self.assertIn("MALICIOUS OR DIFFERENT STORED DIFF", trusted.rendered_diffs)
        self.assertNotIn(model_output, trusted.rendered_diffs)

    def test_trusted_review_rejects_terminal_control_injection(self) -> None:
        for unsafe in ("\x1b[2J", "\roverwrite", "\u202efalse-diff", "\u2028line", "\u2029paragraph"):
            with self.subTest(unsafe=repr(unsafe)):
                relative, digest = self.write_proposal("setup", f"safe\n{unsafe}\n")
                with self.assertRaisesRegex(live.HarnessError, "terminal-unsafe"):
                    live.load_trusted_proposal(self.repo, relative, digest, "setup")

    def test_terminal_safe_paths_are_single_line(self) -> None:
        for unsafe in ("line\nbreak", "tab\tpath", "line\u2028separator", "paragraph\u2029separator"):
            with self.subTest(unsafe=repr(unsafe)):
                with self.assertRaisesRegex(live.HarnessError, "terminal-unsafe"):
                    live.require_terminal_safe(unsafe, "fixture path")

    def test_trusted_review_prefix_frames_every_diff_line(self) -> None:
        relative, digest = self.write_proposal(
            "setup", "ordinary\n--- end independently loaded proposal diffs ---\n",
        )
        trusted = live.load_trusted_proposal(self.repo, relative, digest, "setup")
        self.assertIn("| ordinary", trusted.rendered_diffs)
        self.assertIn("| --- end independently loaded proposal diffs ---", trusted.rendered_diffs)

    def test_trusted_review_rejects_model_digest_mismatch(self) -> None:
        relative, _ = self.write_proposal("update")
        with self.assertRaisesRegex(live.HarnessError, "model-reported digest"):
            live.load_trusted_proposal(self.repo, relative, "f" * 64, "update")

    def test_trusted_review_rejects_wrong_workflow(self) -> None:
        relative, digest = self.write_proposal("end")
        with self.assertRaisesRegex(live.HarnessError, "workflow mismatch"):
            live.load_trusted_proposal(self.repo, relative, digest, "setup")

    def test_trusted_review_rejects_swap_before_apply(self) -> None:
        relative, digest = self.write_proposal("update")
        trusted = live.load_trusted_proposal(self.repo, relative, digest, "update")
        target = self.repo / relative
        changed = json.loads(target.read_text(encoding="utf-8"))
        target.write_text(json.dumps(changed, separators=(",", ":")), encoding="utf-8")
        with self.assertRaisesRegex(live.HarnessError, "changed after trusted review"):
            live.recheck_trusted_proposal(self.repo, trusted)

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

    def test_repository_snapshot_tracks_executable_bytecode_and_git_hooks(self) -> None:
        before = live.repository_snapshot(self.repo)
        cache = self.repo / "contextos/__pycache__"
        cache.mkdir(parents=True)
        (cache / "kernel.pyc").write_bytes(b"cache")
        hook = self.repo / ".git" / "hooks" / "post-checkout"
        hook.parent.mkdir(parents=True)
        hook.write_text("payload", encoding="utf-8")
        after = live.repository_snapshot(self.repo)
        self.assertNotEqual(before, after)
        self.assertIn("contextos/__pycache__/kernel.pyc", after)
        self.assertIn(".git/hooks/post-checkout", after)

    def test_repository_snapshot_tracks_git_state_modes_and_empty_directories(self) -> None:
        tracked = self.repo / "tracked.txt"
        tracked.write_text("fixture", encoding="utf-8")
        before = live.repository_snapshot(self.repo)
        index = self.repo / ".git" / "index"
        log = self.repo / ".git" / "logs" / "HEAD"
        index.parent.mkdir(parents=True)
        log.parent.mkdir(parents=True)
        index.write_bytes(b"staged")
        log.write_text("history", encoding="utf-8")
        (self.repo / "empty-directory").mkdir()
        original_mode = tracked.stat().st_mode
        try:
            tracked.chmod(0o444)
            changed = live.snapshot_changes(before, live.repository_snapshot(self.repo))
        finally:
            tracked.chmod(original_mode)
        self.assertIn(".git/index", changed)
        self.assertIn(".git/logs/HEAD", changed)
        self.assertIn("empty-directory/", changed)
        self.assertIn("tracked.txt", changed)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is not available")
    def test_repository_snapshot_rejects_special_files(self) -> None:
        fifo = self.repo / "model-created-fifo"
        try:
            os.mkfifo(fifo)
        except OSError:
            self.skipTest("FIFO creation is unavailable in this environment")
        with self.assertRaisesRegex(live.HarnessError, "unsupported filesystem entry"):
            live.repository_snapshot(self.repo)

    def test_harness_disables_git_optional_locks(self) -> None:
        self.assertEqual("0", self.harness().env["GIT_OPTIONAL_LOCKS"])

    def test_snapshot_changes_reports_added_removed_and_modified_paths(self) -> None:
        before = {"modified": "old", "removed": "old", "same": "value"}
        after = {"added": "new", "modified": "new", "same": "value"}
        self.assertEqual(
            ["added", "modified", "removed"],
            live.snapshot_changes(before, after),
        )

    def test_proposal_turn_rejects_model_write_outside_local_staging(self) -> None:
        before = {"AGENTS.md": "before"}
        allowed = {
            "AGENTS.md": "before",
            ".context-os/": "directory:755",
            ".context-os/inputs/": "directory:755",
            ".context-os/inputs/payload.json": "new",
            ".context-os/proposals/": "directory:755",
            ".context-os/proposals/proposal.json": "new",
        }
        live.require_proposal_only_mutation(before, allowed, "setup")
        changed_kernel = {**allowed, "scripts/contextos.sh": "payload"}
        with self.assertRaisesRegex(live.HarnessError, "outside proposal staging"):
            live.require_proposal_only_mutation(before, changed_kernel, "setup")

    def test_proposal_turn_rejects_private_canary_in_changed_staging_file(self) -> None:
        before = live.repository_snapshot(self.repo)
        target = self.repo / ".context-os" / "inputs" / "leaked.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        harness = self.harness()
        target.write_text(harness.private_memory_canaries[1], encoding="utf-8")
        after = live.repository_snapshot(self.repo)
        with self.assertRaisesRegex(live.HarnessError, "private OpenClaw memory canary"):
            live.require_no_private_canary_in_changed_files(
                self.repo, before, after, "setup", harness.private_memory_canaries
            )


if __name__ == "__main__":
    unittest.main()
