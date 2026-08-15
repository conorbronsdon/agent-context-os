# Claude Code auto-memory

Claude Code can maintain a host-local memory store for a git repository. It resolves the default store from the repository, so worktrees and subdirectories can share memory. Do not derive or guess its internal directory by encoding `pwd`; that convention is not this repository's API.

Repository `state/` and `sessions/` are the portable continuity layer. Auto-memory and `/dream` are optional Claude Code extensions and may contain personal or confidential material.

## Inspect first

In Claude Code, use `/memory` to inspect the active memory and its source. If you only want normal Claude auto-memory, no repository setup is required.

The `/dream` and `/dream-apply` commands need a stable, explicit directory because they write proposal artifacts and maintain a separate local git history. Configure that directory only if you want those commands.

## Explicit directory contract for `/dream`

1. Choose a private absolute directory outside this repository.
2. Set Claude Code's `autoMemoryDirectory` to that exact absolute path in the project-local `.claude/settings.local.json`, which this repository ignores. Claude Code also supports other settings scopes, but a local file avoids changing unrelated repositories. Do not commit personal paths.
3. Confirm with `/memory` that Claude Code is using the intended store and that its `MEMORY.md` belongs to this workspace.
4. Record the same absolute path as the only line of the ignored local file `.context-os/memory-directory`.
5. Put the canonical repository root as the only line of `<memory-directory>/.context-os-repository`.

Example setup, after replacing the placeholder and reviewing every destination:

```bash
MEMORY_DIR="/absolute/private/path/to/this-workspace-memory"
REPO_ROOT=$(git rev-parse --show-toplevel)
mkdir -p "$MEMORY_DIR/archive" .context-os
printf '%s\n' "$MEMORY_DIR" > .context-os/memory-directory
printf '%s\n' "$REPO_ROOT" > "$MEMORY_DIR/.context-os-repository"
```

Separately add the reviewed absolute path to `.claude/settings.local.json`:

```json
{
  "autoMemoryDirectory": "/absolute/private/path/to/this-workspace-memory"
}
```

The command adapters fail closed unless all of these are true:

- `.context-os/memory-directory` contains exactly one absolute path;
- that directory contains `MEMORY.md` and `.context-os-repository`;
- the repository marker equals the current canonical git root; and
- the memory directory is its own local git repository before a curator runs.

Moving or renaming the checkout intentionally invalidates the marker. Re-open `/memory`, verify the intended store, and update both local records rather than assuming the old path migrated.

## Storage layout

```text
<configured-memory-directory>/
├── MEMORY.md              # compact index, loaded by Claude Code
├── ARCHIVE.md             # tombstone rows for retired memories
├── .context-os-repository # local checkout binding
├── archive/               # retired detail files
├── .dreams/               # proposal and decision artifacts
└── <topic>.md             # one live detail file per memory
```

`MEMORY.md` is an index, not a journal. Keep one short pointer per detail file and cap it at roughly 100 lines.

## What to save

Use four durable types:

- `user` — role, expertise, goals, and non-obvious preferences;
- `feedback` — confirmed guidance about how to work and why;
- `project` — motivation, deadlines, stakeholders, and decisions not derivable from the repository; and
- `reference` — a pointer to an external system by purpose, without credentials.

Convert relative dates to absolute dates. Treat every remembered fact as a claim that may need re-verification.

## What not to save

Do not save:

- credentials, tokens, recovery codes, or private keys;
- code structure, paths, or conventions already visible in the repository;
- git history or recent-change summaries;
- debugging recipes already captured by the code and commit;
- facts already in `CLAUDE.md`; or
- ephemeral task status that belongs in `state/` or `sessions/`.

If a user asks to remember a temporary list, ask which non-obvious lesson or durable preference is worth retaining.

## Detail-file format

```markdown
---
name: {memory name}
description: {specific one-line relevance hook}
type: {user | feedback | project | reference}
---

{durable content}
```

Then add one line to `MEMORY.md`:

```markdown
- [Title](file.md) — one-line hook
```

Before writing outside the repository, show the proposed detail file and index line and wait for an explicit `save`.

## Curation

`/dream` is user-invoked unless the user separately configures a scheduler. The shipped curators are:

- `rot` — compare project/reference memories with current repository evidence;
- `merge` — consolidate overlapping memories;
- `split` — separate multi-concern memories; and
- `lint` — check index/file agreement, duplicates, contradictions, types, and archive integrity.

Pattern, standalone contradiction, untapped-work, and audit curators are roadmap items.

`/dream` writes and commits proposal artifacts to the local memory git repository before review. It does not modify live memory files. `/dream-apply` walks each proposal and requires a per-item decision before live-memory changes. Neither command may push the memory repository.

See [`memory-template.md`](memory-template.md) for the starter index and [`dream-architecture.md`](dream-architecture.md) for the proposal protocol. Claude Code's current behavior and `autoMemoryDirectory` setting are documented in the official [memory documentation](https://code.claude.com/docs/en/memory).
