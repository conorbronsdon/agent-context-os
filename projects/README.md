# Projects

This directory holds context and skills for recurring personal or professional projects. The pattern: one folder per project, with context files Claude loads and skills it can run.

## Why this structure works

Claude doesn't have memory between sessions — it reads files. The more specific and current your project files are, the better it performs on project-specific tasks. A well-built project folder turns a general assistant into something that actually knows your work.

## How to build a project section

### Step 1: Create a folder

```
projects/your-project-name/
```

Name it something short and clear. This becomes how you refer to it in ROUTING.md.

### Step 2: Add a context file

`your-project-name/context.md` — the permanent background Claude should know about this project:
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

### Step 4: Add skills (optional but high-value)

Skills are instruction files Claude loads to perform a specific task consistently. Format:

```
projects/your-project-name/skills/task-name/SKILL.md
```

Each skill file should contain:
- A frontmatter block (see fields below)
- Step-by-step instructions for the task
- Output format
- Examples or calibration notes

**Frontmatter fields:**

| Field | Required | Purpose |
|-------|----------|---------|
| `name` | Yes | Identifier used to reference the skill |
| `description` | Yes | When to load this skill — Claude uses this to decide whether it applies |
| `requires.context` | No | List of context files to read before running |
| `requires.skills` | No | List of other skill files to load alongside this one |
| `allowed-tools` | No | Pre-approve narrowly scoped Claude Code tools while active; this is a grant, not a restriction |
| `upstream` | No | URL of the canonical source if the skill is maintained externally |

Minimal example:
```
---
name: my-skill
description: What this skill does and when to invoke it
---
```

Full example:
```
---
name: my-skill
description: What this skill does and when to invoke it
requires:
  context:
    - projects/my-project/context.md
  skills:
    - writing/skills/avoid-ai-writing/SKILL.md
allowed-tools: Read
---
```

### Step 5: Wire it into ROUTING.md and CLAUDE.md

Add a line to `ROUTING.md` under "Project tasks":
```
- [Project name] work → read `projects/your-project-name/context.md`
```

If you want a slash command:
```
| `/your-command` | brief description |
```
...in the slash commands table in `CLAUDE.md`, and a corresponding file in `.claude/commands/your-command.md`.

---

## Example

See `example-musician/` for a worked example — a musician building out a promotion workflow with Claude. It covers:
- Artist context and strategy files
- A social post skill for consistent platform-native content
- A press outreach skill for pitching blogs and playlists

Use it as a reference, not a template to copy wholesale. Build what's actually useful for your project.

---

## Tips

- **Start with context, add skills later.** A good context file immediately improves Claude's output. Skills take more time to write and are worth it once you have a repeating task.
- **Update context as the project evolves.** A file that accurately reflects where you are beats a comprehensive file that's two months old.
- **One skill per task.** Don't build a skill that does three things. Build three skills.
- **Write skills for tasks you do at least weekly.** If you're only doing something once, just explain it in the conversation.
