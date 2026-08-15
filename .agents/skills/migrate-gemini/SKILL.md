---
name: migrate-gemini
description: Migrate selected Gemini CLI instructions, commands, skills, hooks, and MCP configuration into this workspace with a dry run, review gates, and parity checks.
---

# Migrate Gemini workflows

Move proven Gemini CLI workflows into this workspace without bulk-copying private history or silently changing behavior.

Consumer Gemini CLI requests transitioned to Antigravity CLI in June 2026; continuing enterprise/API-key Gemini CLI remains a distinct path. Treat Gemini files as migration sources. Do not claim that Antigravity shares Gemini skill discovery, hook, permission, or lifecycle behavior unless the installed target has been separately validated.

## Safety rules

- Start with inventory and a dry run. Do not mutate source Gemini files.
- Never print or persist token values, environment values, credentials, or full chat transcripts.
- Work on a branch or worktree and show the proposed file map before writing.
- Require explicit user approval before running a non-dry-run import or replacing an existing file.
- Treat hooks and MCP configuration as executable/security-sensitive configuration. Rebuild and review them; do not blindly copy them.

## Procedure

### 1. Define the scope

Ask for the Gemini project or configuration directory and the 1–3 workflows that matter most. Prefer a narrow migration over an account-wide import.

Inventory only the presence, path, and type of:

- `GEMINI.md` files and imports
- `.gemini/commands/`
- `.gemini/skills/` and `.agents/skills/`
- hook event names and command names (not secret environment values)
- MCP server names and transport types (not credentials)
- extensions and headless scripts that need manual review

Write the inventory to `.context-os/migrations/<timestamp>/inventory.json`. This directory is gitignored.

### 2. Offer Claude Code's native dry run when available

If the user is in Claude Code, offer an explicit handoff to the native interactive command:

```text
/import gemini --dry-run
```

Do not try to invoke another slash command from this skill. If the user chooses the native path, stop and let them invoke it directly, then review its proposed file map and warnings. If it is unavailable for the installed version/provider, continue with the manual mapping below; do not improvise a destructive import.

### 3. Build a reviewed mapping

| Gemini source | Preferred destination | Review focus |
|---|---|---|
| Root/project `GEMINI.md` | `CLAUDE.md` plus `ROUTING.md` detail | Keep `CLAUDE.md` under 100 lines; preserve imports as references |
| Reusable skill | `.agents/skills/<name>/SKILL.md` | Portable core; narrow trigger description |
| Gemini command | `.claude/commands/<name>.md` or a thin adapter to a portable skill | Tool names and argument syntax |
| Gemini hook | `.claude/settings.json` plus `.claude/hooks/` | Event schema, stdin JSON, exit codes, quoting |
| MCP server | Reviewed host-local configuration; no direct copy | Current tool surface, secrets, transport, least privilege, approval posture |
| Extension/headless automation | Manual migration item | Permissions, unattended execution, human gates |

Do not copy provider-specific tool names into a portable skill. Put provider adapters in the provider-specific command or hook layer.

### 4. Define parity before changing files

For each selected workflow, copy `docs/templates/workflow-parity.json` and fill in:

- representative input
- one known-good historical outcome, summarized without private transcript data
- required output sections and files
- required tools or capabilities
- confirmation boundaries and forbidden behavior
- acceptance checks

Compare invariants and outcomes, not exact wording.

### 5. Apply in small batches

Present the mapping and parity checks. After user approval, migrate one workflow at a time, run its checks, and show the diff. Never overwrite an existing `SKILL.md` or command without a collision decision from the user.

### 6. Report

Return:

- migrated, deferred, and rejected items
- source → destination map
- parity result for each workflow
- manual follow-ups for unsupported tools, hooks, or extensions
- privacy note describing what was inspected and what was deliberately excluded
