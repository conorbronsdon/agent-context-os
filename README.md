<div align="center">

# Context OS

A Git-backed context and workflow layer for Claude Code and Codex.

[![GitHub stars](https://img.shields.io/github/stars/conorbronsdon/claude-context-os?style=social)](https://github.com/conorbronsdon/claude-context-os/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-ready-d97757?style=flat-square)](https://docs.anthropic.com/en/docs/claude-code)
[![Codex](https://img.shields.io/badge/Codex-ready-111827?style=flat-square)](docs/codex-onboarding.md)
[![Validate](https://github.com/conorbronsdon/claude-context-os/actions/workflows/validate.yml/badge.svg)](https://github.com/conorbronsdon/claude-context-os/actions/workflows/validate.yml)
[![X](https://img.shields.io/badge/X-@ConorBronsdon-black?style=flat-square&logo=x)](https://x.com/ConorBronsdon)

</div>

Chat history, project instructions, and copied prompts drift apart. Context OS puts the durable parts in plain Markdown: who you are, what you are working on, decisions already made, and the workflows you want an agent to follow.

Claude Code and Codex read the same repository state. Git shows what changed. A reviewed start, checkpoint, and close loop keeps the context current without treating an assistant's private memory as the source of truth.

| What you need | How Context OS handles it |
|---|---|
| Bring useful context forward | A source-neutral [migration workflow](docs/migration-guide.md) turns selected chats, project instructions, memory exports, and documents into reviewable files. |
| Work across coding agents | Provider-neutral state and skills live outside host adapters. Claude Code and Codex share the same lifecycle core. |
| Add the tools that fit | A generated [integration catalog](references/integrations.md) documents install scope, data access, side effects, and confirmation gates. Nothing is enabled automatically. |
| Keep context useful | Session handoffs, staleness checks, decision logs, and reviewable memory proposals make maintenance part of the normal workflow. |

Context OS does not scrape every account, sync product UIs automatically, or install integrations on setup. Imports are selective, browser-project sync is manual, and external capabilities remain opt-in.

## Quick start

Personal and business context often belongs in a private repository. Create an empty private repository first if that applies to you, and never commit credentials or a raw account export.

```bash
git clone https://github.com/conorbronsdon/claude-context-os.git my-context
cd my-context

# Recommended for a private copy:
git remote rename origin upstream
git remote add origin <YOUR_PRIVATE_REPO_URL>

# Pick a host, or omit --agent to auto-detect one:
bash scripts/setup.sh --agent claude
# bash scripts/setup.sh --agent codex
```

Then start your agent from the repository root:

| Starting point | Next action |
|---|---|
| New workspace in Claude Code | Run `/setup` |
| New workspace in Codex | Run `$context-setup` |
| Existing context in another assistant | Follow the [migration guide](docs/migration-guide.md), then use the selected material during setup |
| claude.ai only | Use [SETUP-PROMPTS.md](SETUP-PROMPTS.md) and copy the approved output into the repository |

The setup interview fills the identity, first project, workflows, and weekly state files. It can start from your answers or from a migration packet you reviewed first. See the full [getting started guide](docs/getting-started.md) for prerequisites, privacy choices, and verification.

## See the loop

![A start session in Claude Code: state files load and a session briefing comes back, using sample data from the included example musician project](docs/assets/start-demo.gif)

`/start` in Claude Code and `$context-start` in Codex read your state, priorities, decisions, blockers, and recent handoff. The result is a working briefing grounded in files, not a request to reconstruct everything from chat.

At the end, `/end` or `$context-end` proposes a handoff for review before it updates `sessions/` and `state/`.

<sub>The GIF is scripted with sample data. [`docs/start-demo.tape`](docs/start-demo.tape) regenerates it, and [`docs/demo/start-session.sh`](docs/demo/start-session.sh) contains the transcript. Neither reads your state or calls a model.</sub>

## Daily workflow

Start small. Use the core loop for a week, add one active project, then turn a repeated task into a skill when the repetition is clear.

| Moment | Claude Code | Codex | Shared result |
|---|---|---|---|
| First run or major refresh | `/setup` | `$context-setup` | Identity, projects, workflows, and weekly state |
| Start work | `/start` | `$context-start` | Briefing from current state and recent sessions |
| Save a checkpoint | `/update` | `$context-update` | Short session update with minimal state churn |
| Finish work | `/end` | `$context-end` | Reviewed handoff, state updates, decisions, and git safety report |

Claude Code also ships host-specific commands for capture, daily checks, recovery, context search, and auto-memory curation. The [host boundary](docs/codex-onboarding.md#host-specific-boundaries) names what is portable and what is not.

## Bring existing context with you

Do not import an entire chat archive into active context. Use the [migration guide](docs/migration-guide.md) to:

1. select the assistant, project, or small set of conversations that contains useful context;
2. produce an inventory or compact migration packet;
3. classify each item as keep, verify, skip, or archive;
4. map approved facts, decisions, projects, and workflows into canonical files; and
5. validate the repository before committing.

The guide covers ChatGPT, Claude, Gemini Apps, Gemini CLI, and a generic path for other systems. Gemini CLI also has privacy-first `$migrate-gemini` and `$mine-gemini-workflows` skills for selected configuration and session evidence.

## Host support

| Host | Support level |
|---|---|
| Claude Code | Full experience: shared lifecycle, slash-command adapters, hooks, optional live reads, and Claude-only auto-memory curation |
| Codex | First-class shared lifecycle and repository skills; no claim of Claude hook or auto-memory parity |
| Gemini CLI | Agent Skills-compatible workflows plus reviewed Gemini migration tooling; no complete workspace adapter |
| claude.ai | Manual consumer of selected knowledge files; no repository writes, hooks, or slash-command parity |
| Other agents | Can use the Markdown state and portable skills only when their file and Agent Skills support is compatible |

## One source, explicit host adapters

| Capability | Shared | Claude Code adapter | Codex adapter |
|---|---:|---:|---:|
| Identity, project, state, and session files | Yes | Reads the repository | Reads the repository |
| Lifecycle workflow core | Yes | `/setup`, `/start`, `/update`, `/end` | `$context-setup`, `$context-start`, `$context-update`, `$context-end` |
| Reusable provider-neutral skills | Yes | Thin slash commands when needed | Repository skills under `.agents/skills/` |
| Checked-in hooks and settings | No | Included | No equivalent claimed |
| Claude auto-memory and `/dream` | No | Included | Use repository state and sessions for shared continuity |
| Browser project knowledge | Selected files only | Manual upload to claude.ai | Product-specific import or attachment flows remain separate |

The shared layer is intentionally plain files. Provider-specific tool names, hooks, permissions, and memory features stay in their adapter directories.

## Optional integrations

The [optional integrations catalog](references/integrations.md) is generated from [`integrations/catalog.json`](integrations/catalog.json). Each entry declares supported hosts, credentials, reads, writes, publish or destructive capabilities, confirmation gates, evidence, a health check, and uninstall behavior.

The current catalog includes portable skill collections and creator tools, plus reviewed paths for Tolaria MCP, Obsidian CLI, Beads for Gemini CLI, Granola MCP, Google Workspace CLI, Notion MCP, and Substack MCP. `listed` and `experimental` entries are leads, not endorsements. Setup never installs, authenticates, or activates them.

## Repository layout

```text
AGENTS.md                  Codex repository instructions
CLAUDE.md                  Claude Code root context and adapter index
ROUTING.md                 Task-to-context routing table
TODO.md                    Full backlog
identity/                  Stable personal and professional context
projects/                  Project context and project-specific workflows
state/                     Current focus, priorities, blockers, and decisions
sessions/                  Reviewed session handoffs
.agents/skills/            Provider-neutral workflow cores
.claude/commands/          Claude Code slash-command adapters
.claude/skills/            Claude Code-only skills
.claude/hooks/             Claude Code-only safety and session hooks
integrations/              Machine-checked opt-in integration catalog
references/                Generated catalog and integration setup notes
scripts/                   Setup, validation, migration, and maintenance tools
docs/                      Onboarding, architecture, safety, and migration guides
```

Each fact should have one canonical home. `ROUTING.md` points an agent to the right file instead of copying the same context across prompts.

## Skills and memory

A skill is a Markdown workflow for a task you repeat. Provider-neutral skills belong in `.agents/skills/<name>/SKILL.md`. Claude Code can add a thin adapter under `.claude/commands/`; Codex discovers the repository skill directly. [Build a first Claude Code command](docs/first-skill.md) after the core loop is working, or follow [the portable skill structure](projects/README.md) for a shared workflow.

Claude Code auto-memory is a separate, host-specific layer. The repository includes a typed [auto-memory specification](docs/auto-memory.md) and the [`/dream` curator](docs/dream-architecture.md), which creates proposals before anything writes back. Shared continuity still belongs in `state/` and `sessions/` so another supported agent can use it.

## Safety and validation

- Review generated context before writing or committing it.
- Keep raw exports, credentials, private reasoning, and migration scratch data outside tracked files.
- Treat integrations as disabled until you choose and configure one.
- Use one git worktree per concurrent agent session.
- Follow [`docs/safety-contract.md`](docs/safety-contract.md) before external writes, destructive actions, or permission changes.

Run the full local check after changing instructions, skills, scripts, adapters, or generated references:

```bash
bash scripts/validate-all.sh
```

CI runs the same aggregate validator. It checks structure, adapter mappings, links, shell syntax, hook behavior, JSON, tests, and generated integration documentation. It cannot prove the behavior of an installed agent version or an external service.

## Documentation

| Goal | Guide |
|---|---|
| Install and choose a host | [Getting started](docs/getting-started.md) |
| Import useful context from another system | [Migration guide](docs/migration-guide.md) |
| Use the repository in Codex | [Codex onboarding](docs/codex-onboarding.md) |
| Keep claude.ai projects aligned | [Claude projects sync](docs/claude-projects-sync.md) |
| Choose an optional add-on | [Integration catalog](references/integrations.md) |
| Understand product language and boundaries | [Positioning](docs/positioning.md) |
| Maintain the repository | [Repository maintenance](docs/repo-maintenance.md) |

## Contributing

This is a template. Structural contributions, clearer conventions, and reusable skills are welcome. Open an issue with the pattern and the problem it solves.

## Used by

- [Conor Bronsdon](https://github.com/conorbronsdon), host of the [Chain of Thought podcast](https://chainofthought.show/?utm_source=github&utm_medium=referral&utm_campaign=repo-readme&utm_content=claude-context-os)

Using the template? Open a PR to add yourself.

## Disclaimer

This is an independent personal project. It is not affiliated with, sponsored by, or endorsed by Anthropic, OpenAI, Google, or another provider.

## License

MIT. See [LICENSE](LICENSE). Fork it, adapt it, and make it yours. Attribution is not required.
