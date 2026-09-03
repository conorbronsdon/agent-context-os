from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = json.loads((ROOT / "runtimes/openclaw.json").read_text(encoding="utf-8"))
LIFECYCLE_SKILLS = {
    "setup", "context-setup", "start", "context-start",
    "update", "context-update", "end", "context-end",
}


class OpenClawDescriptorTest(unittest.TestCase):
    def test_support_claims_are_first_class_and_hook_free(self) -> None:
        surface = DESCRIPTOR["surfaces"]["cli"]
        self.assertEqual("first-class", DESCRIPTOR["support_tier"])
        self.assertEqual("first-class", surface["support_tier"])
        self.assertEqual("unsupported", surface["capabilities"]["project_hooks"])
        self.assertEqual("unsupported", surface["capabilities"]["blocking_pre_tool_hook"])
        self.assertIsNone(surface["hook_output"])

    def test_lifecycle_uses_alias_bound_plugin_invocation(self) -> None:
        invocation = DESCRIPTOR["surfaces"]["cli"]["invocation"]
        self.assertEqual(
            {
                name: f"/contextos <alias> {name}"
                for name in ("setup", "start", "update", "end")
            },
            invocation,
        )
        self.assertEqual(
            "adapter",
            DESCRIPTOR["surfaces"]["cli"]["capabilities"]["explicit_invocation"],
        )
        next_steps = "\n".join(DESCRIPTOR["install"]["next_steps"])
        self.assertIn("/contextos <alias> continue <session-key> <response>", next_steps)
        self.assertIn("contextos.continue", next_steps)
        self.assertIn("trusted shell", next_steps)
        self.assertIn("plugin exposes no apply method", next_steps)
        plugin_evidence = next(
            source for source in DESCRIPTOR["evidence"]["sources"]
            if source["id"] == "openclaw-plugin-conformance"
        )
        self.assertNotIn("proposal_apply", plugin_evidence["claims"])

    def test_repository_and_private_workspace_roles_are_distinct(self) -> None:
        sources = DESCRIPTOR["surfaces"]["cli"]["instruction_sources"]
        repository = [source for source in sources if source["scope"] == "repository"]
        workspace = [source for source in sources if source["scope"] == "workspace"]
        self.assertEqual(["AGENTS.md"], [source["path"] for source in repository])
        self.assertEqual(
            {"SOUL.md", "USER.md", "MEMORY.md"},
            {source["path"] for source in workspace},
        )
        self.assertEqual(len(sources), len({source["precedence"] for source in sources}))
        skill_sources = DESCRIPTOR["surfaces"]["cli"]["skill_sources"]
        self.assertTrue(skill_sources)
        self.assertEqual({"workspace"}, {source["scope"] for source in skill_sources})

    def test_guide_preserves_security_and_memory_boundaries(self) -> None:
        guide = (ROOT / "adapters/openclaw/README.md").read_text(encoding="utf-8")
        for required in (
            "private workspace", "Synchronize all eight together", "skills.load.extraDirs",
            "preserves unrelated skills", "Gateway `agent` RPC", "plugin-owned subagent",
            "configured project alias", "operator-scoped Gateway methods",
            "`contextos.continue`", "`lightContext: true`", "trusted shell",
            "if the Gateway\nrestarts or reaches that bound",
            "shell-execution authorization", "installs no project hook",
            "include all eight lifecycle skill names", "not synchronized",
            "doctor --lint --json", "Do not use `--fix`",
        ):
            with self.subTest(required=required):
                self.assertIn(required, guide)

    def test_canonical_lifecycle_skills_enforce_exact_root_roles(self) -> None:
        required = (
            "exact roots supplied by the host attachment",
            "require all three exact absolute paths",
            "Do not search upward or infer a root from cwd or the skill installation",
            "missing, moved, stale, linked, nested, or mismatched binding stops",
            "ContextRoot\nowns all lifecycle writes",
            "WorkingRoot is read-only evidence",
            "colocated\n`bash scripts/contextos.sh <command>` compatibility form remains valid",
        )
        for name in ("context-setup", "context-start", "context-update", "context-end"):
            skill = (ROOT / ".agents/skills" / name / "SKILL.md").read_text(
                encoding="utf-8"
            )
            for phrase in required:
                with self.subTest(skill=name, phrase=phrase):
                    self.assertIn(phrase, skill)

    def test_lifecycle_aliases_delegate_to_guarded_canonical_skills(self) -> None:
        for name in ("setup", "start", "update", "end"):
            skill = (ROOT / ".agents/skills" / name / "SKILL.md").read_text(
                encoding="utf-8"
            )
            self.assertIn(f"../context-{name}/SKILL.md", skill)
            self.assertIn("do not duplicate or modify the workflow", skill)

    def test_openclaw_guide_documents_trusted_cwd_and_containment_limit(self) -> None:
        guide = (ROOT / "adapters/openclaw/README.md").read_text(encoding="utf-8")
        for required in (
            "plugin-owned subagent with the configured root as `cwd`",
            "Do not use `openclaw acp client --cwd <repository>`",
            "not OS-level\n  containment",
            "There is no\n`contextos.apply` Gateway method",
            "does not execute repository-writable scripts",
            "bash scripts/contextos.sh apply <proposal>",
        ):
            with self.subTest(required=required):
                self.assertIn(required, guide)
        self.assertNotIn("bashPath", guide)
        self.assertNotIn("openclaw gateway call contextos.apply", guide)

    def test_plugin_runtime_files_are_component_owned(self) -> None:
        manifest = json.loads(
            (ROOT / "components/manifest.json").read_text(encoding="utf-8")
        )
        component = next(
            item for item in manifest["components"] if item["id"] == "openclaw-adapter"
        )
        owned = {item["path"]: item["policy"] for item in component["paths"]}
        expected = {
            "adapters/openclaw/plugin/index.js": "managed",
            "adapters/openclaw/plugin/lib.js": "managed",
            "adapters/openclaw/plugin/openclaw.plugin.json": "managed",
            "adapters/openclaw/plugin/package.json": "managed",
            "adapters/openclaw/plugin/plugin.test.mjs": "development",
        }
        for path, policy in expected.items():
            with self.subTest(path=path):
                self.assertEqual(policy, owned.get(path))

    def test_shared_guides_use_the_plugin_command_surface(self) -> None:
        for relative in (
            "README.md",
            "docs/commands-and-skills.md",
            "docs/getting-started.md",
            "AGENTS.md",
            "scripts/setup.sh",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertIn("/contextos <alias> setup", text)
                self.assertNotIn("`/skill setup`", text)
                self.assertNotIn("installs no hook or plugin", text)

    def test_canonical_docs_do_not_describe_obsolete_experimental_openclaw(self) -> None:
        for relative in ("AGENTS.md", "CHANGELOG.md"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertNotIn("Experimental OpenClaw", text)
                self.assertNotIn("experimental skills-first OpenClaw", text)


@unittest.skipUnless(
    os.environ.get("CONTEXTOS_OPENCLAW_BIN"),
    "set CONTEXTOS_OPENCLAW_BIN to the exact tested OpenClaw executable",
)
class InstalledOpenClawTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.binary = os.environ["CONTEXTOS_OPENCLAW_BIN"]

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.scratch = Path(self.temporary.name).resolve()
        self.state = self.scratch / "state"
        self.workspace = self.scratch / "private-workspace"
        (self.workspace / ".agents/skills").mkdir(parents=True)
        for skill in LIFECYCLE_SKILLS:
            shutil.copytree(ROOT / ".agents/skills" / skill, self.workspace / ".agents/skills" / skill)
        self._write_config()

    def _write_config(self, *, allowed_skills: list[str] | None = None) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        defaults: dict[str, object] = {
            "workspace": str(self.workspace),
            "skipBootstrap": True,
        }
        if allowed_skills is not None:
            defaults["skills"] = allowed_skills
        (self.state / "openclaw.json").write_text(
            json.dumps({"agents": {"defaults": defaults}}),
            encoding="utf-8",
        )

    def _run(
        self, *args: str, allowed_codes: tuple[int, ...] = (0,),
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["OPENCLAW_STATE_DIR"] = str(self.state)
        result = subprocess.run(
            [self.binary, *args], cwd=cwd or ROOT, env=env, text=True,
            encoding="utf-8", errors="replace", capture_output=True,
            check=False, timeout=60,
        )
        self.assertIn(result.returncode, allowed_codes, result.stderr or result.stdout)
        return result

    def _skills(self, *, cwd: Path | None = None) -> dict[str, dict]:
        report = json.loads(self._run("skills", "list", "--json", cwd=cwd).stdout)
        return {skill["name"]: skill for skill in report["skills"]}

    def test_exact_version_and_copied_lifecycle_inventory(self) -> None:
        expected = DESCRIPTOR["evidence"]["tested_versions"][0]["version"]
        self.assertEqual(expected, self._run("--version").stdout.strip())
        skills = self._skills(cwd=self.workspace)
        self.assertTrue(LIFECYCLE_SKILLS <= set(skills))
        for name in LIFECYCLE_SKILLS:
            with self.subTest(name=name):
                skill = skills[name]
                self.assertEqual("agents-skills-project", skill["source"])
                self.assertTrue(skill["eligible"])
                self.assertTrue(skill["modelVisible"])
                self.assertTrue(skill["userInvocable"])
                self.assertTrue(skill["commandVisible"])

    def test_repository_cwd_does_not_substitute_for_missing_workspace_copies(self) -> None:
        sentinel = self.workspace / "skills/inventory-sentinel"
        sentinel.mkdir(parents=True)
        (sentinel / "SKILL.md").write_text(
            "---\nname: inventory-sentinel\n"
            "description: Proves that the negative-control inventory is live.\n"
            "---\nSentinel.\n",
            encoding="utf-8",
        )
        shutil.rmtree(self.workspace / ".agents/skills")
        (self.workspace / ".agents/skills").mkdir(parents=True)
        skills = self._skills()
        self.assertEqual("openclaw-workspace", skills["inventory-sentinel"]["source"])
        self.assertTrue(
            LIFECYCLE_SKILLS.isdisjoint(skills),
            sorted(LIFECYCLE_SKILLS & skills.keys()),
        )

    def test_workspace_skill_shadows_project_agent_skill_and_fallback_fires(self) -> None:
        project = self.workspace / ".agents/skills/collision-probe"
        workspace = self.workspace / "skills/collision-probe"
        project.mkdir(parents=True)
        workspace.mkdir(parents=True)
        (project / "SKILL.md").write_text(
            "---\nname: collision-probe\ndescription: Project-agent sentinel.\n---\nProject.\n",
            encoding="utf-8",
        )
        (workspace / "SKILL.md").write_text(
            "---\nname: collision-probe\ndescription: Workspace sentinel.\n---\nWorkspace.\n",
            encoding="utf-8",
        )
        winner = self._skills()["collision-probe"]
        self.assertEqual("openclaw-workspace", winner["source"])
        self.assertEqual("Workspace sentinel.", winner["description"])
        shutil.rmtree(workspace)
        fallback = self._skills()["collision-probe"]
        self.assertEqual("agents-skills-project", fallback["source"])
        self.assertEqual("Project-agent sentinel.", fallback["description"])

    def test_empty_agent_allowlist_hides_but_does_not_relabel_skills(self) -> None:
        self._write_config(allowed_skills=[])
        skill = self._skills()["setup"]
        self.assertTrue(skill["eligible"])
        self.assertTrue(skill["blockedByAgentFilter"])
        self.assertFalse(skill["modelVisible"])
        self.assertTrue(skill["userInvocable"])
        self.assertFalse(skill["commandVisible"])

    def test_native_lint_is_machine_readable_without_writing_repo_memory(self) -> None:
        before = {name: (ROOT / name).exists() for name in ("SOUL.md", "USER.md", "MEMORY.md", "memory")}
        report = json.loads(self._run("doctor", "--lint", "--json", allowed_codes=(0, 1)).stdout)
        self.assertGreater(report["checksRun"], 0)
        self.assertEqual(before, {name: (ROOT / name).exists() for name in before})


if __name__ == "__main__":
    unittest.main()
