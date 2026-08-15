---
name: recover
description: Scan for orphaned worktrees and stale branches after crashes or abandoned agent sessions. Read-only scan; offers safe, approval-gated cleanup.
allowed-tools: Read, Glob, Grep, Bash
x-source: skills-sync/skills/recover/SKILL.md
x-source-version: 7ae9852
---

# /recover — Worktree & Branch Cleanup

Scan for orphaned worktrees, stale branches, and partial work left behind by crashed or abandoned agent sessions. Read-only by default — reports findings and waits for approval before any cleanup.

**Invocation:** deliberately model-invocable — scanning is read-only. Every cleanup action is gated on explicit user approval.

## Configuration

This core operates on git worktrees and branches only; it reads no state files, so a `workspace.yaml`'s state paths do not apply. The one setting it depends on is the **default branch**, which it detects (step 0) rather than hardcoding.

## When to Use

- After a system crash or forced session termination
- When parallel-session hooks warn about stale processes
- When `/reconcile` finds commits on unknown branches
- Periodic hygiene (monthly, or after heavy parallel work)

## Instructions

### 0. Detect the default branch

Don't assume `main`. Resolve it once and use it everywhere below:

```bash
git rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git repository — nothing to recover"; exit 0; }
DEFAULT=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
DEFAULT=${DEFAULT:-$(git remote show origin 2>/dev/null | sed -n 's/.*HEAD branch: //p')}
DEFAULT=${DEFAULT:-main}   # no remote at all — fall back and note it in the report
```

### 1. List all worktrees

```bash
git worktree list --porcelain
```

Identify:
- **Recently touched worktrees**: files or `.git` metadata modified in the last hours — treat as *possibly live*. `git worktree list` cannot tell whether a session is actually running; without a lock/heartbeat file or process evidence, classify as **unknown activity** and never as orphaned.
- **Candidate-orphaned worktrees**: no recent modification and no activity signal — proceed to inspection, still gated on user approval before any cleanup.
- **Stale entries**: git tracks a worktree but the directory is gone.

### 2. Inspect candidate-orphaned worktrees

For each candidate-orphaned worktree:

```bash
git -C <worktree-path> status --short
git -C <worktree-path> branch --show-current
git -C <worktree-path> log --oneline -3
git log "$DEFAULT"..<branch-name> --oneline
```

Classify each as:
- **CLEAN**: no unmerged commits, no uncommitted changes — safe to remove
- **HAS COMMITS**: unmerged commits exist — needs a merge decision
- **HAS CHANGES**: uncommitted work — needs a save decision
- **BOTH**: unmerged commits AND uncommitted changes — needs careful handling

### 3. List stale branches

```bash
git branch --no-merged "$DEFAULT"
git remote prune origin --dry-run
git for-each-ref --sort=-committerdate --format='%(refname:short) %(committerdate:relative) %(subject)' refs/heads/
```

Classify:
- **MERGED**: already in the default branch — safe to delete
- **STALE**: last commit >7 days ago, not merged — flag for review
- **ACTIVE**: recent commits — leave alone

### 4. Check for prunable git state

```bash
git worktree prune --dry-run
```

### 5. Report

```
RECOVER — [DATE]

WORKTREES:
- Active: [N]
- Orphaned: [N]
  - [path] — [CLEAN/HAS COMMITS/HAS CHANGES/BOTH] — [branch] — [last commit]
- Stale entries: [N]

BRANCHES:
- Merged (safe to delete): [list]
- Stale (>7 days, not merged): [list]
- Active: [list]

PROPOSED ACTIONS:
1. [action] — [target] — [reason]

OVERALL: [CLEAN — nothing to recover / N items need attention]
```

### 6. Cleanup (with approval only)

**Only proceed when explicitly approved — including for CLEAN worktrees.** Options:
- **Remove CLEAN orphaned worktree**: `git worktree remove <path>`
- **Remove worktree with changes (only after the user confirms the discard)**: `git worktree remove --force <path>` — plain `git worktree remove` refuses a dirty worktree, so this is the one that actually runs, and it is the one that destroys uncommitted work
- Merge unmerged commits: `git merge <branch> --no-ff`
- Cherry-pick specific commits: `git cherry-pick <hash>`
- Delete merged branches: `git branch -d <branch>`
- Delete stale branches (confirmed discard): `git branch -D <branch>`
- Prune stale entries: `git worktree prune`
- Prune remote refs: `git remote prune origin`

## Design Principles

- **Read-only by default.** Report, wait for approval.
- **Preserve work.** Default to merge/cherry-pick over discard.
- **Honest about liveness.** A worktree with recent activity is **unknown**, not orphaned — never remove one without a positive orphan signal and user approval.
- **Specific.** Show exact commit hashes, file lists, branch names.
- **Fast.** Git commands only. Under 15 seconds for the scan.
- **Complement `/reconcile`.** Reconcile checks *content* drift; recover handles *structural* cleanup (worktrees, branches).
