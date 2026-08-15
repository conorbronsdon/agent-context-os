# Migrating proven Gemini CLI workflows

The goal is behavioral parity, not a byte-for-byte copy of Gemini configuration or chat history. Start with the few workflows that are both hardened and worth repeating.

## Fast path

1. Run `/migrate-gemini` to inventory instructions, commands, skills, hooks, and MCP configuration.
2. Use Claude's native `claude import gemini --dry-run` when the installed CLI supports it.
3. Define a parity case for each selected workflow before applying changes.
4. Run `/mine-gemini-workflows` only when session evidence is needed to reconstruct the workflow.
5. Migrate one workflow, validate it, and review the diff before moving to the next.

## Portable core, thin adapters

Reusable provider-neutral instructions belong in `.agents/skills/<name>/SKILL.md`, which Gemini CLI and Codex can discover. Claude-specific slash-command adapters live in `.claude/commands/` and can load the same portable skill. Hooks, tool names, MCP servers, and permission rules stay in provider-specific adapters.

This keeps the workflow logic in one place without pretending each agent runtime has the same execution model.

## What counts as parity

Compare observable invariants:

- required sections and artifacts
- tool/capability use
- approval boundaries
- citations or evidence
- forbidden behavior
- validation results

Exact wording is not a useful parity target. Use `docs/templates/workflow-parity.json` as the review contract.

## Privacy posture

Gemini session recordings can contain source code, local paths, prompts, tool arguments, and credentials. The included miner defaults to metadata-only output, requires an explicitly chosen session directory, folds append-log rewinds and metadata updates, and never emits thought/reasoning fields. Free-form summaries, sanitized paths, and observable content each require explicit session IDs and opt-in flags. Redaction is best-effort, so every opt-in report remains sensitive and needs review before sharing or committing.

Generated inventories belong under `.context-os/migrations/`, which is ignored by git.
