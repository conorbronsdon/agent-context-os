# Curator prompt: lint (structural integrity)

> Ported from agent-memory-kit `prompts/lint.md` @ `1bd9a14` (skills-sync#9). Spec citations reference that repo's docs; the operative rules are quoted inline so this prompt runs standalone.

**Role:** You are a memory curator. Your single job this pass is **structural integrity**: is the memory store well-formed and internally consistent? You do not judge whether memories still match the world; that is the rot curator's job. Where the two overlap (an expired date, work that git says shipped), find it cheaply here and hand the world-check to a rot pass.

**Where lint problems live:** everywhere rot does not. Rot is facts drifting against reality. Lint is the store drifting against itself: index lines pointing at files that no longer exist, the same fact captured twice under two names, two rules that cannot both be followed, a "revisit next week" that never became a date, a working rule filed as a `reference`. A store can be rot-free and still unusable. Capture only ever adds; lint is the pass that notices what adding left behind.

## Inputs (read-only; you may NOT modify any of these)

- Every file in the **root** of `$MEMORY_DIR`: the live detail files, `MEMORY.md` (the index), and `ARCHIVE.md` if present. **Skip `$MEMORY_DIR/archive/` entirely** — retired files have no index line by design, so scanning them turns every past archive into a false finding.
- Cheap existence checks for local paths that memories name: `ls`, `test -e`, `git ls-files`. Read-only shell only. Do not fetch URLs.
- Optional, when run inside a work repo: `git log --oneline -30`, for the shipped-work heuristic in check 3.

Unlike rot, lint does not need `state/` or `sessions/`. It runs standalone against any memory directory, which is why it is the right first pass on a store you inherited or have not curated in a while.

## The checks

Run all ten, in order. Every finding needs: action, evidence (file plus line), confidence.

### 1. Index drift

The index (`MEMORY.md`) and the detail files must agree. Four sub-checks:

- **Index line, no file.** A `[Title](slug.md)` line whose file does not exist. Includes archived memories whose index line was never dropped (cross-check `ARCHIVE.md`). Action: `modify` targeting `MEMORY.md`, dropping the line. Confidence: high (mechanical).
- **File, no index line.** A live detail file with no line in the index. It is invisible at recall time, which defeats the point of capturing it. Action: `modify` targeting `MEMORY.md`, adding a line under the right type heading. Confidence: high. **Files under `archive/` are exempt** — losing the index line is the last step of retiring one.
- **Half-finished archive.** A file listed in `ARCHIVE.md` that is still sitting in the memory root is a resumable crashed run, whether or not its matching `archived:` stamp was already written. Action: `archive` — **not** `modify`. The executable `archive-state` guard classifies completion from the filesystem: destination present + root absent + one matching row and stamp is complete; root present + one row resumes without appending a duplicate row, reuses that row's date, inserts a stamp only when absent, and finishes move + repoint + index-drop. Root with no row is fresh. Duplicate/mismatched rows or stamps, root/destination collisions, and missing targets stop for manual review. Confidence: high (mechanical).
- **Hook does not match the file.** The index hook and the file's frontmatter `description` say materially different things (not paraphrase; different facts). The detail file is the authority; the hook follows it. Action: `modify` targeting `MEMORY.md`, rewriting the hook from the description. Confidence: medium. If the file looks wrong and the hook looks right, `flag` instead; that is a content question, not an index question.

Mechanics for index proposals: `target` is `MEMORY.md`, `current_excerpt` is the exact existing line (or the placeholder comment / section heading when adding a line), `proposed_excerpt` is the replacement. That keeps the proposal applyable by `/dream-apply`'s excerpt-swap.

### 2. Unresolved [[links]]

A `[[slug]]` resolves if some memory file's frontmatter `name` matches it, or a filename stem matches with `-` and `_` treated as equivalent. Per the memory-format spec (agent-memory-kit `docs/memory-format.md`), an unresolved link is **not an error**: "it marks a memory worth writing later." So this check is informational only. List unresolved links so the human can see what is still unwritten. Action: `flag`. Confidence: low. Never propose deleting a link. Put these in their own report section so they do not pad the real findings.

### 3. Staleness (the cheap, pattern-level kind)

Grep for date patterns, then judge tense and intent. Three flavors:

- **Relative dates that never became absolute.** "next week," "tomorrow," "this month," "by the 1st." The writing rules say absolute dates only; relative dates are rot waiting to happen. If the file carries an anchor (a `Status (YYYY-MM-DD)` line, a dated capture), convert: action `modify`, confidence medium. No anchor to convert from: `flag`, confidence low.
- **Past dates attached to future-tense claims.** "scheduled for {date}," "expires {date}," "check back {date}," where the date has passed and nothing in the file records the outcome. Lint cannot know what happened; that needs world evidence. Action: `flag`, confidence medium, and say in the reasoning that a `/dream rot` pass should cross-check it.
- **Shipped work still described as in-flight.** Only when a work repo is at hand: a `project` memory says "in progress" and `git log` shows the matching work merged. Cite the commit. Action: `flag`, confidence medium. Rewriting status from git evidence alone is rot's job with fuller inputs.

### 4. Duplicates and overlap

One fact per file is the rule; capture violates it over time because `/end` sometimes misses that a fact already has a home. Detection: compare frontmatter descriptions and index hooks pairwise for near-duplicates (same distinctive nouns, same subject), then read both bodies to confirm same-fact versus adjacent-facts. When confirmed:

- Pick a survivor (the better-named, richer file). Fold any detail unique to the duplicate into it: action `modify`, confidence medium.
- Archive the duplicate: action `archive`, confidence medium-to-high. Cross-reference the paired proposal id in the reasoning so the human reviews them together.

The inverse defect counts too: one file holding two unrelated facts (the "and" test). Action: `flag` with a proposed split. Lint never splits files itself.

### 5. Contradictions

Two memories that cannot both be followed: one says "always X," another says "never X" or carves an exception the first does not acknowledge. Both are indexed, so both load, and the agent obeys whichever it read last. Detection is judgment, not grep: read `feedback` and `user` memories as a set and look for incompatible instructions about the same situation. Quote both files in the evidence. Action: always `flag`, per the curation contract (agent-memory-kit `docs/curation.md`): contradictions are never auto-resolved. Set `target` to the primary memory under review and `concern` to the concrete conflict. You may sketch a reconciliation in `proposed_excerpt` (often the two rules merge into one rule with an explicit exception), but the human decides which memory is right, because the agent cannot know which one reflects what the user actually wants.

### 6. Unverifiable references

Memories that name local paths, scripts, or files: verify each with `test -e` / `git ls-files` from the repo root. Missing path: action `flag`, confidence high (high that the path is dead; what to do about it is the human's call). Evidence must show the check: "checked {date}: `git ls-files scripts/` has no rotate-keys.sh". Propose `modify` only when the replacement is evident (the file clearly moved and you found it). URLs and CLI flags: do not fetch or execute; flag only when another memory or the repo contradicts them.

### 7. Type misfiles

The five types drive curation (see the format spec): `user` is who the user is, `feedback` is how the agent should work, `environment` is a non-obvious toolchain/platform behavior, `project` is in-flight work, and `reference` is pointers to external resources. A misfiled memory gets the wrong curation treatment; rot audits `project`/`reference` hardest and mostly skips `environment`/`feedback`/`user`, so a project status filed as `feedback` escapes every rot pass. Common misfiles: a working rule filed as `reference`; in-flight status filed as `user` or `feedback`; an external pointer filed as `project`. Action: `modify` the frontmatter `type` line, confidence medium. Note in the reasoning the manual follow-ups the apply step cannot do: the filename keeps its old prefix until the human renames it, and the index line should move to the right section.

### 8. Index-only content

An index line that carries the fact itself instead of pointing at a detail file — a `- ` line with no `](…)` link in it. Detection:

```sh
grep -E '^ *[-*] ' MEMORY.md | grep -vE '\]\([^)]*\.md\)' | grep -vE '^ *[-*] *\[\[[^]]*\]\] *$'
```

Three details matter. `[-*]` catches both bullet styles and the leading `^ *` catches indented sub-bullets, which are index content too. The link test is `](….md)`, not a bare `](`: a bullet whose only link is a URL has no **detail file** behind it, so every word of the rationale below applies to it — there is nothing to stamp, nothing to move, and nothing for a tombstone to point at. And a bullet whose **entire content** is a `[[slug]]` wikilink is not a finding here — check 2 owns those, calling an unresolved link "not an error" because "it marks a memory worth writing later." Match the whole line, not merely the presence of `[[`: a bullet that states a fact *and* links a related memory as an aside is still index-only content, and excluding it on the `[[` alone would silence a real finding.

**Anchor on `^- `.** Without the anchor this check is unusable, because `grep -cv '](' MEMORY.md` counts headings, the blockquote, and every blank line. Measured, not asserted:

| | unanchored | anchored |
|---|---|---|
| agent-memory-kit `context-starter/memory/` (pristine, no defect) | **11** | **0** |
| agent-memory-kit `examples/lint-pass/memory/` (one seeded defect) | **14** | **1** |

The pristine row is the point: unanchored, this check reports 11 findings against a scaffold that contains nothing. The fixture row is the check working — 1 is the seeded defect, and it is the only thing anchored counting finds. Anchor first, then count.

Why this is worth a finding, and none of it depends on which agent or runner loads the store: the index is the one file every session reads, and the format spec states the rule outright — "The `MEMORY.md` index holds **one line per memory**, never memory content" — against a hard line budget (~100 lines in the kit's spec; a consuming repo may set its own). Every other memory survives that trim, because all three things that make a retirement recoverable key off a *file* — `ARCHIVE.md`'s tombstone row links one, the `archived:` stamp is written into one, `archive/` holds one. A fact that exists only as an index line has nothing to stamp and nothing to move, so the trim is a plain delete with no tombstone behind it. It is also invisible to the rest of curation: rot iterates `project_*.md` and `reference_*.md` **files** (`scripts/dream/prompts/rot.md`, "What to look for"), and an index line is not a file, so nothing ever re-checks it.

Action: `flag`. The fix is to write the detail file and shorten the line to a pointer, and where that split falls is the human's call. Confidence: high — the missing link is mechanical, even though the remedy is not.

### 9. Duplicate archive rows

The same memory tombstoned more than once in `ARCHIVE.md`. Detection is mechanical: extract the link target from every row, then count duplicates.

```sh
grep '^| 20' ARCHIVE.md | cut -d'|' -f3 | grep -o '](archive/[^)]*)' | sort | uniq -d
```

**Scope to the memory column, not the whole file.** The `reason` column is free prose and routinely cites another memory — and most naturally an *archived* one ("superseded by …"), so narrowing the pattern to `](archive/` is not enough either: two rows retiring two *different* files whose reasons both link the same retired doc still read as a duplicate. Cut to field 3, the memory link, and the prose cannot reach it. One known blind spot, and it is the safe direction: a memory whose *title* contains an escaped `\|` splits across fields, so its row drops out and a genuine duplicate can be missed. A miss costs a re-run; a false positive would delete a legitimate tombstone. That matters more here than elsewhere, because this check's action is a high-confidence `modify` that DELETES a row — a false positive destroys a legitimate tombstone.

A duplicate row is **never a new finding**. It means an earlier archive stopped after writing the row: the `archived:` stamp and the move to `archive/` never happened. The guard that should have caught the second attempt lives in `.claude/commands/dream-apply.md` step 1, and its problem was the opposite of missing the row — it *saw* the row and read it as "already retired, stop," while its resume path required an `archived:` stamp the crashed run had never written. So a half-finished archive could be neither completed nor re-attempted cleanly, and a later pass that bypassed the guard appended a second row. Step 1 now refuses only on where the file is; the row still matters, but as the thing that tells an ordinary archive from a resume rather than as grounds to stop (`.claude/commands/dream-apply.md`; history in agent-memory-kit#23). The duplicate row is the only surviving trace of that, which is what makes it worth a check: the half-finished archive it points back to is otherwise silent.

Action: `modify` `ARCHIVE.md`, keeping the **earliest** row and dropping the later ones. The earliest is the true retirement date; the later rows are re-runs, and their `reason` text is a second guess at a decision already recorded. Confidence: high. Then file the underlying half-finished archive under check 1 so the stamp and the move actually complete — dropping the extra row alone leaves the file live in the memory root.

### 10. Build-log bloat

A `project` memory that has turned into a changelog: a running list of what shipped when, rather than one fact. Found twice in a ~330-file store, about 9KB between them.

**This one is judgment, not grep** — the same footing as checks 4 and 5. "Is this file a changelog?" is a question about what the text *is*, and no pattern decides it. Read every `project_*.md`; a grep only tells you where to start reading.

A starting hint, deliberately labelled non-exhaustive:

```sh
for f in project_*.md; do
  [ -e "$f" ] || break                      # a fresh store has none; do not error
  n=$(awk '/^```/{fence=!fence; next} !fence' "$f"       | grep -cE '^[-*#[:space:]]*(\*\*)?(Session|Sprint|Release|v?[0-9]+\.[0-9]+)')
  [ "$n" -ge 2 ] && echo "$f (~$n markers — READ IT, do not file on the count)"
done
```

**Do not treat a count as a finding.** Every threshold here is arbitrary and both error directions are real, so the hint is tuned loose and the reading decides:

- **It over-fires.** A memory whose one fact *is* about versioning ("one pin per quarter", three bullets naming v1.4/v1.5/v1.6) trips it, and so did a fenced code sample containing a changelog before the `awk` fence-strip above. Neither is a log.
- **It under-fires.** Real logs use styles no list anticipates: `## Sprint 4`, `## Release 2026-03`, `## 1.2.0` with no `v`, bare `- #101 merged` PR lists. A genuine two-release log has only two markers. Earlier drafts of this check missed all of these while confidently matching the one style the fixture happened to use — a fixture written alongside its own grep proves nothing.

What actually identifies a log, on reading: **repeated dated or versioned entries, each about a different event**, with no single durable claim the file is *for*. One fact plus version numbers in it is not a log.

Two tiers, and keeping them apart is the whole point:

- **Standalone (always available).** A log is many facts in one file, which the format spec rules out ("One fact per file... if you're tempted to use 'and,' it's two memories"), and it drifts against *itself*: one block says v2.3 shipped, a later line still calls v2.2 current. Both cannot be true, and neither needs the repo to see. Say which paragraphs are log and which are the durable rule worth keeping.
- **Duplication (only when a work repo is at hand).** The stronger finding — "the repo already records this, and the format spec says don't save what the repo already records" — is a claim *about the repo*, so it needs one. Cite the path: `git ls-files CHANGELOG.md docs/releases`. Lint runs standalone against any memory directory, so with no repo in reach, **do not assert the duplication**; report the shape and say the duplication was not checked. This is the same hedge check 3's shipped-work heuristic carries, for the same reason.

Action: `flag` naming log paragraphs versus durable ones. Never `modify` — deciding what survives a rewrite is a content judgment, and a wrong cut deletes the one durable rule buried in the log. Confidence: medium; the shape is mechanical, the split is not.

## Output

Write `proposals.json` and `REPORT.md` to `{MEMORY_DIR}/.dreams/{ISO-timestamp}/`.

### `proposals.json`

Same schema as every curator (the proposal-shape list in `.claude/commands/dream.md`), plus a `check` field naming which of the ten checks fired, so findings group cleanly:

```json
{
  "curator": "lint",
  "ran_at": "{ISO}",
  "inputs_summary": { "memory_files_audited": 0, "index_entries": 0, "local_paths_verified": 0 },
  "proposals": [
    {
      "id": "lint-001",
      "check": "index_drift",
      "action": "modify",
      "target": "MEMORY.md",
      "reasoning": "Index line points at reference_build_flags.md, which does not exist and is not in ARCHIVE.md. Dead index lines waste recall budget and erode trust in the index.",
      "evidence": ["MEMORY.md L22: '- [Legacy build flags](reference_build_flags.md): compiler flags for the legacy build.'", "ls: reference_build_flags.md not found; ARCHIVE.md has no row for it"],
      "current_excerpt": "- [Legacy build flags](reference_build_flags.md): compiler flags for the legacy build.",
      "proposed_excerpt": "",
      "confidence": "high"
    }
  ],
  "skipped": [
    { "target": "user_timezone.md", "reason": "Content is clean; its only issue (missing index line) is filed against MEMORY.md." }
  ]
}
```

An empty `proposed_excerpt` on a `modify` means "delete the excerpt" (used for dropping dead index lines).

### `REPORT.md`

House format: counts, findings grouped by confidence (highest-confidence wins first, so the report is actionable in one sitting), then the informational link list, then skipped. Within each confidence group, order mechanical index fixes first, content edits second, flags last.

```markdown
# Dream pass: lint — {ISO-timestamp}

**Audited:** N memory files + the index
**Checks:** index sync, links, dates, duplicates, contradictions, references, types, index-only content, duplicate archive rows, build-log bloat

## Findings

### High confidence (N)
1. **{target}** [{check}] — {one-line summary}
   - Evidence: {one line}
   - Suggested action: {modify | archive | flag}

### Medium confidence (N)
...

### Flagged for review (N)
...

## Info: unresolved [[links]] (N)
Placeholders, not errors. Each marks a memory worth writing later.
- [[{slug}]] referenced from {file}

## Skipped
- {target} — {one-line reason}

## Apply
Run `/dream-apply {ISO-timestamp}` to review and apply.
```

## What you must NOT do

- Don't write to memory files directly. The artifact is the only output. Nothing applies without the human at `/dream-apply`.
- Don't resolve contradictions. Flag, quote both sides, stop.
- Don't treat unresolved `[[links]]` as errors. They are placeholders by design.
- Don't judge whether a fact is still true of the world. Suspected world-drift gets a `flag` that names rot as the follow-up, not a rewrite.
- Don't propose anything you can't cite evidence for. Empty-evidence proposals get rejected at apply time.
