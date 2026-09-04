import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from contextos.cli import parser as contextos_parser
from contextos.kernel import (
    LIFECYCLE_PRODUCT_ROOTS,
    SETUP_FILES,
    SETUP_ROOTS,
    SETUP_SKILL_PREFIX,
)

# Shell out to the interpreter running these tests, never a bare "python3".
#
# On Windows "python3" resolves to the Microsoft Store App Execution Alias — a
# stub that prints "Python was not found; run without arguments to install from
# the Microsoft Store" and exits WITHOUT running Python. Every test that shells
# out then reads empty stdout and dies on json.loads(""), which surfaces as
# "Expecting value: line 1 column 1 (char 0)" and looks like a helper bug rather
# than a missing interpreter. That took out 34 of 89 tests.
#
# sys.executable is also correct on POSIX and in a venv, where a bare "python3"
# can be a DIFFERENT interpreter than the one running the suite.
PYTHON = sys.executable


ROOT = Path(__file__).resolve().parents[1]


class DocumentationPositioningTests(unittest.TestCase):
    def text(self, path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    def test_readme_routes_the_four_core_jobs(self) -> None:
        readme = self.text("README.md")
        self.assertIn("Git-backed context and workflow layer", readme)
        self.assertIn("does not scrape every account", readme)
        self.assertIn("private repository", readme)
        for host in ("Claude Code", "Codex", "claude.ai", "Gemini CLI"):
            self.assertIn(host, readme)
        for target in (
            "docs/migration-guide.md",
            "docs/integrations-guide.md",
            "docs/codex-onboarding.md",
            "docs/getting-started.md",
        ):
            self.assertIn(target, readme)

    def test_repository_name_is_preserved_without_neutral_parity_overclaim(self) -> None:
        readme = self.text("README.md")
        self.assertIn("# Context OS", readme)
        # Renamed claude-context-os -> agent-context-os (Aug 2026); old URLs redirect.
        self.assertIn("conorbronsdon/agent-context-os.git", readme)
        self.assertNotIn("claude-context-os", readme)

    def test_v012_root_contract_is_explicit_and_routed(self) -> None:
        contract = self.text("docs/root-contract.md")
        for role in ("KernelRoot", "ContextRoot", "WorkingRoot"):
            self.assertIn(role, contract)
        self.assertIn(
            "ContextRoot == nominal WorkingRoot == canonical discovered root",
            contract,
        )
        self.assertIn("KernelRoot == ContextRoot", contract)
        self.assertIn("GitEvidenceScope", contract)
        self.assertIn("marker-only", contract)
        self.assertIn("`generic` execution is reserved", contract)
        self.assertIn("Git cannot", contract)
        self.assertIn("`bundle propose` without current", contract)
        self.assertIn("`template.source`", contract)
        self.assertIn("`bundle compose` command is not the marker-only path", contract)
        self.assertIn("The only mutation authority", contract)
        self.assertIn("not a supported v0.12 lifecycle path", contract)
        self.assertIn("no tracked pointer", contract)
        self.assertIn("supplies the starting path", contract)
        self.assertIn("managed` records", contract)
        self.assertIn("enclosing Git worktree", contract)
        self.assertIn("deliberate exception", contract)
        self.assertIn("discovery start", contextos_parser().format_help())
        self.assertIn(
            "archive a complete copy",
            self.text("docs/workspace-configuration.md").casefold(),
        )
        workspace_contract = self.text("docs/workspace-configuration.md")
        self.assertIn("marker-only root is not the same as a core-only profile", workspace_contract)
        self.assertIn("Use `workspace reconcile` for the supported path", workspace_contract)
        self.assertIn("`template.bundle_sha256`", workspace_contract)
        for root in SETUP_ROOTS:
            self.assertIn(f"`{root}/`", contract)
        for filename in SETUP_FILES:
            self.assertIn(f"`{filename}`", contract)
        self.assertEqual((".agents", "skills"), SETUP_SKILL_PREFIX)
        setup_skill_root = "/".join(SETUP_SKILL_PREFIX) + "/"
        self.assertIn(f"`{setup_skill_root}`", contract)
        expected_product_roots = {
            ".agents", ".claude", ".codex", ".cursor", ".github",
            "adapters", "bundles", "components", "contextos", "integrations",
            "runtimes", "scripts", "workspace",
        }
        self.assertEqual(expected_product_roots, LIFECYCLE_PRODUCT_ROOTS)
        for protected in expected_product_roots:
            self.assertIn(f"`{protected}/`", contract)

        for path in (
            "README.md",
            "docs/cross-runtime-architecture.md",
            "docs/getting-started.md",
            "docs/workspace-configuration.md",
        ):
            self.assertIn("root contract", self.text(path).casefold(), path)

        for workflow in ("setup", "start", "update", "end"):
            skill = self.text(f".agents/skills/context-{workflow}/SKILL.md")
            self.assertIn("KernelRoot", skill, workflow)
            self.assertIn("ContextRoot", skill, workflow)
            self.assertIn("WorkingRoot", skill, workflow)
            self.assertIn("--context-root", skill, workflow)
            self.assertIn("WorkingRoot is read-only evidence", skill, workflow)

    def test_getting_started_keeps_mutations_opt_in(self) -> None:
        guide = self.text("docs/getting-started.md")
        for phrase in (
            "do not store credentials, raw account exports",
            "Each optional change is prompted",
            "Avoid bulk ingestion",
            "Core setup requires no external integration",
            "$setup",
            "/setup",
            "private remote",
            "Antigravity",
        ):
            self.assertIn(phrase, guide)
        codex = self.text("docs/codex-onboarding.md")
        self.assertIn("up to 50 recent chats from the last 30 days", codex)
        self.assertIn("cannot prove the behavior of every installed Codex version", codex)

    def test_integration_chooser_links_only_cataloged_entries(self) -> None:
        guide = self.text("docs/integrations-guide.md")
        catalog = json.loads(self.text("integrations/catalog.json"))
        catalog_anchors = {
            re.sub(r"[^a-z0-9]+", "-", item["name"].casefold()).strip("-")
            for item in catalog["integrations"]
        }
        linked_ids = re.findall(r"references/integrations\.md#([a-z0-9-]+)", guide)
        self.assertTrue(linked_ids)
        self.assertEqual(len(linked_ids), len(set(linked_ids)))
        self.assertLessEqual(set(linked_ids), catalog_anchors)
        self.assertIn("curated", guide)
        self.assertIn("not an exhaustive inventory", guide)
        self.assertIn("Nothing in this guide installs", guide)
        self.assertIn("not live authentication", guide)

    def test_integration_prose_routes_to_the_generated_current_inventory(self) -> None:
        catalog = json.loads(self.text("integrations/catalog.json"))
        sections = {
            "README.md": self.text("README.md")
            .split("## Optional integrations", 1)[1]
            .split("\n## ", 1)[0],
            "docs/launch-copy.md": self.text("docs/launch-copy.md")
            .split("## Changelog post", 1)[1]
            .split("\n## ", 1)[0],
        }
        for path, prose in sections.items():
            normalized = re.sub(r"\s+", " ", prose.casefold())
            self.assertIn("generated catalog", normalized, path)
            self.assertIn("current inventory", normalized, path)
            enumerated = [
                item["name"]
                for item in catalog["integrations"]
                if item["name"].casefold() in normalized
            ]
            self.assertEqual(
                [], enumerated, f"{path} must not enumerate catalog entries"
            )
        self.assertIn("references/integrations.md", self.text("README.md"))
        launch = self.text("docs/launch-copy.md")
        self.assertIn("../references/integrations.md", launch)
        self.assertIn("../integrations/entries/", launch)

    def test_uncataloged_integrations_are_not_live(self) -> None:
        tracked_mcp = subprocess.run(
            ["git", "ls-files", "--", ".mcp.json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual("", tracked_mcp, "the template must not track a live MCP configuration")
        tracked_claude = subprocess.run(
            ["git", "ls-files", "--", ".claude"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        for relative_path in tracked_claude:
            host_config = self.text(relative_path)
            self.assertNotIn("mcp__google-workspace", host_config, relative_path)
            self.assertNotIn("gws mcp", host_config, relative_path)
        state_refs = self.text("state/gws-references.md")
        start = self.text(".claude/commands/start.md")
        self.assertRegex(state_refs, r"Claude `/start` adapter may\s+read it")
        self.assertRegex(state_refs, r"already\s+installed and authenticated")
        self.assertIn("state/gws-references.md", start)
        self.assertIn("normal tool approval flow", start)
        notion = self.text("references/notion-mcp-setup.md")
        self.assertIn("hosted, actively maintained MCP server", notion)
        self.assertIn("Context OS does not add the server", notion)
        self.assertNotIn("npm install -g @notionhq/notion-mcp-server", notion)
        self.assertNotIn("ntn_YOUR_KEY_HERE", notion)

    def test_setup_prompts_match_portable_layout(self) -> None:
        prompts = self.text("SETUP-PROMPTS.md")
        self.assertNotIn("commits changes", prompts)
        self.assertIn("Codex", prompts)
        self.assertIn(".agents/skills/", prompts)
        self.assertNotIn("projects/[project-name]/skills/", prompts)
        for section in prompts.split("## Prompt ")[1:]:
            self.assertRegex(
                section,
                r"(?i)(?:do not|without claiming to)[^\n]*(?:write|create|edit|change|update)",
            )
            self.assertRegex(section, r"(?i)draft")
            self.assertIn("durable in git", section)
        prompt_two = prompts.split("## Prompt 2:", 1)[1].split("## Prompt 3:", 1)[0]
        self.assertIn("copy-and-rename checklist", prompt_two)
        self.assertIn("after review", prompt_two)

    def test_migration_guide_covers_supported_source_paths(self) -> None:
        guide = self.text("docs/migration-guide.md")
        for heading in ("ChatGPT", "Claude and claude.ai projects", "Gemini CLI", "Codex `/import`", "Another assistant or agent"):
            self.assertIn(heading, guide)
        self.assertIn("Never commit the archive", guide)
        self.assertIn("Keep raw exports outside the repository", guide)
        self.assertIn("Both paths start metadata-first", guide)

    def test_native_gemini_import_is_handed_off_as_a_slash_command(self) -> None:
        for path in ("docs/gemini-migration.md", ".agents/skills/migrate-gemini/SKILL.md"):
            text = self.text(path)
            self.assertIn("/import gemini --dry-run", text)
            self.assertNotIn("claude import gemini", text)
        self.assertIn("cannot invoke that slash command for you", self.text("docs/gemini-migration.md"))

    def test_current_gemini_and_codex_import_boundaries_are_explicit(self) -> None:
        for path in ("README.md", "docs/getting-started.md", "docs/migration-guide.md", "docs/gemini-migration.md"):
            text = self.text(path)
            self.assertIn("Antigravity", text, path)
        migration = self.text("docs/migration-guide.md")
        self.assertIn("at most 50 recent chats from the last 30 days", migration)
        self.assertIn("unavailable inside a running task", migration)
        self.assertNotIn("not a conversation or memory importer", migration)

    def test_portable_skill_docs_use_native_discovery_paths(self) -> None:
        for path in ("docs/first-skill.md", "docs/agent-template.md", "projects/README.md"):
            self.assertIn(".agents/skills/", self.text(path))
        projects = self.text("projects/README.md")
        self.assertIn("workflow-examples", projects)
        self.assertIn("agents do not discover them as active skills", projects)

    def test_memory_docs_do_not_guess_claude_internal_paths(self) -> None:
        paths = (
            "README.md",
            "CLAUDE.md",
            "docs/auto-memory.md",
            "docs/memory-template.md",
            "docs/dream-architecture.md",
            "scripts/dream/README.md",
            ".claude/commands/dream.md",
            ".claude/commands/dream-apply.md",
            ".claude/commands/end.md",
        )
        for path in paths:
            text = self.text(path)
            self.assertNotIn("<encoded-cwd>", text, path)
            self.assertNotIn("PROJECT_KEY=$(pwd", text, path)
        spec = self.text("docs/auto-memory.md")
        self.assertIn("autoMemoryDirectory", spec)
        self.assertIn(".claude/settings.local.json", spec)
        self.assertIn(".context-os/memory-directory", spec)
        self.assertIn("Pattern, standalone contradiction, untapped-work, and audit", spec)
        self.assertIn("autoMemoryEnabled", spec)
        self.assertIn("git common directory", spec)
        self.assertIn("environment", spec)
        self.assertIn(".claude/settings.local.json", self.text(".gitignore"))

    def test_memory_type_definitions_match_exactly(self) -> None:
        expected = {"user", "feedback", "environment", "project", "reference"}
        spec_section = self.text("docs/auto-memory.md").split(
            "Use five durable types:", 1
        )[1].split("Convert relative dates", 1)[0]
        spec_types = set(re.findall(r"^- `([a-z]+)`", spec_section, re.MULTILINE))
        self.assertEqual(expected, spec_types)

        claude = self.text("CLAUDE.md")
        self.assertIn(
            "Typed entries use `user`, `feedback`, `environment`, `project`, and `reference`",
            claude,
        )
        template = self.text("docs/memory-template.md")
        self.assertIn(
            "(`user`, `feedback`, `environment`, `project`, or `reference`)",
            template,
        )

    def test_dream_commands_delegate_path_safety_to_executable_validator(self) -> None:
        dream = self.text(".claude/commands/dream.md")
        apply = self.text(".claude/commands/dream-apply.md")
        helper = ROOT / "scripts/dream/validate-memory.py"
        self.assertTrue(helper.is_file())
        self.assertIn("validate-memory.py resolve", dream)
        self.assertIn('validate-memory.py artifact "$TS" --for-create', dream)
        self.assertIn('validate-memory.py artifact "$TS"', dream)
        self.assertIn('validate-memory.py artifact "${ARGUMENTS:-latest}"', apply)
        self.assertLess(
            dream.index("### 8. Write `REPORT.md`"),
            dream.index('validate-memory.py artifact "$TS" --for-commit'),
        )
        self.assertIn("validate-memory.py changes", apply)
        self.assertIn("--expect-digest", apply)
        self.assertIn("--staged", apply)
        self.assertIn("disables rename detection", apply)
        self.assertIn("validate-memory.py commit", apply)
        self.assertIn("separate explicit final commit approval", apply)
        self.assertIn('git -C "$MEMORY_DIR" diff "$BASE_HEAD" "$REVIEWED_TREE" --', apply)
        self.assertNotIn('git -C "$MEMORY_DIR" commit ', apply)
        self.assertIn('git -C "$MEMORY_DIR" add -A --', apply)
        self.assertNotIn('git -C "$MEMORY_DIR" add -A\n', apply)
        self.assertNotIn('git -C "$MEMORY_DIR" add ".dreams/$TS/"', dream)
        for text in (dream, apply):
            self.assertIn("untracked", text)
            self.assertIn("unrelated", text)
        for obsolete in (
            "require the marker's only line to equal `git rev-parse --show-toplevel`",
            "treat `$ARGUMENTS` as the ISO timestamp",
        ):
            self.assertNotIn(obsolete, dream + apply)
        self.assertIn("archive-state", apply)
        self.assertIn("Stamp the file only when `insert_stamp` is true", apply)
        lint = self.text("scripts/dream/prompts/lint.md")
        self.assertIn("root present + one row resumes", lint)
        self.assertIn("inserts a stamp only when absent", lint)

    def test_gws_safety_claims_have_direct_pinned_evidence(self) -> None:
        catalog = json.loads(self.text("integrations/catalog.json"))
        gws = next(item for item in catalog["integrations"] if item["id"] == "google-workspace-cli")
        evidence = gws["evidence"]
        self.assertTrue(any(url.endswith("/crates/google-workspace-cli/src/auth_commands.rs") for url in evidence))
        self.assertTrue(any(url.endswith("/CHANGELOG.md") for url in evidence))
        for url in evidence:
            self.assertIn("/blob/a3768d0e82ad83cca2da97724e46bea4ff0e6dbd/", url)

    def test_context_optimization_avoids_fixed_pdf_arithmetic(self) -> None:
        guide = self.text("docs/optimizing-context.md")
        self.assertNotIn("3–5x", guide)
        self.assertNotIn("4,000 tokens", guide)
        self.assertIn("Exact token cost depends on the parser", guide)
        self.assertNotIn("output the full text of each uploaded file", guide)
        self.assertIn("Select exact named files", guide)

    def test_claude_projects_are_documented_as_manual_knowledge_copy(self) -> None:
        guide = self.text("docs/claude-projects-sync.md")
        self.assertIn("manual copy", guide)
        self.assertIn("no live sync", guide)
        self.assertIn("plain project knowledge", guide)
        self.assertIn("cannot write this repository", guide)

    def test_setup_remote_preflight_is_private_by_default(self) -> None:
        setup = self.text("scripts/setup.sh")
        self.assertIn("This workspace can contain identity", setup)
        self.assertIn("does not erase sensitive data from git history", setup)
        self.assertIn("Continue after reviewing this storage and audience boundary?", setup)
        self.assertIn("Have you verified its visibility and intended audience?", setup)
        self.assertIn(
            'prompt_yn "  Have you verified its visibility and intended audience?" "n"',
            setup,
        )
        self.assertEqual(1, setup.count("does not erase sensitive data from git history"))

    def test_setup_help_advertises_every_registered_runtime(self) -> None:
        setup = self.text("scripts/setup.sh")
        usage = re.search(r'^SETUP_USAGE="([^"]+)"$', setup, re.MULTILINE)
        self.assertIsNotNone(usage)
        assert usage is not None
        registered = {
            path.stem for path in (ROOT / "runtimes").glob("*.json")
            if path.name != "schema.json"
        }
        for runtime in registered:
            self.assertIn(runtime, usage.group(1))

    def test_copied_adapter_template_is_narrow_and_user_invoked(self) -> None:
        template = self.text("docs/agent-template.md")
        self.assertIn('allowed-tools: "Read"', template)
        self.assertIn("disable-model-invocation: true", template)
        self.assertNotIn("Read, Bash, Write, Edit, Glob", template)

    def test_command_index_covers_shipped_commands_and_portable_skills(self) -> None:
        index = self.text("docs/commands-and-skills.md")
        workspace = os.environ.get("CONTEXTOS_VALIDATION_PROFILE") == "workspace"
        shipped_commands = {path.stem for path in (ROOT / ".claude/commands").glob("*.md")}
        shared_lifecycle = index.split("## Shared lifecycle", 1)[1].split(
            "The portable cores", 1
        )[0]
        claude_specific = index.split("## Claude-specific command index", 1)[1]
        # Only Claude's lifecycle column and Claude-specific table describe
        # .claude/commands; other host columns may name portable skills.
        indexed_commands = set(
            re.findall(
                r"^\|[^|]+\| `/([a-z0-9]+(?:-[a-z0-9]+)*)` \|",
                shared_lifecycle,
                re.MULTILINE,
            )
        ) | set(
            re.findall(
                r"^\| `/([a-z0-9]+(?:-[a-z0-9]+)*)` \|",
                claude_specific,
                re.MULTILINE,
            )
        )
        if workspace:
            self.assertLessEqual(indexed_commands, shipped_commands)
        else:
            self.assertEqual(shipped_commands, indexed_commands)
        for command in indexed_commands:
            rows = [line for line in index.splitlines() if line.startswith("|") and f"`/{command}`" in line]
            self.assertEqual(1, len(rows), f"/{command} must have exactly one indexed table row")
            cells = [cell.strip() for cell in rows[0].strip("|").split("|")]
            self.assertTrue(all(cells), f"/{command} index row has an empty host/job/effect cell")

        shipped_skills = {path.parent.name for path in (ROOT / ".agents/skills").glob("*/SKILL.md")}
        indexed_skills = set(re.findall(r"`\$([a-z0-9]+(?:-[a-z0-9]+)*)`", index))
        if workspace:
            self.assertLessEqual(indexed_skills, shipped_skills)
        else:
            self.assertEqual(shipped_skills, indexed_skills)

        command_table = self.text("CLAUDE.md").split("## Slash Commands", 1)[1].split("Add more commands", 1)[0]
        claude_commands = set(re.findall(r"^\| `/([a-z0-9]+(?:-[a-z0-9]+)*)`", command_table, re.MULTILINE))
        if workspace:
            self.assertLessEqual(claude_commands, shipped_commands)
        else:
            self.assertEqual(shipped_commands, claude_commands)
        self.assertIn("does not activate", index)

    def test_maintenance_separates_portable_and_host_local_state(self) -> None:
        guide = self.text("docs/maintenance.md")
        self.assertIn("`state/` and `sessions/` are the shared", guide)
        self.assertIn("deleting a file does not erase", guide)
        self.assertIn("`rot`, `merge`, `split`, and `lint`", guide)

    def test_write_or_cleanup_commands_require_explicit_invocation(self) -> None:
        for name in (
            "capture",
            "content-shipped",
            "dream",
            "dream-apply",
            "migrate-gemini",
            "mine-gemini-workflows",
            "reconcile",
            "recover",
            "setup",
            "today",
            "update",
            "end",
        ):
            result = subprocess.run(
                [
                    PYTHON,
                    "tests/validate-openai-metadata.py",
                    "--command",
                    f".claude/commands/{name}.md",
                    name,
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
        reconcile = self.text(".claude/commands/reconcile.md")
        self.assertIn("this command is user-only", reconcile)
        self.assertNotIn("safely model-invocable", reconcile)
        self.assertIn("scoped staged diff", reconcile)


if __name__ == "__main__":
    unittest.main()
