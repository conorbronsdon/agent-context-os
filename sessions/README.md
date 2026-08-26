# Sessions

This directory holds per-day session notes. The `/start` command checks for a file matching today's date — if one exists, it resumes from where you left off. If not, it reads the most recent file for continuity.

## How sessions work

The session loop: `/start` → work → `/update` (optional) → `/end`

- **`/start`** reads the latest session file and state to give you a briefing
- **`/update`** saves a mid-session checkpoint (use when you've made progress but aren't done)
- **`/end`** writes the session log and updates state files for next time

## Session log format

Files are named `YYYY-MM-DD.md`. The `/end` command creates them with this structure:

```markdown
# Session — 2026-03-07

## What happened
- Built out the new landing page copy
- Decided to drop the FAQ section — too much overlap with docs

## Decisions
- Landing page leads with social proof, not features
- Launch target: next Tuesday

## Next time
- Get feedback from [person] on the hero copy
- Wire up the CTA tracking
```

If you run multiple sessions in a day, `/end` appends a new timestamped section rather than overwriting.

## What to put in a session file

Keep it short. The goal is continuity across sessions, not a full journal:
- What you worked on
- Decisions made or conclusions reached
- Open threads and next actions
- Anything Claude should remember coming in next time

## This directory in git

Session files are personal and often contain work-in-progress notes. You may want to add `sessions/` to `.gitignore` if you'd rather not commit them. The `.gitkeep` file is just here to preserve the directory in the repo.
