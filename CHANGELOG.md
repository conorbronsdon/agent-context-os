# Changelog

## [Unreleased]

### Added
- External-project attachment now keeps Context OS in its own ContextRoot while
  binding an ordinary application as a read-only WorkingRoot. `project attach`
  and `project rebind` publish digest-bound proposals for a portable tracked Git
  identity plus an ignored machine-local path binding; start, hooks, apply,
  receipts, rollback, and recovery retain exact role boundaries.
- Split-root start reports ContextRoot and WorkingRoot Git evidence separately,
  including bounded application status and history. Claude and Codex lifecycle
  skills use the same provider-neutral kernel contract, while the existing
  colocated v0.12 command form remains compatible.

### Changed
- Aligned integration proposal, contributor guidance, and PR templates with catalog schema v2 (documentation and template changes only).

### Fixed
- The enabled Claude worktree guard now counts exact Claude executable names and identifies linked worktrees from Git's common-directory structure, with must-fire and must-not-fire controls for primary, linked, guarded, unguarded, and single-session paths.
- Release draft staging now creates only after a classified HTTP 404, recovers duplicate-create races without re-uploading, and binds publication and recovery to an operator-supplied positive numeric release ID.

---

## [0.12.0] — 2026-08-31 — Immutable full-template release

v0.12.0 publishes the colocated full-template, full-component-closure contract.
It does not claim external repository attachment or a durable slim workspace
profile; those require later binding and workspace-schema revisions.

### Release contract
- Release qualification now distinguishes deterministic adapter/kernel
  conformance from installed-client execution. Hermes 0.20.5 was installed and
  its deterministic lifecycle passed, but its retained live run did not complete
  model inference; Hermes is experimental and that attempt is not counted as
  successful installed-client conformance.
- Git-index bundle verification now streams locked blobs through one bounded
  `git cat-file --batch` process per pass, retains only requested candidate
  write payloads, discards current-bundle payloads after validation, and removes
  redundant same-boundary apply checks while preserving planner-end and
  immediate pre-mutation source revalidation. Linux and Windows CI report the
  full-bundle Git process, wall-time, and logical payload-memory bounds.
- The v0.12 root contract now names `KernelRoot`, `ContextRoot`, and
  `WorkingRoot`, versions their colocated compatibility mode, separates the
  nominal WorkingRoot path from a possibly enclosing read-only Git evidence
  scope, distinguishes a full-template core-only profile from a marker-only
  bootstrap root using already-loaded executable code, confines lifecycle
  mutation authority to ContextRoot-owned paths, blocks configured content lifecycle
  targets from product-authority namespaces, reserves descriptor-free
  `generic` execution for authenticated agent-config/materialization workflows,
  keeps verified detached-bundle materialization as the explicit
  product-closure boundary,
  and reserves external project
  attachment for a later schema- and receipt-versioned binding.
- Workspace validation treats `.cursor/` as user-extensible while strict
  maintainer validation still requires ownership for every shipped path.
- `doctor` is set-aware when tracked workspace configuration exists. It reports
  support, component materialization, customization limits, local availability,
  onboarding, descriptor drift, declared conformance, and evidence freshness
  independently; inert adapters cannot fail a selected user profile, while
  explicit and maintainer scopes remain strict.
- Runtime descriptors move from schema v1 to the discoverable, incompatible
  schema v2 with surface-specific capabilities, resolution-only probes,
  instruction and skill precedence, typed evidence, generated JSON Schema and
  README support claims, plus strict maintainer and conformance checks.

### Added
- Deterministic v0.12 release tooling and a gated manual workflow build the exact
  full component closure twice from a clean Linux Git index, bind archive, lock,
  version, tag, commit, provenance, and offline instructions, verify candidate
  bytes on Linux and Windows before creating a tag or draft, then verify the
  exact staged assets on both platforms before immutable publication.
- Digest-bound bundle composition and upgrade proposals that materialize binary
  and text component files through the existing journal, receipt, recovery, and
  rollback engine. Clean composition writes workspace configuration in the same
  transaction; upgrades add, replace, or remove only ownership-authorized paths,
  preserve seed content, and record ignored installed-bundle state.
- Detached immutable bundle locks with Git-index-stable raw-byte identity,
  explicit offline digest verification, exact component compatibility, and a
  deterministic read-only structural planner that rejects stale, dirty,
  unavailable, colliding, linked, or implicitly sourced inputs.
- Experimental Devin onboarding with distinct cloud-session and Review
  surfaces, repository-native AGENTS.md and Agent Skills, a managed-account
  setup/doctor boundary, and hostile controls that reject repository claims for
  Blueprints, snapshots, Knowledge, secrets, permissions, or UI state.
- Experimental Cursor onboarding with separate IDE and Agent CLI surfaces,
  native root-instruction and project-skill discovery, explicit lifecycle
  invocation, separate authorization guidance, no hook or memory claim, and
  an opt-in exact-version/flag CLI smoke without unsafe generic-binary detection.
- First-class OpenClaw onboarding with a machine-readable runtime descriptor,
  separate private-workspace boundary, copied lifecycle skills, an external
  alias-bound plugin with explicit `/contextos` invocation, trusted-shell apply,
  and installed-version conformance against `OpenClaw 2026.7.1-2 (0790d9f)`.
- Transactional `agent list`, `agent add`/`enable`, and configuration-only
  `agent disable` commands with idempotent exact-set proposals and no adapter,
  host-state, credential, integration, binary, or context-file mutation.
- Additive multi-agent setup through `scripts/setup.sh --agents`, with TTY
  selection, exact digest-bound approval, local registration of every approved
  runtime, a deprecated singleton alias, and local-only `auto` behavior.
- A reviewed Pandoc catalog entry with a bounded non-PDF profile, explicit network and sensitive-read boundaries, PDF-engine execution guidance, and overwrite confirmation.
- A reviewed MarkItDown MCP catalog entry covering its local-file and network read boundary, unauthenticated localhost transport, sandboxing guidance, and pinned v0.1.7 evidence.
- A reviewed Trello MCP catalog entry covering one authorized workspace plus account-level Inbox and Planner permissions, connected-calendar reads, create/update/move/archive capabilities, and a no-permanent-delete surface.
- A reviewed Shortcut MCP catalog entry for Shortcut's hosted server, with
  granular OAuth scopes, a dedicated read-only mode, and explicit gates for
  workspace-wide sensitive reads and story or document updates (#49).
- Provider-neutral root discovery through validated `contextos.workspace.json`,
  with legacy compound-marker compatibility, nearest-root selection, explicit
  nested Git boundaries, fail-closed invalid markers, and actionable migration
  notices.
- A workflow-specific `agent-config` transaction for workspace migration. It
  creates digest-bound write/delete proposals, revalidates raw target and
  authorization-source hashes under the shared lock, records exact virtual
  ownership plus planned file modes in receipts, restores exact bytes and modes
  after ordinary failures, verifies committed targets before retiring recovery
  evidence, and keeps a durable recovery journal across process interruption.
- Canonical tracked `contextos.workspace.json` with strict set and path
  semantics, whole-document precedence over legacy `workspace.yaml`,
  loss-aware preview-only migration, generated schema validation, and atomic
  machine-local migration from scalar runtime state to `.context-os/hosts.json`.
- An inactive `workspace/example.json` instead of a live root seed, so upgrades
  cannot shadow an existing clone's legacy paths before explicit migration.
- An authoritative component inventory with dependency resolution, exact
  tracked-file ownership, managed/seed/development policies, runtime-reference
  validation, and documented prerequisites for future clean composition.
- Workspace-aware validation that preserves strict maintainer coverage while
  allowing declared user extensions and intentionally removed seed content.
- `CONTRIBUTING.md` — prerequisites, the validator as the one gate, which files are generated, how to add a catalog entry, skill/adapter structure, and the enforced size limits.
- `SECURITY.md` — private reporting path, what is in and out of scope, and the design boundaries most likely to be misread (validation is not a publication guarantee; `verified` is a metadata claim; nothing here sandboxes an agent).
- Issue templates for integration proposals and bug reports, plus contact links routing security reports away from public issues.
- `scripts/check-doc-reachability.sh` — fails when a tracked doc exists that nothing outside `CHANGELOG.md` points to. `check-links.sh` catches a link whose target is gone; this catches a target nothing links to. Wired into `validate-all.sh`.
- A CI job running the Python suite on 3.10, the true minimum. The floor was previously unexercised: the Linux job used the runner default and the Windows job pinned 3.13. Its first run established that the minimum is 3.10 rather than the 3.9 the source reads like — `contextos/kernel.py` calls `Path.write_text(newline=...)`, which is 3.10+.
- Reviewed optional entries for the official GitHub, Linear, and Readwise MCP servers, including read-only starting profiles and explicit sensitive-read, remote-write, publish, overwrite, deletion, OAuth, and destructive confirmation gates.
- Source-neutral onboarding and migration docs for ChatGPT, Claude, Gemini, and other assistants, with a reviewed migration-packet format and optional import handling in `$context-setup`.
- Context OS positioning, launch-copy drafts, a task-based getting-started guide, and a generated cross-agent social preview.
- Safety-catalog entries and current setup guides for Google Workspace CLI and Notion MCP.
- `state/current-log.md`, the seed file required by the shared checkpoint and close workflows.
- A validated, opt-in integrations catalog with generated documentation, explicit credential/data/side-effect boundaries, and no automatic installation or activation. Initial links cover Agent Skills, Agent Workspace, AI Tools for Creators, and Substack MCP.
- Reviewed optional entries for Tolaria MCP, the official Obsidian CLI, Beads for Gemini CLI, and Granola's hosted MCP, with conservative sensitive-read, remote-write, overwrite, deletion, arbitrary-execution, publish, destructive, OAuth, retention, residency, and transcript gates.
- `scripts/contextos.sh` and `scripts/context-os-hook.sh`, thin wrappers that run the lifecycle kernel and hook entry point through `scripts/python-env.sh`. The Codex and Hermes hook adapters and the four lifecycle skills now use them instead of hardcoding `python3`.
- `CONTEXTOS_PYTHON` for pinning an explicit interpreter, documented in the getting-started prerequisites.
- First-class Codex onboarding with a root `AGENTS.md`, four explicit-invocation lifecycle skills under `.agents/skills/`, generated skill UI metadata, `--agent codex` setup support, portability tests, and a host-boundary guide.

### Fixed
- Lifecycle readiness now gives recovery-specific guidance for future-dated
  `state/current.md`, protects shipped `[DATE]` placeholders, and controls
  missing-Git advisory behavior plus exact PowerShell child-exit propagation.
  Start and automatic session hooks keep readiness files no-follow in every
  mode; canonical JSON also rejects a linked configured `state_dir`. The
  documented pre-JSON internal linked `state_dir` exception remains readable
  for compatibility, then snapshots its files without following further links.
  `doctor` now names the link and resolved target and directs migration.
  Direct start, hook, and doctor API calls canonicalize their exact supplied
  root without upward discovery. Diagnostics derive labels only after the
  guard, accept equivalent POSIX symlink, Windows junction/8.3, and canonical
  root spellings, and degrade concurrent path changes to structured diagnostics
  instead of crashing. Initialization and freshness become explicit unknown
  warnings; a required state file that becomes link-like is a failing check and
  makes the doctor CLI exit with status one.
- Git-index materialization now stages the exact index blobs verified against
  the bundle lock, so CRLF checkout transforms, clean/smudge filters, and
  unrelated unstaged source edits cannot replace or invalidate approved bytes.
- Skill validation now prunes ignored Context OS state and dependency
  `node_modules` trees while retaining strict checks for repository skill
  directories, so installed-runtime conformance cannot poison the contributor
  validation gate.
- `doctor` now distinguishes proposal-ID transaction recovery candidates from
  inert `.building`/`.discard` cleanup artifacts, preserving inspect-and-recover
  advice only for the former and giving path-specific, shared-inode-safe manual
  cleanup guidance for the latter. Unsupported atomic deletion no longer implies
  an unchanged retry will self-heal, and retained staging artifacts now receive
  actionable cleanup guidance without depending on journal-only classification.
- Best-effort transaction cleanup now continues across removable siblings after
  retaining a blocked artifact, while strict recovery still surfaces the exact
  cleanup failure. Windows cleanup no longer widens even single-link read-only
  files when atomic deletion is unavailable; it fails closed and reports the
  observed artifact kind and link count without implying an unchanged retry can
  self-heal. Retained garbage in incomplete or retired journal namespaces no
  longer blocks unrelated applies, same-ID journal retries use collision-free
  retired namespaces, and failure diagnostics now describe incomplete
  transaction recovery without implying that restored targets necessarily remain
  incomplete.
- Windows transaction cleanup now removes read-only hard-link names with
  `FileDispositionInfoEx` instead of temporarily widening the shared inode's
  mode, closing the process-death window that could wedge recovery or silently
  make a committed target writable. Hostile fixtures also compare canonical
  paths and stable snapshot boundaries across Python 3.10 and Windows.
- Content lifecycle proposals now bind exact change shapes, displayed diffs,
  and kernel-derived invariant claims, preventing a resigned write proposal
  from smuggling an undisclosed delete action into apply.
- Transaction rollback now restores only targets that still match the
  transaction's exact post-write bytes. Unrecognized concurrent edits are
  preserved and leave the recovery journal intact instead of being clobbered.
- Agent and content lifecycle applies now share path-bound durable journals,
  forward captures, resumable rollback artifacts, and an exact receipt commit
  hash. Process death can be recovered before publication, during rollback, or
  after receipt publication without confusing reverse-order transaction slots.
- Recovery rejects malformed journal entries with a clean diagnostic, runtime
  and component registries reject link-like inputs consistently, while
  transaction publication fails closed when atomic hard links are unavailable.
- The generated workspace JSON Schema now rejects leading and trailing
  whitespace in configured paths, matching the authoritative Python validator.
- `scripts/setup.sh` now preserves LF line endings when its inline Python helpers update `CLAUDE.md` or `ROUTING.md`, keeping Windows setup diffs narrow under `core.autocrlf=false`.
- `docs/optimizing-context.md` and `docs/mcp-efficiency.md` were unreachable — nothing outside the changelog linked them. Both are now in the README documentation table. `docs/launch-copy.md` is linked from `docs/positioning.md`.
- `docs/maintenance.md` and `docs/repo-maintenance.md` gave two overlapping descriptions of the same session and weekly cadence. Each now states its scope and links the other; the workspace cadence lives in `maintenance.md`, repository conventions in `repo-maintenance.md`.
- `tests/test_dream_paths.py` and `tests/test_mine_gemini_workflows.py` now carry `from __future__ import annotations`, matching the seven other Python files that already do.
- Workspace readiness now has one definition. `start`, `doctor`, and the session-start hook share a single predicate keyed on `state/current.md`; previously the hook and `start` could report opposite verdicts for the same workspace. `weekly-priorities.md` and `blockers.md` freshness is still reported, under a separate `state-freshness` check, but no longer gates readiness — leaving them empty is a valid steady state, not an unfinished setup.
- Future-dated `state/current.md` timestamps no longer satisfy the shared readiness predicate, and the native Windows Codex hooks now honor the same `CONTEXTOS_PYTHON` override and Python 3.10 floor as POSIX hooks.
- Calendar-invalid or unreadable state timestamps now report `unknown` instead of crashing `start`, `doctor`, or advisory session hooks; Claude's configured SessionStart adapter now uses the shared readiness predicate too.
- `setup` now stamps `**Last Updated:**` on the state files that `start` and `doctor` read, so a completed setup reports as initialized without depending on the agent to hand-write the line.
- `start`'s `next_action` names the command to run instead of referring to "the explicit setup workflow" abstractly.
- `CONTEXTOS_PYTHON` is honored exactly: an override that does not resolve to a working interpreter now fails loudly instead of silently falling back to a different one. The interpreter floor is Python 3.10, matching the kernel's use of `Path.write_text(newline=...)`, instead of any Python 3.
- `scripts/setup.sh` no longer relies on GNU-only `sed -i`; literal-name replacement and sample-route cleanup now use the documented Python 3 dependency.
- Replaced the deprecated Notion npm-server instructions with Notion's hosted OAuth MCP path for Claude Code and Codex.
- Aligned manual claude.ai setup prompts with portable skill paths and approval-gated local setup instead of claiming slash-command or commit parity.
- Moved project slash commands from the undiscovered root `commands/` directory to `.claude/commands/`; moved the native meta-skill to `.claude/skills/`; renamed `/context` to `/find-context` to avoid the Claude Code built-in.
- Added checked-in `.claude/settings.json` hook activation using the current nested hook schema. PreToolUse guards now parse Claude's JSON stdin, and blocking messages use stderr with exit code 2.
- Gemini mining now folds current `$set`, `$rewindTo`, and message records into final session state; date filters fail closed on unknown dates, tool sequences preserve repetition, and only positively validated patterns become candidates.
- Sensitive miner fields now require explicit session IDs and opt-in flags. Free-form summaries are excluded by default, redaction is labeled best-effort, and provenance uses stable session identity or file content.
- The SSOT advisory hook now emits a visible Claude `systemMessage`; configured worktree guards fail closed when their documented Python 3 parser dependency is unavailable.
- Malformed recordings are ineligible evidence, sensitive extraction rejects duplicate session IDs, provenance separates session identity from immutable recording digests, and candidate thresholds count positively validated sessions only.
- Configured worktree guards now block malformed/missing hook input; the advisory SSOT guard surfaces the same input failure visibly.
- Recording validation now requires Gemini metadata and recognized record shapes, accepts only schema-valid v1 scratchpads with `validationStatus: passed`, deduplicates session identities globally, and derives representative tool sequences only from validated runs.
- Gemini evidence now rejects invalid UTF-8, empty or conflicting identity/scratchpad aliases, boolean scratchpad versions, and excludes every incomplete recording from candidate metrics.
- `scripts/dream/README.md` — first-time setup created `$MEMORY_DIR` but not `archive/`, so anyone following it by hand hit the same exit-128 the apply step was fixed for, after the tombstone row and stamp were already written.
- `.claude/commands/dream-apply.md` — the five-step archive procedure could not execute. `git mv` does not create its destination, and `$MEMORY_DIR` is its own git repo, so the move now runs `mkdir -p` then `git -C "$MEMORY_DIR" mv`. Without both it exits 128 *after* the tombstone row and stamp are written, producing the half-finished archive the procedure exists to prevent.
- `.claude/commands/dream-apply.md` — the already-archived guard grepped `ARCHIVE.md` for a bare filename, which false-positives on merge survivors and split children (their slugs appear in their own tombstones while the files stay live), and grepped the root path for `^archived:`, which cannot match a correctly-archived file because it has moved.
- `.claude/commands/dream-apply.md` — the moved file's own outbound links were never repointed, so every archived file's references silently broke on the move.

### Changed
- **Repository renamed `claude-context-os` → `agent-context-os`.** Self-references updated across the README (badges, clone commands, UTM), docs, setup remote check, test fixtures, and the og-image SVG; old GitHub URLs redirect automatically. Re-render and re-upload `docs/assets/og-image.png` via Settings → Social preview.
- Added an experimental Hermes Agent adapter: an AGENTS.md Hermes section (Hermes loads `AGENTS.md` as project rules), a memory-mapping guide (`docs/memory-across-agents.md`) covering native Hermes memory and its Curator versus repository state and `/dream`, a hooks-equivalents note, and a new [memory across agents](docs/memory-across-agents.md) README row in host support.
- `scripts/setup.sh` now detects and offers to launch Claude Code, Codex, Hermes, Cursor CLI, or OpenClaw (`--agent auto|claude|codex|hermes|cursor|openclaw|none`), with per-host next steps.
- The public product name and repository slug are now `agent-context-os`; historical `claude-context-os` URLs continue to redirect.
- The README now follows the complete user journey: privacy-aware setup, selective import, honest host support, opt-in integrations, maintenance, and a task-based documentation map.
- Repository maintenance now includes session, weekly, monthly, archive, privacy, browser-sync, and integration-review routines, all using `scripts/validate-all.sh`.
- Project, command tutorial, browser-project sync, and context-optimization docs now distinguish portable files from host-specific behavior and remove unsupported token-ratio claims.
- Integration catalog schema v2 adds typed safety capabilities and matching confirmations/risk tags, structured uninstall data-loss declarations, non-empty auditable evidence links, a remote-write/sensitive-read summary, and hostile regression cases. CI validates internal claims and generated documentation; it does not certify upstream source truth.
- `/setup`, `/start`, `/update`, and `/end` are now thin Claude Code adapters to provider-neutral lifecycle skills. Shared state stays in the repository; Claude hooks and auto-memory remain explicitly host-specific.
- CI now runs one aggregate validator covering command discovery/name parity, links, shell syntax, hook behavior, JSON, and Python unit tests.
- `.claude/commands/{start,end,update,today,reconcile,recover}.md` + `.claude/skills/skill-creator/SKILL.md` — republished from the shared core after it ingested its standalone upstreams (core @ `7ae9852`). What rides in: a `workspace.yaml` config layer with per-file staleness thresholds (`/start`, `/update`, `/today`), a decision log with a rejected-alternatives column and a git safety check (`/end`), "prefer evidence of intent over recency" (`/reconcile`), "recent activity means *unknown*, not orphaned" plus a working dirty-worktree removal path (`/recover`), and a never-silently-clobber-an-existing-`SKILL.md` guard (`skill-creator`). `x-source-version` restamped on all seven; `recover` keeps its downstream `allowed-tools` declaration. The republished `skill-creator` links a pinned frontmatter-spec snapshot, so `.claude/skills/skill-creator/references/claude-code-frontmatter.md` now ships alongside it (verbatim from the canonical agent-skill-builder copy).
- `state/decisions.md` — starter rewritten from a `## [DATE]` prose template ("Newest first") to the four-column table `/end` step 5 actually appends (`| Date | Decision | Context / rationale | Rejected alternatives |`, oldest first). Same failure class #12 fixed for `content/log.md`: the starter and the command described two different formats, so anyone following the starter produced a log the command's table append would then break.
- `/content-shipped` + `content/log.md` — both shipped a `## [DATE] — [Title]` prose section: the command told you to prepend one, and `content/log.md` carried a commented-out template of the same shape. They agreed with each other and disagreed with the convention actually in use, which the shared core has carried since 2026-03-13 — one table row per piece. Both now describe that table: `| Date | Type | Title / Description | Platform | Link | Notes |` — a fixed column order is diffable and scannable at a glance, and one row per piece keeps the file greppable by column instead of by prose. The command gains explicit **Date** and **Notes** fields, a `TBD` convention for a link that isn't live yet, and says where the row goes: the last line of the table. `content/log.md` replaces its "Newest first" header line with the append order — oldest first — that the command now follows, and points at the Date column for strict chronology. The `description:` keeps its `blog post` / `LinkedIn post` / `podcast episode` triggers — a republish had dropped all three, and `check-skill-drift.sh` cannot catch that because it hashes the body with frontmatter stripped — and `x-source-version` now names the core revision this copy was actually synced with.

  Ordering reversed: `/content-shipped` prepended (newest first); it now appends (oldest first). Existing logs keep their old rows; new rows land at the bottom. Re-sort by the Date column if you want one direction throughout.
- `docs/auto-memory.md`, `docs/memory-template.md` — storage layout and retirement steps updated for `archive/`; these are not in the fanout manifest and were missed by the previous publish.
- `scripts/dream/prompts/{rot,merge,split}.md`, `docs/dream-architecture.md` — curator inputs now exclude `memory/archive/`.

### Removed
- The obsolete checked-in `gws mcp` configuration and stale MCP setup guide. The pinned upstream revision no longer exposes that command; optional live reads now use read-only OAuth scopes and per-invocation approval instead of wildcard Bash pre-approval.

---

## [0.11.0] — Active harness and migration

### Added
- Privacy-first Gemini migration: `/migrate-gemini`, `/mine-gemini-workflows`, portable `.agents/skills/` cores, a current JSON/JSONL session miner, workflow parity template, tests, and `docs/gemini-migration.md`.
- `references/ai-data-extraction.md` credits [`0xSero/ai-data-extraction`](https://github.com/0xSero/ai-data-extraction) as extraction prior art while documenting format and privacy review boundaries.
- `docs/assets/start-demo.gif` — animated `/start` demo embedded at the top of the README's "See it work" section. Representative VHS rendering of a `/start` session against the included example musician project (sample data): the state files load in the order `.claude/commands/start.md` specifies, then the session briefing comes back.
- `scripts/check-links.sh` — deterministic broken-link checker. Walks every inline link in tracked markdown, skips fenced/inline code and external URLs, and fails on any local target that doesn't resolve. Pure bash + awk + git; catches SSOT drift when a cross-referenced file is renamed or moved. Wired into `.github/workflows/validate.yml`.
- `docs/first-skill.md`: five-minute Claude Code command tutorial: copy a command, change three things, run it.
- `/end` step 6 — **Propose auto-memory updates.** `/end` now scans the session for durable, cross-conversation patterns and proposes 0–2 additions to Claude Code's auto-memory (`MEMORY.md`), with a friction-point check ("was there a friction point a memory entry would have prevented?"). Closes the capture→curate loop: the repo shipped the auto-memory spec and `/dream` curation, but nothing in the daily loop wrote to memory.
- `/today` — upgraded from a thin staleness check to a proper heartbeat: a `git log` scan that catches work from sessions closed without `/end`, escalating staleness tiers (7d "still relevant?" / 14d "remove or convert"), deadline surfacing from `TODO.md`, a structured output block, and a `state/heartbeat-log.md` entry per run. Memory-gap detection deliberately left to `/dream` so two commands don't both edit memory.
- `/capture` — now proposes a triage plan and waits for approval before moving anything (propose-don't-act), and gains a Design Principles section. Classification table kept generic.
- `/find-context` — adds a `tags:` frontmatter convention with tag-first ranking, a ranked output with match-type markers and line counts, and a "first 30 lines if >3 selected" efficiency pass.
- `/reconcile` — brought up to the stronger generic version: cross-branch `git log --graph` + stash scan, per-file conflict diffing, state-consistency and orphaned-reference checks, an SSOT pass wired to `check-links.sh`, a structured report, and Design Principles.
- `/start` — adds a "what changed since last session" `git log` scan so updates from a parallel session or manual edit surface before the briefing.
### Removed
- **`REPO_MAP.md` is no longer committed or CI-gated.** It's now gitignored and generated on demand (`scripts/generate-repo-map.sh`) as a local overview for claude.ai uploads. The "REPO_MAP up to date" CI gate was structurally unsatisfiable — the file embeds the HEAD commit hash and a per-file date column that advances on every commit — so it had failed on every run. `fetch-depth: 0` and the PR-template checklist item dropped with it.

---

## [0.10.0] — `claude-context-os` slug rename and demo

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
