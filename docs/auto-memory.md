# Claude Code auto-memory

Claude Code can maintain a host-local memory store for a git repository. It resolves the default store from the repository, so worktrees and subdirectories can share memory. Do not derive or guess its internal directory by encoding `pwd`; that convention is not this repository's API.

Repository `state/` and `sessions/` are the portable continuity layer. Auto-memory and `/dream` are optional Claude Code extensions and may contain personal or confidential material.

## Inspect first

In Claude Code, use `/memory` to inspect the active memory and its source. Claude Code enables auto-memory by default and may write it automatically during ordinary sessions. That host behavior is separate from this repository's approval-gated `/end`, `/dream`, and `/dream-apply` flows. If you do not want automatic host memory, set `autoMemoryEnabled` to `false` in the intended Claude settings scope and verify the result with `/memory`.

The `/dream` and `/dream-apply` commands need a stable, explicit directory because they write proposal artifacts and maintain a separate local git history. Configure that directory only if you want those commands.

## Explicit directory contract for `/dream`

1. Choose a private absolute **local** directory outside this repository. UNC paths (`\\server\share`) and Win32 device paths are rejected: the validator resolves the recorded value, and resolving a network path named in a file would reach out to that host. This is enforced, not just advised: a store inside the working tree or the git directory is rejected, because private memory in a shared checkout is one `git add -A` from being staged.
2. Set Claude Code's `autoMemoryDirectory` to that exact absolute path in the project-local `.claude/settings.local.json`, which this repository ignores. Claude Code also supports other settings scopes, but a local file avoids changing unrelated repositories. Do not commit personal paths.
3. Confirm with `/memory` that Claude Code is using the intended store and that its `MEMORY.md` belongs to this workspace.
4. Record the same absolute path as the only line of the ignored local file `.context-os/memory-directory`.
5. Put the resolved git common directory as the only line of `<memory-directory>/.context-os-repository`. That identity is stable across linked worktrees, unlike a checkout root.

Steps 4 and 5 are what `bind` does for you:

```bash
python scripts/dream/validate-memory.py bind   --memory-dir /absolute/private/path/to/this-workspace-memory
```

It writes both recorded files, creates the directory, `archive/`, a git repo,
and `MEMORY.md` if they are absent, and then runs the real validator and prints
its verdict — so a zero exit means the binding actually resolves, not that the
command finished. Prefer it to writing the files by hand: both are read by this
same script, and every path bug this setup has had came from a shell and a
Python script disagreeing about how to spell one directory.

It will not overwrite content it did not create, and it refuses to repoint an
existing binding, or to claim a store already bound to another repository,
unless you pass `--force`. Re-running it against the same directory is a no-op.

<details>
<summary>Equivalent by hand</summary>

After replacing the placeholder and reviewing every destination:

```bash
MEMORY_DIR="/absolute/private/path/to/this-workspace-memory"
REPO_ID=$(realpath "$(git rev-parse --path-format=absolute --git-common-dir)")
mkdir -p "$MEMORY_DIR/archive" .context-os
printf '%s\n' "$MEMORY_DIR" > .context-os/memory-directory
printf '%s\n' "$REPO_ID" > "$MEMORY_DIR/.context-os-repository"
```

</details>

These commands run unchanged on macOS, Linux, and Windows under Git Bash. On
Windows they record MSYS-style paths (`/c/Users/...`, and `/tmp/...` for a shell
mount), because that is how bash spells an absolute path there. The validator
translates those to native paths before checking them — the drive-letter forms
directly, anything else via `cygpath`, which ships with Git for Windows. So both
spellings of the same directory are accepted, and the file stays readable in
whichever shell you wrote it from.

The translation is a spelling change only. Every check still applies to the
translated path: it must be absolute, non-symlinked, canonical (no `..`), an
existing directory, and — for the marker — still the same repository. A path
that cannot be translated is left alone and rejected, rather than guessed at.

Separately add the reviewed absolute path to `.claude/settings.local.json`:

```json
{
  "autoMemoryDirectory": "/absolute/private/path/to/this-workspace-memory"
}
```

The command adapters fail closed unless all of these are true:

- `.context-os/memory-directory` contains exactly one absolute path;
- that directory contains `MEMORY.md` and `.context-os-repository`;
- the repository marker equals the resolved git common directory for the current repository; and
- the memory directory is its own local git repository before a curator runs.

They also require the memory repository to be clean before `/dream` or
`/dream-apply` starts. Proposal creation stages only the three validated
artifact files. Apply stages only the exact reviewed change list, binds its
paths, modes, and bytes to an immutable Git tree and records the reviewed local
branch; detached HEAD is rejected. It shows that tree's diff for a separate final
approval, then advances only that reviewed ref to the exact tree through the
validator. Detected tracked, staged, unignored untracked, ref, or concurrent
unrelated changes stop the operation, and every approved deletion must remain
absent even if ignored; the commit itself cannot absorb anything outside the
approved tree.

Linked worktrees share the same git common-directory identity and may therefore use the same memory store, but each worktree needs its own ignored `.context-os/memory-directory` and applicable `autoMemoryDirectory` setting. Moving the repository's common git directory intentionally invalidates the marker. Re-open `/memory`, verify the intended store, and update local records rather than assuming the old path migrated.

## Storage layout

```text
<configured-memory-directory>/
├── MEMORY.md              # compact index, loaded by Claude Code
├── ARCHIVE.md             # tombstone rows for retired memories
├── .context-os-repository # stable git common-directory identity
├── archive/               # retired detail files
├── .dreams/               # proposal and decision artifacts
└── <topic>.md             # one live detail file per memory
```

`MEMORY.md` is an index, not a journal. Keep one short pointer per detail file and cap it at roughly 100 lines.

## What to save

Use five durable types:

- `user` — role, expertise, goals, and non-obvious preferences;
- `feedback` — confirmed guidance about how to work and why;
- `environment` — non-obvious toolchain or platform behavior that is not already documented in the repository;
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
type: {user | feedback | environment | project | reference}
---

{durable content}
```

Then add one line to `MEMORY.md`:

```markdown
- [Title](file.md) — one-line hook
```

For repository-defined `/end` memory proposals, show the detail file and index line and wait for an explicit `save` before writing outside the repository. This gate does not disable or govern Claude Code's default automatic host-memory writes; use `autoMemoryEnabled: false` if every host-memory write must be manual.

## Curation

`/dream` is user-invoked unless the user separately configures a scheduler. The shipped curators are:

- `rot` — compare project/reference memories with current repository evidence;
- `merge` — consolidate overlapping memories;
- `split` — separate multi-concern memories; and
- `lint` — check index/file agreement, duplicates, contradictions, types, and archive integrity.

Pattern, standalone contradiction, untapped-work, and audit curators are roadmap items.

`/dream` writes and commits proposal artifacts to the local memory git repository before review. It does not modify live memory files. `/dream-apply` walks each proposal and requires a per-item decision before live-memory changes. Structural proposal targets are limited to detail files: `MEMORY.md` and `ARCHIVE.md` cannot be archived, merged, split, or created as detail files. Proposal IDs and mutation targets must be unique across an artifact. Neither command may push the memory repository.

See [`memory-template.md`](memory-template.md) for the starter index and [`dream-architecture.md`](dream-architecture.md) for the proposal protocol. Claude Code's current behavior and `autoMemoryDirectory` setting are documented in the official [memory documentation](https://code.claude.com/docs/en/memory).
