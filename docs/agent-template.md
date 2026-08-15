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

## Portable location

Place the workflow above at `.agents/skills/[skill-name]/SKILL.md`. Add `agents/openai.yaml` only when Codex UI metadata is useful. Keep changing project facts in `projects/` and reference them from the workflow.

## Optional Claude command adapter

Place in `.claude/commands/[skill-name].md`. This is what the slash command loads.

```markdown
---
name: [skill-name]
description: [Short description, 20+ chars]
allowed-tools: [Read, Bash, Write, Edit, Glob — pre-approve only what's needed]
---

Read and follow `.agents/skills/[skill-name]/SKILL.md`.
```

---

## Checklist Before Shipping a New Skill

- [ ] SKILL.md has YAML frontmatter with `name` and `description` (60+ chars)
- [ ] Provider-neutral workflow lives under `.agents/skills/`
- [ ] Optional Claude adapter is thin, user-only when it writes, and grants only reviewed tools
- [ ] Optional Codex metadata uses exact explicit invocation when the workflow writes
- [ ] Routing rule added to ROUTING.md if appropriate
- [ ] CHANGELOG.md updated with new files
- [ ] Run `scripts/validate-all.sh` to verify structure

---

## Directory Convention

```
.agents/skills/
└── [skill-name]/
    └── SKILL.md
```

For a Claude-only general-purpose skill:

```
.claude/skills/
└── [skill-name]/
    └── SKILL.md
```

Project-folder workflow documents are context, not natively discovered skills. Use `.agents/skills/[skill-name]/SKILL.md` for the portable source and add a thin `.claude/commands/[skill-name].md` adapter when a Claude slash command is wanted.

Commands always live flat in `.claude/commands/[skill-name].md`.
