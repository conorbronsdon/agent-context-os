---
name: context-update
description: Save a brief mid-session checkpoint to this workspace and update current state only when a priority or open thread changed. Use only when the user explicitly asks to checkpoint or save current progress.
---

# Checkpoint a workspace session

Save continuity with minimal churn.

## Configuration

If `workspace.yaml` exists, use its state and sessions directories. Otherwise use `state/` and `sessions/`.

## Procedure

1. Identify what was just completed, any decisions made, and whether a priority or open thread changed.
2. Determine today's local date and time.
3. Append to `<sessions_dir>/<YYYY-MM-DD>.md`:

   ```markdown
   ## Update: <HH:MM>
   - <one to three factual progress bullets>
   ```

   Create the file with a date header when it does not exist. Never overwrite earlier entries.
4. Update `<state_dir>/current.md` only when a priority shifted, a thread opened or closed, or a tracked task completed. Preserve unrelated content and its ordering. When changing it:
   - keep exactly one `**Last Updated:**` line and set it to today's date;
   - if that line already has a real prior date, prepend a separate line containing that value under `# current.md update log` in `<state_dir>/current-log.md`; and
   - do not log a placeholder or duplicate the newest existing history entry.
5. If a durable decision was made, mention that `$context-end` can add it to the decision log; do not expand a quick checkpoint into a full close workflow.
6. Confirm in one line what was checkpointed and which files changed.

Do not invent progress or touch files solely to refresh their timestamps.
