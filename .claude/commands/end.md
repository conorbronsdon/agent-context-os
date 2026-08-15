---
name: end
description: "End a session — log what happened, update state and the decision log, propose memory updates, and check for uncommitted or unpushed work"
allowed-tools: "Read, Write, Edit, Glob, Bash"
disable-model-invocation: true
---

# /end — Claude Code adapter

Read and follow `.agents/skills/context-end/SKILL.md` as the canonical workflow.

Before the portable workflow's final handoff, optionally propose zero to two durable Claude Code auto-memory additions:

1. Read `docs/auto-memory.md` for the typed memory rules.
2. Use the explicit `.context-os/memory-directory` contract from that document. Never derive a path from the current working directory. If it is absent or any binding check fails, skip host-local memory writes and explain how to configure them.
3. Prefer confirmed environment quirks, durable working preferences, recurring fixes, or stable project facts.
4. Exclude session-only status, duplicated repository state, credentials, and unverified conclusions.
5. Ask whether a friction point from this session would have been prevented by a durable entry.
6. Show each proposal and wait for an explicit `save` before writing outside the repository. If nothing qualifies, skip silently.

Do not imply that this host-specific memory is shared with other agents. The repository's `state/` and `sessions/` directories remain the portable continuity layer.
