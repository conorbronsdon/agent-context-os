# Memory template

Copy the fenced template below into the exact `MEMORY.md` that Claude Code shows through `/memory`, or into the explicit `autoMemoryDirectory` configured for this workspace. Do not derive the directory by encoding the current working path.

See `docs/auto-memory.md` for the full spec (what to save, what NOT to save, body structure, the two-step write).

---

```markdown
# Auto Memory

## User

<!-- One-line pointers to user_*.md detail files. Examples:
- [Role + expertise](user_role.md) — senior backend, deep Go, new to React side of this repo
-->

## Environment

<!-- One-line pointers to env_*.md detail files (toolchain quirks, platform gotchas). Examples:
- [Windows Git Bash regex](env_git_bash_regex.md) — `grep -P` not supported. Use `sed` in hooks.
-->

## Projects

<!-- One-line pointers to project_*.md detail files (in-flight work, decisions, why). Examples:
- [Auth middleware rewrite](project_auth_rewrite.md) — compliance-driven, not tech debt. Sub-scope decisions favor compliance over ergonomics.
-->

## Feedback

<!-- One-line pointers to feedback_*.md detail files (how the user wants you to work). Examples:
- [No mocked DBs in integration tests](feedback_no_mocked_db.md) — prior mock/prod divergence masked a broken migration.
- [Terse responses, no trailing summaries](feedback_terse_responses.md) — user reads the diff.
-->

## References

<!-- One-line pointers to reference_*.md detail files (external systems by purpose). Examples:
- [Pipeline bug tracker](reference_linear_ingest.md) — Linear project "INGEST"
- [Oncall latency dashboard](reference_grafana_latency.md) — grafana.internal/d/api-latency
-->
```

---

## Conventions

- **One detail file per memory.** Frontmatter: `name`, `description`, and `type` (`user`, `feedback`, `environment`, `project`, or `reference`). Environment entries use the `env_` filename prefix.
- **MEMORY.md is index-only.** One line per entry, under ~150 chars. No frontmatter on this file.
- **Organize by type, then topic.** Not chronologically.
- **Cap at ~100 lines.** When approaching, consolidate, or retire: tombstone row in `ARCHIVE.md` + `archived: <date>` stamp in the file + move it to `archive/`. All three, or the file keeps loading as live.

## First-time setup

Use `/memory` first, then follow the explicit local-path and repository-binding steps in `docs/auto-memory.md`. Copy only the fenced Markdown template above; copying this entire documentation file would create an invalid index.

For `/dream` curator support, also initialize the memory dir as a local-only git repo. See `scripts/dream/README.md`.
