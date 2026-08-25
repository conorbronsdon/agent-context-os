<div align="center">

# Context OS

A Git-backed context and workflow layer for agents like Claude Code, Codex, and Hermes.

[![GitHub stars](https://img.shields.io/github/stars/conorbronsdon/agent-context-os?style=social)](https://github.com/conorbronsdon/agent-context-os/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-ready-d97757?style=flat-square)](https://docs.anthropic.com/en/docs/claude-code)
[![Codex](https://img.shields.io/badge/Codex-ready-111827?style=flat-square)](docs/codex-onboarding.md)
[![Validate](https://github.com/conorbronsdon/agent-context-os/actions/workflows/validate.yml/badge.svg)](https://github.com/conorbronsdon/agent-context-os/actions/workflows/validate.yml)
[![X](https://img.shields.io/badge/X-@ConorBronsdon-black?style=flat-square&logo=x)](https://x.com/ConorBronsdon)

</div>

Chat history, project instructions, and copied prompts drift apart. Context OS puts the durable parts in plain Markdown: who you are, what you are working on, decisions already made, and the workflows you want an agent to follow.

Claude Code, Codex, and Hermes read the same repository state. A deterministic
lifecycle kernel turns reviewed setup, checkpoint, and close requests into
hash-checked proposals and receipts, without treating native memory as the
source of truth.

| What you need | How Context OS handles it |
|---|---|
| Bring useful context forward | A source-neutral [migration workflow](docs/migration-guide.md) turns selected chats, project instructions, memory exports, and documents into reviewable files. |
| Work across coding agents | Provider-neutral state, skills, and lifecycle transitions live outside host adapters. Claude Code, Codex, and Hermes share the same kernel. |
| Add the tools that fit | A generated [integration catalog](references/integrations.md) documents install scope, data access, side effects, and confirmation gates. Nothing is enabled automatically. |
| Keep context useful | Session handoffs, staleness checks, decision logs, and reviewable memory proposals make maintenance part of the normal workflow. |

Context OS does not scrape every account, sync product UIs automatically, or install integrations on setup. Imports are selective, browser-project sync is manual, and external capabilities remain opt-in.

## Quick start

Personal and business context often belongs in a private repository. Create an empty private repository first if that applies to you, and never commit credentials or a raw account export.

```bash
git clone https://github.com/conorbronsdon/agent-context-os.git my-context
cd my-context

# Recommended for a private copy:
git remote rename origin upstream
git remote add origin <YOUR_PRIVATE_REPO_URL>

# Pick a host, or omit --agent to auto-detect one:
bash scripts/setup.sh --agent claude
# bash scripts/setup.sh --agent codex
# bash scripts/setup.sh --agent hermes
```

Then start your agent from the repository root:

| Starting point | Next action |
|---|---|
| New workspace in Claude Code | Run `/setup` |
| New workspace in Codex | Run `$setup` |
| New workspace in Hermes | Run `/setup` after exposing the repository skills |
| Existing context in another assistant | Follow the [migration guide](docs/migration-guide.md), then use the selected material during setup |
| claude.ai only | Use [SETUP-PROMPTS.md](SETUP-PROMPTS.md) and copy the approved output into the repository |

The setup interview fills the identity, first project, workflows, and weekly state files. It can start from your answers or from a migration packet you reviewed first. See the full [getting started guide](docs/getting-started.md) for prerequisites, privacy choices, and verification.

## See the loop

![A start session in Claude Code: state files load and a session briefing comes back, using sample data from the included example musician project](docs/assets/start-demo.gif)

`/start` in Claude Code or Hermes and `$start` in Codex read your state,
priorities, decisions, blockers, and recent handoff. The result is grounded in
files rather than reconstructed from chat.

At the end, `/end` or `$end` proposes a handoff for review before it updates `sessions/` and `state/`. The namespaced `$context-end` form remains supported.

<sub>The GIF is scripted with sample data. [`docs/start-demo.tape`](docs/start-demo.tape) regenerates it, and [`docs/demo/start-session.sh`](docs/demo/start-session.sh) contains the transcript. Neither reads your state or calls a model.</sub>

## Daily workflow

Start small. Use the core loop for a week, add one active project, then turn a repeated task into a skill when the repetition is clear.

| Moment | Claude Code | Codex | Hermes | Shared result |
|---|---|---|---|---|
| First run or major refresh | `/setup` | `$setup` | `/setup` | Reviewed context proposal |
| Start work | `/start` | `$start` | `/start` | Read-only continuity inventory and briefing |
| Save a checkpoint | `/update` | `$update` | `/update` | Hash-checked update and receipt |
| Finish work | `/end` | `$end` | `/end` | Hash-checked handoff, decisions, and receipt |

The namespaced `$context-setup`, `$context-start`, `$context-update`, and
`$context-end` invocations remain available for compatibility.

Claude Code also ships host-specific commands for capture, daily checks, recovery, context search, and auto-memory curation. The [host boundary](docs/codex-onboarding.md#host-specific-boundaries) names what is portable and what is not.

## Bring existing context with you

Do not import an entire chat archive into active context. Use the [migration guide](docs/migration-guide.md) to:

1. select the assistant, project, or small set of conversations that contains useful context;
2. produce an inventory or compact migration packet;
3. classify each item as keep, verify, skip, or archive;
4. map approved facts, decisions, projects, and workflows into canonical files; and
5. validate the repository before committing.

The guide covers ChatGPT, Claude, Gemini Apps, Gemini CLI, and a generic path for other systems. Gemini CLI also has privacy-first `$migrate-gemini` and `$mine-gemini-workflows` skills for selected configuration and session evidence. Consumer Gemini CLI requests transitioned to Antigravity CLI in June 2026; continuing enterprise/API-key Gemini CLI and Antigravity are separate targets, and this repository does not claim Antigravity lifecycle or permission parity.

## Host support

| Host | Support level |
|---|---|
| Claude Code | Full experience: shared lifecycle, slash-command adapters, hooks, optional live reads, and Claude-only auto-memory curation |
| Codex | First-class lifecycle, repository skills, trusted project hooks, and the shared deterministic kernel; native memory remains outside the contract |
| Hermes Agent | `AGENTS.md`, portable skills, the shared kernel, and optional hook adapter; copied skills and native memory remain explicit host boundaries |
| Gemini CLI / Antigravity CLI | Migration tooling plus portable-skill discovery for continuing enterprise/API-key Gemini CLI; no complete workspace adapter, and no Antigravity discovery or permission parity is claimed |
| Cursor / OpenClaw | Read `AGENTS.md` from the repository root; portable skills usable where their Agent Skills support allows |
| claude.ai | Manual consumer of selected knowledge files; no repository writes, hooks, or slash-command parity |
| Other agents | Can use the Markdown state and portable skills only when their file and Agent Skills support is compatible |

## One source, explicit host adapters

| Capability | Shared | Claude Code | Codex | Hermes |
|---|---:|---:|---:|---:|
| Identity, project, state, and session files | Yes | Reads | Reads | Reads |
| Deterministic proposal/apply and receipts | Yes | Adapter | Native skill calls | Installed skill calls |
| Lifecycle vocabulary | Semantics | `/setup` etc. | `$setup` etc. | `/setup` etc. |
| Project hooks | Event contract only | `.claude/` | `.codex/` | Optional adapter |
| Native memory | No | Claude auto-memory | Outside contract | `MEMORY.md` / `USER.md` |

The shared layer is intentionally plain files. Provider-specific tool names, hooks, permissions, and memory features stay in their adapter directories.

## Optional integrations

The [optional integrations catalog](references/integrations.md) is generated from [`integrations/catalog.json`](integrations/catalog.json). Each entry declares supported hosts, credentials, reads, writes, publish or destructive capabilities, confirmation gates, evidence, a health check, and uninstall behavior.

Start with the task-based [integration chooser](docs/integrations-guide.md), add at most one new trust boundary at a time, then read the selected generated entry in full.

The current catalog includes portable skill collections and creator tools, plus reviewed paths for MarkItDown MCP, Tolaria MCP, Obsidian CLI, Beads for Gemini CLI, Granola MCP, Google Workspace CLI, Notion MCP, and Substack MCP. `listed` and `experimental` entries are leads, not endorsements. Setup never installs, authenticates, or activates them.

## Repository layout

```text
AGENTS.md                  Portable repository instructions
CLAUDE.md                  Claude Code root context and adapter index
ROUTING.md                 Task-to-context routing table
TODO.md                    Full backlog
identity/                  Stable personal and professional context
projects/                  Project context and project-specific workflows
state/                     Current focus, priorities, blockers, and decisions
sessions/                  Reviewed session handoffs
.agents/skills/            Provider-neutral workflow cores
contextos/                 Deterministic lifecycle kernel
.claude/commands/          Claude Code slash-command adapters
.claude/skills/            Claude Code-only skills
.claude/hooks/             Claude Code-only safety and session hooks
.codex/hooks.json          Codex lifecycle advisory adapter
adapters/hermes/           Hermes installation and optional hook adapter
runtimes/                  Machine-readable capability manifests
integrations/              Machine-checked opt-in integration catalog
references/                Generated catalog and integration setup notes
scripts/                   Setup, validation, migration, and maintenance tools
docs/                      Onboarding, architecture, safety, and migration guides
```

Each fact should have one canonical home. `ROUTING.md` points an agent to the right file instead of copying the same context across prompts.

## Skills and memory

A skill is a Markdown workflow for a task you repeat. Provider-neutral skills belong in `.agents/skills/<name>/SKILL.md`. Claude Code can add a thin adapter under `.claude/commands/`; Codex discovers the repository skill directly. [Build a first portable skill](docs/first-skill.md) after the core loop is working, or follow [the portable skill structure](projects/README.md) for a shared workflow.

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
| Use the repository in Hermes Agent | [Memory across agents](docs/memory-across-agents.md) and the Hermes section of [AGENTS.md](AGENTS.md) |
| Keep claude.ai projects aligned | [Claude projects sync](docs/claude-projects-sync.md) |
| See every command and portable skill | [Commands and skills](docs/commands-and-skills.md) |
| Choose an optional add-on | [Integration chooser](docs/integrations-guide.md) and [catalog](references/integrations.md) |
| Understand product language and boundaries | [Positioning](docs/positioning.md) |
| Keep context files small and cheap to load | [Optimizing context files](docs/optimizing-context.md) |
| Keep optional MCP calls inside a token budget | [MCP efficiency](docs/mcp-efficiency.md) |
| Maintain workspace context and memory | [Workspace maintenance](docs/maintenance.md) |
| Maintain the repository | [Repository maintenance](docs/repo-maintenance.md) |

## Contributing

This is a template. Structural contributions, clearer conventions, reusable skills, and integration catalog entries are welcome. Open an issue with the pattern and the problem it solves.

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the validator, generated files, and conventions, and [SECURITY.md](SECURITY.md) to report a vulnerability privately. Issues labelled [`good first issue`](https://github.com/conorbronsdon/agent-context-os/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) need no external account or credential.

## Used by

- [Conor Bronsdon](https://github.com/conorbronsdon), host of the [Chain of Thought podcast](https://chainofthought.show/?utm_source=github&utm_medium=referral&utm_campaign=repo-readme&utm_content=agent-context-os)

Using the template? Open a PR to add yourself.

## Disclaimer

This is an independent personal project. It is not affiliated with, sponsored by, or endorsed by Anthropic, OpenAI, Google, or another provider.

## License

MIT. See [LICENSE](LICENSE). Fork it, adapt it, and make it yours. Attribution is not required.
