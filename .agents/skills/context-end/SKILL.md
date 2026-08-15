---
name: context-end
description: Close a workspace session by reviewing a proposed summary, recording approved outcomes, updating state and decisions, and checking repository safety. Use only when the user explicitly asks to end, close, or hand off the current session.
---

# End a workspace session

Leave durable, reviewable state for the next session.

## Configuration

If `workspace.yaml` exists, use its state and sessions directories. Otherwise use `state/` and `sessions/`.

## Procedure

### 1. Draft before writing

Determine today's local date and time. Extract:

- work completed,
- decisions and their rationale,
- meaningful rejected alternatives,
- priority or thread changes,
- blockers,
- open work, and
- next actions.

Present the draft and wait for confirmation before editing context files.

### 2. Record the approved session

Create `<sessions_dir>/<YYYY-MM-DD>.md` with this shape when it does not exist:

```markdown
# Session — <YYYY-MM-DD>

## What happened
- <approved facts>

## Decisions
- <approved decisions>

## Next time
- <approved open work>
```

If the file exists, append `## Session <HH:MM>` and the three subsections instead of overwriting it.

### 3. Update state

- Update `<state_dir>/current.md` with approved active threads, completions, and a brief recent-context note.
- Keep exactly one `**Last Updated:**` line in `current.md` and set it to today's date. Let `old_date` be the prior real date and `newest_history_date` be the newest date already in the log; archive only when `old_date != today && old_date != newest_history_date`. When that invariant passes, prepend a separate line containing `old_date` under `# current.md update log` in `<state_dir>/current-log.md`. Never log a placeholder; a second checkpoint or close on the same day leaves both the current date and history unchanged.
- Update `<state_dir>/blockers.md` only for a new, changed, or resolved dependency.
- Update `<state_dir>/weekly-priorities.md` only when meaningful progress changed the weekly view.
- Preserve unrelated content in every file.

### 4. Record durable decisions

For each approved decision future sessions need, append one row to `<state_dir>/decisions.md`:

```markdown
| <date> | <decision> | <context or rationale> | <rejected alternatives> |
```

Skip trivial choices. Leave rejected alternatives blank when there was no real branch point.

### 5. Check repository state

If this is a git repository:

1. inspect recent commits for parallel work touching the same files,
2. show uncommitted files, and
3. show the count of unpushed commits when an upstream exists.

Flag conflicts and wait for direction. Never commit, push, discard, or reconcile work without explicit approval. Outside git, skip this step.

### 6. Confirm the handoff

Report what was logged, which state files changed, and the top next action. Mention any conflict or repository work still awaiting a decision.
