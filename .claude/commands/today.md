---
name: today
description: "Create a morning heartbeat from repository state and update the local heartbeat log."
allowed-tools: "Read, Write, Bash, Glob"
disable-model-invocation: true
x-source: "skills-sync/commands/today.md"
x-source-version: "7ae9852"
---

# /today — Morning Heartbeat

Lightweight daily check-in that catches staleness, surfaces deadlines, and proposes state updates — including gaps left by sessions that closed without `/end`. Run at the start of each day or after any long gap between sessions. Designed to finish in under 60 seconds — if it's slow, it won't get used.

**Invocation:** user-timed and explicitly user-invoked. The heartbeat writes its audit log, so it is not an ambient read-only helper.

## Configuration

If the project root carries a `workspace.yaml`, read it. Below, `<state_dir>`, `<sessions_dir>`, and `<task_file>` are its resolved values; the defaults are `state/`, `sessions/`, and `TODO.md`. Staleness thresholds come from `staleness.current_days` (3), `weekly_days` (5), and `blockers_days` (7).

## Instructions

### 1. Establish context
Run `date +%Y-%m-%d` and `date +%A`. Read `<state_dir>/heartbeat-log.md` (if present) to find the last check-in date.

### 2. Scan recent activity
Catch work even from sessions that closed without `/end`. In a git repository:

```bash
git log --oneline --since="3 days ago"
```

Also check `<sessions_dir>` for logs newer than the last heartbeat. Note what was last worked on for continuity. Outside a git repository, rely on the session logs alone.

### 3. Load state
Read `<state_dir>/current.md`, `<state_dir>/weekly-priorities.md`, and `<state_dir>/blockers.md`.

### 4. Check staleness (escalating)
- `current.md` `**Last Updated:**` older than `staleness.current_days` → flag
- `weekly-priorities.md` `**Week of:**` from a previous week (or older than `staleness.weekly_days`) → flag
- `blockers.md` older than `staleness.blockers_days` → flag
- Open threads in `current.md` carrying a date annotation:
  - older than 7 days → "stale — still relevant?"
  - older than 14 days → "likely stale — remove or convert to a task?"

Present these as proposals. **Do not auto-update.**

### 5. Surface deadlines
Scan `<task_file>` for unchecked items (`[ ]`) with a date in the next 7 days, or marked urgent / time-sensitive. List them, most urgent first.

### 6. Identify state gaps
Compare the git-log activity from step 2 against the state files:
- Decisions committed but not recorded in `<state_dir>/decisions.md`?
- Completed work not reflected in `<state_dir>/current.md`?

List proposed updates. **Do not auto-update. Wait for approval.**

This step reconciles *state files* against what actually shipped. It is not memory curation — see the boundary note at the bottom.

### 7. Optional live data
This template ships without a live-data adapter or pre-approved external tools. Skip this step unless the user has separately enabled a reviewed read-only integration and explicitly asks to include it. Never authenticate, expand scopes, or call write-capable tools as part of the heartbeat.

### 8. Deliver the heartbeat

```
MORNING CHECK-IN — [DATE] ([day of week])
Last heartbeat: [date] ([N] days ago)

SINCE LAST CHECK-IN:
- [N] commits: [brief themes]
- Session logs: [found / none]

STATE:
- current.md — [fresh / N days stale]
- weekly-priorities.md — [fresh / N days stale]
- blockers.md — [fresh / N days stale]

DEADLINES (next 7 days):
- [items, most urgent first]

[If stale items found:]
STALE ITEMS:
- [item] — [N] days old [propose: remove / convert to task]

[If state gaps found:]
STATE GAPS:
- [proposed update]

[Scoped live-data highlights, only when explicitly requested]
```

Skip any section that's clean — if everything's fresh and nothing's due, say so in one line.

### 9. Log the heartbeat
Append to `<state_dir>/heartbeat-log.md`:

```markdown
## [DATE]
- Commits since last: [N]
- State staleness: [summary]
- Deadlines flagged: [count]
- Stale items flagged: [count]
- State gaps found: [count]
- Updates applied: [list or "none — awaiting response"]
```

### 10. Transition
Ask: "What's the focus today?" Do NOT re-run the full `/start` flow — this is the lighter, faster check-in.

## Design principles

- **Fast.** Under 60 seconds. If it's slow, it won't get used.
- **Propose, don't act.** Never silently edit state during the heartbeat.
- **Skip what's clean.** All fresh and no near deadlines → say so in one line.
- **Graceful degradation.** A session that closed without `/end` is caught here; missing files are noted, not fatal.

> Memory curation lives in `/dream`, not here. `/today` surfaces staleness, deadlines, and state-file gaps; `/dream` proposes changes to `MEMORY.md`. Keeping them separate avoids two commands editing memory.
