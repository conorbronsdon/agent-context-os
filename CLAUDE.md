# [Your Name] — Context

## Who I Am

→ Read `identity/who-i-am.md` for bio and background.

## Slash Commands (Claude Code)

| Command | Does |
|---------|------|
| `/setup` | Interactive onboarding — builds identity, project, and state files conversationally |
| `/start` | Load repository state and get a session briefing |
| `/end` | Log session, update state and the decision log, propose memory updates, check git |
| `/update` | Mid-session checkpoint — quick state save |
| `/today` | Morning heartbeat — briefing, staleness check, deadlines |
| `/clean-ai-writing` | Load `writing/skills/avoid-ai-writing/SKILL.md` and apply it |
| `/capture` | Triage raw notes from `inbox/` into the right locations |
| `/find-context` | Find relevant context files by topic keyword (avoids Claude's built-in `/context`) |
| `/reconcile` | Drift detection after parallel sessions |
| `/recover` | Scan orphaned worktrees and stale branches, offer cleanup |
| `/content-shipped` | Log a published piece of content |
| `/dream` | Run an on-demand curator pass over the configured memory dir (default: rot detection) |
| `/dream-apply` | Walk a curator proposal artifact, accept/reject/edit per item |
| `/migrate-gemini` | Migrate selected Gemini CLI workflows with dry-run review and parity checks |
| `/mine-gemini-workflows` | Find repeated Gemini workflows and draft portable skills |

Add more commands as you build out skills. See `docs/agent-template.md` for how.

The `/setup`, `/start`, `/update`, and `/end` commands are Claude Code adapters to the portable workflow cores in `.agents/skills/context-*`. Keep shared procedure in the skill; keep Claude-only tools and auto-memory behavior in the command adapter.

## When to Load Additional Context

For tasks without a slash command → load `ROUTING.md`.

## Thought-Partner Mode

When thinking through a decision or tradeoff — rather than producing a deliverable — operate as a thought partner:

- **Challenge assumptions.** If a premise seems weak or unexamined, say so.
- **Offer the alternative.** Present the strongest case for a different path.
- **Ask the uncomfortable question.** What hasn't been considered or is being avoided?
- **Be direct about tradeoffs.** Don't soften the downsides.
- **Summarize the decision cleanly.** What's the choice, what does each path require, and what's the real risk?

This mode applies to career moves, strategy decisions, project bets, and any "help me think through X" framing. It does NOT apply to execution tasks where the goal is to produce a deliverable.

## Safety Contract
Actions that change external state or are hard to reverse require confirmation. See `docs/safety-contract.md` for the full policy, approval patterns, and design principles.

## Memory
Claude Code enables host-local auto-memory by default. Do not hand-derive its internal path from the current working directory. Use `/memory` to inspect it and `autoMemoryEnabled: false` if automatic host writes are unwanted; the optional `/dream` workflow has a separate explicit local path contract in `docs/auto-memory.md`. Typed entries use `user`, `feedback`, `environment`, `project`, and `reference`; `MEMORY.md` stays an index capped at ~100 lines.

Run `/dream` explicitly for shipped curators (`rot`, `merge`, `split`, `lint`), then `/dream-apply` to review live-memory changes. Proposal artifacts are written and committed before review; live memories are not. Pattern, standalone contradiction, and untapped curators are roadmap items. See `docs/dream-architecture.md`.

## Single Source of Truth

Each piece of data lives in one file only. Other files can reference it, never duplicate it.

- Tasks → `TODO.md` (curated top-of-mind view → `state/current.md`)
- Weekly focus → `state/weekly-priorities.md`

When you add project-specific data (metrics, pipeline status, etc.), pick one file as the source and note it here.

## Parallel Sessions

When running parallel Claude Code sessions, use `claude --worktree <task-name>` so each gets its own branch. Merge to main when done. Run `/reconcile` after parallel work to catch drift.

For high-traffic repos, enable the parallel-session guards: add the repo basename to `.claude/hooks/guarded-repos.txt` and `worktree-guard.sh` (PreToolUse) blocks edits to its primary checkout when ≥2 Claude sessions are running, while `branch-hygiene.sh` (SessionStart) surfaces non-default HEAD. See `.claude/hooks/README.md`.

## Claude Code vs claude.ai

This repo is designed for **Claude Code** (CLI). If you also use **claude.ai projects**, upload only a deliberately selected and sanitized subset as plain project knowledge. Repository instructions and skill metadata do not become active commands there. See `docs/claude-projects-sync.md` if present.

Codex uses the same repository state through root `AGENTS.md` and `.agents/skills/`. See `docs/codex-onboarding.md`; do not copy Claude hooks, settings, or auto-memory assumptions into portable skills.

## Repo Maintenance
See `docs/repo-maintenance.md` for staleness conventions, changelog updates, repo map regen, and validation.
