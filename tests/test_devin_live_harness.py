from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
import urllib.parse
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
    def __init__(self, *, implicit_skill: bool = False) -> None:
        self.phase = "implicit"
        self.implicit_skill = implicit_skill
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
            return {"ok": True}
        if method == "GET" and path.endswith("/messages"):
            if self.phase == "implicit":
                text = f"{live.ROOT_CANARY} {'a' * 40}"
                if self.implicit_skill:
                    text += f" {live.SKILL_CANARY}"
                return {"items": [{"event_id": "event-root", "source": "devin", "message": text}]}
            return {"items": [
                {"event_id": "event-root", "source": "devin", "message": live.ROOT_CANARY},
                {"event_id": "event-skill", "source": "devin", "message": live.SKILL_CANARY},
            ]}
        if method == "GET" and "/sessions/devin-fixture" in path:
            return {"status": "running", "status_detail": "finished", "pull_requests": []}
        if method == "DELETE" and "/sessions/devin-fixture" in path:
            return {"session_id": "devin-fixture", "status": "exit"}
        raise AssertionError((method, url, payload))

    @staticmethod
    def assert_query(query, key, value):
        if query.get(key) != [value]:
            raise AssertionError(query)


class DevinLiveHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def harness(self, transport: FakeTransport | None = None):
        selected = transport or FakeTransport()
        client = live.DevinClient("cog_fixture", "org-fixture", transport=selected)
        return live.DevinHarness(
            client,
            repository="conorbronsdon/contextos-devin-live-fixture",
            fixture_sha="a" * 40,
            source_sha="b" * 40,
            expected_active_build="build-fixture",
            poll_timeout=1,
            poll_interval=0,
        ), selected

    def test_fixture_canaries_match_harness_and_skill_is_user_only(self) -> None:
        fixture = ROOT / "adapters/devin/live-fixture"
        agents = (fixture / "AGENTS.md").read_text(encoding="utf-8")
        skill = (
            fixture / ".agents/skills/contextos-devin-live-control/SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn(live.ROOT_CANARY, agents)
        self.assertIn(live.SKILL_CANARY, skill)
        self.assertIn('triggers: ["user"]', skill)

    def test_client_rejects_legacy_or_missing_credentials(self) -> None:
        for token in ("", "apk_fixture", "plain"):
            with self.subTest(token=token):
                with self.assertRaisesRegex(live.HarnessError, "cog_-"):
                    live.DevinClient(token, "org-fixture")

    def test_live_flow_binds_repo_build_commit_and_separate_skill_turn(self) -> None:
        harness, transport = self.harness()
        evidence = harness.execute()
        self.assertTrue(all(evidence.controls.values()))
        self.assertEqual("build-fixture", evidence.active_build_id)
        self.assertEqual("normal", evidence.devin_mode)
        self.assertNotEqual("", evidence.session_id_sha256)
        self.assertEqual("DELETE", evidence.requests[-1]["method"])
        self.assertNotIn("cog_fixture", json.dumps(evidence.requests))
        create = next(call for call in transport.calls if call[0] == "POST" and call[1].endswith("/sessions"))
        self.assertFalse(create[2]["resumable"])
        self.assertEqual(["conorbronsdon/contextos-devin-live-fixture"], create[2]["repos"])
        self.assertTrue(all(call[3]["Authorization"] == "Bearer cog_fixture" for call in transport.calls))

    def test_implicit_skill_failure_still_terminates_session(self) -> None:
        harness, transport = self.harness(FakeTransport(implicit_skill=True))
        with self.assertRaisesRegex(live.HarnessError, "fired without explicit"):
            harness.execute()
        self.assertTrue(any(call[0] == "DELETE" for call in transport.calls))
        self.assertTrue(harness.evidence.controls["session_terminated_and_archived"])

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


if __name__ == "__main__":
    unittest.main()
