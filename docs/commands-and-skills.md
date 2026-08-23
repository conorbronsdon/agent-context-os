# Commands and skills

Context OS guarantees shared state transitions, not identical host features.
Portable skills gather and review intent; the deterministic kernel owns paths,
dates, append behavior, optimistic hashes, locking, and receipts.

## Shared lifecycle

| Job | Claude Code | Codex | Hermes | Deterministic operation |
|---|---|---|---|---|
| Initialize context | `/setup` | `$setup` | `/setup` | `contextos propose setup` then `apply` |
| Start a session | `/start` | `$start` | `/start` | read-only `contextos start` |
| Checkpoint | `/update` | `$update` | `/update` | `contextos propose update` then `apply` |
| Close a session | `/end` | `$end` | `/end` | `contextos propose end` then `apply` |

The portable cores are `.agents/skills/context-setup`, `context-start`,
`context-update`, and `context-end`. Short skill directories are thin aliases;
Claude files are host adapters. All lifecycle names require explicit invocation.

The mutation protocol is always:

1. the agent drafts reviewed JSON input under ignored `.context-os/inputs/`;
2. `python3 -m contextos propose` emits exact diffs and a proposal digest;
3. the agent presents those diffs and waits;
4. `python3 -m contextos apply` receives that exact digest; and
5. the kernel verifies target hashes, takes an exclusive lock, writes only the
   proposal paths, and records a receipt.

## Runtime boundary

| Capability | Claude Code | Codex | Hermes |
|---|---|---|---|
| Project instructions | `CLAUDE.md` | `AGENTS.md` | `AGENTS.md` |
| Portable skill source | Thin slash adapters | `.agents/skills/` | External directory or copied skills |
| Project hooks | `.claude/settings.json` | `.codex/hooks.json` after trust | Optional shell/plugin adapter |
| Lifecycle enforcement | Kernel | Kernel | Kernel |
| Native memory | Claude auto-memory | Not part of the shared contract | `MEMORY.md` and `USER.md` |

Runtime manifests in `runtimes/` are machine-readable claims. Hooks are defense
in depth: the kernel repeats mutation invariants during every proposal and apply.

## Portable skill index

| Skill | Job | Effects |
|---|---|---|
| `$context-setup` | Canonical setup core | Proposal/apply only |
| `$context-start` | Canonical read-only start core | No writes |
| `$context-update` | Canonical checkpoint core | Proposal/apply only |
| `$context-end` | Canonical close core | Proposal/apply only |
| `$migrate-gemini` | Map selected Gemini configuration | Reviewed mapping only |
| `$mine-gemini-workflows` | Recover repeated Gemini workflows | Narrow selected evidence |

The `$setup`, `$start`, `$update`, and `$end` rows in the shared lifecycle table
are the short portable aliases. The ten tokens above and in that table are the
complete shipped portable skill catalog.

The two migration skills do not expose private reasoning or make bulk-history
import safe. Their Claude adapters appear in the command index below.

## Claude-specific command index

| Command | Job | Effects and prerequisites |
|---|---|---|
| `/today` | Morning heartbeat | Reviewed heartbeat write; live data stays opt-in |
| `/capture` | Triage inbox notes | Approved destinations only; source cleanup remains separate |
| `/find-context` | Locate relevant context | Read-only |
| `/reconcile` | Detect repository drift | Read-only report unless fixes are separately approved |
| `/recover` | Inspect stale worktrees and branches | Read-only until destructive cleanup approval |
| `/content-shipped` | Log confirmed published content | Local content-log write; does not publish |
| `/clean-ai-writing` | Apply the writing workflow | Proposed revision only |
| `/dream` | Curate host-local auto-memory | Proposal artifacts only |
| `/dream-apply` | Apply reviewed memory proposals | Host-local write with per-item review |
| `/migrate-gemini` | Claude adapter for selected migration | Routes to the portable skill |
| `/mine-gemini-workflows` | Claude adapter for workflow recovery | Routes to the portable skill |

Uploading these files to claude.ai does not activate commands, hooks, tool
permissions, or skill metadata. See `docs/claude-projects-sync.md`.

Run `python3 -m contextos doctor` for runtime and state diagnostics, then
`bash scripts/validate-all.sh` after repository changes.
