# Commands and skills

This index separates portable workflow cores from host-specific adapters. A command or skill exists only where listed; a similar name does not imply permission, hook, or runtime parity on another host.

## Shared lifecycle

| Job | Claude Code | Codex | Effects and prerequisites |
|---|---|---|---|
| Initialize context | `/setup` | `$setup` (`$context-setup` compatibility) | Proposes identity, project, state, routing, and approved workflow files; review before writes |
| Start a session | `/start` | `$start` (`$context-start` compatibility) | Repository reads only; no live external data or authentication by default |
| Checkpoint | `/update` | `$update` (`$context-update` compatibility) | Writes a reviewed session checkpoint and minimal current state |
| Close a session | `/end` | `$end` (`$context-end` compatibility) | Writes a reviewed handoff, state, and decisions; Claude may separately propose host-local memory |

The portable workflow cores are `.agents/skills/context-setup`, `context-start`,
`context-update`, and `context-end`. The matching short skill directories are
thin compatibility adapters, and Claude Code files are host-specific adapters.
Both naming forms require explicit user invocation.

## Portable migration

| Job | Claude Code | Codex/compatible skill host | Effects and prerequisites |
|---|---|---|---|
| Map selected Gemini configuration | `/migrate-gemini` | `$migrate-gemini` | Metadata-first inventory in ignored staging; writes only an approved mapping |
| Recover repeated Gemini workflows | `/mine-gemini-workflows` | `$mine-gemini-workflows` | Selected session directory; content and paths require separate opt-ins |

These are the portable skills `.agents/skills/migrate-gemini` and `.agents/skills/mine-gemini-workflows`. They do not expose private reasoning or make a bulk-history import safe by default.

## Claude Code context and maintenance

| Command | Job | Effects and prerequisites |
|---|---|---|
| `/today` | Morning heartbeat from repository state | Writes `state/heartbeat-log.md`; live data is skipped unless separately enabled and requested |
| `/capture` | Triage reviewed inbox notes | Writes only approved destinations, verifies them, and leaves each source for separate user-controlled cleanup |
| `/find-context` | Find relevant repository context | Read-only |
| `/reconcile` | Detect repository and session drift | Read-only report by default; explicit fix mode may edit and commit individually approved repairs |
| `/recover` | Inspect orphaned worktrees/branches and offer cleanup | Cleanup is destructive and remains approval-gated |
| `/content-shipped` | Record a confirmed published item | Writes `content/log.md`; it does not publish the item |
| `/clean-ai-writing` | Apply the included writing workflow | Reads supplied content and returns a proposed revision in chat; no file write grant |

## Claude Code auto-memory

| Command | Job | Effects and prerequisites |
|---|---|---|
| `/dream` | Run one shipped curator: `rot`, `merge`, `split`, or `lint` | Requires the explicit local memory-directory contract; writes and commits proposal artifacts only |
| `/dream-apply` | Review a proposal artifact item by item | Applies accepted live-memory changes and commits locally; refuses a memory remote |

Claude Code's ordinary auto-memory is enabled by default and may write automatically; `/dream` and `/dream-apply` add separate artifact/apply gates but do not govern that host behavior. Auto-memory is not shared with Codex. See [`auto-memory.md`](auto-memory.md).

## Claude Code customization

| Command or skill | Job | Effects and prerequisites |
|---|---|---|
| `.claude/skills/skill-creator` | Scaffold or revise a Claude-native skill and optional adapter | Claude Code only; shows files and safety metadata for review before installation |

To create a provider-neutral workflow, start under `.agents/skills/` and follow [`first-skill.md`](first-skill.md).

## Claude.ai Projects

Claude.ai does not activate these repository slash commands or skill metadata. Selected files can be uploaded as guidance only. See [`claude-projects-sync.md`](claude-projects-sync.md).
