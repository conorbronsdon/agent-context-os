# Context Routing

For tasks without a slash command, use this table to determine which files to load.

## Writing tasks
- Any writing/editing task → read `writing/skills/avoid-ai-writing/SKILL.md`
- Add more writing skills here as you build them (see `docs/agent-template.md` for the pattern)

## Project tasks
- Add a line per project as you build them out
- Example: `[Your Project] work → read projects/[project-name]/[relevant files]`
- See `projects/README.md` for how to structure a project section

## Personal context
- Bio/background → read `identity/who-i-am.md`
- Professional credentials → read `identity/professional-background.md`

## Session management
- Starting a session → `/start`
- Ending a session → `/end`
- Quick checkpoint → `/update`
- Morning check-in → `/today`
- Synthesize session patterns → review `sessions/` logs directly
- Weekly review → read `state/current.md` and `state/weekly-priorities.md`
- Task backlog → read `TODO.md`

## Strategy & reflection
- Thinking through a decision → apply thought-partner mode (see CLAUDE.md)

## Building new skills
- Creating a new skill → read `docs/agent-template.md` for the scaffold and checklist
- Validating skill structure → run `scripts/validate-all.sh`

## Agent migration
- Migrating selected Gemini CLI configuration or workflows → `/migrate-gemini`
- Discovering repeated workflows from selected Gemini sessions → `/mine-gemini-workflows`
