from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.parse
import base64
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "adapters/devin/live_conformance.py"
SPEC = importlib.util.spec_from_file_location("contextos_devin_live", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
live = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = live
SPEC.loader.exec_module(live)


class FakeTransport:
    def __init__(
        self, *, implicit_skill: bool = False, archive_fails: bool = False,
        extra_output: bool = False, implicit_skill_first: bool = False,
        delayed_implicit_skill: bool = False, delayed_status: bool = False,
        terminate_fails: bool = False,
    ) -> None:
        self.phase = "implicit"
        self.implicit_skill = implicit_skill
        self.archive_fails = archive_fails
        self.extra_output = extra_output
        self.implicit_skill_first = implicit_skill_first
        self.delayed_implicit_skill = delayed_implicit_skill
        self.delayed_status = delayed_status
        self.terminate_fails = terminate_fails
        self.implicit_message_reads = 0
        self.explicit_prompt = ""
        self.calls: list[tuple[str, str, object, dict[str, str]]] = []

    def __call__(self, method, url, payload, headers, _timeout):
        self.calls.append((method, url, payload, dict(headers)))
        path = urllib.parse.urlsplit(url).path
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        if path.endswith("/repositories"):
            return {"items": [{"repo_path": "conorbronsdon/contextos-devin-live-fixture"}]}
        if path.endswith("/snapshot-setup/builds"):
            self.assert_query(query, "active", "true")
            return {"items": [{"build_id": "build-fixture", "status": "succeeded"}]}
        if method == "POST" and path.endswith("/sessions"):
            return {
                "session_id": "devin-fixture",
                "org_id": "org-fixture",
                "devin_mode": "normal",
            }
        if method == "POST" and path.endswith("/messages"):
            self.phase = "explicit"
            self.explicit_prompt = str(payload["message"])
            return {"ok": True}
        if method == "GET" and path.endswith("/messages"):
            if self.phase == "implicit":
                self.implicit_message_reads += 1
                text = f"{live.ROOT_CANARY} {'a' * 40}"
                if self.delayed_implicit_skill and self.implicit_message_reads > 1:
                    return {"items": [
                        {"event_id": "event-root", "source": "devin", "message": text},
                        {"event_id": "event-late-skill", "source": "devin", "message": live.SKILL_CANARY},
                    ]}
                if self.delayed_status and self.implicit_message_reads > 1:
                    return {"items": [
                        {"event_id": "event-root", "source": "devin", "message": text},
                        {"event_id": "event-status", "source": "devin", "message": "Status: ready"},
                    ]}
                if self.implicit_skill_first:
                    return {"items": [
                        {"event_id": "event-skill-leak", "source": "devin", "message": live.SKILL_CANARY},
                        {"event_id": "event-root", "source": "devin", "message": text},
                    ]}
                if self.implicit_skill:
                    text += f" {live.SKILL_CANARY}"
                elif self.extra_output:
                    text += " extra"
                return {"items": [{"event_id": "event-root", "source": "devin", "message": text}]}
            return {"items": [
                {"event_id": "event-root", "source": "devin", "message": live.ROOT_CANARY},
                {"event_id": "event-user-explicit", "source": "user", "message": self.explicit_prompt},
                {"event_id": "event-skill", "source": "devin", "message": live.SKILL_CANARY},
            ]}
        if method == "GET" and "/sessions/devin-fixture" in path:
            return {"status": "running", "status_detail": "finished", "pull_requests": []}
        if method == "POST" and path.endswith("/sessions/devin-fixture/archive"):
            if self.archive_fails:
                raise live.HarnessError("synthetic archive failure")
            return {
                "session_id": "devin-fixture",
                "status": "suspended",
                "is_archived": True,
            }
        if method == "DELETE" and path.endswith("/sessions/devin-fixture"):
            if self.terminate_fails:
                raise live.HarnessError("synthetic termination failure")
            return {"session_id": "devin-fixture", "status": "exit"}
        raise AssertionError((method, url, payload))

    @staticmethod
    def assert_query(query, key, value):
        if query.get(key) != [value]:
            raise AssertionError(query)


class FakeGitHub:
    def __init__(self, *heads: str, drifted_path: str | None = None) -> None:
        self.heads = list(heads)
        self.reference_calls = 0
        self.drifted_path = drifted_path

    def __call__(self, url: str, _timeout: float):
        parsed = urllib.parse.urlsplit(url)
        path = parsed.path
        if path.endswith("/repos/conorbronsdon/contextos-devin-live-fixture"):
            return {"default_branch": "main"}
        if path.endswith("/git/ref/heads/main"):
            index = min(self.reference_calls, len(self.heads) - 1)
            self.reference_calls += 1
            return {"object": {"type": "commit", "sha": self.heads[index]}}
        fixture_sha = self.heads[0]
        if path.endswith(f"/commits/{fixture_sha}"):
            return {"sha": fixture_sha}
        if path.endswith(f"/git/trees/{fixture_sha}"):
            return {
                "truncated": False,
                "tree": [{"path": item, "type": "blob"} for item in live.FIXTURE_PATHS],
            }
        marker = "/contents/"
        if marker in path:
            relative = urllib.parse.unquote(path.split(marker, 1)[1])
            content = (live.LOCAL_FIXTURE / live.LOCAL_FIXTURE_FILES[relative]).read_bytes()
            if relative == self.drifted_path:
                content += b"drift\n"
            return {"encoding": "base64", "content": base64.b64encode(content).decode()}
        raise AssertionError(url)


class DevinLiveHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def harness(
        self, transport: FakeTransport | None = None, github: FakeGitHub | None = None
    ):
        selected = transport or FakeTransport()
        client = live.DevinClient("cog_fixture", "org-fixture", transport=selected)
        fixture_sha = "a" * 40
        return live.DevinHarness(
            client,
            repository="conorbronsdon/contextos-devin-live-fixture",
            fixture_sha=fixture_sha,
            source_sha="b" * 40,
            expected_active_build="build-fixture",
            poll_timeout=1,
            poll_interval=0,
            github_transport=github or FakeGitHub(fixture_sha),
        ), selected

    def test_fixture_canaries_match_harness_and_skill_is_user_only(self) -> None:
        fixture = ROOT / "adapters/devin/live-fixture"
        agents = (fixture / "AGENTS.md.fixture").read_text(encoding="utf-8")
        skill = (fixture / "SKILL.md.fixture").read_text(encoding="utf-8")
        self.assertIn(live.ROOT_CANARY, agents)
        self.assertIn(live.SKILL_CANARY, skill)
        self.assertIn(f"`{live.ROOT_CANARY}`", agents)
        self.assertIn(f"`{live.SKILL_CANARY}`", skill)
        self.assertIn('triggers: ["user"]', skill)

    def test_live_evidence_must_be_outside_the_source_repository(self) -> None:
        with self.assertRaisesRegex(live.HarnessError, "outside the source"):
            live.require_outside_source(ROOT / "evidence.json")

    def test_client_rejects_legacy_or_missing_credentials(self) -> None:
        for token in ("", "apk_fixture", "plain"):
            with self.subTest(token=token):
                with self.assertRaisesRegex(live.HarnessError, "cog_-"):
                    live.DevinClient(token, "org-fixture")

    def test_client_repr_and_error_details_do_not_expose_tokens(self) -> None:
        client = live.DevinClient("cog_fixture_secret", "org-fixture")
        self.assertNotIn("cog_fixture_secret", repr(client))
        detail = live.safe_error_detail("request rejected for cog_fixture_secret")
        self.assertEqual("request rejected for [REDACTED]", detail)

    def test_fixture_inline_code_wrapper_is_normalized_without_accepting_extra_text(self) -> None:
        self.assertEqual(
            live.ROOT_CANARY + " " + "a" * 40,
            live.normalize_fixture_reply(f"`{live.ROOT_CANARY}` {'a' * 40}", live.ROOT_CANARY),
        )
        self.assertNotEqual(
            live.SKILL_CANARY,
            live.normalize_fixture_reply(f"extra `{live.SKILL_CANARY}`", live.SKILL_CANARY),
        )

    def test_live_flow_binds_repo_build_commit_and_separate_skill_turn(self) -> None:
        harness, transport = self.harness()
        evidence = harness.execute()
        self.assertTrue(all(evidence.controls.values()))
        self.assertEqual("build-fixture", evidence.active_build_id)
        self.assertEqual("normal", evidence.devin_mode)
        self.assertNotEqual("", evidence.session_id_sha256)
        endpoints = [request["endpoint"] for request in evidence.github_requests]
        self.assertEqual("repository", endpoints[0])
        self.assertEqual("default_branch_ref", endpoints[1])
        self.assertEqual(2, endpoints.count("fixture_commit"))
        self.assertEqual(2, endpoints.count("fixture_tree"))
        self.assertTrue(all(f"fixture_content:{path}" in endpoints for path in live.FIXTURE_PATHS))
        self.assertTrue(all(len(request["response_sha256"]) == 64 for request in evidence.github_requests))
        self.assertEqual("POST", evidence.requests[-1]["method"])
        self.assertTrue(evidence.requests[-1]["path"].endswith("/archive"))
        self.assertNotIn("cog_fixture", json.dumps(evidence.requests))
        create = next(call for call in transport.calls if call[0] == "POST" and call[1].endswith("/sessions"))
        self.assertNotIn("resumable", create[2])
        self.assertEqual(["conorbronsdon/contextos-devin-live-fixture"], create[2]["repos"])
        self.assertTrue(all(call[3]["Authorization"] == "Bearer cog_fixture" for call in transport.calls))

    def test_public_fixture_default_head_drift_fails_and_archives(self) -> None:
        harness, transport = self.harness(github=FakeGitHub("a" * 40, "c" * 40))
        with self.assertRaisesRegex(live.HarnessError, "default branch drifted"):
            harness.execute()
        self.assertTrue(
            any(call[0] == "POST" and call[1].endswith("/archive") for call in transport.calls)
        )

    def test_implicit_skill_failure_still_terminates_session(self) -> None:
        harness, transport = self.harness(FakeTransport(implicit_skill=True))
        with self.assertRaisesRegex(live.HarnessError, "fired without explicit"):
            harness.execute()
        self.assertTrue(
            any(call[0] == "POST" and call[1].endswith("/archive") for call in transport.calls)
        )
        self.assertTrue(harness.evidence.controls["session_archived"])

    def test_implicit_skill_leak_in_earlier_message_fails_and_archives(self) -> None:
        harness, transport = self.harness(FakeTransport(implicit_skill_first=True))
        with self.assertRaisesRegex(live.HarnessError, "fired without explicit"):
            harness.execute()
        self.assertTrue(
            any(call[0] == "POST" and call[1].endswith("/archive") for call in transport.calls)
        )

    def test_delayed_implicit_skill_fails_before_the_explicit_turn(self) -> None:
        harness, transport = self.harness(FakeTransport(delayed_implicit_skill=True))
        with self.assertRaisesRegex(live.HarnessError, "fired without explicit"):
            harness.execute()
        self.assertFalse(any(call[1].endswith("/messages") for call in transport.calls))

    def test_delayed_status_does_not_fail_the_implicit_control(self) -> None:
        harness, transport = self.harness(FakeTransport(delayed_status=True))
        self.assertTrue(harness.execute().controls["implicit_skill_must_not_fire"])
        self.assertTrue(any(call[0] == "POST" and call[1].endswith("/messages") for call in transport.calls))

    def test_public_fixture_content_drift_fails_before_session_creation(self) -> None:
        harness, transport = self.harness(github=FakeGitHub(
            "a" * 40, drifted_path="AGENTS.md"
        ))
        with self.assertRaisesRegex(live.HarnessError, "content drifted"):
            harness.execute()
        self.assertFalse(any(call[1].endswith("/sessions") for call in transport.calls))

    def test_root_prompt_requires_discovery_without_embedding_the_canary(self) -> None:
        harness, transport = self.harness()
        harness.execute()
        create = next(call for call in transport.calls if call[0] == "POST" and call[1].endswith("/sessions"))
        self.assertIn("root instruction canary from your repository instructions", create[2]["prompt"])
        self.assertNotIn(live.ROOT_CANARY, create[2]["prompt"])
        self.assertNotIn(harness.fixture_sha, create[2]["prompt"])
        self.assertIn("git rev-parse HEAD", create[2]["prompt"])
        for instruction_file in (
            "AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "REVIEW.md", "SKILL.md"
        ):
            self.assertNotIn(instruction_file, create[2]["prompt"])
        self.assertNotRegex(create[2]["prompt"], r"\b[\w.-]+\.(?:md|mdc)\b")

    def test_root_response_must_match_local_fixture_sha(self) -> None:
        class WrongHead(FakeTransport):
            def __call__(self, method, url, payload, headers, timeout):
                response = super().__call__(method, url, payload, headers, timeout)
                if method == "GET" and url.endswith("/messages?first=200") and self.phase == "implicit":
                    response["items"][0]["message"] = f"{live.ROOT_CANARY} {'c' * 40}"
                return response

        harness, _ = self.harness(WrongHead())
        with self.assertRaisesRegex(live.HarnessError, "exact root and fixture"):
            harness.execute()

    def test_extra_model_output_fails_exact_control_and_archives(self) -> None:
        harness, transport = self.harness(FakeTransport(extra_output=True))
        with self.assertRaisesRegex(live.HarnessError, "exact root and fixture"):
            harness.execute()
        self.assertTrue(
            any(call[0] == "POST" and call[1].endswith("/archive") for call in transport.calls)
        )

    def test_archive_failure_terminates_session_and_fails_conformance(self) -> None:
        harness, transport = self.harness(FakeTransport(archive_fails=True))
        with self.assertRaisesRegex(
            live.HarnessError, "terminated, but required archival failed"
        ):
            harness.execute()
        self.assertTrue(any(call[0] == "DELETE" for call in transport.calls))
        self.assertTrue(
            harness.evidence.controls["session_terminated_after_archive_failure"]
        )

    def test_archive_and_termination_failures_are_both_reported(self) -> None:
        harness, _ = self.harness(FakeTransport(archive_fails=True, terminate_fails=True))
        with self.assertRaises(live.HarnessError) as raised:
            harness.execute()
        self.assertIn("synthetic archive failure", str(raised.exception))
        self.assertIn("synthetic termination failure", str(raised.exception))

    def test_control_failure_survives_both_cleanup_failures(self) -> None:
        harness, _ = self.harness(FakeTransport(
            implicit_skill=True, archive_fails=True, terminate_fails=True
        ))
        with self.assertRaises(live.HarnessError) as raised:
            harness.execute()
        detail = str(raised.exception)
        self.assertIn("user-only Devin skill fired without explicit invocation", detail)
        self.assertIn("synthetic archive failure", detail)
        self.assertIn("synthetic termination failure", detail)

    def test_control_failure_survives_archive_failure_and_termination(self) -> None:
        harness, _ = self.harness(FakeTransport(implicit_skill=True, archive_fails=True))
        with self.assertRaises(live.HarnessError) as raised:
            harness.execute()
        detail = str(raised.exception)
        self.assertIn("user-only Devin skill fired without explicit invocation", detail)
        self.assertIn("synthetic archive failure", detail)
        self.assertIn("terminated", detail)

    def test_main_prints_combined_failure_diagnostic(self) -> None:
        diagnostic = (
            "control: root mismatch; archive: synthetic archive failure; "
            "fallback termination: synthetic termination failure"
        )
        with mock.patch.dict(os.environ, {"DEVIN_API_TOKEN": "cog_fixture"}):
            with mock.patch.object(live, "repository_source_sha", return_value="a" * 40):
                with mock.patch.object(live.DevinHarness, "execute", side_effect=live.HarnessError(diagnostic)):
                    output = io.StringIO()
                    with redirect_stderr(output):
                        status = live.main([
                            "--org-id", "org-fixture",
                            "--repository", "owner/repo",
                            "--fixture-sha", "b" * 40,
                            "--source-sha", "a" * 40,
                            "--expected-active-build", "build-fixture",
                            "--evidence", str(self.root / "evidence.json"),
                            "--allow-account-access", "--allow-session-create",
                            "--acknowledge-public-fixture",
                        ])
        self.assertEqual(1, status)
        self.assertIn(diagnostic, output.getvalue())

    def test_expected_build_and_exact_identifiers_are_required(self) -> None:
        client = live.DevinClient("cog_fixture", "org-fixture", transport=FakeTransport())
        with self.assertRaisesRegex(live.HarnessError, "expected-active-build"):
            live.DevinHarness(
                client,
                repository="owner/repo",
                fixture_sha="a" * 40,
                source_sha="b" * 40,
                expected_active_build="",
            )
        with self.assertRaisesRegex(live.HarnessError, "owner/name"):
            live.DevinHarness(
                client,
                repository="https://example.com/repo",
                fixture_sha="a" * 40,
                source_sha="b" * 40,
                expected_active_build="build",
            )

    def test_evidence_is_create_only_and_contains_no_token(self) -> None:
        target = self.root / "evidence.json"
        evidence = live.Evidence("a" * 40, "b" * 40, "owner/repo")
        live.write_evidence(target, evidence)
        self.assertEqual("devin", json.loads(target.read_text())["runtime"])
        with self.assertRaisesRegex(live.HarnessError, "refusing to overwrite"):
            live.write_evidence(target, evidence)

    def test_main_requires_all_opt_ins_before_reading_token_or_git(self) -> None:
        with mock.patch.object(live, "repository_source_sha") as source:
            with mock.patch.dict(os.environ, {"DEVIN_API_TOKEN": "cog_fixture"}):
                status = live.main([
                    "--org-id", "org-fixture",
                    "--repository", "owner/repo",
                    "--fixture-sha", "a" * 40,
                    "--source-sha", "b" * 40,
                    "--expected-active-build", "build",
                    "--evidence", str(self.root / "evidence.json"),
                ])
        self.assertEqual(1, status)
        source.assert_not_called()

    def test_main_rechecks_source_before_writing_evidence(self) -> None:
        evidence = live.Evidence("a" * 40, "b" * 40, "owner/repo")
        with mock.patch.dict(os.environ, {"DEVIN_API_TOKEN": "cog_fixture"}):
            with mock.patch.object(
                live, "repository_source_sha", side_effect=["a" * 40, "c" * 40]
            ):
                with mock.patch.object(
                    live.DevinHarness, "execute", return_value=evidence
                ):
                    with mock.patch.object(live, "write_evidence") as write:
                        with redirect_stderr(io.StringIO()):
                            status = live.main([
                                "--org-id", "org-fixture",
                                "--repository", "owner/repo",
                                "--fixture-sha", "b" * 40,
                                "--source-sha", "a" * 40,
                                "--expected-active-build", "build-fixture",
                                "--evidence", str(self.root / "evidence.json"),
                                "--allow-account-access",
                                "--allow-session-create",
                                "--acknowledge-public-fixture",
                            ])
        self.assertEqual(1, status)
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
