---
name: context-update
description: Save a brief mid-session checkpoint to this workspace and update current state only when a priority or open thread changed. Use only when the user explicitly asks to checkpoint or save current progress.
---

# Checkpoint a workspace session

## Execution roots (required)

Use the exact roots supplied by the host attachment: `KernelRoot` is the trusted
Context OS product containing `scripts/contextos.sh`; `ContextRoot` owns tracked
identity and lifecycle state; and `WorkingRoot` is the ordinary application.
For an external attachment, require all three exact absolute paths and run:

```text
bash <KernelRoot>/scripts/contextos.sh --context-root <ContextRoot> --working-root <WorkingRoot> <command>
```

Do not search upward or infer a root from cwd or the skill installation. The
kernel must validate the ignored local binding before strict lifecycle work. A
missing, moved, stale, linked, nested, or mismatched binding stops the workflow;
use the explicit `project rebind` proposal after a legitimate move. ContextRoot
owns all lifecycle writes. WorkingRoot is read-only evidence. The colocated
`bash scripts/contextos.sh <command>` compatibility form remains valid.

Throughout this procedure, resolve every context and local-artifact path beneath
`ContextRoot`. In split mode, spell local paths as absolute `<ContextRoot>/...`
paths and invoke every lifecycle command through the absolute KernelRoot wrapper
with both exact role options. In colocated mode, run the relative compatibility
commands from the colocated root.

Save continuity with minimal churn through the deterministic lifecycle kernel.

## Procedure

1. Identify what was completed, any decisions, and whether a priority or open
   thread changed. Do not invent progress.
2. Create a reviewed JSON payload under
   `<ContextRoot>/.context-os/inputs/` with `progress` as one to three factual
   strings. Include `current_markdown` only when a priority shifted, a thread
   opened or closed, or a tracked task completed. When present, it is the
   complete desired ContextRoot `current.md` before the kernel advances its date
   and history. Preserve unrelated content and ordering.
3. Run exactly one matching form:

   ```text
   split:     bash <KernelRoot>/scripts/contextos.sh --context-root <ContextRoot> --working-root <WorkingRoot> propose update --input <ContextRoot>/.context-os/inputs/<payload.json>
   colocated: bash scripts/contextos.sh propose update --input .context-os/inputs/<payload.json>
   ```

   The kernel owns session append behavior, dates, the single `Last Updated`
   line, and same-day history. Present every returned diff and the exact
   proposal digest. The digest binds the exact content but does not authenticate
   a human approver; rely on the host permission boundary for confirmation.
4. Wait for explicit approval of that exact proposal. Then run:

   ```text
   split:     bash <KernelRoot>/scripts/contextos.sh --context-root <ContextRoot> --working-root <WorkingRoot> apply <ContextRoot>/<proposal> --confirm <digest> --runtime <active-runtime>
   colocated: bash scripts/contextos.sh apply <proposal> --confirm <digest> --runtime <active-runtime>
   ```

   If any target changed after proposal creation, create and review a new
   proposal. Never bypass stale-write, path-containment, or locking checks.
5. If a durable decision was made, mention that `$end` can add it to the
   decision log; do not expand a checkpoint into a full close workflow.
6. Report the receipt path and changed files. Do not edit lifecycle state
   directly, commit, push, or touch files only to refresh timestamps.
