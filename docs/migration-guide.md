# Bring context forward safely

Migration means extracting a small set of durable facts, decisions, preferences, and proven workflows from a named source. It does not mean copying an account, bulk chat archive, or provider-specific tool configuration into this repository.

Work on one source, one project, and one date range at a time. Keep inventories and excerpts under the ignored `.context-os/migrations/` staging directory until the destination diff is approved.

## Supported source paths

| Source | Supported path | Important boundary |
|---|---|---|
| Claude Projects | Manual metadata-first inventory and selected knowledge-file review | Project uploads are not live repository sync; do not request all chat content |
| Gemini CLI / Antigravity CLI | `/migrate-gemini` or `$migrate-gemini`; optional explicit Claude Code `/import gemini --dry-run` handoff | Consumer Gemini CLI transitioned to Antigravity; only continuing enterprise/API-key Gemini CLI skill discovery is in scope, and host permissions still require review |
| Codex | Optional Codex `/import` from Claude Code or Cursor | Selects supported setup, project files, and bounded recent chats; it is not an account-wide or arbitrary-history importer |
| Other AI systems | Manual, user-selected extraction into ignored staging | No universal importer is claimed; exports may contain credentials and sensitive history |

The included [`0xSero/ai-data-extraction` reference](../references/ai-data-extraction.md) is useful prior art for extraction design. It is not installed, executed, or treated as a dependency.

## The safe flow

### 1. Scope the source

Record:

- the exact provider or local tool;
- account, workspace, or project name;
- an explicit date range;
- the one to three outcomes worth preserving; and
- whether the material belongs in a local-only or private repository.

Do not start with an account-wide export. Do not bulk-commit any migration output.

### 2. Inventory metadata first

List only names, types, dates, sizes, and locations. Do not emit message bodies, hidden reasoning, environment values, tool arguments, or credentials during inventory.

Write the local inventory to:

```text
.context-os/migrations/<source>-<timestamp>/inventory.json
```

Ignored files remain sensitive; gitignore is not encryption or access control.

### 3. Select named items

Choose exact conversations, instructions, skills, or artifacts from the inventory. Retrieve content only for those named items and only after the user approves the selection.

Classify each item before mapping it:

- sensitivity and intended audience;
- ownership or license restrictions;
- staleness and last verified date;
- whether it conflicts with current repository facts; and
- whether it is a durable fact, decision, preference, workflow, or merely history.

Reject credentials, private reasoning, speculative model conclusions, redundant transcripts, and provider-specific noise.

### 4. Normalize and map

Deduplicate repeated facts and surface conflicts instead of silently choosing a winner. Propose a destination map such as:

| Durable content | Preferred destination |
|---|---|
| Identity or professional fact | `identity/` |
| Project background or strategy | `projects/<project>/` |
| Current priority, blocker, or decision | `state/` |
| Reusable provider-neutral workflow | `.agents/skills/<name>/SKILL.md` |
| Host-specific invocation or tool binding | A thin host adapter, reviewed separately |
| Historical evidence only | Keep in ignored staging or the backed-up source; do not track by default |

Never put credential values in a destination. Never copy a provider permission grant or MCP configuration without an independent least-privilege review.

### 5. Preview, scan, and approve

Before applying:

1. show the complete source-to-destination map;
2. show the proposed repository diff;
3. run a secret scan, while stating that automated scans are limited and not proof of safety;
4. call out replacements, conflicts, and deletions explicitly; and
5. wait for approval of the exact files.

Apply one small batch, run `bash scripts/validate-all.sh`, and review the diff again. A migration command must not commit or push automatically.

### 6. Verify before retiring the source

Use the migrated context in a representative task. Verify dates, links, routing, workflow outputs, and permission boundaries. Keep a separate backup of the source until the result is proven complete.

Never delete the source merely because files were written. Source deletion is a separate destructive action and requires explicit approval after verification and backup.

## Claude Projects

Start from project names and uploaded knowledge-file names, not every chat. Ask for content only from files or conversations the user selects. Map uploaded instructions to current repository facts and portable skills; do not assume a browser Project can activate slash commands, tool grants, or repository writes.

For ongoing use, see [Using repo files in Claude.ai Projects](claude-projects-sync.md). It is a manual knowledge-copy workflow with no write-back.

## Gemini CLI

Use `/migrate-gemini` in Claude Code or `$migrate-gemini` in a compatible skill host. The workflow inventories configuration, proposes a mapping, and uses parity cases before writes. It does not bulk-ingest chat history.

On June 18, 2026, consumer Gemini CLI stopped serving free and Google AI Pro/Ultra requests and transitioned to Antigravity CLI. Standard/Enterprise and paid Gemini or Enterprise Agent Platform API-key use remains supported. Google does not promise initial 1:1 parity, and this repository has not validated Antigravity discovery, permissions, or lifecycle behavior. Treat old Gemini directories as migration sources, not proof of current host compatibility. See Google's [transition announcement](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/).

Current Claude Code versions may also expose `/import gemini --dry-run` as an explicit interactive alternative. Invoke it yourself in Claude Code; one custom skill cannot silently invoke another slash command. Review version/provider limitations and every proposed change. See [Gemini migration](gemini-migration.md).

Use `/mine-gemini-workflows` or `$mine-gemini-workflows` only when a repeated workflow must be reconstructed from explicitly selected session recordings. It is metadata-first and keeps raw reasoning excluded.

## Codex

Codex CLI `/import` can inspect Claude Code or Cursor and let the user select supported setup, project files, and recent chats. Its chat window is bounded to at most 50 chats from the last 30 days; it is not arbitrary, account-wide, or universal history ingestion. Run it before starting a task in a local interactive CLI—it is unavailable inside a running task, a remote session, or the local app-server daemon. Review the item list and resulting diff because imported instructions, skills, MCP configuration, and recent work can duplicate or conflict with this repository's `AGENTS.md`, `.agents/skills/`, and state. See the official [Codex import documentation](https://developers.openai.com/codex/import).

## Other AI systems

There is no universal context importer. Ask the source system for a metadata inventory first, then request exact named items. If an export is the only option, keep the raw archive outside the repository or in ignored staging, inspect it for secrets and private content, and extract only approved durable facts.

Unsupported or inaccessible sources should be reported as such. Do not fabricate parity, infer hidden history, or ask a user to paste an entire private archive into a chat.

## Completion report

Every migration should end with:

- source, project, and date range inspected;
- items selected and excluded;
- source-to-destination map;
- files changed and validation result;
- conflicts or uncertainty still requiring a human decision;
- what sensitive content was deliberately excluded; and
- confirmation that the source remains intact and backed up.
