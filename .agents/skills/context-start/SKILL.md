---
name: context-start
description: Load this workspace's current state, recent decisions, blockers, priorities, and session continuity, then give a concise briefing. Use only when the user explicitly asks to begin or resume a workspace session.
---

# Start a workspace session

Resume from durable repository state instead of reconstructing context from chat history.

## Procedure

1. Run `bash scripts/contextos.sh start` from the repository root. Treat its JSON as
   the deterministic inventory of configured paths, freshness, latest session,
   and repository revision. If the kernel is unavailable, stop and recommend
   `bash scripts/contextos.sh doctor`; do not silently substitute another lifecycle
   implementation.
2. Determine today's local date and day of week. Read `ROUTING.md`, then load:
   - the configured `current.md`;
   - the latest five entries in the configured `decisions.md`;
   - the configured `blockers.md` and `weekly-priorities.md`; and
   - today's session file, or the most recent session when today's does not exist.
3. If this is a git repository, inspect commits since the most recent session
   date and read changed state or context files relevant to today's work.
4. Use only explicitly configured, connected, read-only live sources when they
   materially improve the briefing. Keep queries narrow and fall back to
   repository files. Never activate or authenticate an integration here.
5. Report only actionable health findings, including kernel-reported staleness,
   non-placeholder inbox files, overdue dated tasks, unresolved blockers, and
   deadlines.
6. Give a short briefing with date, state freshness, relevant changes, top two
   or three priorities, time-sensitive threads, blockers, and any scoped
   live-data highlights.
7. If today's session exists, acknowledge it and resume from its latest entry.
   End by asking what to focus on.

Keep this read-only. Do not update timestamps merely because files were read.
