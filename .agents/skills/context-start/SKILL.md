---
name: context-start
description: Load this workspace's current state, recent decisions, blockers, priorities, and session continuity, then give a concise briefing. Use only when the user explicitly asks to begin or resume a workspace session.
---

# Start a workspace session

Resume from durable repository state instead of reconstructing context from chat history.

## Configuration

If `workspace.yaml` exists at the project root, use its configured state directory, sessions directory, task file, and staleness thresholds. Otherwise use:

- state directory: `state/`
- sessions directory: `sessions/`
- task file: `TODO.md`
- stale after: `current.md` 3 days, `weekly-priorities.md` 5 days, `blockers.md` 7 days

## Procedure

1. Determine today's local date and day of week.
2. Read `ROUTING.md`, then load in order:
   - `<state_dir>/current.md`
   - the latest five entries in `<state_dir>/decisions.md`
   - `<state_dir>/blockers.md`
   - `<state_dir>/weekly-priorities.md`
   - today's session file, or the most recent session file when today's does not exist
3. If this is a git repository, inspect commits since the most recent session date and read any changed state or context files relevant to today's work. Outside git, skip this check.
4. Use only explicitly configured, connected, read-only live sources when they materially improve the briefing. Keep queries narrow, follow the source's documented data boundary, and fall back to repository files if the source is unavailable. Never activate or authenticate an integration as part of this workflow.
5. Report only actionable health findings:
   - state files past their configured thresholds,
   - non-placeholder files in a configured inbox,
   - unchecked dated tasks whose date has passed, and
   - unresolved blockers or deadlines.
6. Give a short briefing with the date, state freshness, relevant changes, top two or three priorities, time-sensitive threads, blockers, and any scoped live-data highlights.
7. If today's session already exists, acknowledge it and resume from its latest entry. End by asking what to focus on.

Keep this read-only. Do not update timestamps merely because the files were read.
