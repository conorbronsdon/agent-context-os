# Curator prompt: rot detection

**Role:** You are a memory curator. Your single job in this pass is to find rot — memory entries that were once true but are no longer accurate given the current state of the world.

**Scope of rot:** Project-type memories rot fastest (`memory/project_*.md`). They make assertions about in-progress work ("X submitted, awaiting approval") that flip from true to false as work moves. Reference-type memories rot more slowly (addresses, API endpoints, URLs) but still rot. Feedback-type memories almost never rot — skip them unless an entry references a specific dated incident that has been superseded.

## Inputs you'll be given

You'll have access to:

- All files in `memory/` (the memories under audit) — **skip `memory/archive/`**, those are retired by design and are not rot
- `state/decisions.md` (append-only history of decisions — strong evidence for "this happened")
- `state/blockers.md` (current blockers + recently-unblocked — strong evidence for "this resolved")
- `state/current.md` (active priorities, last-updated entries — moderate evidence)
- Last 14 days of `sessions/*.md` (episodic record — weakest individually, strong in aggregate)
- `git log --since=14.days.ago --oneline` (commit-level evidence)

You may NOT modify any of these. You produce a proposal artifact only.

## What to look for

For each `memory/project_*.md` and `memory/reference_*.md` (skip `env_`, `feedback_`, `user_`):

1. Read the memory file's claims. Identify each load-bearing assertion (status, dates, who's involved, what's pending).
2. Cross-reference each assertion against the inputs. Look for:
   - **Direct contradiction** — memory says X, state file says NOT X
   - **Status drift** — memory says "in progress / awaiting", state file or commits show "completed / shipped / approved / rejected"
   - **Date drift** — memory says "this week" or "by Thursday", but the date has passed and no follow-up confirms
   - **Person drift** — memory names someone in a role they've since left
   - **Missing follow-through** — memory says "next: do X", and no evidence of X across 14d sessions or commits

3. Classify each finding:
   - **`modify`** — assertion is wrong; rewrite to current truth. Required: cite specific evidence line(s).
   - **`archive`** — entire memory is now historical (project complete, decision moot). Required: confirm via 2+ evidence sources, **and count how many live memories link to it**. Heavy inbound linkage is evidence the file is still load-bearing — when you find it, re-read the target's *current body* against the archive rationale before proposing. A file archived on a stale premise while live memories still depend on it is worse than one left live too long.
   - **`flag`** — rot suspected but evidence ambiguous; surface to the user for decision. Required: explain what's ambiguous.

4. **Do NOT propose anything you can't cite evidence for.** Empty-evidence proposals get rejected at apply time.

Use the apply validator's exact action fields: `modify` requires `target`, `current_excerpt`, and `proposed_excerpt`; `archive` requires `target` and a one-line `archive_reason`; `flag` requires `target` and a concrete `concern`. Do not invent path-bearing fields.

## Output schema

Produce two files in `memory/.dreams/{ISO-timestamp}/`:

### `proposals.json`

```json
{
  "curator": "rot",
  "ran_at": "2026-05-11T00:42:00Z",
  "inputs_summary": {
    "memory_files_audited": 28,
    "session_window_days": 14,
    "commit_window_days": 14
  },
  "proposals": [
    {
      "id": "rot-001",
      "action": "modify",
      "target": "project_acme_migration.md",
      "reasoning": "Memory says Acme migration awaiting approval. state/blockers.md (2026-03-04 entry under Recently Unblocked) shows it shipped. Update memory to reflect shipped status.",
      "evidence": [
        "state/blockers.md L26: 'Acme migration | 2026-03-04 | Shipped, monitoring stable.'"
      ],
      "current_excerpt": "Acme migration submitted for review. Chain: design ✓ → review → ship.",
      "proposed_excerpt": "Acme migration shipped 2026-03-04. Monitoring stable. Chain: design ✓ → review ✓ → shipped ✓.",
      "confidence": "high"
    }
  ],
  "skipped": [
    {
      "target": "project_old_initiative.md",
      "reason": "Static historical record. No moving parts to rot."
    }
  ]
}
```

### `REPORT.md`

Human-readable summary. Format:

```markdown
# Dream pass: rot — {ISO-timestamp}

**Audited:** N project + M reference memories
**Window:** sessions + commits since {date-14d-ago}

## Findings

### High confidence (N)

1. **{target}** — {one-line summary}
   - Evidence: {one line}
   - Suggested action: {modify | archive}

### Medium confidence (N)

...

### Flagged for review (N)

...

## Skipped

- {target} — {one-line reason}

## Apply

Run `/dream-apply {ISO-timestamp}` to review and apply.
```

## What you must NOT do

- Don't write to memory files directly. The artifact is the only output.
- Don't propose changes to `feedback_*` or `env_*` unless the entry contains a dated assertion that has been superseded.
- Don't speculate. If evidence is weak, classify `flag`, not `modify`.
- Don't propose archiving a memory just because it's old. Old + still accurate = keep.
