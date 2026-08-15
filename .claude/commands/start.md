---
name: start
description: "Start a session — load state files, flag staleness, and give a briefing on current priorities, deadlines, and blockers"
allowed-tools: "Read, Glob"
disable-model-invocation: true
---

# /start — Claude Code adapter

Read and follow `.agents/skills/context-start/SKILL.md` as the canonical workflow.

While performing its optional live-source step, use the `gws` CLI only when it is already installed and authenticated. Every CLI invocation requires the normal tool approval flow so the user can review the exact command and arguments:

- Calendar: list the primary calendar from today through the next seven days with single events ordered by start time; request only summary, start, end, and attendees.
- Gmail: optionally request the unread count only, with `is:unread` and a single-result limit.
- Project trackers: read `state/gws-references.md` and query only identifiers the user placed there.

If the CLI or identifiers are unavailable, continue from repository state without treating that as an error. Do not authenticate, change configuration, use `--page-all` or `--output`, send messages, or write to any connected service.
