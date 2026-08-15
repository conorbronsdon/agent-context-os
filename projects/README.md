# Projects

This directory holds canonical context for recurring personal or professional projects. One folder per project keeps durable facts separate from reusable workflow logic.

## Project files

Start with:

```text
projects/<project-name>/
├── context.md   # purpose, audience, constraints, durable decisions
└── strategy.md  # success, current focus, explicit non-goals
```

Keep these files current and concise. Out-of-date context is worse than missing context. Add a route in `ROUTING.md` so an agent knows when to read them:

```markdown
- <Project> work → read `projects/<project-name>/context.md` and `projects/<project-name>/strategy.md`
```

## Reusable workflows

Native portable skills do not live under `projects/<project>/skills/`. Put a reusable workflow at:

```text
.agents/skills/<project-name>-<task-name>/SKILL.md
```

Reference project files from the skill instead of copying their facts. Add optional Codex metadata under the skill's `agents/openai.yaml`, and add a thin `.claude/commands/<name>.md` adapter only when a Claude slash command is useful. See [`docs/first-skill.md`](../docs/first-skill.md).

A workflow document stored inside a project folder is ordinary context. Claude Code, Codex, Gemini, and claude.ai should not be assumed to discover or invoke it as a native skill. It needs an explicit route, host adapter, or manual upload appropriate to that host.

## Worked example

`example-musician/` shows project context plus two workflow documents for social posts and press outreach. Its nested `skills/` files are retained as readable examples, not as natively discovered skills. To activate one, copy its provider-neutral procedure to `.agents/skills/example-musician-<task>/SKILL.md`, update paths, validate it, and optionally add a thin host adapter.

## Practical rules

- Start with context; add a skill after a task repeats.
- Keep one canonical fact in one project file.
- Use one skill per outcome.
- Prefer read-only procedures first.
- Review changed files and run `bash scripts/validate-all.sh` before commit.
