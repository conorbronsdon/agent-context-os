---
name: update
description: "Mid-session checkpoint — append progress to today's session log and update state files if a priority shifted, without ending the session"
allowed-tools: "Read"
disable-model-invocation: true
---

# /update — Claude Code adapter

Read and follow `.agents/skills/context-update/SKILL.md` as the canonical workflow. Treat the slash-command invocation as the user's explicit request to checkpoint this session.
