# Getting started with Context OS

Context OS can begin with a blank interview or selected context from another
assistant. The result is a small, reviewable repository that Claude Code,
Codex, and Hermes can use as shared state.

## Before you clone

You need Git, Bash, Python 3.10 or newer, and at least one supported local
agent: Claude Code, Codex, or Hermes. claude.ai can help produce files but
cannot maintain a local checkout directly.

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

Choose the host you expect to use first:

```bash
bash scripts/setup.sh --agent claude
# or
bash scripts/setup.sh --agent codex
# or
bash scripts/setup.sh --agent hermes
```

You can omit `--agent` to auto-detect an installed host, or use `--agent none` to prepare the repository without launching one.

The script can:

- replace the name placeholder;
- point `origin` at your repository;
- remove the sample musician project;
- install the local pre-commit hook; and
- generate a local, gitignored repository map.

Each optional change is prompted. The script shows setup-file changes before offering a narrowly scoped commit, and that commit defaults to no.

## Choose fresh setup or migration

### Start from your answers

Launch the selected host from the repository root:

```bash
claude
# or
codex
# or
hermes
```

Run `/setup` in Claude Code or Hermes, or `$setup` in Codex. The guided
interview asks one question at a time, builds a deterministic proposal, and
waits before applying the exact reviewed diff.

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

Commit and push only after the diff matches what you intend to preserve.

## Run the daily loop

| Moment | Claude Code | Codex | Hermes |
|---|---|---|---|
| Start work | `/start` | `$start` | `/start` |
| Save progress without closing | `/update` | `$update` | `/update` |
| End with a reviewed handoff | `/end` | `$end` | `/end` |

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
