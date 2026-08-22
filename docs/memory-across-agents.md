# Memory across agents

Context OS is deliberately not a memory product. It is a Git-backed context layer, and its relationship to each host's native memory feature is worth stating plainly so users do not double-book the same fact in two systems.

## The short version

| Concern | Where it lives |
|---|---|
| Durable facts you want every agent to see | This repository (`identity/`, `state/`, `projects/`) — versioned, reviewable, portable |
| Host-local working memory (one agent's private scratch) | That host's native memory feature |
| Curated long-term memory with provenance and review gates | Repository state plus a reviewed curator workflow |

## Claude Code

Claude Code auto-memory writes machine-local files under `~/.claude/projects/<encoded-cwd>/memory/` automatically. Context OS treats it as a separate layer: `/dream` curates it via proposal artifacts, `/dream-apply` applies accepted changes, and neither governs auto-memory's ordinary automatic writes. See [`auto-memory.md`](auto-memory.md) and [`dream-architecture.md`](dream-architecture.md).

## Hermes Agent

Hermes has two native memory mechanisms that overlap conceptually with parts of this repository:

| Hermes native | Closest Context OS concept | How they differ |
|---|---|---|
| `MEMORY.md` + `USER.md` persistent memory (typed entries, injected every session) | `state/current.md`, `identity/who-i-am.md` | Hermes memory is per-profile and machine-local; repository state is versioned, diffable, and travels with the clone. Keep facts that must survive a machine or agent switch in the repository. |
| Background Curator (usage tracking, staleness detection, archival of skills and memories) | `/dream` rot-detection pass | Both detect drift and propose maintenance. The Curator runs autonomously on Hermes' own stores; `/dream` writes reviewable proposal artifacts before anything mutates. |

Practical guidance for Hermes users:

1. Let Hermes remember session-level preferences natively — do not mirror them into `state/`.
2. Put identity, project briefs, decisions, and priorities in this repository. They are the durable layer.
3. If you run `/dream` against a Hermes memory directory, treat the output exactly as designed: proposals only, reviewed item by item before any write-back.
4. Do not configure the same fact as both a Hermes memory entry and a repository file without picking one canonical home. See the SSOT rule in `AGENTS.md`.

The design bet is the same one described in [`positioning.md`](positioning.md): durable context belongs in files you control, and an assistant's private memory is never the source of truth.
