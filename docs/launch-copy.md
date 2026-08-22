# Context OS launch copy

Drafts only. Review links, release status, and platform length before publishing.

## Main announcement

I built `agent-context-os` because I was tired of rebuilding the same context across chats, projects, and coding agents.

The project now has a clearer public name: Context OS.

It keeps the durable parts of working with an agent in plain Markdown:

- identity and project context
- current priorities, blockers, and decisions
- reusable workflows
- reviewed session handoffs

Claude Code and Codex can now use the same repository state and the same setup, start, checkpoint, and end workflow. There is also a selective migration guide for bringing useful context forward from ChatGPT, Claude, Gemini, or another assistant without dumping your full private history into Git.

The new integration catalog is opt-in and explicit about what each add-on can read, write, publish, overwrite, or delete. Setup enables nothing automatically.

If your AI context is scattered across five places and slowly going stale, this is the problem I want Context OS to solve.

https://github.com/conorbronsdon/agent-context-os

## Short announcement

`agent-context-os` is now Context OS: a Git-backed context and workflow layer for Claude Code and Codex.

New in this release:

- one shared lifecycle across both coding agents
- a selective migration guide for ChatGPT, Claude, Gemini, and other systems
- a safety-gated catalog of optional integrations
- clearer setup, privacy, and maintenance docs

Your durable context stays in files you can inspect, version, and move.

https://github.com/conorbronsdon/agent-context-os

## Changelog post

Context OS update:

Codex is now a first-class path, not a fork. The same repository state powers `$context-setup`, `$context-start`, `$context-update`, and `$context-end`, while Claude Code keeps its slash-command adapters.

The optional integration catalog now covers portable skill collections and creator tools, plus reviewed paths for Tolaria, Obsidian, Beads, Granola, Google Workspace, Notion, and Substack. Each entry declares data access, side effects, confirmation gates, evidence, health checks, and uninstall behavior.

I also rewrote the onboarding and migration docs around the actual user journey: bring forward selected context, choose a host, add only the tools you need, and keep the result current.

https://github.com/conorbronsdon/agent-context-os
