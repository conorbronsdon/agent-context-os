# Getting started with Context OS

Context OS can begin with a blank interview or selected context from another
assistant. The result is a small, reviewable repository that Claude Code,
Codex, and OpenClaw, plus the experimental Hermes, Cursor, and Devin adapters,
can use as shared state.

## Before you clone

You need Git, Bash, and Python 3.10 or newer. Local hosts include Claude Code,
Codex, OpenClaw, and the experimental Hermes and Cursor adapters; verify Devin's
managed cloud path separately in its account UI. claude.ai cannot maintain a
local checkout directly.

Python may be installed as either `python3` or `python`; the repository resolves
whichever works. To pin a specific interpreter — a virtualenv, or one of several
installed versions — set `CONTEXTOS_PYTHON` to its path or command. That setting
is honored exactly: if it does not resolve to a working Python 3.10+, setup and
validation stop instead of falling back to a different interpreter.

Decide where the repository will live. If it will contain personal, client, employer, financial, or unpublished project context, use a private remote. Repository visibility is only one control; do not store credentials, raw account exports, or information you would not want every configured agent to read.

## Create your copy

Clone the public template:

```bash
git clone https://github.com/conorbronsdon/agent-context-os.git my-context
cd my-context
```

For a private copy, create an empty private repository, then keep this template as `upstream` and make your repository `origin`:

```bash
git remote rename origin upstream
git remote add origin <YOUR_PRIVATE_REPO_URL>
git remote -v
```

Do not push until you have reviewed the placeholder files, example project, and first setup diff.

## Run the local setup

Choose every registered agent you expect to use with this repository:

```bash
bash scripts/setup.sh --agents claude,codex
# or
bash scripts/setup.sh --agents hermes
# or
bash scripts/setup.sh --agents openclaw
# or
bash scripts/setup.sh --agents cursor
# or
bash scripts/setup.sh --agents devin
# or, for the provider-neutral core only
bash scripts/setup.sh --agents none
```

Setup shows the exact tracked workspace diff and proposal digest, then defaults
the apply decision to no. An approved selection is additive: rerunning with a
subset or `none` preserves the existing set, while a new runtime expands it.
Selected local runtimes are also registered in the gitignored local host map.
Managed-account runtimes such as Devin record tracked intent without claiming
the remote account is configured. Omit
the option, or use `--agents auto`, to auto-detect local launch instructions
without changing tracked intent. `--agent` remains a deprecated singleton
alias. See [workspace configuration](workspace-configuration.md) for the full
transaction and rerun contract.

The script can:

- replace the name placeholder;
- point `origin` at your repository;
- remove the sample musician project;
- install the local pre-commit hook; and
- generate a local, gitignored repository map; and
- propose an additive tracked agent set and register approved selections locally.

Each optional change is prompted. The script shows setup-file changes before offering a narrowly scoped commit, and that commit defaults to no.

Later, inspect or change the tracked set with `agent list`, `agent enable`, and
`agent disable`. Each change is an exact proposal that requires a separate
digest-confirmed `apply`; disabling never deletes the bundled adapter.

## Choose fresh setup or migration

### Start from your answers

Launch repository-discovery hosts from the repository root. In v0.12 that root
is the colocated KernelRoot, ContextRoot, and nominal WorkingRoot for this
full-template wrapper path. For a separate application, create a reviewed
`project attach --id <id>` proposal using exact `--context-root` and
`--working-root` options through the KernelRoot wrapper. The application stays
read-only to lifecycle operations; see the [root contract](root-contract.md).
OpenClaw's plugin continues to resolve an operator-configured alias to a
colocated Context OS root in this first attachment slice, so its Gateway and
private workspace do not need to start in the repository:

```bash
claude
# or
codex
# or
hermes
# or, after installing and configuring adapters/openclaw/plugin
openclaw gateway run
# or, open the repository in Cursor or start its Agent CLI here
agent
```

Run `/setup` in Claude Code or Hermes, `/context-setup` in Cursor, `$setup` in
Codex, or `/contextos <alias> setup` through an authorized OpenClaw messaging
surface. OpenClaw first requires the separate private-workspace, verified skill
synchronization, plugin installation, and configured project-alias binding
steps in its [adapter guide](../adapters/openclaw/README.md). The guided
interview asks one question at a time, builds a deterministic proposal, and
waits before applying the exact reviewed diff.
For OpenClaw, continue each owned interview with
`/contextos <alias> continue <session-key> <response>`. Independently review the
proposal file and apply it with the documented trusted-shell kernel command;
the plugin does not expose proposal application.

Cursor has separate IDE and Agent CLI permission surfaces. Follow its
[experimental adapter guide](../adapters/cursor/README.md); setup registers the
runtime but launches neither surface and changes no Cursor authorization setting.

For Devin, follow the [experimental managed-account guide](../adapters/devin/README.md),
verify repository access and the active environment in Devin, then start a fresh
cloud session and invoke `@skills:context-setup`. Local setup does not authenticate,
launch, or verify Devin, and Devin Review is not a lifecycle surface.

### Bring existing context

Read the [migration guide](migration-guide.md) first. Create one reviewed migration packet from a selected project, conversation set, memory export, or group of source files. Then run the same setup command and provide that packet as your starting material.

Avoid bulk ingestion. A small set of current facts and proven workflows is more useful than years of unfiltered history.

Gemini artifacts remain useful migration sources, but consumer Gemini CLI requests transitioned to Antigravity CLI in June 2026. Continuing enterprise/API-key Gemini CLI and Antigravity are separate targets; this repository does not claim that Antigravity shares Gemini skill discovery, hooks, permissions, or lifecycle behavior. See the [Gemini migration boundary](gemini-migration.md).

## Review the first result

Check the files that setup proposes or changes:

- `identity/` for stable facts and background;
- `projects/` for long-lived project context;
- `state/` for current work, priorities, blockers, and decisions;
- `.agents/skills/` for provider-neutral recurring workflows; and
- `ROUTING.md` for the paths an agent should load for each task.

Remove any unsupported inference, stale claim, duplicate fact, or context that is too sensitive for the repository.

Then run:

```bash
bash scripts/contextos.sh doctor
bash scripts/validate-all.sh --workspace
git diff --check
git status --short
```

With tracked workspace configuration, bare `doctor` validates the selected
agent set and reports the other shipped adapters as inert. Missing local
binaries warn without changing support claims. Use `doctor --runtime ID` for a
strict one-runtime inspection and reserve `doctor --all` for maintainers
checking every shipped adapter.

Commit and push only after the diff matches what you intend to preserve.

## Run the daily loop

| Moment | Claude Code | Codex | Hermes | OpenClaw | Cursor IDE/CLI (experimental) | Devin session (experimental) |
|---|---|---|---|---|---|---|
| Start work | `/start` | `$start` | `/start` | `/contextos <alias> start` | `/context-start` | `@skills:context-start` |
| Save progress without closing | `/update` | `$update` | `/update` | `/contextos <alias> update` | `/context-update` | `@skills:context-update` |
| End with a reviewed handoff | `/end` | `$end` | `/end` | `/contextos <alias> end` | `/context-end` | `@skills:context-end` |

The lifecycle kernel writes shared continuity to `state/` and `sessions/` only
after exact-proposal approval, then emits a local receipt. Each host retains
different hooks, commands, permissions, and native memory. See the
[cross-runtime architecture](cross-runtime-architecture.md).

## Add capabilities later

Core setup requires no external integration. When you have a concrete need, start with the [integration chooser](integrations-guide.md), then open the selected [catalog entry](../references/integrations.md) and check:

- which agents the integration supports;
- what it reads and writes;
- which credentials it needs;
- whether it can publish, overwrite, delete, or run arbitrary code;
- which confirmations are required; and
- how to verify and uninstall it.

Install and authenticate one add-on at a time. Run its narrow health check before relying on it in a workflow.

## Keep the workspace healthy

- Run the start and end loop instead of rewriting top-level context in every chat.
- Update stable identity only when it changes. Update state when active work changes.
- Keep one fact in one canonical file and route to it elsewhere.
- Review files that pass their staleness threshold.
- Use one git worktree per concurrent agent session.
- Run `bash scripts/validate-all.sh --workspace` after changing instructions,
  skills, scripts, generated references, or tracked personal context. The
  contributor and CI form omits `--workspace` to enforce complete product-file
  ownership.

See [repository maintenance](repo-maintenance.md) and the [safety contract](safety-contract.md) for the operating rules.
