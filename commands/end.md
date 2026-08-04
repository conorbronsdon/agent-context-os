---
name: end
description: End a session — log what happened, update state and the decision log, propose durable memory updates, and check for uncommitted or unpushed work
allowed-tools: Read, Write, Edit, Glob, Bash
x-source: skills-sync/commands/end.md
x-source-version: 7ae9852
---

# /end — Close Session

Capture the session and leave state ready for the next one: a session log, state updates, a decision-log append, memory proposals, and a git safety check.

**Invocation:** user-timed. A home that packages this core as a skill should set `disable-model-invocation: true` — session close is timed by the user, and the flag keeps the description out of ambient context.

## Configuration

If the project root carries a `workspace.yaml`, read it. Below, `<state_dir>` and `<sessions_dir>` are its resolved values; the defaults are `state/` and `sessions/`.

## Instructions

### 1. Get today's date
Run `date +%Y-%m-%d` and store as TODAY, `date +%H:%M` as TIME.

### 2. Auto-extract the session summary

Scan the full conversation and extract:
- **Topics covered** — what was worked on
- **Decisions made** — anything concluded or chosen, with rationale
- **Rejected alternatives** — for each meaningful decision, what else was considered and why it lost. If a bug was fixed, note the wrong theory tried first. If an approach changed mid-session, capture the pivot. This is the failed-hypothesis record that keeps a future session from repeating the same wrong starting point.
- **State changes** — priorities that shifted, threads that opened or closed
- **Open threads** — unfinished items or things waiting on someone
- **Next actions** — what needs to happen next session

Present the summary for quick confirmation before writing anything.

### 3. Write the session log

Create or update `<sessions_dir>/{TODAY}.md`:

```markdown
# Session — {TODAY}

## What happened
- [Bullet summary of work done]

## Decisions
- [Any decisions made or conclusions reached]

## Next time
- [Open threads, next actions, things to pick up]
```

If a session file already exists for today, append a new section with a timestamp header (`## Session {TIME}`) rather than overwriting.

### 4. Update state files

- **Always update `<state_dir>/current.md`:** add new threads, remove completed items, refresh timestamps on touched items, and update "Recent context" with a brief note on what was covered.
- **Roll the `Last Updated` line through `current-log.md` (chain protocol).** Keep exactly one `**Last Updated:**` line at the top of `current.md`, the newest. Never stack extra lines and never build a single-line "previous-entry" chain — that breaks the Read tool, breaks `grep`, and splices parallel-session merges into single-line conflicts. Instead:
  1. Read the existing `**Last Updated:**` line from `current.md`.
  2. Prepend it as its own line at the top of `<state_dir>/current-log.md`, directly under the file header, newest first. Create the file with a `# current.md update log` header if it does not exist.
  3. Replace the `**Last Updated:**` line in `current.md` with today's entry.

  One entry per line keeps history append-only and merges line-based.
- **Update `<state_dir>/blockers.md` if needed:** add new dependencies, move resolved blockers to "Recently Unblocked."
- **Update `<state_dir>/weekly-priorities.md` if needed:** check off completed items. Only touch it if meaningful progress was made; don't force an update if nothing changed.

### 5. Update the decision log

If decisions were made, append to `<state_dir>/decisions.md`:

```markdown
| {TODAY} | {decision} | {context / rationale} | {rejected alternatives} |
```

Only log decisions future sessions need: source-of-truth changes, strategy pivots, scope calls, tool or process choices. Skip trivial ones. Fill the **rejected alternatives** column when there was a real branch point — what else was considered and why it lost; leave it blank when there was one obvious option.

### 6. Propose auto-memory updates

Scan the session for durable patterns worth preserving across *all* conversations in this project — not just today's work. Claude Code auto-loads `MEMORY.md` from this project's memory dir (`~/.claude/projects/<encoded-cwd>/memory/`, where `<encoded-cwd>` is the project path with `/`, `\`, and `:` replaced by `-`) at the start of every conversation, so anything saved there compounds. If the host repo carries a memory spec (e.g. `docs/auto-memory.md`), read it for the typed categories before proposing.

Propose 0–2 additions. Good candidates:
- Environment quirks or tool behaviors confirmed this session
- Workflow preferences the user expressed ("always do X", "never do Y")
- Debugging solutions that will recur
- Stable facts about projects, people, or processes

Bad candidates:
- Session-specific context (what was worked on today — that's the session log's job)
- Anything already in `CLAUDE.md` or the state files
- Unverified conclusions from a single observation

**Friction-point check:** before presenting proposals, ask yourself — *was there a friction point this session that a memory entry would have prevented?* A tool you had to re-learn, an error you'd hit before, a convention you had to re-infer. If yes, write the entry. Repeating a mistake is a system failure — turn it into a durable rule.

Present proposals inline and wait for approval; never write to memory without confirmation:

```
MEMORY PROPOSALS:
- [proposed addition 1]
- [proposed addition 2]
(Reply "save" to apply, or skip)
```

If nothing qualifies, skip silently.

### 7. Quick drift check (if parallel sessions ran)

In a git repository, run `git log --oneline --all --since="6 hours ago"` to catch commits from sessions working in parallel.

- If any of those commits touched files this session also edited, flag the potential conflict: "Parallel session also edited [file], check for conflicts." Wait for the user before fixing anything.
- If none are found, skip silently — do not mention this step.
- This is a fast spot-check, not a full reconcile (see the `reconcile` core for that).
- Outside a git repository, skip this step.

### 8. Git safety check (do not skip)

In a git repository, run `git status` and check for uncommitted or unpushed work:

- Uncommitted changes? Show the files and ask whether to commit.
- Unpushed commits? Show the count and ask whether to push.
- Clean and pushed? Skip silently.
- Outside a git repository, skip this step.

### 9. Confirm with user

Two-line summary: what was logged, and the top open thread or next action. If memory proposals are awaiting a save/skip reply, note that.

## Design principles

- **Propose, don't act.** State updates are confirmed; memory is never written without a "save"; commits and pushes need explicit approval.
- **Standing rule.** Every `/end` runs steps 1–9 in order; the chain protocol in step 4 is how the timestamp always rolls — never append a second `Last Updated` line as a shortcut.
