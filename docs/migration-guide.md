# Move existing context into Context OS

Most useful context is scattered across project instructions, memory summaries, uploaded files, chats, and local agent configuration. Move the durable parts, not the entire history.

This workflow works with ChatGPT, Claude, Gemini, and other assistants. Gemini CLI has an additional reviewed automation path for configuration and repeated workflows.

## The safe default

1. Pick one source, project, or small set of conversations.
2. Inventory it before copying anything.
3. Extract facts, decisions, preferences, and reusable workflows.
4. Mark uncertain or time-sensitive claims for verification.
5. Map each approved item to one canonical file.
6. Review the diff and run validation before committing.

Keep raw exports outside the repository. They can contain complete conversation history, uploaded documents, personal data, local paths, and credentials. A private repository reduces exposure but does not make indiscriminate collection safe.

## Choose an input

Use the smallest input that captures what you need.

| Input | Best use | Main caution |
|---|---|---|
| A current project or chat | Recover its instructions, decisions, and active work | It can only report context available in that scope |
| An assistant memory export | Seed stable preferences and background | Memory can be stale, compressed, or inferred |
| Selected uploaded files | Preserve source documents and project context | Convert only the useful sections to Markdown |
| A full account export | Find specific conversations you cannot access another way | Never commit the archive or ingest it wholesale |
| Local agent configuration | Recover proven instructions, skills, hooks, and tools | Provider-specific behavior needs a reviewed adapter |

If the source can answer questions, ask it to create a migration packet. If it cannot, use the same headings while reviewing the selected material yourself.

## Create a migration packet

Run this prompt inside the source project or a conversation that has the context you want. It does not grant access to other chats or account-wide history.

```text
I am moving durable context into a Git-backed workspace that multiple coding agents can read.

Use only information available in this project or conversation. Do not claim account-wide coverage.

Create a migration packet with these sections:
1. Stable identity and background facts
2. Working preferences and feedback that should affect future collaboration
3. Active projects, goals, collaborators, and explicit non-goals
4. Decisions already made, including rationale and rejected alternatives when known
5. Repeated workflows that may be worth turning into reusable instructions
6. Current priorities, blockers, and dated commitments
7. Source documents or links worth preserving

For every item, add:
- status: KEEP, VERIFY, ARCHIVE, or SKIP
- source: the conversation, instruction, memory entry, or file it came from
- confidence: high, medium, or low
- sensitivity: public, private, or restricted

Do not include passwords, tokens, recovery codes, private reasoning, full transcripts, or a raw copy of every uploaded file. Preserve exact wording only for instructions, commitments, and claims where wording matters. Put contradictions and stale-looking facts in a separate review section.
```

Read the packet before bringing it into this repository. Remove anything you do not want an agent to load later.

## Source-specific paths

### ChatGPT

For a small migration, create a packet in the relevant chat or project. If the context is spread across old conversations, [request a ChatGPT data export](https://help.openai.com/en/articles/7260999-exporting-your-chatgpt-history-and-data), keep the archive outside the repository, and use it only to locate a short list of relevant conversations.

Do not treat an uploaded export as a full account migration. OpenAI's own [conversation transfer guidance](https://help.openai.com/en/articles/9106926-transfer-exported-conversations-between-chatgpt-accounts) makes the same distinction: an uploaded export can be reference material, but it does not merge histories or recreate the original account state.

### Claude and claude.ai projects

For a project, inventory its custom instructions and uploaded knowledge, then create a packet from the material you still use. Individual users can also [export Claude data](https://support.anthropic.com/en/articles/9450526-how-can-i-export-my-claude-ai-data) or use Claude's [memory import and export flow](https://support.anthropic.com/en/articles/12123587-importing-and-exporting-your-memory-from-claude). Keep either export outside the repository and verify its claims before filing them as current context.

After migration, selected repository files can be uploaded back to claude.ai project knowledge. That is a manual consumer copy, not automatic synchronization. See [claude-projects-sync.md](claude-projects-sync.md).

### Gemini Apps

Create a packet in the relevant conversation when possible. Google's [Gemini Apps export guide](https://support.google.com/gemini/answer/16920332?hl=en) documents the current Takeout path. Export contents and availability can change, so treat the archive as discovery material and keep it outside tracked files.

### Gemini CLI

Use `$migrate-gemini` to inventory selected instructions, commands, skills, hooks, and MCP configuration. Use `$mine-gemini-workflows` only when selected session evidence is needed to reconstruct a repeated workflow. Both paths start metadata-first, exclude private reasoning, and require review before writing.

Consumer Gemini CLI requests transitioned to Antigravity CLI in June 2026, while continuing enterprise/API-key Gemini CLI remains a separate path. Treat Gemini files as migration sources; do not infer Antigravity discovery, hook, permission, or lifecycle parity. See [gemini-migration.md](gemini-migration.md) for the current host boundary, parity checks, and privacy rules.

### Codex `/import`

Codex CLI `/import` supports Claude Code and Cursor sources, including selected setup, project files, and at most 50 recent chats from the last 30 days. It runs before a task in a local interactive CLI and is unavailable inside a running task, a remote session, or the local app-server daemon. Treat its result as bounded staging material, not an account-wide importer or canonical context. Review each proposed file, separate durable facts from host configuration, map approved context through the table below, and avoid importing material that this repository already provides natively.

See the official [Codex import guide](https://developers.openai.com/codex/import) and the repository's [Codex onboarding boundary](codex-onboarding.md#optional-import).

### Another assistant or agent

Use the migration packet prompt if the system can see the relevant context. Otherwise export or copy a narrow set of source material, store it outside the repository, and build the packet manually. Document any provider-specific tool or permission behavior as an adapter requirement rather than placing it in a portable workflow.

## Map approved context into the repository

| Content | Canonical destination |
|---|---|
| Stable identity and personal context | `identity/who-i-am.md` |
| Professional background and verifiable credentials | `identity/professional-background.md` |
| Long-lived project facts | `projects/<project>/context.md` |
| Project goals, choices, and non-goals | `projects/<project>/strategy.md` |
| Current work and open threads | `state/current.md` |
| This week's outcomes and non-goals | `state/weekly-priorities.md` |
| Active dependencies | `state/blockers.md` |
| Durable decisions | `state/decisions.md` |
| Repeated provider-neutral workflow | `.agents/skills/<workflow>/SKILL.md` |
| Claude Code-only command, hook, or memory behavior | `.claude/` |
| Migration scratch data and inventories | `.context-os/migrations/` (gitignored) |

Do not create a second copy because two agents need the same fact. Put it in one canonical file and add a route in `ROUTING.md`.

## Merge instead of overwrite

When a destination already contains real content:

1. compare each incoming item with the current file;
2. keep current facts that the packet does not address;
3. flag contradictions instead of selecting the newest-looking wording automatically;
4. preserve source wording for preferences and instructions where it matters; and
5. show the proposed replacement or merged section before writing.

Use `VERIFY` until a person confirms a credential, deadline, relationship, financial fact, or other consequential claim. An assistant's confidence label is not evidence.

## Turn workflows into portable skills

Move a workflow only when it is repeated, useful, and validated by an outcome you trust. Keep the reusable procedure in `.agents/skills/`. Put host-specific tools, command syntax, hooks, and permission settings in a thin adapter.

Define parity before migrating automation:

- representative input;
- required output or artifact;
- tool or capability needs;
- approval boundaries;
- forbidden behavior; and
- a known-good outcome or acceptance check.

Use [`templates/workflow-parity.json`](templates/workflow-parity.json) as the review contract.

## Review and validate

Before committing:

- [ ] Raw exports and transcripts remain outside tracked files
- [ ] No credentials, tokens, private keys, or recovery codes were copied
- [ ] Every kept fact has one canonical destination
- [ ] Stale, contradictory, and high-impact claims were verified or marked clearly
- [ ] Provider-specific behavior stays out of portable skills
- [ ] `ROUTING.md` points to each new project or skill
- [ ] Populated files were merged, not silently replaced
- [ ] The final diff contains only intended context
- [ ] `bash scripts/validate-all.sh` passes

When the packet is approved, run `/setup` in Claude Code or `$setup` in Codex and provide the packet as the selected import material. The setup workflow will inventory the current workspace, propose a file map, and wait before overwriting populated files.
