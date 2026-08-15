---
name: setup
description: Interactive onboarding — interview the user and build all context files in one conversation
allowed-tools: Read, Write, Edit, Bash, Glob
---

# /setup — Interactive Onboarding

One conversation that replaces manual file editing. Interview the user and build their context files step by step. This command is idempotent — safe to re-run if files already exist (update them with new answers).

## Instructions

### Before you start

Read these files to understand the structure you're filling in:
- `identity/who-i-am.md`
- `identity/professional-background.md`
- `projects/README.md`
- `state/current.md`
- `state/weekly-priorities.md`

Check if any of these files already have real content (not just template placeholders). If so, mention what's already filled in and offer to update rather than overwrite.

### Phase 1: Identity (~3 minutes)

Tell the user: "I'll ask you some questions to build your context files. Answer however feels natural — I'll write the files from your answers."

Ask these questions **one at a time**, waiting for each answer:

1. What's your name, and what do you do in one sentence?
2. What's your current role or main focus?
3. What's your relevant background? (Previous roles, experience, whatever matters)
4. What are you trying to accomplish in the next 3 months?
5. How do you like to work? Any preferences Claude should know about?
6. Anything personal worth knowing — location, life situation, whatever feels relevant?
7. Short bio (2-3 sentences) — how would you introduce yourself?
8. Key credentials or social proof — what establishes your credibility?
9. Where are you online? (Website, social handles)

After all answers:
- Write `identity/who-i-am.md` and `identity/professional-background.md`
- Use their exact words — don't polish or generalize
- Set `**Last Updated:**` to today's date
- Update the `[Your Name]` placeholder in `CLAUDE.md` if it hasn't been replaced yet

Tell them what you wrote. Then move to Phase 2.

### Phase 2: First project (~5 minutes)

Ask: "What's a project you'd want Claude to know about? Something you work on regularly — a side business, a creative project, a content series, a job search, anything recurring."

Then ask **one at a time**:

1. What's the project? One sentence.
2. What are you trying to accomplish? What does success look like?
3. Who's the audience or who does it involve?
4. What are you currently focused on? What are you NOT doing right now?
5. Any decisions already made that Claude should know?
6. What tasks do you do repeatedly for this project?
7. Of those, which ones take the most time or feel the most inconsistent?

After all answers:
- Create `projects/[project-name]/context.md` with permanent background
- Create `projects/[project-name]/strategy.md` with goals and current focus
- For the top 1-2 recurring tasks mentioned, create basic skill files at `projects/[project-name]/skills/[task-name]/SKILL.md`
- Add a line to `ROUTING.md` under the appropriate section
- Set `**Last Updated:**` dates

Ask if they want a slash command for any of the skills. If yes:
- Create the command file in `.claude/commands/`
- Add a row to the slash commands table in `CLAUDE.md`

Tell them what you built.

Ask: "Want to add another project, or move on to setting your priorities?"
- If another project → repeat Phase 2
- If done → move to Phase 3

### Phase 3: Weekly priorities (~2 minutes)

Ask:
1. What are the top 3 things you need to accomplish this week?
2. What are you explicitly NOT doing this week?
3. What does a good week look like — what would you want done by Friday?
4. Anything you're waiting on or blocked by?

After all answers:
- Update `state/current.md` with active priorities
- Update `state/weekly-priorities.md` with this week's focus
- Set dates

### Phase 4: Wrap up

After all phases:
1. Run `bash scripts/generate-repo-map.sh` to update REPO_MAP.md
2. Update `CHANGELOG.md` with what was created
3. Stage and commit all changes with message: "Initial context setup via /setup"
4. Give a summary of everything that was created

Tell them:
- "Run `/start` at the beginning of each session — it loads your state and gives you a briefing."
- "Run `/end` when you're done — it logs what happened so the next session picks up where you left off."
- "To add more projects or skills later, just describe what you need and I'll build it — or re-run `/setup` to update your identity or priorities."
