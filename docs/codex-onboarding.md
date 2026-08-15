# Codex onboarding

Codex can use the same repository state as Claude Code. The portable boundary is the root `AGENTS.md`, reusable workflows in `.agents/skills/`, and the existing `identity/`, `projects/`, `state/`, and `sessions/` files. A fork is not required.

## Set up

From a fresh clone:

```bash
bash scripts/setup.sh --agent codex
```

Then launch Codex from the repository root and invoke the onboarding skill explicitly:

```text
$context-setup
```

Codex discovers the root [`AGENTS.md`](../AGENTS.md) and repository skills automatically. The lifecycle is:

| Moment | Codex skill | Shared result |
|---|---|---|
| First run or major refresh | `$context-setup` | Identity, projects, reusable workflows, and weekly state |
| Start work | `$context-start` | Briefing from repository state and recent sessions |
| Mid-session | `$context-update` | Append-only checkpoint and minimal state change |
| Finish work | `$context-end` | Reviewed session log, state updates, decisions, and git safety report |

The four lifecycle skills disable implicit invocation. This prevents an agent from opening, checkpointing, or closing a session merely because a prompt resembles the workflow.

## What is shared

- Identity and professional context in `identity/`
- Project context in `projects/`
- Current priorities, decisions, and blockers in `state/`
- Session handoffs in `sessions/`
- Provider-neutral workflow instructions in `.agents/skills/`
- Routing and safety rules in `ROUTING.md` and `docs/safety-contract.md`

Commit these files only when they are appropriate for the repository's visibility. They may contain personal or business-sensitive information.

## Host-specific boundaries

| Capability | Portable | Claude Code only in this repository | Codex path |
|---|---:|---:|---|
| Repository state and session logs | Yes | No | Read and update through the lifecycle skills |
| Lifecycle workflow core | Yes | No | `.agents/skills/context-*` |
| Slash commands | No | Yes | Invoke `$context-*` skills instead |
| Checked-in hooks and settings | No | Yes | No equivalence is claimed |
| Claude auto-memory and `/dream` | No | Yes | Use repository `state/` and `sessions/` for shared continuity |
| Personal agent configuration | No | No | Keep it outside the repository |

Codex supports trusted repository-scoped [`.codex/config.toml` overrides](https://developers.openai.com/codex/config-basic). This template intentionally does not ship one: its portable lifecycle does not need project-level model, sandbox, approval, MCP, or hook overrides, and adding them would expand the template's trust boundary. If a project later adopts shared Codex configuration, review it like infrastructure. Keep credentials, personal preferences, and provider/auth settings at user or managed scope.

## Optional import

Codex offers `/import` for bringing supported instructions and configuration from another agent environment. It is optional migration help, not the runtime path for this repository. The repository already has native `AGENTS.md` and `.agents/skills/`; importing the same material can duplicate or conflict with them. If you use `/import` for older local configuration, preview and review every proposed change before applying it.

## Official references

- [How Codex discovers `AGENTS.md`](https://developers.openai.com/codex/agent-configuration/agents-md)
- [Build and use Codex skills](https://developers.openai.com/codex/build-skills)
- [Import configuration into Codex](https://developers.openai.com/codex/import)

## Verify

Run:

```bash
bash scripts/validate-all.sh
```

CI validates file structure, adapter mapping, explicit invocation policy, local links, shell syntax, hooks, JSON, and unit tests. It cannot prove the behavior of every installed Codex version or external integration, so keep the host boundaries above explicit.
