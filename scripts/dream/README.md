# /dream — on-demand memory curator

Substrate for curator passes against the explicit local directory recorded in `.context-os/memory-directory`. See `docs/auto-memory.md`; never infer the directory from `pwd`.

**Full architectural rationale: `docs/dream-architecture.md`.**

## Usage

```
/dream [curator]              # default: rot. produces a proposal artifact, no apply.
/dream-apply {ISO-timestamp}  # walks the proposal, accept/reject/edit per item.
```

Two curator **classes**: *content* (compare memory against the world — "is it still true?") and *structural* (examine the shape of the memory set itself — "is it well-shaped?").

Curator catalog (build order):
- `rot` (content, v0.1, ships with starter) — flag project memories that no longer match state files / recent commits
- `merge` (structural, v0.2) — consolidate overlapping memories into one entry; collapse redundant index lines (main relief for the MEMORY.md 100-line budget)
- `split` (structural, v0.2) — divide multi-concern files into focused, single-responsibility ones
- `lint` (structural, v0.3) — structural-integrity audit: index/file agreement, duplicates, contradictions, type misfiles, half-finished archives, index-only content (ported from agent-memory-kit, skills-sync#9)
- `pattern` (content, v0.4, planned) — propose new memories from recurring session-log frictions
- `contradiction` (content, v0.5, planned) — flag memory rules giving conflicting guidance
- `untapped` (content, v0.6, planned) — surface session-log themes never raised to memory
- `audit` (content, v0.7, maybe) — flag sessions that ignored MEMORY.md rules

## First-time setup

After using `/memory` and completing the explicit directory contract in `docs/auto-memory.md`, initialize a local git repository there once:

```bash
MEMORY_DIR=$(sed -n '1p' .context-os/memory-directory)
mkdir -p "$MEMORY_DIR/archive"        # retired memories move here
if [ ! -e "$MEMORY_DIR/ARCHIVE.md" ]; then
  printf '# Archive\n\n| Date | Memory | Reason |\n|---|---|---|\n' > "$MEMORY_DIR/ARCHIVE.md"
fi
cd "$MEMORY_DIR"
touch archive/.gitkeep                # git does not track empty dirs
git init
git add -A
git commit -m "initial memory snapshot"
```

`archive/` has to exist before the first retirement: `git mv x.md archive/x.md`
does **not** create it, and fails at exit 128 *after* the tombstone row and the
`archived:` stamp are already written — leaving the half-finished state the
archive procedure exists to prevent.

No remote. The memory dir often contains personal or confidential context.

Validate the binding before the first curator run:

```bash
python3 scripts/dream/validate-memory.py resolve
```

The helper is the safety contract used by `/dream` and `/dream-apply`: it rejects non-canonical memory paths, symlinks, marker mismatches, memory remotes, dirty memory state, unsafe artifact timestamps, control-file targets, duplicate IDs or mutation targets, curator/action mismatches, and proposal paths that escape the memory root. Apply requires an attached local branch and exact changed-path allowlist, binds file modes and bytes to an immutable Git tree and branch identity shown for final approval, and advances only that reviewed ref to the exact tree. Detected tracked, staged, unignored untracked, ref, or concurrent changes stop the operation, and every approved deletion must remain absent even if ignored; the commit cannot absorb anything outside the approved tree.

## Where things live

- **Curator prompts:** `prompts/{name}.md` here
- **Slash commands:** `.claude/commands/dream.md` + `.claude/commands/dream-apply.md` in the repo root
- **Validator:** `validate-memory.py` here, called before artifact creation or apply
- **Proposal artifacts:** `<configured-memory-directory>/.dreams/{ISO}/`
- **Memory git repo:** `<configured-memory-directory>/.git/` (local-only, no remote)

## Adding a new curator

1. Write `prompts/{name}.md` with the curator's role + question + output schema (use `prompts/rot.md` for a content curator, `prompts/merge.md` / `prompts/split.md` for a structural one).
2. Add the curator name to the `/dream` slash command's accepted list.
3. Run `/dream {name}`, review the artifact, iterate the prompt.
4. Update `docs/dream-architecture.md` to mark the curator shipped.

## Automation & backup (optional)

The curator never auto-applies. A run still writes and commits proposal artifacts, so scheduling the *propose* step is an advanced external-write choice, not a no-op. The apply step always stays human-gated.

- **Nudge:** a `SessionStart` hook that warns when memory is stale-curated (days since the last `.dreams/` artifact) is the lowest-risk reminder. It surfaces; it never runs a curator.
- **Unattended (advanced):** schedule a headless run on your platform's scheduler. Two gotchas worth knowing: (1) `claude -p "/dream rot"` does **not** invoke the slash command — print mode treats it as literal text, so pass a plain prompt that points Claude at `.claude/commands/dream.md` (the command file is the spec). (2) Run with `--permission-mode dontAsk` and an `--allowedTools` allowlist that includes the `Bash` tool wholesale (the command issues compound shell commands that prefix-pattern allowlists can't match) — never `bypassPermissions` for an unattended loop. Gate the run so it doesn't collide with an interactive session writing the same memory git.
- **Off-machine backup:** the memory dir is local-only by design (no remote). For machine-loss insurance without a remote, `git bundle create memory.bundle --all` produces a single restorable file (`git clone memory.bundle memory`) you can copy to private storage. Don't push the memory repo to a hosted remote — it usually holds confidential context.

## Why slash commands, not Python

Curator runs inside the existing Claude Code session — no separate API key, easier prompt iteration, structured-tool access for the apply step.
