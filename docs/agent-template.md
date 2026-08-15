# Portable skill template

Reusable scaffold for provider-neutral skills. Put the canonical workflow under `.agents/skills/`; add a host adapter only when that host needs one.

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

## Optional Claude Code adapter

Place this thin adapter in `.claude/commands/[skill-name].md` only when a Claude slash command is useful. Host permissions belong here, not in the portable skill.

```markdown
---
name: [skill-name]
description: [Short description, 20+ chars]
allowed-tools: "Read"
disable-model-invocation: true
---

Read and follow `.agents/skills/[skill-name]/SKILL.md`.
```

The example is deliberately read-only and user-invoked. Add a write, shell, or external tool only after documenting its exact effect and approval point; never paste a broad convenience grant into a new command.

---

## Checklist before shipping a portable skill

- [ ] SKILL.md has YAML frontmatter with `name` and `description` (60+ chars)
- [ ] Context dependencies and related workflows are named in the body
- [ ] Host-specific tools, permission grants, hooks, and commands stay out of `.agents/skills/`
- [ ] Routing rule added to ROUTING.md if appropriate
- [ ] CHANGELOG.md updated with new files
- [ ] Run `scripts/validate-all.sh` to verify structure

If you add the optional Claude adapter:

- [ ] The command routes to the canonical `.agents/skills/` file
- [ ] Any `allowed-tools` grant is the smallest reviewed set
- [ ] The slash command row is added to the `CLAUDE.md` command table

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

For a provider-neutral skill shared with compatible agents, use `.agents/skills/[skill-name]/SKILL.md` and add a thin `.claude/commands/[skill-name].md` adapter when a Claude slash command is wanted.

Commands always live flat in `.claude/commands/[skill-name].md`.
