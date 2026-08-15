# Agent Template

Reusable scaffold for building new skills. Use this as a reference when creating skills for your projects.

---

## Skill File Template

```markdown
---
name: [skill-name]
description: [One sentence, 60+ chars, what this skill does and when to use it]
---

# [Skill Name] — [Short Tagline]

[1-2 sentences explaining the skill's purpose and context]

## When to Use

[Bullet list of triggers: what tasks, requests, or keywords activate this skill]

## Before You Start

[What context to gather or load before executing. Reference other files if needed.]

## Instructions

### 1. [First step]
[Detail]

### 2. [Second step]
[Detail]

### 3. [Third step — output/delivery]
[Format specification]

## Output Format

[Describe what the output should look like. Include a template or example if useful.]
```

---

## Command Routing File Template

Place in `.claude/commands/[skill-name].md`. This is what the slash command loads.

```markdown
---
name: [skill-name]
description: [Short description, 20+ chars]
allowed-tools: [Read, Bash, Write, Edit, Glob — pre-approve only what's needed]
---

Load `[path/to/SKILL.md]` and follow its instructions.
```

---

## Checklist Before Shipping a New Skill

- [ ] SKILL.md has YAML frontmatter with `name` and `description` (60+ chars)
- [ ] Command routing file exists in `.claude/commands/` with 20+ char description
- [ ] Slash command row added to CLAUDE.md command table
- [ ] Routing rule added to ROUTING.md if appropriate
- [ ] CHANGELOG.md updated with new files
- [ ] Run `scripts/validate-all.sh` to verify structure

---

## Directory Convention

```
projects/your-project/skills/
└── [skill-name]/
    └── SKILL.md
```

For a Claude-only general-purpose skill:

```
.claude/skills/
└── [skill-name]/
    └── SKILL.md
```

For a provider-neutral skill shared with Gemini CLI and Codex, use `.agents/skills/[skill-name]/SKILL.md` and add a thin `.claude/commands/[skill-name].md` adapter when a Claude slash command is wanted.

Commands always live flat in `.claude/commands/[skill-name].md`.
