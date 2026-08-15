---
name: dream
description: Run a curator pass against the memory dir. Produces a proposal artifact for /dream-apply. Default curator: rot.
allowed-tools: Read, Bash, Write, Glob, Grep
x-source: skills-sync/commands/dream.md
x-source-version: 8ede26c
---

# /dream — autonomous memory curator pass

Substrate background: `docs/dream-architecture.md`. Curator prompts: `scripts/dream/prompts/`.

## Usage

```
/dream             # default curator: rot
/dream rot         # content class: memory vs. world — "is it still true?"
/dream merge       # structural class: consolidate overlapping memories + collapse index lines
/dream split       # structural class: divide multi-concern files into focused ones
/dream lint        # structural class: index/file agreement, duplicates, misfiles, half-finished archives
/dream pattern     # NOT YET BUILT (v0.4)
/dream contradiction  # NOT YET BUILT (v0.5)
/dream untapped    # NOT YET BUILT (v0.6)
/dream audit       # NOT YET BUILT (v0.7)
```

## Steps

### 1. Resolve curator name

If `$ARGUMENTS` is empty or `rot`, proceed with rot. If anything else, check whether `scripts/dream/prompts/{name}.md` exists. If not, list available curators and stop.

### 2. Resolve the memory dir + generate ISO timestamp

```
PROJECT_KEY=$(pwd | sed 's|[:\\/]|-|g')
MEMORY_DIR="$HOME/.claude/projects/$PROJECT_KEY/memory"
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
DREAM_DIR="$MEMORY_DIR/.dreams/$TS"
mkdir -p "$DREAM_DIR"
```

If `$MEMORY_DIR/.git` doesn't exist, stop and tell the user to run the first-time setup from `scripts/dream/README.md`.

### 3. Load the curator prompt

Read `scripts/dream/prompts/{curator}.md` in full. This is your role + output schema for the rest of this command.

### 4. Gather inputs (read-only)

Read the **"Inputs you'll be given"** section of the loaded curator prompt and gather *exactly* those — extra inputs dilute the pass. There are two curator classes with different input needs:

**Content curators** (`rot`; later `pattern` / `contradiction` / `audit`) — compare memory against the world:

- `ls $MEMORY_DIR/*.md` and read each `project_*.md` / `reference_*.md` (skip `env_`, `feedback_`, `user_` unless the curator asks)
- Read `state/decisions.md`, `state/blockers.md`, `state/current.md`
- Select session logs **by filename date, never by mtime**, and read each:
  ```
  CUT=$(date -u -d '14 days ago' +%F 2>/dev/null || date -u -v-14d +%F)
  ls sessions/*.md | sed 's|.*/||' | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$' | sort | awk -v c="$CUT.md" '$0 >= c'
  ```
  **Why not `find -mtime -14`:** any git history rewrite resets mtime on every tracked file, after which `-mtime -14` matches the whole directory and silently blows up the input set. Session filenames are `YYYY-MM-DD.md` and sort lexically, so the date compare above stays exact through any rewrite.
- `git log --since="14 days ago" --oneline` for the current repo

**Structural curators** (`merge`, `split`, `lint`) — examine the *shape of the memory set itself*; no state/session file inputs (lint's extras below are existence probes and commit titles, not state):

- Read every `$MEMORY_DIR/*.md` detail file
- Read `$MEMORY_DIR/MEMORY.md` (the index) and `$MEMORY_DIR/ARCHIVE.md`
- Optionally `git -C "$MEMORY_DIR" log --since="30 days ago" --oneline` (accretion signal)
- `lint` additionally: cheap read-only existence checks for local paths memories name (`ls`, `test -e`, `git ls-files`), and optionally `git log --oneline -30` of the current work repo for its shipped-work heuristic — never URL fetches

### 5. Write `inputs.json` to the dream dir

Record what was fed in (file paths + line counts), so the run is reproducible.

```json
{
  "curator": "rot",
  "ran_at": "{ISO}",
  "memory_files_read": [...],
  "state_files_read": [...],
  "session_files_read": [...],
  "git_log_window_days": 14,
  "git_log_commit_count": N
}
```

### 6. Run the curator

Following the role + question + classification logic in the loaded prompt, walk every input target and produce findings. **Be conservative — empty-evidence proposals get rejected at apply time.**

### 7. Write `proposals.json` to the dream dir

Schema is defined in the curator prompt and varies by curator class. Every proposal has `id`, `action`, `reasoning`, `evidence` (array, never empty), `confidence`. Beyond that:

- **Content curators** (`rot`): `target`, `current_excerpt`, `proposed_excerpt`.
- **`merge`**: `targets` (array), `survivor`, `merged_body`, `index_changes` ({remove[], add}), `archive_tombstones`, `net_index_lines`.
- **`split`**: `target`, `result_files` (array of {name, purpose, index_line, body}), `original_index_line`.
- **`lint`**: content-curator shape (`target`, `current_excerpt`, `proposed_excerpt`) plus a `check` field naming which of its ten checks fired.

`/dream-apply` branches on `action` to apply each shape.

### 8. Write `REPORT.md` to the dream dir

Human-readable summary per the curator prompt's format. Top: dream-pass header + counts. Then findings grouped by confidence. Then skipped items. Footer: `Run /dream-apply {ISO} to review and apply.`

### 9. Commit the artifact to memory git

```
cd "$MEMORY_DIR"
git add ".dreams/$TS/"
git commit -m "dream($TS): {curator} — N proposals (H high / M med / L flag)"
```

### 10. Surface the result

Print:

```
Dream pass complete: {curator}
Artifact: memory/.dreams/{ISO}/REPORT.md
Proposals: N (H high, M medium, L flag)
Top finding: {one-line summary of the highest-confidence proposal}

Review and apply: /dream-apply {ISO}
```

## Scope guards

- Curator MUST NOT modify any input file. Read-only on `memory/`, `state/`, `sessions/`.
- Curator MUST NOT push the memory git repo to any remote. Local-only by design.
- Curator outputs MUST NOT carry content the consuming repo's scope rules exclude (work-domain identifiers, internal project names, other repos' state). Session logs may contain residue that upstream filters missed — exclude it from proposals rather than propagating it into memory.
- If `$ARGUMENTS` names a curator that hasn't been built yet, refuse politely and list what is available.
