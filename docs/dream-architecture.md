# Dream — on-demand memory curator

**Status:** v0.3. Curators: rot (content), merge + split + lint (structural).

## Why this exists

Memory accumulates faster than humans review it. The only forcing functions are `/end` (hand-curated at session close, biased toward what's fresh in context) and `/today` (morning heartbeat, biased toward today's priorities). Neither catches:

1. **Rot** — project memories stale within days ("X submitted, awaiting approval" → false a week later)
2. **Cross-session patterns** — same friction hit 3+ times across sessions but only captured as a memory once
3. **Contradictions** — two memory rules giving conflicting guidance, both still indexed
4. **Untapped patterns** — recurring session-log themes that never got promoted to memory
5. **Adherence drift** — sessions ignoring rules they should have followed
6. **Shape drift** — files that bundle unrelated concerns, or several files that say the same thing

The shipped curators cover rot, merge, split, and lint. Pattern, standalone contradiction, untapped-work, and audit passes below are roadmap designs rather than current capabilities.

These are LLM-shaped tasks: comparing durable memory with current evidence, contradiction detection inside lint, and structural consolidation.

The bet: compounding pattern-capture over months beats waiting for the perfect memory product. Curator file shapes (markdown + JSON proposals) stay portable even if the runner gets thrown away.

## Architecture

### Three layers

```
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 1: Inputs (read-only)                                     │
│   sessions/*.md  state/*.md  memory/*.md  git log (14d)         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 2: Curator pass (prompted)                                │
│   /dream {curator-name}                                         │
│   Curator prompts live in scripts/dream/prompts/                │
│   {rot, merge, split, ...}.md                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 3: Proposal artifact (write to memory git)                │
│   memory/.dreams/{ISO}/                                         │
│     REPORT.md       — human-readable summary                    │
│     proposals.json  — machine-readable per-item diff            │
│     inputs.json     — what was fed in (reproducibility)         │
│   Committed to memory git on creation.                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ APPLY: separate command, gated on human review                  │
│   /dream-apply {ISO-timestamp}                                  │
│   Walks proposals.json, asks accept/reject/edit per item,       │
│   applies accepted to memory files, commits in memory git.      │
└─────────────────────────────────────────────────────────────────┘
```

### Why slash commands, not standalone Python

1. **No separate API key.** The curator runs inside the existing Claude Code session — same model, same auth.
2. **Easier prompt iteration.** Curator prompts are markdown files; tweak one, run again, no redeploy.
3. **Structured-tool access.** `AskUserQuestion` for the apply step gives a real review UI rather than terminal Y/N.

Tradeoff: can't run truly unattended without a headless run. See **Automation** below.

### Why git on the memory dir

Three load-bearing benefits once a curator writes proposal artifacts:

1. **Diff before/after.** "What changed in this dream pass" is the most-asked question after every run.
2. **Revert path.** A bad accept-all on `/dream-apply` is one `git revert` away.
3. **Migration insurance.** `cp -r memory/ <new machine>` + `git log` keeps the full history.

**Local-only repo. No remote.** Memory often contains personal or confidential context. For backup, see **Backup & recovery** below — snapshot to a private location, do not add a hosted remote.

### Storage layout

```
<configured-memory-directory>/
├── .git/                   ← local-only repo
├── MEMORY.md               ← index (cap 100 lines)
├── ARCHIVE.md              ← tombstone rows, one per retired file
├── {topic}.md              ← LIVE detail files only
├── archive/                ← retired files, moved here on archive
│   └── {topic}.md          ← each stamped `archived: YYYY-MM-DD` in frontmatter
└── .dreams/                ← curator artifacts
    └── {ISO-timestamp}/
        ├── REPORT.md       ← human review surface
        ├── proposals.json  ← machine apply surface
        └── inputs.json     ← reproducibility
```

### Proposal schema

Every proposal has `id`, `action`, `reasoning`, `evidence` (array, never empty), `confidence`. The rest varies by curator class:

- **Content curators** (`rot`): `target`, `current_excerpt`, `proposed_excerpt`. Actions: `modify`, `archive`, `add`, `flag`.
- **`merge`** (structural): `targets[]`, `survivor`, `merged_body`, `index_changes`, `archive_tombstones`, `net_index_lines`.
- **`split`** (structural): `target`, `result_files[]`, `original_index_line`.

Apply step honors `confidence`: `high` defaults to accept, `medium` shows full diff, `low` requires explicit edit.

## Curator catalog (build order)

Curators fall into two **classes**:

- **Content curators** ask *"is this memory still true?"* — they compare memory against the world (state files, sessions, commits). `rot`, `pattern`, `contradiction`, `audit`.
- **Structural curators** ask *"is this memory well-shaped?"* — they examine the shape of the memory set itself (detail files + the `MEMORY.md` index) and read no state or session files (lint adds only read-only existence probes and an optional work-repo `git log`). `merge`, `split`, `lint`.

### v0.1: rot (content) — shipped

**Question:** "For each project-type memory entry, does it still match the current state of the world?"

**Inputs:** `memory/project_*.md` + `state/{decisions,blockers,current}.md` + `git log --since=14.days.ago`.

**Output actions:** `modify`, `archive`, `flag`.

**Why first:** Easiest objective spec. Lowest false-positive cost ("no, this is still true" is cheap to dismiss). Runs against existing data, proves substrate value on day 1.

### v0.2: merge + split (structural) — shipped

**Questions:** merge — *"Do 2+ memories cover the same thing and always get recalled together?"* split — *"Has one file accreted 2+ unrelated concerns?"*

**Inputs:** `memory/*.md` (live detail files only — `memory/archive/**` is excluded) + `memory/MEMORY.md` (index) + `memory/ARCHIVE.md`. No state/session inputs.

**Output actions:** `merge` (consolidate `targets` → `survivor`, write ARCHIVE tombstones, collapse index lines), `split` (divide `target` → `result_files`, expand index lines), `flag` (boundary is a judgment call).

**Why second:** `MEMORY.md` drifts over its 100-line / loaded-budget cap; merge is the direct pressure-relief, and split enforces one-fact-per-file. Structural ops touch many files at once, so they lean hard on the git-revert safety net and human review. Guiding principle: **Focus Over Coverage** — never produce vaguer files just to hit a number; merge and split are opposing forces and a good pass leaves the other nothing to undo.

### v0.3: lint (structural) — shipped

**Question:** "Is the store well-formed and internally consistent — index and files in agreement, no duplicates, no contradictions, no half-finished archives?"

**Inputs:** `memory/*.md` + `memory/MEMORY.md` + `memory/ARCHIVE.md` (live root only — `memory/archive/**` excluded), plus cheap read-only existence checks (`ls`, `test -e`, `git ls-files`) for local paths memories name, and optionally `git log --oneline -30` when run inside a work repo. No state/session inputs, no URL fetches — it runs standalone against any memory directory, which makes it the right first pass on an inherited or long-uncurated store.

**Output actions:** `modify`, `archive`, `flag` (content-curator proposal shape plus a `check` field naming which of its ten checks fired: index drift, unresolved links, pattern-level staleness, duplicates, contradictions, unverifiable references, type misfiles, index-only content, duplicate archive rows, build-log bloat).

**Why third:** rot compares memory against the world; lint catches the store drifting against *itself* — the class rot structurally cannot see. Sharpest case: a type misfile, where a project status filed as `feedback` escapes every rot pass because rot audits `project`/`reference` hardest. Ported from agent-memory-kit (`prompts/lint.md` @ `1bd9a14`, skills-sync#9), where it was capability the publication node had and the core lacked.

### v0.4: pattern (content, later)

**Question:** "What recurring frictions in the last 14 days of sessions don't have a memory entry yet?"

**Output actions:** `add` (new memory candidate). Required-evidence floor: must appear in 3+ sessions to propose.

### v0.5: contradiction (content, later)

**Question:** "Does memory contain rules that give conflicting guidance for the same situation?"

**Output actions:** `flag` (always — never auto-resolve a contradiction; surface to the user).

### v0.6: untapped (content, later)

**Question:** "What recurring themes in session logs have never been raised into memory or a skill?"

**Output actions:** `flag`.

### v0.7: audit (content, later, possibly never)

**Question:** "Did sessions in the last 7 days follow the rules in MEMORY.md?"

**Risk:** Memory rules aren't structured enough to mechanically check adherence. May produce noise. Hold until `untapped` ships.

## What this deliberately doesn't do

- **No skill generation.** Skills stay manual via `/skill-creator` (or your own equivalent).
- **No autonomous apply.** Review gate stays. Maybe never removed for high-stakes scopes.
- **No vector store / SQLite / FTS.** Plain markdown + JSON. Smallest substrate that works.

## Automation (optional)

The curator never auto-applies, so automating the *propose* step is safe; apply stays human-gated.

- **Passive nudge.** A `SessionStart` hook that computes days since the last `.dreams/` artifact and prints a one-line reminder when memory is stale-curated. It surfaces; it never runs a curator (hooks can't invoke Claude).
- **Active unattended.** Schedule a headless run on your platform's scheduler. Two non-obvious gotchas:
  1. **Headless can't run slash commands.** `claude -p "/dream rot"` treats the slash command as literal text — print mode is non-interactive. Pass a *plain prompt that points Claude at `.claude/commands/dream.md`* (the command file is itself the step-by-step spec).
  2. **Permission posture.** Run with `--permission-mode dontAsk` plus an `--allowedTools` allowlist that includes the `Bash` tool **wholesale** — the command issues compound shell commands (`TS=$(date ...)`, `git add && git commit`) that prefix-pattern allowlists (`Bash(git:*)`) can't match, so a narrow list makes the run flail on denials. `dontAsk` still denies every non-shell tool. Never use `bypassPermissions` for an unattended loop.
  - **Collision guard.** Gate the run so it doesn't fire while an interactive session is writing the same memory git (e.g. skip if another Claude process is running). A pass over a few dozen memories can take ~15 minutes.

## Backup & recovery

Three distinct failure modes; only one needs new infra.

0. **Failure to forget** (the inverse of the two below) — an `archive` that writes the tombstone row and stops. The file stays in the memory root, unstamped and unchanged, so every later session reads it as a live memory. Git backups do not help, because nothing was lost: the corpus is quietly asserting stale things as current. The tell is a curator proposing to archive something that was archived weeks ago — it has no way to see the earlier row.

   Fix it structurally, not by discipline: archiving is stamp + move to `archive/` + inbound-link rewrite, and the apply step refuses to re-archive a file already carrying an `archived:` stamp. The refusal *is* the tripwire.

   Same root cause, adjacent gap: a `split` that removes its target without writing a tombstone deletes a memory silently, and leaves any live file that linked the old slug pointing at nothing.

1. **Mistaken forgetting** (a bad `merge`/`split`/`archive` drops a fact) — **already covered by memory git.** Every `/dream-apply` commits before it changes anything, and structural ops use `git rm` (not destructive deletion), so absorbed/split-away content stays in history. Recovery is `git revert HEAD` or `git show HEAD~N:<file>`.
2. **Machine loss** — local git can't help; you need an off-machine copy. Keep the no-remote rule (memory may hold confidential context) and use a `git bundle` instead of a hosted remote: `git bundle create memory-<date>.bundle --all` produces one restorable file (`git clone <bundle> memory`) you copy to private storage. Cadence: periodic, or after a large `/dream-apply`.

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Curator hallucinates rot that's actually current | Required `evidence` array — every claim cites a state-file line or commit. Apply rejects empty-evidence proposals. |
| Apply step accept-all destroys good memories | Git on memory dir → revert is one command. Apply shows full diff before each accept. Structural ops use `git rm`, never destructive delete. |
| Memory + state files drift apart over time | Curator reads both each pass; rot detector specifically cross-references them. |
| Confidential memory leaks via accidental `git push` | No remote configured. Optionally a pre-commit hook on memory git that refuses if any remote is added. |

## Open questions

- Should `state/decisions.md` ever be a curator write target? Currently read-only.
- Should the curator propose `CLAUDE.md` changes when a feedback rule validates 3+ times? Promotion changes Claude's default behavior — high-leverage and high-risk.
- Multi-repo curators? Same substrate could run against any project's `state/` + `memory/`.

## Files

| Path | Role |
|---|---|
| `docs/dream-architecture.md` | This file. |
| `scripts/dream/README.md` | How to use, how to add curators. |
| `scripts/dream/prompts/rot.md` | Rot-detector prompt body (content class). |
| `scripts/dream/prompts/merge.md` | Merge curator prompt body (structural class). |
| `scripts/dream/prompts/split.md` | Split curator prompt body (structural class). |
| `.claude/commands/dream.md` | `/dream {curator}` slash command. Default: `rot`. |
| `.claude/commands/dream-apply.md` | `/dream-apply {timestamp}` slash command. |
| `<configured-memory-directory>/.git/` | Local-only repo for memory dir. Run `git init` there on first use. |
| `<configured-memory-directory>/.dreams/` | Per-pass artifacts. Tracked. |
