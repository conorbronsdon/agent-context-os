---
name: start
description: "Start a session — load state files, flag staleness, and give a briefing on current priorities, deadlines, and blockers"
allowed-tools: "Read, Glob"
disable-model-invocation: true
---

# /start — Claude Code adapter

Read and follow `.agents/skills/context-start/SKILL.md` as the canonical workflow.

This adapter ships without a live-data integration or pre-approved external tools. If the user separately enables a reviewed integration, follow its documented data boundary and normal permission prompts; do not authenticate, change configuration, or broaden access as part of `/start`.
