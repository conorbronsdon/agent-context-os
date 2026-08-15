# Getting started

`claude-context-os` is a Claude-first, Codex-compatible workspace harness for durable agent context. It organizes version-controlled context, reusable workflows, session handoffs, optional integrations, and review gates. It does not invoke a model or provide an agent loop; an explicitly supported host does that.

This guide takes you from a fresh clone to a repeatable session loop without silently importing history, enabling tools, or publishing private context.

## 1. Choose where the context will live

The repository can contain personal identity, business plans, meeting references, and project decisions. Before adding real content:

- keep the workspace local-only or use a private remote by default;
- keep passwords, access tokens, recovery codes, and raw credentials out of the repository;
- add only context that every intended collaborator may read; and
- review staged changes before every commit or push.

A later deletion does not erase material from git history. Do not push until you have checked both the exact diff and the remote audience.

The template ignores local migration inventories under `.context-os/`, but ignored files are still sensitive local data.

## 2. Clone and run the local setup

```bash
git clone https://github.com/conorbronsdon/claude-context-os.git my-context
cd my-context
bash scripts/setup.sh --agent codex
# or: bash scripts/setup.sh --agent claude
```

The shell setup can personalize the template, offer an optional local hook, and launch the selected host. Each infrastructure or commit action has its own prompt. It does not import conversations. It does not install integrations, authenticate services, or enable publishing tools.

Choose the host workflow after setup:

| Host | First-time context | Start | Checkpoint | Close |
|---|---|---|---|---|
| Claude Code | `/setup` | `/start` | `/update` | `/end` |
| Codex | `$context-setup` | `$context-start` | `$context-update` | `$context-end` |
| Claude.ai | [`SETUP-PROMPTS.md`](../SETUP-PROMPTS.md) | Use uploaded project knowledge | Manual | Copy reviewed changes back |
| Gemini CLI | Migration and portable-skill discovery only | No lifecycle adapter | No lifecycle adapter | No lifecycle adapter |

The repository currently validates the complete lifecycle for Claude Code and Codex. Claude.ai is a manual knowledge copy with no write-back. Gemini support is limited to migration helpers and the portable skill layout. Treat another agent as a new adapter: verify its instruction discovery, invocation, permissions, and write behavior before claiming parity.

## 3. Start fresh or bring context forward

For a clean start, run the first-time context workflow above. It interviews you, shows the proposed file map, and waits before replacing populated context.

If useful context already exists in another AI system, follow the [migration guide](migration-guide.md). Import one source and one project at a time. Preserve durable facts, decisions, preferences, and proven workflows—not entire chat histories by default.

Available paths include:

- a manual audit prompt for Claude Projects and other browser-hosted workspaces;
- reviewed Gemini CLI configuration migration with `/migrate-gemini` or `$migrate-gemini`;
- evidence-based Gemini workflow recovery with `/mine-gemini-workflows` or `$mine-gemini-workflows`; and
- optional Codex `/import` for supported legacy instructions or configuration, followed by a diff review.

No migration path should copy credentials, private reasoning, or an unreviewed bulk export into tracked files.

## 4. Run the core loop

The portable loop is deliberately small:

1. **Start** — load current state, decisions, blockers, and recent session continuity.
2. **Work** — use only the project context and optional tools needed for the task.
3. **Checkpoint** — append a factual progress note when continuity would otherwise be lost.
4. **Close** — review the proposed handoff before state or decisions are updated.

Shared continuity lives in `state/` and `sessions/`. Claude Code auto-memory is an optional host-specific layer; it is not silently shared with Codex.

## 5. Add one optional integration at a time

Use the [integration chooser](integrations-guide.md) to match a goal to a reviewed catalog entry. Then read the generated [capability and safety reference](../references/integrations.md) before installing anything.

The catalog is descriptive, not an installer. Setup never activates an entry. Add at most one new trust boundary at a time, and confirm the exact destination, credentials, sensitive reads, writes, remote effects, and uninstall behavior for the one integration you choose.

## 6. Maintain context without busywork

| Cadence | Recommended action | Why |
|---|---|---|
| Each session | Start and close the lifecycle | Preserve an accurate handoff |
| During long sessions | Checkpoint only meaningful progress | Avoid state churn |
| Weekly | Review `state/current.md`, priorities, and blockers | Remove stale urgency |
| When a project changes | Update its canonical context and route | Prevent duplicated facts |
| Periodically | Review session patterns and optional integrations | Retire stale workflows and permissions |
| Claude Code only, when useful | Run `/dream`, then review with `/dream-apply` | Curate auto-memory through proposals |

Update files when meaning changes, not merely to refresh dates. The [auto-memory specification](auto-memory.md) and [dream architecture](dream-architecture.md) explain the optional Claude-only curation layer.

## Verify the workspace

```bash
bash scripts/validate-all.sh
```

Validation checks repository structure, local links, lifecycle adapters, hooks, JSON, catalog consistency, shell syntax, and tests. It cannot certify external services or prove that a third-party integration has not changed; re-check linked evidence before enabling one.
