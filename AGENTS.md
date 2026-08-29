# Context OS

This repository is the durable source of truth for personal, project, and session
context. Keep provider-neutral state here and host-specific behavior in its adapter.

## Session lifecycle

- First-time onboarding: use `$setup`.
- Begin work: use `$start`.
- Save a mid-session checkpoint: use `$update`.
- Close a session: use `$end`.

Invoke these workflows explicitly with the form documented by the host adapter;
this is guidance, not a host-enforced gate. The `$context-setup`, `$context-start`,
`$context-update`, and `$context-end` compatibility names remain supported.

## Lifecycle kernel

- `bash scripts/contextos.sh start` is the read-only continuity inventory.
- Setup, update, and end use `propose` then exact-digest `apply`; never edit
  lifecycle state directly.
- Present every proposal diff. Apply only after explicit approval of that exact
  proposal and report its receipt.
- Run `bash scripts/contextos.sh doctor` when discovery, runtime setup, a lock, or
  copied skills may be stale.

## Context routing

- Read `ROUTING.md` before loading task-specific context.
- Treat `TODO.md` as the backlog and `state/current.md` as top-of-mind context.
- Keep each fact in one canonical file and link to it elsewhere.
- Load only what the current task needs. Identity and session data may be sensitive.

## Safety

- Follow `docs/safety-contract.md` before any external write, publish,
  destructive action, credential change, or permission expansion.
- Show proposed context changes before broad or destructive rewrites.
- Never commit or push without explicit approval.
- Optional integrations stay disabled until chosen and configured; see
  `references/integrations.md` for data and side-effect boundaries.

## Portability boundary

- `.agents/skills/` contains portable workflow cores.
- `.claude/` contains Claude Code commands, hooks, settings, and memory adapters.
- `.codex/hooks.json` maps Codex events to the same read-only policy checks.
- `adapters/hermes/` documents optional Hermes hooks and skill installation.
- `adapters/openclaw/` documents first-class external-plugin OpenClaw support.
- `adapters/cursor/` documents separate experimental Cursor IDE and CLI support.
- `adapters/devin/` documents experimental Devin cloud-session and Review support.
- Runtime manifests under `runtimes/` declare support instead of implying parity.
- Kernel proposal/apply is the enforcement boundary on every host; hooks are
  defense in depth and host-local memory is never shared automatically.

## Hermes Agent

- Hermes loads `AGENTS.md` as project context.
- Expose `.agents/skills/` as an external skill directory, or install the four
  short aliases and all four `context-*` cores together. Copied skills must be
  refreshed after source changes.
- Invoke `/setup`, `/start`, `/update`, and `/end` explicitly.
- Keep Hermes `MEMORY.md` and `USER.md` separate from repository state. See
  `docs/memory-across-agents.md`.
- `.claude/hooks/` does not run in Hermes; its hooks are optional defense in depth.

## OpenClaw

- Keep private memory outside this repository. After reviewing its source commit,
  sync all eight skills and install this adapter's local external plugin.
- Bind an alias to this canonical root, then invoke
  `/contextos <alias> setup`, `start`, `update`, or `end` and its owned continuation.
- The plugin exposes no apply method. Review the stored proposal, then apply its
  exact digest per `adapters/openclaw/README.md`; allowlists are not authorization.

## Cursor

- Open the repository as the IDE workspace or start the Agent CLI from its root;
  both discover `AGENTS.md` and `.agents/skills/` natively.
- Invoke `/context-setup`, `/context-start`, `/context-update`, and
  `/context-end` explicitly; Cursor CLI reserves `/update` for self-updates.
- Keep `.cursor/rules` non-overlapping with this file because Cursor does not
  document their conflict order. IDE and CLI permissions remain separate.
- Cursor CLI also reads the removable root `CLAUDE.md` when present. Treat its
  short lifecycle commands as Claude adapters, not Cursor invocations.
- This adapter ships no hook or memory bridge; see `adapters/cursor/README.md`.

## Devin

- Cloud sessions use `@skills:context-setup`, `@skills:context-start`,
  `@skills:context-update`, and `@skills:context-end`; automatic skill discovery
  remains possible. Digests prevent proposal substitution, not automated approval.
- Review sends code externally and is not a lifecycle host. Account state is not
  locally configured or verified; see `adapters/devin/README.md`.

## Validation

Run `bash scripts/validate-all.sh --workspace` for workspace changes. Product
contributors and CI omit `--workspace` after instructions, hooks, scripts, manifests, or generated references change.
