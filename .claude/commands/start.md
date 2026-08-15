---
name: start
description: "Start a session — load state files, flag staleness, and give a briefing on current priorities, deadlines, and blockers"
allowed-tools: "Read, Glob, mcp__google-workspace__calendar_events_list, mcp__google-workspace__gmail_users_messages_list, mcp__google-workspace__drive_files_list, mcp__google-workspace__sheets_spreadsheets_values_get"
disable-model-invocation: true
---

# /start — Claude Code adapter

Read and follow `.agents/skills/context-start/SKILL.md` as the canonical workflow.

While performing its optional live-source step, use the connected `google-workspace` server only when it is already configured:

- Calendar: list the primary calendar from today through the next seven days with single events ordered by start time; request only summary, start, end, and attendees.
- Gmail: optionally request the unread count only, with `is:unread` and a single-result limit.
- Project trackers: read `state/gws-references.md` and query only identifiers the user placed there.

If the server or identifiers are unavailable, continue from repository state without treating that as an error. Do not authenticate, change configuration, send messages, or write to any connected service.
