---
name: setup
description: "Guided onboarding or import for durable workspace context"
allowed-tools: "Read, Write, Edit, Bash, Glob"
disable-model-invocation: true
---

# /setup — Claude Code adapter

Read and follow `.agents/skills/context-setup/SKILL.md` as the canonical workflow.

After the user approves the portable workflow's proposed changes:

- replace the `[Your Name]` placeholder in `CLAUDE.md` when a name was supplied and the placeholder still exists;
- if the user wants a Claude Code slash command for a newly approved portable skill, create only a thin adapter in `.claude/commands/` and add its row to the table in `CLAUDE.md`; and
- offer, but never assume, a commit after showing the final diff and validation result.

Finish by mapping the portable lifecycle back to Claude Code: `/start` begins a session and `/end` closes it.
