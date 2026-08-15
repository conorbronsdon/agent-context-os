---
name: update
description: Mid-session checkpoint — append progress to today's session log and update state files if a priority shifted, without ending the session
allowed-tools: Read, Write, Edit, Bash
x-source: skills-sync/commands/update.md
x-source-version: 7ae9852
---

# /update — Quick Checkpoint

Save progress mid-session without closing. Fast and low-ceremony: a log line, plus a state touch only if something actually changed.

**Invocation:** user-timed. A home that packages this core as a skill should set `disable-model-invocation: true` — checkpoints are timed by the user, and the flag also keeps the description out of ambient context.

## Configuration

If the project root carries a `workspace.yaml`, read it. Below, `<state_dir>` and `<sessions_dir>` are its resolved values; the defaults are `state/` and `sessions/`.

## Instructions

### 1. Scan recent conversation
Identify in 30 seconds:
- What was just worked on
- Any decisions made
- Any state changes needed

### 2. Append to session log
Run `date +%Y-%m-%d` for TODAY, `date +%H:%M` for TIME.

Append to `<sessions_dir>/{TODAY}.md`:

```markdown
## Update: {TIME}
- {what was worked on, 1-3 bullets max}
```

Create the file with a header if it doesn't exist yet.

### 3. Update state only if something changed
Only touch `<state_dir>/current.md` if a priority shifted, a thread opened or closed, or a task was completed. Skip otherwise — an `/update` that changed nothing writes only the log line.

### 4. Confirm
One line: "Checkpointed: {brief description}"

## Design principles

- **Fast.** A checkpoint should cost seconds, not minutes.
- **Skip what's clean.** Don't rewrite `current.md` for a checkpoint that changed nothing.
- **Standing rule.** Every `/update` logs first, then decides whether state actually moved — don't invent a state change to justify the run.
