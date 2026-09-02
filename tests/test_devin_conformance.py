from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = json.loads((ROOT / "runtimes/devin.json").read_text(encoding="utf-8"))
GUIDE_PATH = ROOT / "adapters/devin/README.md"
LIFECYCLE_SKILLS = tuple(
    ROOT / ".agents" / "skills" / name / "SKILL.md"
    for name in (
        "context-setup", "context-start", "context-update", "context-end",
        "setup", "start", "update", "end",
    )
)


class DevinDescriptorTest(unittest.TestCase):
    def test_session_and_review_remain_separate_and_unversioned(self) -> None:
        self.assertEqual("experimental", DESCRIPTOR["support_tier"])
        self.assertEqual({"session", "review"}, set(DESCRIPTOR["surfaces"]))
        session = DESCRIPTOR["surfaces"]["session"]
        review = DESCRIPTOR["surfaces"]["review"]
        self.assertEqual("cloud", session["kind"])
        self.assertEqual("review", review["kind"])
        self.assertEqual("experimental", session["support_tier"])
        self.assertEqual("compatibility", review["support_tier"])
        self.assertEqual([], DESCRIPTOR["evidence"]["tested_versions"])
        self.assertEqual([], session["binary_probes"])
        self.assertEqual([], review["binary_probes"])

    def test_session_uses_only_repository_native_contract_files(self) -> None:
        session = DESCRIPTOR["surfaces"]["session"]
        self.assertEqual(
            ["AGENTS.md"],
            [source["path"] for source in session["instruction_sources"]],
        )
        self.assertEqual(
            [".agents/skills"],
            [source["path"] for source in session["skill_sources"]],
        )
        self.assertEqual(
            {name: f"@skills:context-{name}" for name in ("setup", "start", "update", "end")},
            session["invocation"],
        )
        self.assertEqual("native", session["capabilities"]["agent_skills"])
        self.assertEqual("native", session["capabilities"]["explicit_invocation"])
        self.assertIn("tests/test_devin_live_harness.py", session["conformance_tests"])
        self.assertIn("tests/test_devin_ui_harness.py", session["conformance_tests"])
        self.assertIn("devin-live-harness", session["evidence"])
        self.assertIn("devin-ui-harness", session["evidence"])
        self.assertIn("devin-api-auth", session["evidence"])

    def test_every_lifecycle_skill_is_user_only_in_devin(self) -> None:
        for skill in LIFECYCLE_SKILLS:
            with self.subTest(skill=skill.parent.name):
                frontmatter = skill.read_text(encoding="utf-8").split("---", 2)[1]
                self.assertIn('triggers: ["user"]', frontmatter)

    def test_review_does_not_inherit_session_lifecycle_or_skills(self) -> None:
        review = DESCRIPTOR["surfaces"]["review"]
        self.assertEqual([], review["skill_sources"])
        self.assertTrue(all(value is None for value in review["invocation"].values()))
        self.assertEqual(
            {"AGENTS.md"},
            {source["path"] for source in review["instruction_sources"]},
        )
        self.assertTrue(
            all(value == "unsupported" for value in review["capabilities"].values())
        )
        self.assertNotIn("devin-skills", review["evidence"])

    def test_no_managed_account_state_is_encoded_as_a_repo_artifact(self) -> None:
        serialized = json.dumps(DESCRIPTOR).lower()
        for forbidden in (".devin/", "blueprint.yaml", "memory.md"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)
        paths = {
            source["path"]
            for surface in DESCRIPTOR["surfaces"].values()
            for field in ("instruction_sources", "skill_sources")
            for source in surface[field]
        }
        self.assertEqual({"AGENTS.md", ".agents/skills"}, paths)

    def test_unsupported_host_features_are_not_claimed(self) -> None:
        session = DESCRIPTOR["surfaces"]["session"]
        self.assertEqual(
            {
                "agent_skills": "native",
                "explicit_invocation": "native",
                "project_hooks": "unsupported",
                "blocking_pre_tool_hook": "unsupported",
                "mcp": "unsupported",
                "native_memory": "unsupported",
                "proposal_apply": "adapter",
                "skill_allowlists": "unsupported",
                "execution_authorization": "unsupported",
            },
            session["capabilities"],
        )
        for surface in DESCRIPTOR["surfaces"].values():
            self.assertIsNone(surface["hook_output"])

    def test_guide_preserves_repo_account_and_data_transfer_boundaries(self) -> None:
        guide = " ".join(GUIDE_PATH.read_text(encoding="utf-8").split())
        for required in (
            "Git-based blueprints are not currently supported",
            "Context OS ships no `.devin/` file or blueprint YAML",
            "That means only \"selected for this workspace.\"",
            "does not certify the Devin account",
            "Secrets are injected by Devin rather than committed here",
            "can persist it in the snapshot",
            "Devin Review is not a session",
            "sends the diff and file contents to Devin servers",
            "local git access for the Review CLI does not prove Devin account access",
            "documentation or local registration alone must never turn them green",
            "Review needs its own fixtures",
            "does not authenticate who supplied the confirmation",
            "do not run lifecycle skills in unattended sessions",
            "Every shipped lifecycle core and short alias carries",
        ):
            with self.subTest(required=required):
                self.assertIn(required, guide)

    def test_adapter_does_not_ship_fake_devin_configuration(self) -> None:
        for path in (".devin", "devin.yaml", "devin.yml", "blueprint.yaml"):
            with self.subTest(path=path):
                self.assertFalse((ROOT / path).exists())

    def test_review_fixture_is_scoped_inert_and_unique(self) -> None:
        fixture = ROOT / "adapters/devin/review-fixture"
        instructions = (fixture / "REVIEW.md").read_text(encoding="utf-8")
        control = (fixture / "control.txt").read_text(encoding="utf-8")
        self.assertIn("Do not propose or apply fixes", instructions)
        self.assertIn("CONTEXTOS_DEVIN_REVIEW_CANARY_63F0A2D8", instructions)
        self.assertEqual("CONTEXTOS_DEVIN_REVIEW_PROHIBITED_MARKER\n", control)


class DevinLiveAccountGateTest(unittest.TestCase):
    def test_live_account_harness_requires_explicit_credentials_and_opt_ins(self) -> None:
        source = (ROOT / "adapters/devin/live_conformance.py").read_text(encoding="utf-8")
        for required in (
            "DEVIN_API_TOKEN",
            "--expected-active-build",
            "--allow-account-access",
            "--allow-session-create",
            "--acknowledge-public-fixture",
            '"review_not_invoked": True',
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)


if __name__ == "__main__":
    unittest.main()
