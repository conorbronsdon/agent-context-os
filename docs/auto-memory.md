# Auto-memory

Claude Code reads `~/.claude/projects/<encoded-cwd>/memory/MEMORY.md` automatically at the start of every conversation in that project. The starter uses this to give Claude a persistent, file-based memory that survives across sessions.

This doc is the spec. Add it to your global `~/.claude/CLAUDE.md` (so every Claude session in this project follows it) or copy the relevant rules into this project's `CLAUDE.md`.

## Storage layout

```
~/.claude/projects/<encoded-cwd>/memory/
├── MEMORY.md           ← index, loaded into every conversation (cap 100 lines)
├── ARCHIVE.md          ← tombstone rows, one per retired memory
├── archive/            ← the retired files themselves, each stamped `archived: YYYY-MM-DD`
└── <topic>.md          ← one detail file per memory, loaded on demand
```

`<encoded-cwd>` is your current working directory with `:`, `/`, and `\` replaced by `-`. For example `C:\Users\you\my-context` becomes `C--Users-you-my-context`. Claude Code creates the directory automatically the first time a memory is written.

`MEMORY.md` is an index, not a memory. Each entry is one line — a pointer to the detail file plus a short hook. Detail files load only when relevant.

## What to save (four types)

### user
Information about who the user is — role, goals, knowledge, preferences. Helps tailor responses.

**Save when:** you learn role, expertise, responsibilities, or non-obvious preferences.

**Example:** "Senior backend engineer, deep Go expertise, new to this repo's frontend — frame frontend explanations in terms of backend analogues."

### feedback
Guidance the user gave you about *how to work* — corrections AND validated approaches.

**Save when:** the user corrects your approach ("don't do X") OR confirms a non-obvious choice worked ("yes, that was the right call"). Corrections are easy to spot; confirmations are quieter — watch for them.

**Body structure:**
- The rule, in one sentence
- **Why:** the reason the user gave (often a past incident)
- **How to apply:** when this guidance kicks in

The *why* lets you judge edge cases instead of following rules blindly.

**Example:** "Integration tests must hit a real database, not mocks. **Why:** prior incident where mock/prod divergence masked a broken migration. **How to apply:** any test touching the persistence layer."

### project
Context about ongoing work that isn't derivable from the code or git history — who's doing what, why, by when.

**Save when:** you learn motivation, deadlines, stakeholder context, or decisions.

**Important:** convert relative dates to absolute when saving. "Thursday" → "2026-03-05". Memories outlive the conversation that created them.

**Body structure:** Fact / decision, then **Why:** and **How to apply:** lines.

**Example:** "Merge freeze begins 2026-03-05 for mobile release cut. **Why:** mobile team is cutting a release branch. **How to apply:** flag any non-critical PR work scheduled after that date."

### reference
Pointers to where information lives in external systems.

**Save when:** the user names a tracker, dashboard, channel, or doc by purpose.

**Example:** "Pipeline bugs tracked in Linear project 'INGEST'." / "grafana.internal/d/api-latency is the oncall latency dashboard."

## What NOT to save

These belong in code, git history, or the conversation — not memory:

- Code patterns, conventions, architecture, file paths, or project structure — these can be derived by reading the project.
- Git history, recent changes, or who-changed-what — `git log` / `git blame` is authoritative.
- Debugging solutions or fix recipes — the fix is in the code; the commit message has the context.
- Anything already documented in `CLAUDE.md`.
- Ephemeral state: in-progress work, current conversation context, today's plan.

These exclusions apply even when the user explicitly asks you to save. If they ask you to save a PR list or activity summary, ask what was *surprising* or *non-obvious* about it — that is the part worth keeping.

## How to save

Two steps.

**Step 1 — write the detail file** (e.g., `feedback_testing.md`) with frontmatter:

```markdown
---
name: {memory name}
description: {one-line description — used to decide relevance in future conversations, so be specific}
type: {user | feedback | project | reference}
---

{memory content — for feedback/project, structure as: rule/fact, then **Why:** and **How to apply:** lines}
```

**Step 2 — add a pointer to `MEMORY.md`:**

```markdown
- [Title](file.md) — one-line hook
```

`MEMORY.md` has no frontmatter. It's a flat index, organized semantically by topic (not chronologically). Keep entries to one line under ~150 characters — the index loads on every conversation and excess truncates.

## When to access memories

- When memories seem relevant, or the user references prior-conversation work.
- You MUST access memory when the user explicitly asks you to check, recall, or remember.
- If the user says to *ignore* or *not use* memory, don't apply remembered facts.

Memories can become stale. Before acting on a memory that names a specific file, function, or flag, verify it still exists. The memory is a claim about what was true when it was written — current state is the source of truth.

## Memory budget

`MEMORY.md` loads on every conversation. Cap it at ~100 lines. When approaching the cap, consolidate, or retire a memory: write a tombstone row in `ARCHIVE.md`, stamp `archived: <date>` into the file's frontmatter, and move the file to `archive/`. Detail files are exempt from the cap — they load on demand.

An `ARCHIVE.md` row is not on its own an archive. A row without the stamp and the move leaves the file in the memory root, where every later session reads it as live.

## Curation: /dream

Memory accumulates faster than humans review it. The `/dream` substrate runs autonomous curator passes against the memory dir (rot detection, pattern surfacing, contradiction flagging) and produces a proposal artifact you review with `/dream-apply`. See `docs/dream-architecture.md`.
