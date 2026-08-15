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
- First-time onboarding → Claude Code `/setup`; portable skill `$context-setup`
- Starting a session → Claude Code `/start`; portable skill `$context-start`
- Ending a session → Claude Code `/end`; portable skill `$context-end`
- Quick checkpoint → Claude Code `/update`; portable skill `$context-update`
- Morning check-in → Claude Code `/today`; no Codex equivalent is shipped yet
- Synthesize session patterns → review `sessions/` logs directly
- Weekly review → read `state/current.md` and `state/weekly-priorities.md`
- Task backlog → read `TODO.md`

## Strategy & reflection
- Thinking through a decision → apply thought-partner mode (see CLAUDE.md)

## Building new skills
- Creating a portable skill → use `.agents/skills/<name>/SKILL.md` and keep host adapters thin
- Creating a Claude-only skill → read `docs/agent-template.md` for the scaffold and checklist
- Validating skill structure → run `scripts/validate-all.sh`

## Agent migration
- Importing selected context from an assistant, project, memory export, or account export → read `docs/migration-guide.md`, then use Claude Code `/setup` or portable `$context-setup`
- Migrating selected Gemini CLI configuration or workflows → Claude Code `/migrate-gemini`; portable skill `$migrate-gemini`
- Discovering repeated workflows from selected Gemini sessions → Claude Code `/mine-gemini-workflows`; portable skill `$mine-gemini-workflows`
- Running the workspace in Codex → read `docs/codex-onboarding.md`
