<div align="center">

# claude-context-os

A Claude-first, Codex-compatible workspace harness for durable agent context — version-controlled files, reviewable memory, reusable workflows, and a start → work → end loop.

[![GitHub stars](https://img.shields.io/github/stars/conorbronsdon/claude-context-os?style=social)](https://github.com/conorbronsdon/claude-context-os/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Built for Claude Code](https://img.shields.io/badge/built%20for-Claude%20Code-d97757?style=flat-square)](https://docs.anthropic.com/en/docs/claude-code)
[![Codex lifecycle adapter](https://img.shields.io/badge/Codex-lifecycle%20adapter-111827?style=flat-square)](docs/codex-onboarding.md)
[![Validate](https://github.com/conorbronsdon/claude-context-os/actions/workflows/validate.yml/badge.svg)](https://github.com/conorbronsdon/claude-context-os/actions/workflows/validate.yml)
[![X](https://img.shields.io/badge/X-@ConorBronsdon-black?style=flat-square&logo=x)](https://x.com/ConorBronsdon)

</div>

---

Most people paste context into an AI product and forget about it. It goes stale, gets duplicated across tools, and has no useful change history.

This repository makes context an inspectable workspace. Claude Code and Codex use checked-in adapters to read the same canonical files; Claude.ai projects can use selected files as uploaded knowledge. Provider-neutral workflows live in `.agents/skills/`, while host-only commands, hooks, permissions, and memory stay labeled.

It is a workspace harness, not an agent runtime: it does not provide a model or agent loop. Your chosen host supplies execution. The repository supplies durable state, routing, workflows, validation, and confirmation boundaries.

> **Name note:** the established repository name stays to preserve links and history. The shared lifecycle is provider-neutral, while support is stated per host instead of implying that every feature works everywhere.

## What it helps you do

| Goal | Path |
|---|---|
| Bring forward useful context from another AI system | Use the [migration guide](docs/migration-guide.md); import one reviewed source at a time |
| Add a tool without guessing at its trust boundary | Use the [integration chooser](docs/integrations-guide.md) and generated safety catalog |
| Work from the same state in Claude Code and Codex | Use the shared lifecycle and [Codex onboarding](docs/codex-onboarding.md) |
| Keep context and memory useful over time | Follow the [maintenance guide](docs/maintenance.md) and current [command/skill index](docs/commands-and-skills.md) |

Start with the core filesystem loop. Migration, integrations, and Claude-specific auto-memory are optional layers.

## Before you add real context

This repository can hold identity, goals, business plans, session logs, and links to private systems. Keep it local-only or use a private remote by default. Make a public repository only after deliberately sanitizing every tracked file. Never fork or push a personalized workspace publicly by accident.

Review the exact diff before each commit and the destination before each push. A later deletion does not erase a secret or personal detail from git history; history cleanup is a separate operation. The setup script never pushes.

## Host scope

| Host | What is supported here | What is not implied |
|---|---|---|
| Claude Code | Full lifecycle plus checked-in Claude commands, hooks, and optional auto-memory curation | External integrations are not enabled by default |
| Codex | Structurally validated setup/start/update/end adapters through `AGENTS.md` and `.agents/skills/` | CI does not run an installed-host end-to-end session; Claude hooks, commands, permissions, and auto-memory do not carry over |
| Claude.ai Projects | Manually uploaded, selected knowledge files | No live sync, repository writes, slash-command activation, or lifecycle parity |
| Gemini CLI / Antigravity CLI | Migration/discovery from Gemini artifacts; portable skills for continuing enterprise/API-key Gemini CLI | Consumer Gemini CLI moved to Antigravity CLI in June 2026; Antigravity lifecycle, discovery, and permission parity are not validated here |

---

## See it work

![A /start session in Claude Code: the state files load and a session briefing comes back — sample data from the included example musician project](docs/assets/start-demo.gif)

`/setup` in Claude Code—or `$context-setup` in Codex—interviews you and fills in your files. After that, `/start` or `$context-start` reads your state, priorities, and projects and hands you a session plan instead of a blank prompt. The demo below shows the Claude Code adapter against the included example musician project:

> **Session briefing — Tuesday**
>
> **Top 3 this week** *(from `state/weekly-priorities.md`)*
> 1. Pitch "Slow Light" to 10 playlist curators — release window closes Friday
> 2. Draft the EP press one-pager
> 3. Book one more show for the August run
>
> **Picking up from last session:** you drafted 4 curator emails and were waiting on the updated cover art before sending — it landed in `inbox/` yesterday.
>
> **Suggested first move:** send the 4 drafted pitches, then write the next 6.

Every line came from plain markdown in the repo—not a chat you rebuild from memory each morning. Run `/end` in Claude Code or `$context-end` in Codex and the reviewed handoff goes to `sessions/` and `state/`.

<sub>The GIF is scripted, not screen-captured — [`docs/start-demo.tape`](docs/start-demo.tape) regenerates it, and [`docs/demo/start-session.sh`](docs/demo/start-session.sh) holds the transcript it plays back. Neither reads state nor calls a model.</sub>

---

## Quick start

Read the full [getting-started guide](docs/getting-started.md) before the repository holds personal or business-sensitive context.

```bash
git clone https://github.com/conorbronsdon/claude-context-os.git my-context
cd my-context
bash scripts/setup.sh
```

The setup script walks through local template choices, detects an installed host, and offers to launch it. It does not import histories, install integrations, or authenticate services. Choose a host explicitly when both are installed:

```bash
bash scripts/setup.sh --agent claude
# or
bash scripts/setup.sh --agent codex
```

If you don't have Claude Code yet, use the [official installation guide](https://code.claude.com/docs/en/installation). The native installer is recommended; npm remains an advanced alternative that requires Node.js.

Once you're in Claude Code, run:

```
/setup
```

Claude interviews you, shows the proposed context changes, and builds the approved identity, project, and weekly-state files.

In Codex, invoke `$context-setup` instead. The same portable workflow writes the same repository state. See [`docs/codex-onboarding.md`](docs/codex-onboarding.md) for the complete lifecycle and host-specific limits.

**Using Claude.ai instead?** Open [`SETUP-PROMPTS.md`](SETUP-PROMPTS.md). The browser workflow can draft content, but you review and copy changes back to the repository manually.

Already have useful context elsewhere? Do not bulk-copy chat history. Follow the [migration guide](docs/migration-guide.md) before running onboarding so you can decide what is durable, current, and safe to track.

---

## Core loop

Run your first Claude Code session:

```bash
cd /path/to/my-context
claude
/start
```

For Codex, launch `codex` in the repository and use `$context-start` → work → `$context-end`. Both hosts use the same `state/` and `sessions/` files.

**Start small.** Don't port your whole working life on day one. Run the core loop for a week, add one project, build one skill when you hit a task you repeat. The structure scales when you're ready — it doesn't demand everything up front.

| Claude Code / Codex | When | What it does |
|---|---|---|
| `/setup` / `$context-setup` | First time | Interactive onboarding—builds the shared context files |
| `/start` / `$context-start` | Beginning of session | Loads repository state and gives a briefing; no external data is pre-approved |
| `/update` / `$context-update` | Mid-session | Saves a quick checkpoint without closing |
| `/end` / `$context-end` | End of session | Records a reviewed handoff, updates shared state and decisions, and checks repository safety |
| `/today` / — | Start of day | Claude-only heartbeat with staleness, deadlines, priorities, and an audit-log write |
| `/capture` / — | When inbox has items | Triages raw notes from `inbox/` into the right files |
| `/find-context` / — | Any time | Finds relevant context files by topic keyword |
| `/reconcile` / — | After parallel work | Detects drift between sessions and source-of-truth violations |
| `/recover` / — | After a crash | Scans orphaned worktrees and stale branches and offers safe cleanup |
| `/content-shipped` / — | After publishing | Logs a published piece to `content/log.md` |
| `/clean-ai-writing` / — | Before sharing | Applies the included writing skill |
| `/dream` / — | Periodically | Runs a Claude auto-memory curator pass |
| `/dream-apply` / — | After `/dream` | Reviews and applies Claude auto-memory proposals |
| `/skill-creator` / — | Adding Claude skills | Generates a Claude-native skill and adapter for review |
| `/migrate-gemini` / `$migrate-gemini` | Porting Gemini setup | Inventories and migrates selected workflows with review and parity checks |
| `/mine-gemini-workflows` / `$mine-gemini-workflows` | Recovering workflows | Ranks repeated validated workflows without exporting private reasoning |

---

## What's in the repo

```
AGENTS.md                          # Codex adapter — lifecycle, routing, safety, validation
CLAUDE.md                         # Root context — loaded on every session
ROUTING.md                        # Context routing for tasks without a slash command
TODO.md                           # Task backlog
SETUP-PROMPTS.md                  # Setup prompts for claude.ai users
identity/                         # Your bio, background, goals
projects/                         # Project context (with a worked example)
writing/skills/                   # Writing skills (avoid-ai-writing included)
state/                            # Session state, priorities, decisions, blockers
sessions/                         # Per-day session logs (created by /end)
inbox/                            # Drop zone for raw notes (triaged by /capture)
content/log.md                    # Published content log
.agents/skills/                   # Portable workflows shared across supported agents
.claude/commands/                 # Claude Code slash commands and portable-skill adapters
.claude/skills/                   # Native Claude Code skills (e.g., skill-creator)
.claude/settings.json             # Checked-in hook activation
scripts/                          # Setup, validation, repo map generation
scripts/dream/                    # Curator prompts + how-to for the /dream substrate
docs/                             # Architecture and onboarding guides, including Codex
references/                       # Generated integration safety details and source notes
integrations/                     # Machine-checked catalog of opt-in add-ons and risk boundaries
.claude/hooks/                    # Session start + SSOT guard + parallel-session guards
.github/                          # CI validation + PR template

# Auto-memory lives outside the repo (Claude-only, often confidential):
<configured-memory-directory>/
  MEMORY.md                       # Index loaded into every conversation
  <topic>.md                      # Detail files loaded on demand
  .dreams/<ISO>/                  # Curator proposal artifacts
```

---

## Portable skills, explicit adapters

A skill is a markdown file that tells an agent how to do a recurring task. Provider-neutral workflow cores belong in `.agents/skills/`; Claude Code slash commands can be thin adapters to them, and Codex discovers the repository skills directly.

The session loop is the first complete portable example: Claude Code maps `/setup`, `/start`, `/update`, and `/end` to `$context-setup`, `$context-start`, `$context-update`, and `$context-end`. Host-only features remain in `.claude/` and are not presented as portable.

The `avoid-ai-writing` skill remains a Claude-oriented working example. In Claude Code, run `/clean-ai-writing`; in claude.ai, upload `writing/skills/avoid-ai-writing/SKILL.md` as project knowledge and ask Claude to apply it.

To build your own:

1. For a portable workflow, create `.agents/skills/<skill-name>/SKILL.md`; add `agents/openai.yaml` when it should appear cleanly in Codex's skill UI.
2. Add a `.claude/commands/` adapter only when Claude Code needs a slash command or host-specific tools.
3. Run `scripts/validate-all.sh` and test each host-specific path you claim to support.

New here? **[docs/first-skill.md](docs/first-skill.md)** walks you through building your first skill by hand in five minutes — copy one, change three things, run it. See `projects/README.md` for conventions and the example musician project for the full pattern.

---

## Auto-memory

Claude Code enables auto-memory by default and may write it automatically during ordinary sessions. This is a Claude-only host extension, not the portable memory layer or a behavior controlled by this repository's `/end` approval gate. Use `/memory` to inspect it or `autoMemoryEnabled: false` to opt out. The optional `/dream` curation commands have their own explicit local-memory contract and per-item apply review described in [`docs/auto-memory.md`](docs/auto-memory.md). Shared continuity lives in `state/` and `sessions/`.

- **user** — role, expertise, preferences
- **feedback** — guidance about *how* to work, both corrections and validated approaches
- **environment** — non-obvious toolchain or platform behavior not already documented in the repository
- **project** — in-flight work, decisions, the *why* behind them
- **reference** — pointers to external systems (trackers, dashboards, channels)

`MEMORY.md` is an index. Detail files load on demand. Cap the index at ~100 lines.

`docs/memory-template.md` is the seed file. Copy its fenced template only after you have inspected or configured the exact Claude memory directory.

### /dream — on-demand curator

Memory accumulates faster than humans review it. `/dream` runs only when a user invokes it (unless they separately configure a scheduler). The shipped curators are **rot**, **merge**, **split**, and **lint**. A pass writes and commits proposal artifacts in the local memory repository; it does not change live memories. `/dream-apply` separately reviews every proposed live-memory change. Pattern, standalone contradiction, and untapped-work curators remain roadmap items.

See [`docs/dream-architecture.md`](docs/dream-architecture.md) for the full design (curator catalog, proposal schema, scope guards).

---

## Running multiple Claude sessions

Running more than one agent session against the same checkout can corrupt your tree—silent branch switches, one session's staging landing in another session's commit, or files committed to the wrong branch. Use one git worktree per concurrent session. The checked-in enforcement hooks described below are Claude Code adapters; Codex users should still use separate worktrees, but this repository does not claim equivalent hook enforcement there.

The repo ships two hooks that enforce this pattern:

- **`worktree-guard.sh`** (`PreToolUse`) — blocks `Edit`/`Write` to a guarded repo's primary checkout when ≥2 Claude sessions are running. Worktrees are still free. Emergency override: `touch .allow-shared-edit` at the repo root.
- **`branch-hygiene.sh`** (`SessionStart`) — surfaces non-default HEAD on guarded repos so a silent branch-switch is noticed before any edits land.

Both hooks no-op until you list a repo basename in `.claude/hooks/guarded-repos.txt`. See `.claude/hooks/README.md` for setup.

---

## Optional integrations

Start with the task-oriented [integration chooser](docs/integrations-guide.md), then read the generated [optional integrations catalog](references/integrations.md). The catalog links compatible add-ons without installing, activating, authenticating, or expanding permissions for any of them. Its source of truth is [`integrations/catalog.json`](integrations/catalog.json), enforced by `scripts/integrations.py`; CI rejects missing typed safety gates, contradictory declared capabilities, unsafe source metadata, empty evidence, and documentation drift. This is structural and semantic validation of the catalog entry—not proof that an upstream source remains correct. Follow each entry's dated evidence links before enabling it. `listed` and `experimental` entries are leads, not endorsements.

Current catalog entries include portable skills and workspace add-ons plus reviewed paths for [Tolaria MCP](https://github.com/refactoringhq/tolaria), [Obsidian CLI](https://obsidian.md/help/cli), [Beads for Gemini CLI](https://beads.gascity.com/integrations/gemini), and [Granola MCP](https://docs.granola.ai/help-center/sharing/integrations/mcp). Each entry distinguishes sensitive reads, local writes, remote writes, OAuth, overwrite, deletion, arbitrary execution, publish, and destructive boundaries where they apply.

**Google Workspace status:** the previous tracked configuration targeted a removed `gws mcp` subcommand and has been removed. No Google Workspace integration is currently shipped or pre-approved. See [`references/gws-mcp-setup.md`](references/gws-mcp-setup.md) before following older setup instructions.

**Claude.ai knowledge copy** — upload a deliberately selected subset of files as project knowledge and manually replace them when the source changes. This is not live sync or command/runtime parity. See `docs/claude-projects-sync.md`.

---

## Bring context forward

The [migration guide](docs/migration-guide.md) covers Claude Projects, Gemini CLI, Codex import, and manual extraction from other AI systems. The goal is durable context—not a bulk archive of conversations.

For Gemini CLI artifacts, run `/migrate-gemini` or `$migrate-gemini` for a reviewed configuration migration. Use `/mine-gemini-workflows` or `$mine-gemini-workflows` only to discover repeated workflows in an explicitly selected session directory. Consumer Gemini CLI requests moved to Antigravity CLI on June 18, 2026; Standard/Enterprise and paid API-key Gemini CLI use continues, while this repository does not yet claim Antigravity compatibility or 1:1 parity. See Google's [transition announcement](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/). Both repository flows remain privacy-first: dry run before mutation, metadata before message content, no private reasoning export, and parity checks before a workflow is accepted.

See [`docs/gemini-migration.md`](docs/gemini-migration.md). [`0xSero/ai-data-extraction`](https://github.com/0xSero/ai-data-extraction) is credited as useful extraction prior art in [`references/ai-data-extraction.md`](references/ai-data-extraction.md); it is not installed as a dependency.

---

## Validation

```bash
bash scripts/validate-all.sh
```

The aggregate validator checks skill/command frontmatter, Codex portability and adapter mappings, CLAUDE.md size, a limited set of common committed-secret signatures and filenames, stale files, local links, shell syntax, hook behavior, JSON, and Python tests. It is not DLP and cannot prove a repository is safe to publish. The harness needs Bash and Python 3. CI runs the same command on every push and PR.

---

## Key conventions

- **Single source of truth:** Each fact lives in one file. Others reference, never duplicate.
- **CLAUDE.md stays small:** Under 100 lines. Detail goes in skills and ROUTING.md.
- **Staleness dates:** `**Last Updated:**` near the top of context files. Validation flags 90+ days.
- **TODO.md vs. current.md:** TODO is the full backlog; `state/current.md` is the top-of-mind view.

---

## Contributing

This is a template — the most useful contributions are structural: better examples, cleaner conventions, and skills others can adapt. Open an issue if you have a pattern worth adding.

---

## Used by

- [Conor Bronsdon](https://github.com/conorbronsdon) host of [Chain of Thought podcast](https://chainofthought.show/?utm_source=github&utm_medium=referral&utm_campaign=repo-readme&utm_content=claude-context-os)

Using this template? Open a PR adding yourself.

---

## Disclaimer

*This is an independent personal project, not affiliated with, sponsored by, or endorsed by any company. All views expressed are my own.*

## License

MIT — see [LICENSE](LICENSE). Fork it, adapt it, make it yours; no attribution required.
