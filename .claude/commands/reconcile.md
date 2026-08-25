---
name: reconcile
description: "Scan multi-session drift and offer individually reviewed fixes only after explicit approval."
allowed-tools: "Read, Bash, Glob, Grep"
disable-model-invocation: true
x-source: "skills-sync/commands/reconcile.md"
x-source-version: "7ae9852"
---

# /reconcile — Multi-Session Drift Check

When multiple agent sessions run in parallel (especially with worktrees), files drift out of sync. This core scans for inconsistencies and proposes fixes — it flags problems but doesn't fix them without approval.

> This is the generic core. A consuming repo with single-source-of-truth rules (e.g. a pipeline file that other files reference) adds those specific cross-checks as its own overlay — see step 4.

**Invocation:** this command is user-only because its optional fix mode can write and commit. The default scan remains read-only. It never pulls, rebases, or moves the working tree — sync divergence is reported, not fixed. A home that wants a sync-first reconcile adds a pull step in its own overlay, and should weigh the cost first: an auto-rebase in a shared checkout can strand other sessions' worktree bases, which is the exact situation this core is run to diagnose. Everything that changes *files* is proposed and separately approved before it is applied.

## Configuration

Run `bash scripts/contextos.sh workspace show` and use its resolved `state_dir`
and `task_file`. Canonical JSON is authoritative; legacy YAML is used only when
JSON is absent. Stop and report a configuration error instead of guessing paths.

## When to Use

- After merging worktree branches back to the default branch
- When something "feels off" after parallel work
- After a crash where multiple sessions were open
- As a periodic sanity check during heavy parallel workflows

## Instructions

### 0. Orientation (run FIRST)

Scope the check and resolve the default branch before reading any files. Don't assume `main`:

```bash
git rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git repository — nothing to reconcile"; exit 0; }
REPO_ROOT=$(git rev-parse --show-toplevel)
DEFAULT=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
DEFAULT=${DEFAULT:-$(git remote show origin 2>/dev/null | sed -n 's/.*HEAD branch: //p')}
DEFAULT=${DEFAULT:-main}   # no remote configured — fall back and say so in the report
find "$REPO_ROOT" -name "*.md" -mtime -1 -not -path "*/node_modules/*" | sort   # recently modified
git -C "$REPO_ROOT" log --oneline -10
```

Focus the reconcile on files that actually changed recently.

### 1. Sync status (read-only)

```bash
git rev-list --left-right --count "origin/$DEFAULT...HEAD" 2>/dev/null || echo "no remote-tracking ref — sync status unknown"
```

Report behind/ahead counts against the remote-tracking ref as it sits on disk. Do **not** pull or rebase here — a rebase in a shared checkout can strand other sessions' worktrees, and surfacing divergence is this core's job; resolving it is the user's. If the refs may be stale, say so and let the user decide whether to fetch first (`git fetch` updates remote-tracking refs and FETCH_HEAD; it never touches the working tree).

### 2. Uncommitted / cross-session changes

```bash
git status --short
git stash list
```

Flag unstaged changes you didn't make ("likely from another session — review before proceeding") and any forgotten stashes.

### 3. Cross-branch scan + file-level conflicts

```bash
git log --all --oneline --since="24 hours ago" --graph
```

Look for multiple branches touching the same files, and commits on branches that haven't been merged. For each file modified on more than one branch, diff the versions:

```bash
git diff "$DEFAULT"..<branch> -- <file>
```

Flag where both branches changed the same lines, one branch deleted what another modified, or `**Last Updated:**` fields diverged.

### 4. SSOT violations

If the project has single-source-of-truth rules (a fact lives in exactly one file; others reference it):

- Scan for the same fact duplicated across files with **different values** (DUPLICATE)
- Flag a cross-reference that hardcoded a value instead of pointing at the source (STALE COPY)
- Confirm cross-references resolve to files that still exist — `bash scripts/check-links.sh` covers tracked markdown if present

A consuming repo lists its canonical-fact table here in its own overlay; the generic core only checks the *pattern*.

### 5. State-file consistency

Read the state files under `<state_dir>` (e.g. `current.md`, `weekly-priorities.md`, `blockers.md`, the decision log, session logs) and any task file (`<task_file>`), and check:

- **Duplication** — an actionable task in `current.md` that should only live in `<task_file>`; the same item logged twice from different sessions
- **Contradiction** — one session marked something complete while another still has it open
- **Timestamp drift** — a `**Last Updated:**` line older than the most recent commit touching that file; a *stacked or spliced* `Last Updated` line is itself a drift signal
- **Orphaned references** — sections pointing at files or items another session removed

### 6. Report

```
RECONCILE — [DATE]

GIT: sync [behind X / ahead Y / unknown] · uncommitted [none/list] · branches [N, collisions?]
SSOT: [PASS / violations]
STATE: [PASS / issues]
OVERALL: [CLEAN / N issues found]
```

List each issue with the file, the line, and a proposed fix. Wait for approval before changing anything.

### 7. Fix mode (with approval only)

Present each fix individually. Show the exact affected paths and intended edits, then wait for explicit approval of that reviewed set. Apply only approved fixes. Before committing, show `git status --short` and the scoped staged diff; never stage unrelated work, and wait for a separate explicit commit approval:

```
reconcile: fix [N] drift issues from parallel sessions
```

Common fixes: merge the newer version of a conflicting file, remove duplicate entries (keep the more detailed one), correct timestamps to match actual last-edit dates, resolve SSOT violations by keeping the canonical source and updating the references.

## Design Principles

- **Read-only by default and user-invoked.** The scan changes nothing; fix mode can edit and commit, so each fix needs explicit approval and the command is never ambiently invoked.
- **Prefer evidence of intent over recency.** When two versions conflict, look at which change the surrounding work depends on (commit messages, linked edits, whether other files reference the new value). A stale session can easily produce the *newer* timestamp. Use recency only as a tie-breaker when intent is unreadable.
- **Preserve intent.** Don't auto-resolve — different sessions may have had different goals.
- **Fast.** Targeted checks only — under 30 seconds. Don't deep-read every file.
- **Specific.** Every flag names the file, the line, and the conflict. "Something seems off" is not a flag.
- **No false alarms.** A cross-reference that correctly points at its source is fine — only flag real value mismatches or duplicated facts.
- **Complement `/recover`.** Reconcile checks *content* drift; `/recover` handles *structural* worktree and branch cleanup.
