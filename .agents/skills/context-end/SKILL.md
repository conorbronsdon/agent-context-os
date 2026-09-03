---
name: context-end
description: Close a workspace session by reviewing a proposed summary, recording approved outcomes, updating state and decisions, and checking repository safety. Use only when the user explicitly asks to end, close, or hand off the current session.
---

# End a workspace session

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

Throughout this procedure, resolve routing, state, session, proposal, receipt,
and local-artifact paths beneath `ContextRoot`. In split mode, spell local paths
as absolute `<ContextRoot>/...` paths and invoke every lifecycle command through
the absolute KernelRoot wrapper with both exact role options. In colocated mode,
run the relative compatibility commands from the colocated root.

Leave durable, reviewable state for the next session.

## Procedure

### 1. Draft before writing

Determine today's local date and time. Extract completed work, durable decisions
and rationale, meaningful rejected alternatives, priority or thread changes,
blockers, open work, and next actions. Present the draft and obtain confirmation
before creating a proposal.

### 2. Build the deterministic proposal

Create a reviewed JSON payload under `<ContextRoot>/.context-os/inputs/` with:

- `what_happened`: approved factual strings;
- `decisions`: durable objects containing `decision`, `rationale`, and optional
  `rejected_alternatives`;
- `next_time`: approved open-work strings; and
- optional complete desired Markdown for `current_markdown`,
  `blockers_markdown`, or `weekly_priorities_markdown`, only when that state
  materially changed.

Run exactly one matching form:

```text
split:     bash <KernelRoot>/scripts/contextos.sh --context-root <ContextRoot> --working-root <WorkingRoot> propose end --input <ContextRoot>/.context-os/inputs/<payload.json>
colocated: bash scripts/contextos.sh propose end --input .context-os/inputs/<payload.json>
```

The kernel owns session append behavior, decision rows, dates, exact paths, the
single `Last Updated` line, and same-day history. Present every returned diff
and its proposal digest. The digest binds the exact content but does not
authenticate a human approver; rely on the host permission boundary for
explicit confirmation.

### 3. Apply only the approved proposal

After explicit approval of that exact diff, run:

```text
split:     bash <KernelRoot>/scripts/contextos.sh --context-root <ContextRoot> --working-root <WorkingRoot> apply <ContextRoot>/<proposal> --confirm <digest> --runtime <active-runtime>
colocated: bash scripts/contextos.sh apply <proposal> --confirm <digest> --runtime <active-runtime>
```

The kernel must refuse altered proposals, changed targets, path escapes, or a
concurrent apply. Never bypass those checks or edit lifecycle state directly.

### 4. Check repository state

Inspect WorkingRoot Git history and status for application work: show recent
commits that may overlap this run, uncommitted files, and the count of unpushed
commits when an upstream exists. Inspect ContextRoot Git state separately for
the lifecycle files just changed. Do not conflate either repository's history
or status. Flag conflicts and wait for direction. Never commit, push, discard,
or reconcile without explicit approval. Outside Git, skip the corresponding
repository check.

### 5. Coordination board (when present)

In split mode, skip coordination-board operations explicitly because the CLI
rejects board commands for attachments; do not probe WorkingRoot for board
files. In colocated mode only, if `<ContextRoot>/coordination/README.md` exists,
offer—never auto-execute—to post a short board message for other runs
(`bash scripts/contextos.sh board post ...` from ContextRoot) and to release or
hand off any claims this run holds (`board release`, optionally with
`--then-claim-*`). Follow the ContextRoot board contract: no secrets or
sensitive personal data ever (git history keeps every message), durable facts
stay canonical elsewhere and are referenced with `commit:path`, and publishing
pushes to the ContextRoot remote, so it happens only with the user's approval at
the host permission boundary.

### 6. Confirm the handoff

Report the receipt path, what was logged, changed state files, and the top next
action. Mention any conflict or repository work still awaiting a decision.
