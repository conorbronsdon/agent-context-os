# Context OS

This repository is the durable source of truth for personal, project, and session context. Keep provider-neutral state in the repository and keep host-specific behavior in its adapter directory.

## Session lifecycle

- First-time onboarding: use `$setup`.
- Begin work: use `$start`.
- Save a mid-session checkpoint: use `$update`.
- Close a session: use `$end`.

These skills are deliberately explicit-invocation workflows. Do not start, checkpoint, or close a session merely because their descriptions seem relevant.
The namespaced `$context-setup`, `$context-start`, `$context-update`, and
`$context-end` forms remain supported compatibility names.

## Context routing

- Read `ROUTING.md` before loading task-specific context.
- Treat `TODO.md` as the task backlog and `state/current.md` as the curated top-of-mind view.
- Keep each fact in one canonical file; link to it elsewhere instead of duplicating it.
- Load only the files needed for the current task. Identity and session data may be sensitive.

## Safety

- Follow `docs/safety-contract.md` before any external write, publish, destructive action, credential change, or permission expansion.
- Show proposed context-file changes before broad or destructive rewrites.
- Never commit or push without explicit approval.
- Treat optional integrations as disabled until the user chooses and configures one. Check `references/integrations.md` for its data and side-effect boundaries.

## Portability boundary

- `.agents/skills/` contains the portable workflow cores.
- `.claude/` contains Claude Code commands, hooks, settings, and memory adapters. Do not assume those features run in Codex or Hermes.
- Do not commit personal Codex configuration or credentials. Keep machine-level configuration outside this repository.

## Hermes Agent

Hermes Agent reads this repository's instructions automatically:

- Project rules: Hermes loads `AGENTS.md` from the working directory into every session in this repository. This file is the portable entry point; `CLAUDE.md` remains Claude Code-specific.
- Session loop: the lifecycle skills under `.agents/skills/` are agentskills.io-compatible SKILL.md files. Install the short `setup`, `start`, `update`, and `end` aliases with `hermes skills install <path>` (or import via `hermes import-agent claude-code`, which picks up skill directories), then invoke them as `/start`, `/update`, and `/end`. The `context-*` directories remain the canonical workflow cores and compatibility names.
- Memory: Hermes has its own persistent memory (`MEMORY.md`) plus a background Curator. See `docs/memory-across-agents.md` for how this repository's state layer relates to native Hermes memory, and when to run `/dream` equivalents.
- Hooks: the checked-in `.claude/hooks/` guards do not run under Hermes. Hermes' equivalent is its plugin/hooks system (`hermes config get plugins`, docs: Features → Hooks); the safety contract in `docs/safety-contract.md` still applies as instructions even without enforcement.

## Validation

Run `bash scripts/validate-all.sh` after changing instructions, skills, commands, hooks, scripts, or generated references.
