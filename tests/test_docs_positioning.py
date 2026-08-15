import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocumentationPositioningTests(unittest.TestCase):
    def text(self, path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    def test_readme_routes_the_four_core_jobs(self) -> None:
        readme = self.text("README.md")
        self.assertIn("workspace harness", readme)
        self.assertIn("does not provide a model or agent loop", readme)
        self.assertIn("Claude-first, Codex-compatible", readme)
        self.assertIn("Keep it local-only or use a private remote by default", readme)
        self.assertIn("does not erase", readme)
        for host in ("Claude Code", "Codex", "Claude.ai Projects", "Gemini CLI"):
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
        self.assertIn("# claude-context-os", readme)
        self.assertIn("established repository name stays", readme)
        self.assertNotIn("# agent-context-os", readme)

    def test_getting_started_keeps_mutations_opt_in(self) -> None:
        guide = self.text("docs/getting-started.md")
        for phrase in (
            "does not import conversations",
            "does not install integrations",
            "No migration path should copy credentials",
            "at most one new trust boundary at a time",
            "$context-setup",
            "/setup",
            "local-only or use a private remote by default",
            "No lifecycle adapter",
        ):
            self.assertIn(phrase, guide)
        self.assertIn("does not run an installed-host end-to-end session", guide)
        self.assertIn("up to 50 recent chats from the last 30 days", guide)

    def test_integration_chooser_covers_the_catalog(self) -> None:
        guide = self.text("docs/integrations-guide.md")
        catalog = json.loads(self.text("integrations/catalog.json"))
        for item in catalog["integrations"]:
            self.assertIn(item["name"], guide)
        self.assertIn("Nothing in this guide installs", guide)
        self.assertIn("not live authentication", guide)

    def test_uncataloged_integrations_are_not_live(self) -> None:
        tracked_mcp = subprocess.run(
            ["git", "ls-files", "--", ".mcp.json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual("", tracked_mcp, "the template must not track a live MCP configuration")
        for command_path in sorted((ROOT / ".claude/commands").glob("*.md")):
            command = command_path.read_text(encoding="utf-8")
            self.assertNotIn("mcp__google-workspace", command)
            self.assertNotIn("gws mcp", command)
        notion = self.text("references/notion-mcp-setup.md")
        self.assertIn("does not currently ship", notion)
        self.assertNotIn("npm install -g @notionhq/notion-mcp-server", notion)
        self.assertNotIn("ntn_YOUR_KEY_HERE", notion)

    def test_setup_prompts_match_portable_layout(self) -> None:
        prompts = self.text("SETUP-PROMPTS.md")
        self.assertNotIn("commits changes", prompts)
        self.assertIn("Codex", prompts)
        self.assertIn(".agents/skills/", prompts)
        self.assertNotIn("projects/[project-name]/skills/", prompts)
        for section in prompts.split("## Prompt ")[1:]:
            self.assertRegex(section, r"(?i)do not (?:write|create|edit)")
            self.assertRegex(section, r"(?i)(?:explicitly approve|ask me to approve)")
        prompt_two = prompts.split("## Prompt 2:", 1)[1].split("## Prompt 3:", 1)[0]
        self.assertIn("Separately explain that renaming removes the old path", prompt_two)

    def test_migration_guide_covers_supported_source_paths(self) -> None:
        guide = self.text("docs/migration-guide.md")
        for heading in ("Claude Projects", "Gemini CLI", "Codex", "Other AI systems"):
            self.assertIn(heading, guide)
        self.assertIn("Do not bulk-commit", guide)
        self.assertIn("Never delete the source", guide)
        self.assertIn("metadata-first", guide)

    def test_native_gemini_import_is_handed_off_as_a_slash_command(self) -> None:
        for path in ("docs/gemini-migration.md", ".agents/skills/migrate-gemini/SKILL.md"):
            text = self.text(path)
            self.assertIn("/import gemini --dry-run", text)
            self.assertNotIn("claude import gemini", text)
        self.assertIn("cannot silently invoke another slash command", self.text("docs/migration-guide.md"))

    def test_current_gemini_and_codex_import_boundaries_are_explicit(self) -> None:
        for path in ("README.md", "docs/getting-started.md", "docs/migration-guide.md", "docs/gemini-migration.md"):
            text = self.text(path)
            self.assertIn("Antigravity", text, path)
        migration = self.text("docs/migration-guide.md")
        self.assertIn("at most 50 chats from the last 30 days", migration)
        self.assertIn("unavailable inside a running task", migration)
        self.assertNotIn("not a conversation or memory importer", migration)

    def test_portable_skill_docs_use_native_discovery_paths(self) -> None:
        for path in ("docs/first-skill.md", "docs/agent-template.md", "projects/README.md"):
            self.assertIn(".agents/skills/", self.text(path))
        projects = self.text("projects/README.md")
        self.assertIn("do not live under `projects/<project>/skills/`", projects)
        self.assertIn("ordinary context", projects)

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

    def test_dream_commands_delegate_path_safety_to_executable_validator(self) -> None:
        dream = self.text(".claude/commands/dream.md")
        apply = self.text(".claude/commands/dream-apply.md")
        helper = ROOT / "scripts/dream/validate-memory.py"
        self.assertTrue(helper.is_file())
        self.assertIn("validate-memory.py resolve", dream)
        self.assertIn('validate-memory.py artifact "$TS" --for-create', dream)
        self.assertIn('validate-memory.py artifact "$TS"', dream)
        self.assertIn('validate-memory.py artifact "${ARGUMENTS:-latest}"', apply)
        for obsolete in (
            "require the marker's only line to equal `git rev-parse --show-toplevel`",
            "treat `$ARGUMENTS` as the ISO timestamp",
        ):
            self.assertNotIn(obsolete, dream + apply)

    def test_context_optimization_avoids_fixed_pdf_arithmetic(self) -> None:
        guide = self.text("docs/optimizing-context.md")
        self.assertNotIn("3–5x", guide)
        self.assertNotIn("4,000 tokens", guide)
        self.assertIn("no reliable fixed conversion ratio", guide)
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
        self.assertIn("does not remove sensitive data from git history", setup)
        self.assertIn("Continue after reviewing this storage and audience boundary?", setup)
        self.assertIn("Have you verified its visibility and intended audience?", setup)
        self.assertIn(
            'prompt_yn "  Have you verified its visibility and intended audience?" "n"',
            setup,
        )

    def test_copied_adapter_template_is_narrow_and_user_invoked(self) -> None:
        template = self.text("docs/agent-template.md")
        self.assertIn('allowed-tools: "Read, Glob"', template)
        self.assertIn("disable-model-invocation: true", template)
        self.assertNotIn("Read, Bash, Write, Edit, Glob", template)

    def test_command_index_covers_shipped_commands_and_portable_skills(self) -> None:
        index = self.text("docs/commands-and-skills.md")
        shipped_commands = {path.stem for path in (ROOT / ".claude/commands").glob("*.md")}
        indexed_commands = set(re.findall(r"`/([a-z0-9]+(?:-[a-z0-9]+)*)`", index))
        self.assertEqual(shipped_commands, indexed_commands)
        for command in shipped_commands:
            rows = [line for line in index.splitlines() if line.startswith("|") and f"`/{command}`" in line]
            self.assertEqual(1, len(rows), f"/{command} must have exactly one indexed table row")
            cells = [cell.strip() for cell in rows[0].strip("|").split("|")]
            self.assertTrue(all(cells), f"/{command} index row has an empty host/job/effect cell")

        shipped_skills = {path.parent.name for path in (ROOT / ".agents/skills").glob("*/SKILL.md")}
        indexed_skills = set(re.findall(r"`\$([a-z0-9]+(?:-[a-z0-9]+)*)`", index))
        self.assertEqual(shipped_skills, indexed_skills)

        command_table = self.text("CLAUDE.md").split("## Slash Commands", 1)[1].split("Add more commands", 1)[0]
        claude_commands = set(re.findall(r"^\| `/([a-z0-9]+(?:-[a-z0-9]+)*)`", command_table, re.MULTILINE))
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
            "recover",
            "setup",
            "today",
            "update",
            "end",
        ):
            result = subprocess.run(
                [
                    "python3",
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


if __name__ == "__main__":
    unittest.main()
