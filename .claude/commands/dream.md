---
name: dream
description: "Run a curator pass against the validated memory directory and produce a proposal artifact."
allowed-tools: "Read, Bash, Write, Glob, Grep"
disable-model-invocation: true
x-source: "skills-sync/commands/dream.md"
x-source-version: "8ede26c"
---

# /dream — on-demand memory curator pass

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

### 2. Resolve and validate the explicit memory dir

Run the executable validator before reading or writing memory state:

```sh
python3 scripts/dream/validate-memory.py resolve
```

Parse the returned JSON. Set `MEMORY_DIR` from `memory_dir` and treat `repository_identity` as the stable binding for this repository. The helper verifies `.context-os/memory-directory`, rejects non-canonical or symlinked paths, requires `MEMORY.md` and `.context-os-repository`, binds the marker to Git's resolved common directory identity (safe across linked worktrees), requires the memory dir to be its own git repo, refuses any memory remote, and requires tracked, staged, and untracked memory state to be clean before the pass. If host auto-memory left changes, stop so the user can review or snapshot them separately.

Only after that succeeds, generate `TS` in exact `YYYY-MM-DDTHH-MM-SSZ` form and preflight the target artifact path:

```sh
python3 scripts/dream/validate-memory.py artifact "$TS" --for-create
```

Create only the validated `$MEMORY_DIR/.dreams/$TS` path returned by the helper, then continue.

Do not create or guess a path when a check fails. Stop and direct the user to `docs/auto-memory.md` or the first-time local-git setup in `scripts/dream/README.md`.

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

- **Content curators** (`rot`): `modify` uses `target`, `current_excerpt`, and `proposed_excerpt`; `archive` uses `target` and `archive_reason`; `flag` uses `target` and `concern`.
- **`merge`**: `targets` (array), `survivor`, `merged_body`, `index_changes` ({remove[], add}), `archive_tombstones`, `net_index_lines`.
- **`split`**: `target`, `result_files` (array of {name, purpose, index_line, body}), `original_index_line`.
- **`lint`**: `modify` uses the content-curator shape plus `check`; `flag` uses `target`, `concern`, and may include a non-authoritative `proposed_excerpt`, plus `check`.

`/dream-apply` branches on `action` to apply each shape.

### 8. Write `REPORT.md` to the dream dir

Human-readable summary per the curator prompt's format. Top: dream-pass header + counts. Then findings grouped by confidence. Then skipped items. Footer: `Run /dream-apply {ISO} to review and apply.`

Now validate the complete new artifact and its exact three-file change set:

```sh
python3 scripts/dream/validate-memory.py artifact "$TS" --for-commit
```

If validation fails, do not stage or commit the artifact. Fix the schema/path issue or stop and surface the validator error. This check rejects unrelated tracked, staged, or untracked memory changes.

### 9. Commit the artifact to memory git

```sh
git -C "$MEMORY_DIR" add -- \
  ".dreams/$TS/inputs.json" \
  ".dreams/$TS/proposals.json" \
  ".dreams/$TS/REPORT.md"
python3 scripts/dream/validate-memory.py artifact "$TS" --for-commit
git -C "$MEMORY_DIR" diff --quiet
git -C "$MEMORY_DIR" commit -m "dream($TS): {curator} — N proposals (H high / M med / L flag)"
```

The second validator call and unstaged-diff check are the concurrent-change guard. If either fails, stop with the reviewed artifact staged; never broaden the add command.

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
