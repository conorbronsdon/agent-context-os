# Projects

This directory holds context for recurring personal or professional projects. The pattern is one folder per project, with focused files that supported agents load when a route calls for them.

## Project files

Product memory differs across hosts and can be stale or unavailable. Repository files are the shared, reviewable layer. The more specific and current your project files are, the better an agent can perform on project-specific tasks.

```text
projects/<project-name>/
├── context.md   # purpose, audience, constraints, durable decisions
└── strategy.md  # success, current focus, explicit non-goals
```

Keep these files current and concise. Out-of-date context is worse than missing context. Add a route in `ROUTING.md` so an agent knows when to read them:

```markdown
| Questions about My Project | Read `projects/my-project/context.md` and `strategy.md` |
```

### Step 2: Add a context file

`your-project-name/context.md` — the permanent background a supported agent should know about this project:
- What the project is and what you're trying to accomplish
- Audience, tone, platform (if relevant)
- Key constraints or decisions already made
- Links to external resources (docs, spreadsheets, etc.)

Keep this current. Out-of-date context is worse than no context.

### Step 3: Add a strategy or goals file (optional)

`your-project-name/strategy.md` — higher-level thinking:
- What success looks like
- Current focus and what you're NOT doing
- What's working, what isn't

### Step 4: Add portable skills (optional)

Skills are instruction files an agent loads to perform a specific task consistently. Provider-neutral skills live at:

```
.agents/skills/your-project-name-task-name/SKILL.md
```

## Reusable workflows

**Portable frontmatter:**

| Field | Required | Purpose |
|-------|----------|---------|
| `name` | Yes | Identifier used to reference the skill |
| `description` | Yes | What the skill does and when an agent should use it |

Keep context dependencies, related skills, provenance, and tool requirements in the Markdown body. Do not put host-specific permission fields such as `allowed-tools` or nonstandard dependency fields such as `requires` in a provider-neutral skill. A thin host adapter may declare its own permissions.

Minimal example:
```
---
name: my-skill
description: What this skill does and when to invoke it
---
```

Example with explicit dependencies in the body:
```
---
name: my-skill
description: What this skill does and when to invoke it
---

# My skill

Before starting, read `projects/my-project/context.md` and the related
`writing/skills/avoid-ai-writing/SKILL.md` instructions.
```

### Step 5: Wire it into `ROUTING.md` and optional host adapters

If you want an optional Claude Code slash command:
```
| `/your-command` | brief description |
```
...in the slash commands table in `CLAUDE.md`, and a thin corresponding adapter in `.claude/commands/your-command.md`. Keep tool grants and Claude-only behavior in that adapter, not in `.agents/skills/`.

## Worked example

See `example-musician/` for a worked example of a musician promotion workspace. It covers:
- Artist context and strategy files
- A reference-only social post workflow for consistent platform-native content
- A reference-only press outreach workflow for pitching blogs and playlists

The workflows live under `workflow-examples/` so agents do not discover them as active skills. Copy an example to `.agents/skills/<unique-name>/SKILL.md`, replace the sample paths, and add a host adapter only if needed. Use it as a reference, not a template to copy wholesale.

---

## Tips

- **Start with context, add skills later.** A good context file immediately improves an agent's output. Skills take more time to write and are worth it once you have a repeating task.
- **Update context as the project evolves.** A file that accurately reflects where you are beats a comprehensive file that's two months old.
- **One skill per task.** Don't build a skill that does three things. Build three skills.
- **Write skills for tasks you do at least weekly.** If you're only doing something once, just explain it in the conversation.
