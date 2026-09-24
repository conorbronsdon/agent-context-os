from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "adapters/devin/ui_conformance.py"
SPEC = importlib.util.spec_from_file_location("contextos_devin_ui", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ui = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ui
SPEC.loader.exec_module(ui)


class FakeGitHub:
    def __init__(self, fixture_sha: str) -> None:
        self.fixture_sha = fixture_sha
        self.pulls: list[dict[str, object]] = []
        self.calls: list[str] = []

    def __call__(self, url: str) -> object:
        self.calls.append(url)
        parsed = urllib.parse.urlsplit(url)
        path = parsed.path
        if path.endswith("/repos/conorbronsdon/contextos-devin-live-fixture"):
            return {"default_branch": "main"}
        if path.endswith("/git/ref/heads/main"):
            return {"object": {"type": "commit", "sha": self.fixture_sha}}
        if path.endswith(f"/commits/{self.fixture_sha}"):
            return {"sha": self.fixture_sha}
        if path.endswith(f"/git/trees/{self.fixture_sha}"):
            return {
                "truncated": False,
                "tree": [{"path": item, "type": "blob"} for item in ui.FIXTURE_PATHS],
            }
        marker = "/contents/"
        if marker in path:
            relative = urllib.parse.unquote(path.split(marker, 1)[1])
            content = (ui.LOCAL_FIXTURE / ui.LOCAL_FIXTURE_FILES[relative]).read_bytes()
            return {"encoding": "base64", "content": base64.b64encode(content).decode()}
        if path.endswith("/pulls"):
            return list(self.pulls)
        raise AssertionError(url)


class DevinUiHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source_sha = "a" * 40
        self.fixture_sha = "b" * 40
        self.repository = "conorbronsdon/contextos-devin-live-fixture"
        self.manifest = self.root / "manifest.json"
        self.evidence = self.root / "evidence.json"
        self.github = FakeGitHub(self.fixture_sha)

    def prepare(self) -> dict[str, object]:
        args = argparse.Namespace(
            repository=self.repository,
            fixture_sha=self.fixture_sha,
            source_sha=self.source_sha,
            manifest=self.manifest,
            allow_public_fixture_access=True,
            acknowledge_operator_session=True,
        )
        with mock.patch.object(ui, "repository_source_sha", return_value=self.source_sha):
            ui.prepare(args, transport=self.github)
        return json.loads(self.manifest.read_text(encoding="utf-8"))

    def observations(self) -> dict[str, object]:
        return {
            "root_response": f"{ui.ROOT_CANARY} {self.fixture_sha}",
            "explicit_response": ui.SKILL_CANARY,
            "repository_remained_read_only": True,
            "no_pull_request_observed": True,
            "review_not_invoked": True,
            "session_archived": True,
            "session_url": "https://app.devin.ai/sessions/devin-synthetic",
            "product_build": "unavailable",
            "environment_identity": "unavailable",
            "devin_mode": "normal",
        }

    def test_prepare_verifies_exact_public_fixture_and_pr_baseline(self) -> None:
        manifest = self.prepare()
        self.assertEqual("session-ui", manifest["surface"])
        self.assertEqual(0, manifest["baseline_pull_count"])
        self.assertNotIn(self.fixture_sha, manifest["prompts"]["root"])
        self.assertIn("root instruction canary from your repository instructions", manifest["prompts"]["root"])
        self.assertIn("git rev-parse HEAD", manifest["prompts"]["root"])
        self.assertNotIn(ui.ROOT_CANARY, manifest["prompts"]["root"])
        for instruction_file in (
            "AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "REVIEW.md", "SKILL.md"
        ):
            self.assertNotIn(instruction_file, manifest["prompts"]["root"])
        self.assertNotRegex(manifest["prompts"]["root"], r"\b[\w.-]+\.(?:md|mdc)\b")
        self.assertIn(f"@skills:{ui.SKILL_NAME}", manifest["prompts"]["explicit"])
        self.assertTrue(any("/git/trees/" in url for url in self.github.calls))
        self.assertEqual(list(ui.FIXTURE_PATHS), sorted(ui.FIXTURE_PATHS))

    def test_record_accepts_exact_canaries_and_hashes_session_identity(self) -> None:
        self.prepare()
        observations = self.root / "observations.json"
        observations.write_text(json.dumps(self.observations()) + "\n", encoding="utf-8")
        args = argparse.Namespace(
            manifest=self.manifest,
            observations=observations,
            evidence=self.evidence,
            allow_public_fixture_access=True,
            acknowledge_operator_attestation=True,
        )
        with mock.patch.object(ui, "repository_source_sha", return_value=self.source_sha):
            ui.record(args, transport=self.github)
        evidence = json.loads(self.evidence.read_text(encoding="utf-8"))
        self.assertEqual("session-ui", evidence["surface"])
        self.assertEqual("operator-attested-with-local-verification", evidence["evidence_kind"])
        self.assertTrue(all(evidence["verified_controls"].values()))
        self.assertTrue(all(evidence["attested_controls"].values()))
        self.assertFalse(evidence["account_identity_inspectable"])
        self.assertFalse(evidence["build_identity_inspectable"])
        self.assertNotIn("session_url", evidence)
        self.assertNotIn("devin-synthetic", json.dumps(evidence))

    def test_public_fixture_inline_code_wrapper_is_accepted_without_extra_text(self) -> None:
        self.assertEqual(
            f"{ui.ROOT_CANARY} {self.fixture_sha}",
            ui.normalize_fixture_reply(f"`{ui.ROOT_CANARY}` {self.fixture_sha}", ui.ROOT_CANARY),
        )
        self.assertNotEqual(
            ui.SKILL_CANARY,
            ui.normalize_fixture_reply(f"extra `{ui.SKILL_CANARY}`", ui.SKILL_CANARY),
        )

    def test_record_rejects_skill_leak_or_pull_request_drift(self) -> None:
        self.prepare()
        observations = self.observations()
        observations["root_response"] += f" {ui.SKILL_CANARY}"
        path = self.root / "observations.json"
        path.write_text(json.dumps(observations), encoding="utf-8")
        args = argparse.Namespace(
            manifest=self.manifest,
            observations=path,
            evidence=self.evidence,
            allow_public_fixture_access=True,
            acknowledge_operator_attestation=True,
        )
        with mock.patch.object(ui, "repository_source_sha", return_value=self.source_sha):
            with self.assertRaisesRegex(ui.HarnessError, "implicit-skill"):
                ui.record(args, transport=self.github)

    def test_record_rejects_wrong_observed_fixture_commit(self) -> None:
        self.prepare()
        observations = self.observations()
        observations["root_response"] = f"{ui.ROOT_CANARY} {'c' * 40}"
        path = self.root / "observations.json"
        path.write_text(json.dumps(observations), encoding="utf-8")
        args = argparse.Namespace(
            manifest=self.manifest, observations=path, evidence=self.evidence,
            allow_public_fixture_access=True, acknowledge_operator_attestation=True,
        )
        with mock.patch.object(ui, "repository_source_sha", return_value=self.source_sha):
            with self.assertRaisesRegex(ui.HarnessError, "root"):
                ui.record(args, transport=self.github)

    def test_record_requires_exact_devin_session_url(self) -> None:
        self.prepare()
        observations = self.observations()
        observations["session_url"] = "https://app.devin.ai/devin-synthetic"
        path = self.root / "observations.json"
        path.write_text(json.dumps(observations), encoding="utf-8")
        args = argparse.Namespace(
            manifest=self.manifest,
            observations=path,
            evidence=self.evidence,
            allow_public_fixture_access=True,
            acknowledge_operator_attestation=True,
        )
        with mock.patch.object(ui, "repository_source_sha", return_value=self.source_sha):
            with self.assertRaisesRegex(ui.HarnessError, "session URL"):
                ui.record(args, transport=self.github)

        observations["root_response"] = f"{ui.ROOT_CANARY} {self.fixture_sha}"
        path.write_text(json.dumps(observations), encoding="utf-8")
        self.github.pulls.append({
            "number": 1, "state": "open",
            "head": {"sha": "c" * 40}, "base": {"sha": self.fixture_sha},
        })
        with mock.patch.object(ui, "repository_source_sha", return_value=self.source_sha):
            with self.assertRaisesRegex(ui.HarnessError, "pull-request inventory changed"):
                ui.record(args, transport=self.github)

    def test_fixture_drift_and_unexpected_files_fail(self) -> None:
        class Drifted(FakeGitHub):
            def __call__(self, url: str) -> object:
                result = super().__call__(url)
                if "/git/trees/" in url:
                    result["tree"].append({"path": "secret.txt", "type": "blob"})
                return result

        fixture = ui.GitHubFixture(
            self.repository, self.fixture_sha, transport=Drifted(self.fixture_sha)
        )
        with self.assertRaisesRegex(ui.HarnessError, "unexpected files"):
            fixture.verify()

    def test_default_branch_head_drift_fails(self) -> None:
        class DriftedHead(FakeGitHub):
            def __call__(self, url: str) -> object:
                result = super().__call__(url)
                if urllib.parse.urlsplit(url).path.endswith("/git/ref/heads/main"):
                    return {"object": {"type": "commit", "sha": "c" * 40}}
                return result

        fixture = ui.GitHubFixture(
            self.repository, self.fixture_sha, transport=DriftedHead(self.fixture_sha)
        )
        with self.assertRaisesRegex(ui.HarnessError, "default branch drifted"):
            fixture.verify()

    def test_opt_ins_and_create_only_output_are_required(self) -> None:
        args = argparse.Namespace(
            allow_public_fixture_access=False,
            acknowledge_operator_session=False,
        )
        with self.assertRaisesRegex(ui.HarnessError, "opt-in"):
            ui.prepare(args, transport=self.github)
        self.evidence.write_text("existing\n", encoding="utf-8")
        with self.assertRaisesRegex(ui.HarnessError, "refusing to overwrite"):
            ui.write_create_only(self.evidence, {"value": True})

    def test_source_never_opens_devin_or_invokes_review(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("webbrowser", source)
        self.assertNotIn("devinreview.com", source)
        self.assertNotIn("devin-review", source)
        self.assertNotIn("Start-Process", source)
        self.assertIn("review_must_not_be_invoked", source)


if __name__ == "__main__":
    unittest.main()
