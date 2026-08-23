---
name: context-update
description: Save a brief mid-session checkpoint to this workspace and update current state only when a priority or open thread changed. Use only when the user explicitly asks to checkpoint or save current progress.
---

# Checkpoint a workspace session

Save continuity with minimal churn through the deterministic lifecycle kernel.

## Procedure

1. Identify what was completed, any decisions, and whether a priority or open
   thread changed. Do not invent progress.
2. Create a reviewed JSON payload under `.context-os/inputs/` with `progress`
   as one to three factual strings. Include `current_markdown` only when a
   priority shifted, a thread opened or closed, or a tracked task completed.
   When present, it is the complete desired `current.md` before the kernel
   advances its date and history. Preserve unrelated content and ordering.
3. Run:

   ```text
   python3 -m contextos propose update --input <payload.json>
   ```

   The kernel owns session append behavior, dates, the single `Last Updated`
   line, and same-day history. Present every returned diff and the exact
   proposal digest. The digest binds the exact content but does not authenticate
   a human approver; rely on the host permission boundary for confirmation.
4. Wait for explicit approval of that exact proposal. Then run:

   ```text
   python3 -m contextos apply <proposal> --confirm <digest> --runtime <active-runtime>
   ```

   If any target changed after proposal creation, create and review a new
   proposal. Never bypass stale-write, path-containment, or locking checks.
5. If a durable decision was made, mention that `$end` can add it to the
   decision log; do not expand a checkpoint into a full close workflow.
6. Report the receipt path and changed files. Do not edit lifecycle state
   directly, commit, push, or touch files only to refresh timestamps.
