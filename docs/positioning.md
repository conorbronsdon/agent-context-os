# Context OS positioning

## Product name

The product name and the repository slug are both **Context OS** (`agent-context-os`). The repository was renamed from `claude-context-os` in August 2026; old GitHub URLs redirect automatically.

## One-line description

Context OS is a Git-backed context and workflow layer shared across Claude Code and Codex.

## The problem

Useful context is scattered across chats, project instructions, memory features, copied prompts, and local configuration. Those copies drift. Users cannot easily review what changed, move to another agent, or distinguish a durable fact from an assistant inference.

## The promise

Keep durable context in files you control. Bring forward selected material from earlier systems, use the same state across supported coding agents, add external capabilities by choice, and maintain the result through reviewed session handoffs.

## Primary audience

People who use coding agents for ongoing work and have enough projects, preferences, decisions, or repeated workflows that rebuilding context has become costly.

This is not a general knowledge base, a replacement for every notes app, or an account-wide memory scraper.

## Four product jobs

1. Import selected useful context without committing an entire private history.
2. Route supported agents to one canonical source for identity, projects, state, and workflows.
3. Add tools through explicit, documented trust boundaries.
4. Keep context current through start, checkpoint, close, staleness, and review workflows.

## Language to use

- Git-backed context
- durable, reviewable state
- provider-neutral workflow core
- explicit host adapter
- selective migration
- opt-in integration
- reviewed handoff
- one canonical source

## Claims to avoid

- "Works everywhere." Name the tested hosts and their limits.
- "Automatic sync." Browser project uploads remain manual unless a specific integration says otherwise.
- "Imports all your memory." Imports are selected, reviewed, and source-limited.
- "Secure by default." Describe concrete controls and data boundaries instead.
- "Verified integration" without the date and evidence scope. Catalog validation checks internal consistency, not continuing upstream truth.
- "Universal agent OS." The repository provides a context and workflow layer, not a complete runtime.

## Feature hierarchy

Lead with the shared repository and lifecycle. Then show migration and portability. Present integrations as optional expansion. Treat Claude Code auto-memory, `/dream`, and hooks as valuable host-specific extensions, not the definition of the whole product.
