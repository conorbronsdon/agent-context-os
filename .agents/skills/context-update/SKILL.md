---
name: context-update
description: Save a brief mid-session checkpoint to this workspace and update current state only when a priority or open thread changed. Use only when the user explicitly asks to checkpoint or save current progress.
---

# Checkpoint a workspace session

## Execution root (required)

Before reading or writing repository content or running a lifecycle command,
establish the exact repository working directory supplied by the host for this
invocation. Accept that directory as the lifecycle execution root only when it
contains both `AGENTS.md` and `scripts/contextos.sh`. Do not substitute the
process or tool working directory, an agent/private workspace, the skill install
location, or any parent or ancestor discovered by searching upward. If the
host-supplied directory is unavailable or either marker is absent, stop and
report the problem without creating a payload or running the kernel.

Anchor every repository read and write under that exact root. Run
`scripts/contextos.sh` and repository validation with their working directory
explicitly set to that root (or use absolute paths beneath it); this includes
all `.context-os/inputs/`, proposal, receipt, state, session, and routing paths.

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
   bash scripts/contextos.sh propose update --input <payload.json>
   ```

   The kernel owns session append behavior, dates, the single `Last Updated`
   line, and same-day history. Present every returned diff and the exact
   proposal digest. The digest binds the exact content but does not authenticate
   a human approver; rely on the host permission boundary for confirmation.
4. Wait for explicit approval of that exact proposal. Then run:

   ```text
   bash scripts/contextos.sh apply <proposal> --confirm <digest> --runtime <active-runtime>
   ```

   If any target changed after proposal creation, create and review a new
   proposal. Never bypass stale-write, path-containment, or locking checks.
5. If a durable decision was made, mention that `$end` can add it to the
   decision log; do not expand a checkpoint into a full close workflow.
6. Report the receipt path and changed files. Do not edit lifecycle state
   directly, commit, push, or touch files only to refresh timestamps.
