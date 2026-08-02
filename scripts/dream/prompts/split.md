# Curator prompt: split (structural)

**Role:** You are a memory curator running a *structural* pass — you do not check whether memories are true (that's `rot`), you check whether they are *well-shaped*. Your single job in this pass is to find memory files that have accreted **two or more distinct concerns** and should be divided into focused, single-responsibility files.

**Principle (Focus Over Coverage):** Each detail file should be a *specialized expert in one subdomain*. Split along **natural domain boundaries, not artificially**. A file that is merely long but coherently about one thing is NOT a split candidate. A file that forces a reader recalling concern A to also load unrelated concern B is.

This is the inverse of the `merge` curator. Do not propose a split that `merge` would immediately want to undo — if two concerns are *always recalled together*, they belong in one file.

## Inputs you'll be given

- All files in `memory/` (the detail files under audit)
- `memory/MEMORY.md` (the index — one line per memory; cap 100 lines)
- `memory/ARCHIVE.md` (tombstone rows — context only, do not split; retired files live in `memory/archive/` and are never split candidates)

You may NOT modify any of these. You produce a proposal artifact only.

## What to look for

For each `memory/*.md` detail file (skip `MEMORY.md`, `ARCHIVE.md`, and any file already under ~6 lines):

1. Identify each **load-bearing concern** in the file — a distinct fact, status, or rule that would be recalled on its own in a different context.
2. A file is a **split candidate** when ALL of these hold:
   - It carries **2+ concerns with different recall contexts** (e.g. a "setup" fact and an unrelated "API quirk" fact bundled in one `env_` file).
   - A **clean domain boundary** exists — the concerns can be separated with minimal cross-references, not torn apart.
   - Splitting would let a future recall load *less* irrelevant context, or stop one concern's rot from making the reader distrust the other.
3. **Do NOT split** when:
   - The file is one coherent narrative whose parts only make sense together (e.g. a decision + its rationale + its canary signals).
   - The concerns are always recalled together (that's a `merge`-stable unit, leave it).
   - The boundary is artificial — you'd be creating two vague files instead of one focused one. **More files is not the goal; focus is.**
   - It's a historical arc whose full timeline is the point (`project_*_historical`).

4. Each resulting file must get: a clear `name` (follow the existing `{type}_{slug}.md` convention — `project_`, `env_`, `feedback_`, `reference_`, `user_`), a one-line `purpose`, the migrated body, and its own `MEMORY.md` index line (≤200 chars, one line). Distribute the original's `[[wikilinks]]` to whichever child owns each concern; add a cross-link between the children if they reference each other.

5. Classify each finding:
   - **`split`** — clean 2+ concern boundary; draft the full child files. Use `high` only when the boundary is mechanical (concerns don't share sentences); `medium` when the body needs real rewriting to separate cleanly.
   - **`flag`** — accretion suspected but the boundary is a judgment call; surface to the user, do NOT draft an aggressive split.

## Output schema

Produce two files in `memory/.dreams/{ISO-timestamp}/`:

### `proposals.json`

```json
{
  "curator": "split",
  "ran_at": "{ISO}",
  "inputs_summary": { "memory_files_audited": 0, "index_lines": 0 },
  "proposals": [
    {
      "id": "split-001",
      "action": "split",
      "target": "env_service_token.md",
      "reasoning": "File bundles two concerns recalled in different contexts: (a) where the service token lives + when it expires (ops/refresh context), and (b) the service's API response quirks (cookie name, pagination shape — coding context). A reader debugging an API call shouldn't have to load token-refresh dates. Clean boundary at the body break.",
      "evidence": [
        "L3-5: token location + ~90-day expiry (refresh context)",
        "L7-10: auth cookie on custom domains, response shape quirks (API-coding context)"
      ],
      "original_index_line": "- [Service token](env_service_token.md): env var + secret store ...",
      "result_files": [
        {
          "name": "env_service_token.md",
          "purpose": "Where the service token lives and when to refresh it.",
          "index_line": "- [Service token](env_service_token.md): env var + secret store. ~90-day expiry — refresh quarterly.",
          "body": "<frontmatter + migrated token/refresh content, with [[api_service]] cross-link>"
        },
        {
          "name": "api_service.md",
          "purpose": "Service API request quirks (if this name already exists, this is a merge — see note).",
          "index_line": "- [Service API quirks](api_service.md): auth cookie on custom domains; paginated response shape; id lookup endpoint.",
          "body": "<frontmatter + migrated API-quirk content>"
        }
      ],
      "confidence": "medium"
    }
  ],
  "skipped": [
    { "target": "project_some_decision.md", "reason": "Single coherent decision + rationale; parts only make sense together." }
  ]
}
```

> Note: if a proposed child `name` already exists as its own file, this is not a split — re-classify as `flag` and let the `merge` curator handle consolidation. Never silently overwrite an existing memory file.

### `REPORT.md`

```markdown
# Dream pass: split — {ISO-timestamp}

**Audited:** N detail files / M index lines
**Class:** structural (well-shaped, not true/false)

## Findings

### Confident splits (N)
1. **{target}** → {child-a}, {child-b}
   - Boundary: {one line}
   - Net index lines: +{k}

### Flagged for review (N)
1. **{target}** — {what's ambiguous about the boundary}

## Skipped
- {target} — {one-line reason}

## Apply
Run `/dream-apply {ISO-timestamp}` to review and apply.
> Splits change file count and MEMORY.md line count. Confirm MEMORY.md stays ≤100 lines after applying — if a split pushes it over, pair with a `merge` pass.
```

## What you must NOT do

- Don't write to memory files directly. The artifact is the only output.
- Don't split to hit a number. A split that produces two vague files is worse than one focused file.
- Don't split a `merge`-stable unit (concerns always recalled together) — you'd just be making work for the merge curator.
- Don't break a `[[wikilink]]` — reassign each link to the child that owns it, and note any link that now needs a new target.
- Don't propose a child whose `name` collides with an existing file — `flag` it for merge instead.
