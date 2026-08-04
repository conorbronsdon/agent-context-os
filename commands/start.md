---
name: start
description: Start a session — load state files, flag staleness, and give a briefing on current priorities, deadlines, and blockers
allowed-tools: Read, Bash, Glob, mcp__google-workspace
x-source: skills-sync/commands/start.md
x-source-version: 7ae9852
---

# /start — Begin Session

Load workspace state so the session begins where the last one left off, then give a short briefing. User-timed, so nothing runs ambiently.

**Invocation:** user-timed. A home that packages this core as a skill should set `disable-model-invocation: true` — the user decides when a session starts, and the flag keeps the description out of ambient context.

## Configuration

If the project root carries a `workspace.yaml`, read it. Below, `<state_dir>`, `<sessions_dir>`, and `<task_file>` are its resolved values; the defaults are `state/`, `sessions/`, and `TODO.md`. Staleness thresholds come from `staleness.current_days` (3), `weekly_days` (5), and `blockers_days` (7); a project without a `workspace.yaml` uses those defaults.

## Instructions

### 1. Get today's date
Run `date +%Y-%m-%d` and store as TODAY. Note the day of week.

### 2. Load context (read in order)
- `CLAUDE.md` — routing rules and slash commands
- `<state_dir>/current.md` — active priorities and open threads
- `<state_dir>/decisions.md` — scan the last ~5 entries for recent-decision awareness
- `<state_dir>/blockers.md` — what's waiting on external dependencies
- `<state_dir>/weekly-priorities.md` — what matters most this week
- `<sessions_dir>/{TODAY}.md` — if it exists, resume today's session; if not, check for the most recent file in `<sessions_dir>` for continuity; if it's empty, start fresh
- See `<sessions_dir>/README.md` for how session files work

### 2b. Check what changed since last session

If this is a git repository, find the most recent session log in `<sessions_dir>` and run `git log --oneline --since="<last session date>"`. Flag any state or context files modified since your last session — they may hold updates from another parallel session or a manual edit you should read before starting.

If `git rev-parse --git-dir` fails, skip this step and continue with the file-based checks.

### 3. Pull live data from Google Workspace (if MCP available)

If the `google-workspace` MCP server is connected, pull live context. Fall back to markdown files if not.

**Calendar — today + next 7 days:**
Use `calendar_events_list` with:
```json
{
  "calendarId": "primary",
  "timeMin": "<TODAY>T00:00:00Z",
  "timeMax": "<TODAY+7>T23:59:59Z",
  "singleEvents": true,
  "orderBy": "startTime"
}
```
Fields: `"items(summary,start,end,attendees)"` — flag anything time-sensitive in the briefing.

**Gmail — unread count (optional):**
Use `gmail_users_messages_list` with `{"userId": "me", "q": "is:unread", "maxResults": 1}` and fields `"resultSizeEstimate"`. Only mention if count is notably high.

**Project trackers (if configured):**
If you use Google Sheets to track anything (tasks, pipeline, content log), check `<state_dir>/gws-references.md` for configured Sheet IDs and query them here. If the file has no IDs yet, skip this step — see `<state_dir>/gws-references.md` for setup instructions.

### 4. Health checks

Run these quick checks and include any findings in the briefing:

**Stale state files:** scan for the `**Last Updated:**` line in each state file and compare against the configured thresholds:
- `current.md` older than `staleness.current_days` — flag it
- `weekly-priorities.md` older than `staleness.weekly_days` — flag it
- `blockers.md` older than `staleness.blockers_days` — flag it

**Inbox items:** if the project keeps a drop-zone (e.g. `inbox/`) and it holds files (excluding `.gitkeep`), note the count and suggest triaging them.

**Overdue TODOs:** scan `<task_file>` for unchecked items (`[ ]`) with a date that has passed. List any overdue items.

Only mention findings — skip silently if everything is clean.

### 5. Give a briefing
Keep it short:
- Date and day of week
- State freshness (one line if all fresh, individual flags if stale)
- Files changed since last session
- Top 2-3 priorities from `current.md`
- Any time-sensitive open threads
- Any blockers worth flagging
- Calendar highlights for the week (from live data if available)
- Ask: "What's the focus today?"

If resuming today's session, acknowledge what was already covered and pick up from there.

## Design principles

- **Fast.** Under 60 seconds. If it's slow, it won't get used.
- **Skip what's clean.** All fresh, nothing near a deadline → say so in one line.
- **Graceful degradation.** If state files don't exist yet, note it and point at `templates/state/`; outside a git repository, run the file-based checks only; without the MCP server, fall back to the markdown files.
