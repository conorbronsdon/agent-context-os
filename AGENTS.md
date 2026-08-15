# claude-context-os

This repository is the durable source of truth for personal, project, and session context. Keep provider-neutral state in the repository and keep host-specific behavior in its adapter directory.

## Session lifecycle

- First-time onboarding: use `$context-setup`.
- Begin work: use `$context-start`.
- Save a mid-session checkpoint: use `$context-update`.
- Close a session: use `$context-end`.

These skills are deliberately explicit-invocation workflows. Do not start, checkpoint, or close a session merely because their descriptions seem relevant.

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
- `.claude/` contains Claude Code commands, hooks, settings, and memory adapters. Do not assume those features run in Codex.
- Do not commit personal Codex configuration or credentials. Keep machine-level configuration outside this repository.

## Validation

Run `bash scripts/validate-all.sh` after changing instructions, skills, commands, hooks, scripts, or generated references.
