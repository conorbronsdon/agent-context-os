# Context OS launch copy

Drafts only. Review links, release status, and platform length before publishing.

## Main announcement

I built `agent-context-os` because I was tired of rebuilding the same context across chats, projects, and coding agents.

Context OS is a portable, evolving Git-backed context and workflow layer for
coding agents. Claude Code, Codex, and OpenClaw are first-class; Hermes Agent,
Cursor, and Devin have experimental adapters with explicit evidence limits.

It keeps the durable parts of working with an agent in plain Markdown:

- identity and project context
- current priorities, blockers, and decisions
- reusable workflows
- reviewed session handoffs

v0.13 adds a clean boundary for ongoing application work: Context OS can stay
in its own repository while an attached application contributes read-only Git
evidence. The new workspace reconciliation flow also makes component and bundle
changes reviewable before they touch a workspace.

Concurrent runs can use the new file-backed coordination board for bounded
claims and handoffs. The integration catalog remains opt-in and explicit about
what each add-on can read, write, publish, overwrite, or delete. Setup enables
nothing automatically.

If your AI context is scattered across five places and slowly going stale, this is the problem I want Context OS to solve.

https://github.com/conorbronsdon/agent-context-os

## Short announcement

Context OS is a portable, evolving Git-backed context and workflow layer for
coding agents. Claude Code, Codex, and OpenClaw are first-class; Hermes Agent,
Cursor, and Devin adapters are experimental.

New in this release:

- external-project attachment with a read-only application boundary
- schema v2 workspace reconciliation, composition, rollback, and recovery
- a file-backed coordination board for concurrent agent runs
- a safety-gated catalog of optional integrations

Your durable context stays in files you can inspect, version, and move.

https://github.com/conorbronsdon/agent-context-os

## Changelog post

Context OS update:

v0.13 adds external-project attachment: Context OS keeps its own writable
repository while an application repository contributes read-only Git evidence.
Workspace schema v2 makes reconciliation, composition, rollback, and recovery
explicit. The new coordination board lets concurrent runs record bounded claims
and handoffs without a central service.

Claude Code, Codex, and OpenClaw share the lifecycle core. Hermes Agent, Cursor,
and Devin are separate experimental adapters with their own documented limits.

The optional integration catalog covers portable skill collections, creator
tools, CLIs, and MCP servers. The [generated catalog](../references/integrations.md)
and its entry-local sources, [`integrations/entries/`](../integrations/entries/), are
the current inventory rather than this launch summary. Each entry declares data
access, side effects, confirmation gates, evidence, health checks, and uninstall
behavior.

I also rewrote the onboarding and migration docs around the actual user journey: bring forward selected context, choose a host, add only the tools you need, and keep the result current.

https://github.com/conorbronsdon/agent-context-os

## Experimental starter announcement

Draft only. Verify the starter is available in the linked branch or release
before publishing this copy.

Context OS has an experimental three-file starter for keeping current work and
a handoff beside one project. Copy the files, ask your agent to read them, and
review each saved update. A single instruction file may be enough; the guide
includes a one-week comparison to test whether separate notes earn their upkeep.
The full template remains available for managed lifecycle updates and host
adapters. No human time savings have been measured.

[Read the starter guide](minimal-starter.md).
