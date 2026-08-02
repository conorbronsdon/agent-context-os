# Changelog

## [Unreleased]

### Fixed
- `scripts/dream/README.md` — first-time setup created `$MEMORY_DIR` but not `archive/`, so anyone following it by hand hit the same exit-128 the apply step was fixed for, after the tombstone row and stamp were already written.
- `commands/dream-apply.md` — the five-step archive procedure could not execute. `git mv` does not create its destination, and `$MEMORY_DIR` is its own git repo, so the move now runs `mkdir -p` then `git -C "$MEMORY_DIR" mv`. Without both it exits 128 *after* the tombstone row and stamp are written, producing the half-finished archive the procedure exists to prevent.
- `commands/dream-apply.md` — the already-archived guard grepped `ARCHIVE.md` for a bare filename, which false-positives on merge survivors and split children (their slugs appear in their own tombstones while the files stay live), and grepped the root path for `^archived:`, which cannot match a correctly-archived file because it has moved.
- `commands/dream-apply.md` — the moved file's own outbound links were never repointed, so every archived file's references silently broke on the move.

### Changed
- `docs/auto-memory.md`, `docs/memory-template.md` — storage layout and retirement steps updated for `archive/`; these are not in the fanout manifest and were missed by the previous publish.
- `scripts/dream/prompts/{rot,merge,split}.md`, `docs/dream-architecture.md` — curator inputs now exclude `memory/archive/`.
### Added
- `docs/assets/start-demo.gif` — animated `/start` demo embedded at the top of the README's "See it work" section. Representative VHS rendering of a `/start` session against the included example musician project (sample data): the state files load in the order `commands/start.md` specifies, then the session briefing comes back.
- `scripts/check-links.sh` — deterministic broken-link checker. Walks every inline link in tracked markdown, skips fenced/inline code and external URLs, and fails on any local target that doesn't resolve. Pure bash + awk + git; catches SSOT drift when a cross-referenced file is renamed or moved. Wired into `.github/workflows/validate.yml`.
- `docs/first-skill.md` — five-minute hand-held tutorial: copy a command, change three things, run it. Lowers the activation barrier for building your first skill.
- `/end` step 6 — **Propose auto-memory updates.** `/end` now scans the session for durable, cross-conversation patterns and proposes 0–2 additions to Claude Code's auto-memory (`MEMORY.md`), with a friction-point check ("was there a friction point a memory entry would have prevented?"). Closes the capture→curate loop: the repo shipped the auto-memory spec and `/dream` curation, but nothing in the daily loop wrote to memory.
- `/today` — upgraded from a thin staleness check to a proper heartbeat: a `git log` scan that catches work from sessions closed without `/end`, escalating staleness tiers (7d "still relevant?" / 14d "remove or convert"), deadline surfacing from `TODO.md`, a structured output block, and a `state/heartbeat-log.md` entry per run. Memory-gap detection deliberately left to `/dream` so two commands don't both edit memory.
- `/capture` — now proposes a triage plan and waits for approval before moving anything (propose-don't-act), and gains a Design Principles section. Classification table kept generic.
- `/context` — adds a `tags:` frontmatter convention with tag-first ranking, a ranked output with match-type markers and line counts, and a "first 30 lines if >3 selected" efficiency pass.
- `/reconcile` — brought up to the stronger generic version: cross-branch `git log --graph` + stash scan, per-file conflict diffing, state-consistency and orphaned-reference checks, an SSOT pass wired to `check-links.sh`, a structured report, and Design Principles.
- `/start` — adds a "what changed since last session" `git log` scan so updates from a parallel session or manual edit surface before the briefing.
### Removed
- **`REPO_MAP.md` is no longer committed or CI-gated.** It's now gitignored and generated on demand (`scripts/generate-repo-map.sh`) as a local overview for claude.ai uploads. The "REPO_MAP up to date" CI gate was structurally unsatisfiable — the file embeds the HEAD commit hash and a per-file date column that advances on every commit — so it had failed on every run. `fetch-depth: 0` and the PR-template checklist item dropped with it.
### Added
- `docs/assets/og-image.{svg,png}` — social-preview card (1280×640), updated to the `claude-context-os` name, the new "operating system" tagline, and the correct URL. The old preview still showed `claude-context-starter`. Upload the PNG via Settings → Social preview.
### Changed
- **Renamed `claude-context-starter` → `claude-context-os`** (old GitHub URLs redirect). Self-references, About, and topics updated to the "os" framing.
- `.github/workflows/validate.yml` — adds a "Check for broken local links" step; deepens checkout (`fetch-depth: 0`) and ignores the volatile REPO_MAP header so the long-broken "REPO_MAP up to date" gate can pass; bumps `actions/checkout` to v5.
- `README.md` — centered hero + badge row (stars, MIT, Built-for-Claude-Code, live CI status, X), a "See it work" `/start` demo, a "Start small" nudge, a License section, the first-skill tutorial link, and `check-links.sh` in the Validation section.

## [0.9.0] — Parallel-session hooks + skill-creator
### Added
- `.claude/hooks/worktree-guard.sh` — `PreToolUse` hook that blocks `Edit`/`Write` to a guarded repo's primary checkout when ≥2 Claude sessions are running. Allows worktrees. Emergency override via `.allow-shared-edit` at the repo root.
- `.claude/hooks/branch-hygiene.sh` — `SessionStart` hook that surfaces non-default HEAD on guarded repos (last commit, uncommitted count, ahead/behind vs default). Stays quiet on freshly-created worktrees (clean tree + commit < 2 min old).
- `.claude/hooks/guarded-repos.txt` — config file listing repo basenames the parallel-session guards apply to. Both hooks no-op until at least one repo is listed.
- `skills/skill-creator/SKILL.md` — meta-skill that generates a new skill from a plain-language description: clarifies inputs/outputs, drafts the SKILL.md + command file + CLAUDE.md additions, runs a pre-ship checklist, asks before committing.
- `commands/skill-creator.md` — `/skill-creator` slash command that loads the skill.
### Changed
- `.claude/hooks/README.md` — adds the parallel-session guards to the file table, adds an "enable" section, adds both new hooks to the `settings.local.json` example.
- `README.md` — command table adds `/skill-creator`; file tree includes `skills/` and notes the parallel-session guards; new "Running multiple Claude sessions" section explains the hooks; "Skills work everywhere" promotes `/skill-creator` over manual scaffolding.
- `CLAUDE.md` template — command table adds `/skill-creator`; "Parallel Sessions" section points at `.claude/hooks/guarded-repos.txt` and the two guard hooks.

---

## [0.8.0] — Auto-memory + dream curator substrate
### Added
- `docs/auto-memory.md` — spec for Claude Code's auto-memory: four typed entries (`user`, `feedback`, `project`, `reference`), what to save / NOT save, body structure with **Why:** + **How to apply:** lines, two-step write (detail file + index pointer), 100-line MEMORY.md cap
- `docs/memory-template.md` — seed `MEMORY.md` template with one-line example pointers per type + first-time setup
- `docs/dream-architecture.md` — three-layer design (inputs → curator pass → proposal artifact → human-gated apply), curator catalog (rot v0.1 ships, pattern/contradiction/untapped/audit planned), proposal schema, local-only memory git rationale, risks + mitigations
- `commands/dream.md` — `/dream {curator}` slash command. Default curator: `rot`. Derives memory dir from pwd, gathers inputs (read-only), writes `proposals.json` + `REPORT.md` + `inputs.json` to `memory/.dreams/{ISO}/`, commits to memory git
- `commands/dream-apply.md` — `/dream-apply {ISO}` slash command. Walks proposals with `AskUserQuestion`, supports Accept / Reject / Edit-then-accept / Skip-rest, applies `modify`/`archive`/`add`/`flag` actions, writes `applied.json`, commits to memory git
- `scripts/dream/README.md` — usage, first-time setup (init memory git, no remote), how to add new curators
- `scripts/dream/prompts/rot.md` — rot-detector curator prompt: role, inputs, classification rules, required-evidence rule, output schema (`proposals.json` + `REPORT.md`)
### Changed
- `README.md` — opening paragraph now leads with auto-memory + `/dream` as the second-most-distinctive thing the starter ships; new "Auto-memory" section with the four types and curator overview; command table adds `/dream`, `/dream-apply`, `/recover`; file tree shows `scripts/dream/` and the external memory dir layout
- `CLAUDE.md` template — command table adds `/dream` + `/dream-apply`; new "Memory" section points at `docs/auto-memory.md` + `docs/dream-architecture.md`

---

## [0.7.1] — Safety contract and /recover
### Added
- `docs/safety-contract.md` — centralized policy for actions requiring confirmation (approval patterns, advisory warnings, design principles)
- `commands/recover.md` — scan orphaned worktrees and stale branches after crashes, offer safe cleanup
- `CLAUDE.md` — added `/recover` to command table, added safety contract reference

---

## [0.7.0] — Infrastructure, hooks, state layer, and new commands
### Added
- `scripts/pre-commit-hook.sh` — pre-commit hook: validates skills, guards CLAUDE.md size, warns on large context files, blocks secrets
- `scripts/setup.sh` — first-run setup: installs hook, makes scripts executable, generates repo map, checks tools
- `scripts/generate-repo-map.sh` — auto-generates REPO_MAP.md from directory structure
- `REPO_MAP.md` — auto-generated file/directory map
- `.github/workflows/validate.yml` — CI: skill validation on push/PR, REPO_MAP freshness check
- `.github/PULL_REQUEST_TEMPLATE.md` — PR checklist for skills, commands, and repo hygiene
- `.claude/hooks/session-start.sh` — advisory SessionStart hook: surfaces stale state, inbox items, overdue TODOs
- `.claude/hooks/ssot-guard.sh` — advisory PreToolUse hook: warns when editing SSOT files
- `.claude/hooks/README.md` — hook documentation with settings.local.json example
- `state/decisions.md` — append-only decision log template
- `state/blockers.md` — active blockers tracker template
- `state/heartbeat-log.md` — /today morning briefing log template
- `inbox/` — drop zone for unstructured notes, triaged by /capture
- `content/log.md` — published content log template
- `commands/capture.md` — /capture: triage inbox items into correct locations
- `commands/context.md` — /context: find relevant context files by topic keyword
- `commands/reconcile.md` — /reconcile: drift detection after parallel sessions
- `commands/content-shipped.md` — /content-shipped: log published content
- `references/notion-mcp-setup.md` — Notion MCP server setup guide
### Changed
- `CLAUDE.md` — added new commands to table; added parallel session guidance; added Claude Code vs claude.ai routing note; added generate-repo-map.sh to repo maintenance
- `README.md` — updated file tree with all new files; added setup.sh to setup steps; expanded command table with new commands

## [0.6.0] — Session lifecycle, validation, and skill scaffolding
### Added
- `commands/end.md` — `/end` command: log session, update state files, close the session loop
- `commands/update.md` — `/update` command: mid-session checkpoint for quick state saves
- `commands/today.md` — `/today` command: morning heartbeat with staleness checks and calendar
- `TODO.md` — canonical task backlog template (separate from state/current.md top-of-mind view)
- `docs/agent-template.md` — reusable scaffold for building new skills: SKILL.md template, command file template, pre-ship checklist
- `scripts/validate-skills.sh` — validation script: checks frontmatter, CLAUDE.md line count, secrets, staleness
### Changed
- `CLAUDE.md` — added `/end`, `/update`, `/today` to command table; added Single Source of Truth rules; added line limit convention; pointed skill creation at `docs/agent-template.md`
- `ROUTING.md` — added session management section; added skill-building section with agent-template reference
- `README.md` — updated file tree; added Session Lifecycle and Validation sections; documented the full session loop
- `sessions/README.md` — added structured session log format and `/end` integration guidance

## [0.5.0] — Skill infrastructure and housekeeping
### Added
- `commands/clean-ai-writing.md` — command file for `/clean-ai-writing`; also serves as the minimal command file pattern example
### Changed
- `writing/skills/avoid-ai-writing/SKILL.md` — added `upstream` frontmatter field and visible note pointing to https://github.com/conorbronsdon/avoid-ai-writing
- `projects/README.md` — documented full skill frontmatter spec: `requires`, `allowed-tools`, `upstream` fields with table, minimal example, and full example
- `references/gws-mcp-setup.md` — replaced hardcoded date with placeholder
- `CLAUDE.md` — `/clean-ai-writing` routing now points explicitly to skill file path instead of describing the task
- `README.md` — file tree updated to include `sessions/`, `state/gws-references.md`, `commands/clean-ai-writing.md`

## [0.4.0] — Broken references, missing files, and clarity fixes
### Added
- `.gitignore` — excludes .DS_Store, editor files, secrets, logs
- `sessions/` directory with `.gitkeep` and `sessions/README.md` explaining the session log pattern
- `state/gws-references.md` — template for storing Google Sheet/Drive IDs used by `/start`
### Changed
- `SETUP-PROMPTS.md` — intro updated to cover both Claude Code and claude.ai; Prompt 2 retitled "Set up your first project" with a note that questions are musician-specific and Prompt 3 is generic; Tips de-musician-ified
- `commands/start.md` — sessions reference updated to handle empty directory gracefully; gws-references step updated to degrade gracefully if no IDs are configured yet
- `projects/example-musician/README.md` — slash commands section now explains the commands/ pattern and links to Prompt 3 for automated setup

## [0.3.0] — claude.ai sync docs and cross-interface positioning
### Added
- `docs/claude-projects-sync.md` — dedicated guide for keeping claude.ai projects in sync: what to upload, how skills work in claude.ai, staying current, multi-project patterns
### Changed
- `README.md` — opening reframed to lead with cross-interface value; Step 5 updated to point to sync doc; new "Skills work everywhere" section with avoid-ai-writing as the concrete example
- `docs/migration-guide.md` — Part 3 condensed; links to claude-projects-sync.md for ongoing workflow

## [0.2.0] — Setup prompts
### Added
- `SETUP-PROMPTS.md` — four interactive prompts: fill in identity, set up musician project, build any new project section, refresh weekly state

## [0.1.0] — Initial template
### Added
- `CLAUDE.md` — main context file with slash commands and thought-partner mode
- `ROUTING.md` — context routing table
- `identity/who-i-am.md` — personal bio template
- `identity/professional-background.md` — credentials template
- `writing/skills/avoid-ai-writing/SKILL.md` — AI writing pattern audit skill
- `projects/README.md` — guide for building project sections
- `projects/example-musician/` — example project: musician promotion workflow
- `references/gws-mcp-setup.md` — Google Workspace CLI setup guide
- `state/current.md` — session state template
- `state/weekly-priorities.md` — weekly priorities template
- `commands/start.md` — /start session command
- `.mcp.json` — Google Workspace MCP server config
