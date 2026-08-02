---
name: dream-apply
description: Walk a dream proposal artifact, review each item, apply accepted ones to memory and commit.
allowed-tools: Read, Write, Edit, Bash, AskUserQuestion
x-source: skills-sync/commands/dream-apply.md
x-source-version: 2d8b897
---

# /dream-apply — review + apply a curator pass

Substrate background: `docs/dream-architecture.md`.

## Usage

```
/dream-apply {ISO-timestamp}
/dream-apply latest        # auto-resolves to most recent .dreams/ subdir
```

## Steps

### 1. Resolve the dream dir

```
PROJECT_KEY=$(pwd | sed 's|[:\\/]|-|g')
MEMORY_DIR="$HOME/.claude/projects/$PROJECT_KEY/memory"
DREAMS_ROOT="$MEMORY_DIR/.dreams"
```

If `$ARGUMENTS` is `latest` or empty: pick the most recent subdir by name (ISO timestamps sort lexically). Otherwise treat `$ARGUMENTS` as the ISO timestamp.

If the dir doesn't exist, list available dreams and stop.

### 2. Load the proposal artifact

Read `$DREAMS_ROOT/$TS/proposals.json` and `$DREAMS_ROOT/$TS/REPORT.md`. If either is missing, stop with an error.

### 3. Show the report header

Print the top of REPORT.md (header + counts). Don't dump the whole thing — the user already has it if they want the full text.

### 4. Walk each proposal

For each `proposals[i]`:

a. Print a header, then the fields relevant to the action:
   ```
   ─── Proposal {id} ({i+1}/{N}) ───
   Action: {action}    Confidence: {confidence}
   Reasoning: {reasoning}
   Evidence:
     - {evidence[0]}
     - {evidence[1]}
   ```
   - **`modify`** (content): `Target: {target}` then `Current:` / `Proposed:` excerpts.
   - **`archive`**: `Target: {target}` then the one-line archive reason.
   - **`merge`** (structural): `Absorb: {targets}` → `Survivor: {survivor}` (net index lines: {net_index_lines}), then the `merged_body` and the `index_changes`.
   - **`split`** (structural): `Target: {target}` → `Into: {result_files[*].name}`, then each child's `purpose` + `index_line` and its `body`.
   - **`add` / `flag`**: target + proposed content (add) or the flagged concern (flag).

b. Ask via `AskUserQuestion`:
   - Question: "Apply this proposal?"
   - Options: `Accept` / `Reject` / `Edit then accept` / `Skip rest`
   - For `high` confidence: order options Accept-first.
   - For `medium`: order Reject-first (forces reading).
   - For `flag`: order Reject-first; treat Accept as opt-in only.

c. On `Accept`: apply the change.
   - For `modify` action: use Edit tool on `$MEMORY_DIR/{target}`, replacing `current_excerpt` with `proposed_excerpt`.
   - For `archive` action, all five steps — an archive that stops early leaves the file reading as live:
     1. **Check it isn't already archived.** `grep "^archived:" $MEMORY_DIR/{target}` and grep `$MEMORY_DIR/ARCHIVE.md` for the filename. If either hits, stop and report — re-archiving an already-retired file is the symptom of a previous archive skipping steps 3-4, not a new finding.
     2. Append a row to `$MEMORY_DIR/ARCHIVE.md`: `| {today} | [{target}](archive/{target}) | {one-line reason} |`.
     3. **Stamp the file**: insert `archived: {today}` as the last line of its frontmatter block. This is what stops a future session reading it as a live memory.
     4. **Move it**: `git mv $MEMORY_DIR/{target} $MEMORY_DIR/archive/{target}`, then rewrite every inbound reference in the *live* set — `]({slug}.md)` → `](archive/{slug}.md)`, and `[[{slug}]]` → `[{slug}](archive/{slug}.md)` so wikilinks still resolve across the directory boundary. Grep the live files for the slug; don't assume the proposal enumerated them.
     5. Remove the corresponding line from `$MEMORY_DIR/MEMORY.md` — **unless** the reference is a sub-link inside another entry's line, in which case just add the `archive/` prefix. An archived file cited as evidence for a still-live rule is a legitimate reference.

     **Never `rm` an archived file.** It stays readable under `archive/` for on-demand recall; only `merge`/`split` remove files, and only because their content moved into a survivor.

     ⚠️ **Before archiving, count how many live memories link to the target.** Heavy inbound linkage is evidence the file is still load-bearing — re-read its *current body* against the archive rationale before proceeding. A file archived on a premise that has since gone stale, while live memories still depend on it, is a worse outcome than one left live too long.
   - For `add` action (pattern curator): create new memory file with proposed content, add an index line to `$MEMORY_DIR/MEMORY.md`.
   - For `merge` action (structural):
     1. Write the survivor: if `survivor` matches an existing file in `targets`, Edit/overwrite it with `merged_body`; if it's a new name, Write `$MEMORY_DIR/{survivor}`.
     2. For each absorbed file in `targets` that is **not** the survivor: `git rm` it (content now lives in the survivor; the file stays recoverable from memory git history), and append its tombstone line from `archive_tombstones` to `$MEMORY_DIR/ARCHIVE.md`.
     3. Apply `index_changes` to `$MEMORY_DIR/MEMORY.md`: remove each line in `index_changes.remove`, add `index_changes.add`.
     4. Redirect dangling `[[wikilinks]]`: for any link the proposal flagged as pointing at an absorbed file, Edit it to point at the survivor. If the proposal didn't enumerate them, grep `$MEMORY_DIR` for the absorbed slugs and fix what you find.
   - For `split` action (structural):
     1. For each entry in `result_files`: Write `$MEMORY_DIR/{name}` with its `body`. If a child's `name` equals `target`, overwrite the original in place.
     2. If `target` is **not** among the `result_files` names, `git rm` it (content redistributed; recoverable from history) **and append a tombstone row to `$MEMORY_DIR/ARCHIVE.md`** naming the children it split into. Never remove a memory file without a tombstone — a silent deletion is unrecoverable except by git archaeology, and any live file still linking the old slug is left pointing at nothing. Then grep the live set for the removed slug and repoint each hit at whichever child now carries that fact; if none does, de-link it but keep the sentence.
     3. Apply index changes to `$MEMORY_DIR/MEMORY.md`: remove `original_index_line`, add each child's `index_line`.
   - For `flag` action: write nothing — flags are just surfacing.

   After any `merge`/`split`/`add`, check `wc -l $MEMORY_DIR/MEMORY.md`. If it now exceeds 100 lines, tell the user and suggest a follow-up `/dream merge` pass.

d. On `Edit then accept`: open the proposed content for inline edit (use `AskUserQuestion` with an "Other" textarea option), then apply the edited version.

e. On `Reject`: skip, log to `applied.json` as `rejected`.

f. On `Skip rest`: break the loop, log remaining as `deferred`.

### 5. Write `applied.json` to the dream dir

```json
{
  "applied_at": "{ISO}",
  "decisions": [
    {"id": "rot-001", "decision": "accepted"},
    {"id": "rot-002", "decision": "rejected"},
    {"id": "rot-003", "decision": "edited", "edited_excerpt": "..."}
  ]
}
```

### 6. Commit to memory git

```
cd "$MEMORY_DIR"
git add -A
git commit -m "dream-apply($TS): N accepted / M rejected / K deferred"
```

If no proposals were accepted, still commit `applied.json` so the audit trail is complete.

### 7. Final summary

```
Dream apply complete: {TS}
Accepted: N    Rejected: M    Edited: K    Deferred: L
Memory git HEAD: {short-sha}    Files changed: {count}

Reverting this pass: cd <memory dir> && git revert HEAD
```

## Safety rules

- Never push memory git anywhere. Local-only. If a remote has been added, refuse to apply and ask the user to remove it.
- Never accept a proposal with empty `evidence`. Reject + warn that the curator violated the schema.
- If applying a `modify` and the `current_excerpt` doesn't match the file (because memory was edited between dream + apply), Edit tool will error. Surface the conflict, ask the user to resolve manually.
- Structural ops (`merge`/`split`) use `git rm`, never destructive deletion — absorbed/split-away content stays in memory git history, so a bad apply is one `git revert` away.
- Don't auto-apply anything. Every proposal goes through review.
