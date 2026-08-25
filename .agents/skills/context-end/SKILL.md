---
name: context-end
description: Close a workspace session by reviewing a proposed summary, recording approved outcomes, updating state and decisions, and checking repository safety. Use only when the user explicitly asks to end, close, or hand off the current session.
---

# End a workspace session

Leave durable, reviewable state for the next session.

## Procedure

### 1. Draft before writing

Determine today's local date and time. Extract completed work, durable decisions
and rationale, meaningful rejected alternatives, priority or thread changes,
blockers, open work, and next actions. Present the draft and obtain confirmation
before creating a proposal.

### 2. Build the deterministic proposal

Create a reviewed JSON payload under `.context-os/inputs/` with:

- `what_happened`: approved factual strings;
- `decisions`: durable objects containing `decision`, `rationale`, and optional
  `rejected_alternatives`;
- `next_time`: approved open-work strings; and
- optional complete desired Markdown for `current_markdown`,
  `blockers_markdown`, or `weekly_priorities_markdown`, only when that state
  materially changed.

Run `bash scripts/contextos.sh propose end --input <payload.json>`. The kernel owns
session append behavior, decision rows, dates, exact paths, the single
`Last Updated` line, and same-day history. Present every returned diff and its
proposal digest. The digest binds the exact content but does not authenticate a
human approver; rely on the host permission boundary for explicit confirmation.

### 3. Apply only the approved proposal

After explicit approval of that exact diff, run:

```text
bash scripts/contextos.sh apply <proposal> --confirm <digest> --runtime <active-runtime>
```

The kernel must refuse altered proposals, changed targets, path escapes, or a
concurrent apply. Never bypass those checks or edit lifecycle state directly.

### 4. Check repository state

If this is a git repository, inspect recent commits for parallel work touching
the same files, show uncommitted files, and show the count of unpushed commits
when an upstream exists. Flag conflicts and wait for direction. Never commit,
push, discard, or reconcile without explicit approval. Outside git, skip this.

### 5. Confirm the handoff

Report the receipt path, what was logged, changed state files, and the top next
action. Mention any conflict or repository work still awaiting a decision.
