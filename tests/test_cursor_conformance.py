from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = json.loads((ROOT / "runtimes/cursor.json").read_text(encoding="utf-8"))
LIFECYCLE_SKILLS = tuple(
    ROOT / ".agents" / "skills" / name / "SKILL.md"
    for name in (
        "context-setup", "context-start", "context-update", "context-end",
        "setup", "start", "update", "end",
    )
)
LIFECYCLE = {
    name: f"/context-{name}" for name in ("setup", "start", "update", "end")
}


class CursorDescriptorTest(unittest.TestCase):
    def test_ide_and_cli_remain_distinct_experimental_surfaces(self) -> None:
        self.assertEqual("experimental", DESCRIPTOR["support_tier"])
        self.assertEqual({"ide", "cli"}, set(DESCRIPTOR["surfaces"]))
        ide = DESCRIPTOR["surfaces"]["ide"]
        cli = DESCRIPTOR["surfaces"]["cli"]
        self.assertEqual("ide", ide["kind"])
        self.assertEqual("cli", cli["kind"])
        self.assertEqual(
            [
                {"purpose": "availability", "candidates": ["cursor"]},
                {"purpose": "version", "candidates": ["cursor"]},
            ],
            ide["binary_probes"],
        )
        self.assertEqual([], cli["binary_probes"])
        self.assertNotEqual(
            ide["binary_probes"], cli["binary_probes"],
            "IDE availability must not stand in for CLI availability",
        )

    def test_both_surfaces_use_shared_instructions_and_explicit_skills(self) -> None:
        for surface_name, surface in DESCRIPTOR["surfaces"].items():
            with self.subTest(surface=surface_name):
                self.assertEqual(LIFECYCLE, surface["invocation"])
                self.assertEqual(
                    ["AGENTS.md"],
                    [source["path"] for source in surface["instruction_sources"]],
                )
                self.assertEqual(
                    [".agents/skills"],
                    [source["path"] for source in surface["skill_sources"]],
                )
                self.assertEqual("native", surface["capabilities"]["agent_skills"])
                self.assertEqual("native", surface["capabilities"]["explicit_invocation"])

    def test_every_lifecycle_skill_is_explicit_only_in_cursor(self) -> None:
        for skill in LIFECYCLE_SKILLS:
            with self.subTest(skill=skill.parent.name):
                frontmatter = skill.read_text(encoding="utf-8").split("---", 2)[1]
                self.assertIn("disable-model-invocation: true", frontmatter)

    def test_unverified_hooks_memory_and_collisions_are_not_claimed(self) -> None:
        self.assertEqual([], DESCRIPTOR["evidence"]["tested_versions"])
        for surface_name, surface in DESCRIPTOR["surfaces"].items():
            with self.subTest(surface=surface_name):
                self.assertEqual("unsupported", surface["capabilities"]["project_hooks"])
                self.assertEqual(
                    "unsupported", surface["capabilities"]["blocking_pre_tool_hook"]
                )
                self.assertEqual("unsupported", surface["capabilities"]["native_memory"])
                self.assertEqual("unsupported", surface["capabilities"]["skill_allowlists"])
                self.assertIsNone(surface["hook_output"])

    def test_evidence_and_install_steps_do_not_flatten_the_surfaces(self) -> None:
        ide_evidence = set(DESCRIPTOR["surfaces"]["ide"]["evidence"])
        cli_evidence = set(DESCRIPTOR["surfaces"]["cli"]["evidence"])
        self.assertFalse(any(item.startswith("cursor-cli-") for item in ide_evidence))
        self.assertTrue(
            {"cursor-cli-using", "cursor-cli-headless", "cursor-cli-permissions"}
            <= cli_evidence
        )
        self.assertNotIn("cursor-run-modes", cli_evidence)
        install_text = "\n".join(DESCRIPTOR["install"]["next_steps"])
        self.assertNotIn("--trust", install_text)
        self.assertNotIn("--force", install_text)
        cli = DESCRIPTOR["surfaces"]["cli"]
        self.assertIn("tests/test_cursor_live_harness.py", cli["conformance_tests"])
        self.assertIn("cursor-live-harness", cli["evidence"])
        self.assertNotIn(
            "tests/test_cursor_live_harness.py",
            DESCRIPTOR["surfaces"]["ide"]["conformance_tests"],
        )
        self.assertNotIn("cursor-live-harness", ide_evidence)

    def test_unrun_harnesses_do_not_claim_capability_evidence(self) -> None:
        sources = {source["id"]: source for source in DESCRIPTOR["evidence"]["sources"]}
        for name in ("cursor-ide-harness", "cursor-live-harness"):
            self.assertEqual(["support"], sources[name]["claims"])

    def test_guide_states_discovery_and_ide_file_read_limits(self) -> None:
        guide = (ROOT / "adapters/cursor/README.md").read_text(encoding="utf-8")
        self.assertIn("do not isolate\nautomatic discovery from a prompted file read", guide)
        self.assertIn("cannot establish that the slash\ncommand resolved", guide)
        self.assertIn("as `unverified`", guide)

    def test_adapter_does_not_ship_unverified_cursor_configuration(self) -> None:
        if os.environ.get("CONTEXTOS_VALIDATION_PROFILE") == "workspace":
            self.skipTest("workspace-owned .cursor configuration is permitted")
        for path in (
            ".cursor/rules",
            ".cursor/hooks.json",
            ".cursor/cli.json",
            ".cursor/permissions.json",
            ".cursor/mcp.json",
            ".cursor/skills",
        ):
            with self.subTest(path=path):
                self.assertFalse((ROOT / path).exists())

    def test_guide_names_the_unsupported_and_authorization_boundaries(self) -> None:
        guide = (ROOT / "adapters/cursor/README.md").read_text(encoding="utf-8")
        normalized = " ".join(guide.split())
        for required in (
            "A green CLI check is not IDE evidence",
            "does not document which source wins",
            "ships no Cursor rule file",
            "same-name collision winner",
            "built-in `/update`",
            "Cursor discovers both sets",
            "does not document whether its built-in `/update`",
            "agent -p --force",
            "too generic for safe automatic detection",
            "explicit deny wins an allow",
            "not approval of a Context OS proposal",
            "ships no Cursor hook adapter",
            "otherwise fail open by default",
            "No Cursor-native memory is synchronized",
            "Never run a `--force` conformance check against a real context repository",
            "exact-version conformance for both surfaces",
            "aggregate availability status reflects only",
            "exact-version and required-flag smoke test",
            "Cursor CLI also reads a root `CLAUDE.md`",
            "removable seed",
            "Project-owned `.cursor/` configuration is permitted",
            "Every shipped lifecycle core and short alias",
            "A passing CLI artifact is not IDE evidence",
        ):
            with self.subTest(required=required):
                self.assertIn(required, normalized)


@unittest.skipUnless(
    os.environ.get("CONTEXTOS_CURSOR_CLI_BIN")
    and os.environ.get("CONTEXTOS_CURSOR_CLI_VERSION"),
    "set CONTEXTOS_CURSOR_CLI_BIN and CONTEXTOS_CURSOR_CLI_VERSION for the exact CLI",
)
class CursorCliSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.binary = Path(os.environ["CONTEXTOS_CURSOR_CLI_BIN"]).resolve(strict=True)
        if not cls.binary.is_file():
            raise unittest.SkipTest("CONTEXTOS_CURSOR_CLI_BIN is not an exact file")
        cls.expected_version = os.environ["CONTEXTOS_CURSOR_CLI_VERSION"]
        cls.temporary = tempfile.TemporaryDirectory()
        cls.cwd = Path(cls.temporary.name).resolve()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.binary), *args],
            cwd=self.cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=60,
        )

    def test_exact_version_and_required_headless_controls(self) -> None:
        version = self._run("--version")
        self.assertEqual(0, version.returncode, version.stderr)
        self.assertEqual(self.expected_version, version.stdout.strip())
        help_result = self._run("--help")
        self.assertEqual(0, help_result.returncode, help_result.stderr)
        help_text = help_result.stdout + help_result.stderr
        for required in ("--print", "--force", "--workspace", "--trust"):
            with self.subTest(required=required):
                self.assertIn(required, help_text)


if __name__ == "__main__":
    unittest.main()
