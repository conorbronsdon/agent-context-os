# Getting started with Context OS

Context OS can begin with a blank interview or selected context from another assistant. The result is the same: a small, reviewable repository that Claude Code and Codex can use as shared state.

## Before you clone

You need Git, Bash, and Python 3. You also need Claude Code or Codex for the guided lifecycle. claude.ai can help produce files, but it cannot maintain a local checkout directly.

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
```

Run `/setup` in Claude Code or `$context-setup` in Codex. The guided interview asks one question at a time, proposes a file map, and waits before changing populated files.

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
bash scripts/validate-all.sh
git diff --check
git status --short
```

Commit and push only after the diff matches what you intend to preserve.

## Run the daily loop

| Moment | Claude Code | Codex |
|---|---|---|
| Start work | `/start` | `$context-start` |
| Save progress without closing | `/update` | `$context-update` |
| End with a reviewed handoff | `/end` | `$context-end` |

The lifecycle writes shared continuity to `state/` and `sessions/`. Claude Code has additional host-specific hooks, commands, and auto-memory features. The [Codex onboarding guide](codex-onboarding.md) documents the exact boundary.

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
- Run `bash scripts/validate-all.sh` after changing instructions, skills, scripts, or generated references.

See [repository maintenance](repo-maintenance.md) and the [safety contract](safety-contract.md) for the operating rules.
