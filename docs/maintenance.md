# Maintain the workspace

Maintenance should keep context accurate and permissions narrow without creating calendar-driven churn. Update a file when meaning changes, not merely to refresh its date.

## Every working session

1. Run `/start` in Claude Code or `$context-start` in Codex.
2. Use `/update` or `$context-update` only when a long session needs a durable handoff.
3. Finish with `/end` or `$context-end` and review the proposed session/state diff.
4. Inspect `git status` and the exact diff. Commit or push only after a separate approval and remote-audience check.

## Weekly

- Re-rank `state/weekly-priorities.md`.
- Remove completed or stale items from `state/current.md` rather than copying the whole backlog.
- Review `state/blockers.md` and `state/decisions.md` for facts whose status changed.
- Make sure active project routes still point to one canonical file.

## Periodically

- Review identity and professional files for facts that are no longer appropriate for the repository's audience.
- Archive completed project context while preserving any durable decision that still matters.
- Inspect optional integration permissions and remove entries that no longer serve a concrete task.
- Review session logs for a genuinely repeatable workflow before creating a skill.
- Run `bash scripts/validate-all.sh` and treat secret scanning as a limited tripwire, not a publication guarantee.

## Portable continuity versus Claude memory

`state/` and `sessions/` are the shared, version-controlled continuity layer for Claude Code and Codex. Claude Code auto-memory is a separate, host-local and often confidential store. It is not copied to Codex or Claude.ai.

If you opt into `/dream`, first configure and verify the explicit path in [`auto-memory.md`](auto-memory.md). Run `/dream` on demand, then inspect its committed proposal artifact. `/dream-apply` is a separate live-memory write workflow with per-item review. The shipped curators are `rot`, `merge`, `split`, and `lint`; later curator designs are not current functionality.

## Moving or renaming the checkout

Repository-relative context continues to work after a normal git move, but host-local memory may not. Use Claude Code `/memory` to inspect the resolved store, then update the explicit local binding. Do not guess or copy an internal path. GitHub redirects also do not migrate local memory.

## Before sharing or publishing

- verify the repository visibility and collaborators;
- inspect tracked history as well as the working tree;
- remove or rotate any exposed credential outside git;
- remember that deleting a file does not erase prior commits; and
- never push host-local memory or ignored migration staging by accident.

See [`getting-started.md`](getting-started.md) for onboarding and [`commands-and-skills.md`](commands-and-skills.md) for the current host matrix.
