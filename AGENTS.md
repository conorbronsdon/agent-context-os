# Context OS

This repository is the durable source of truth for personal, project, and
session context. Keep provider-neutral state here and host-specific behavior in
its adapter directory.

## Session lifecycle

- First-time onboarding: use `$setup`.
- Begin work: use `$start`.
- Save a mid-session checkpoint: use `$update`.
- Close a session: use `$end`.

These workflows require explicit invocation. The `$context-setup`,
`$context-start`, `$context-update`, and `$context-end` compatibility names
remain supported.

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
- Optional integrations stay disabled until chosen and configured. Review
  `references/integrations.md` for data and side-effect boundaries.

## Portability boundary

- `.agents/skills/` contains portable workflow cores.
- `.claude/` contains Claude Code commands, hooks, settings, and memory adapters.
- `.codex/hooks.json` maps Codex events to the same read-only policy checks.
- `adapters/hermes/` documents optional Hermes hooks and skill installation.
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
- `.claude/hooks/` does not run under Hermes. The optional Hermes adapter maps
  supported events to portable checks; kernel enforcement does not depend on it.

## Validation

Run `bash scripts/validate-all.sh` after changing instructions, skills,
commands, hooks, scripts, manifests, or generated references.
