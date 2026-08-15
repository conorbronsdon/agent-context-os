# Write your first portable skill in 5 minutes

A skill is a reusable instruction file. Provider-neutral procedures live under
`.agents/skills/`; Codex discovers them there, while this repository gives
Claude Code thin slash-command adapters where needed. Start with the portable
procedure and add a host adapter only for host-specific presentation or tool
permissions.

This example builds a read-only standup skill. It reads repository state and returns a three-line briefing; it does not change files or call external services.

## 1. Look at a portable skill — 30 sec

Open `.agents/skills/context-start/SKILL.md`. A portable skill has frontmatter
followed by a focused procedure:

```markdown
---
name: context-start
description: Load this workspace's current state, recent decisions, blockers, priorities, and session continuity, then give a concise briefing. Use only when the user explicitly asks to begin or resume a workspace session.
---

# Start a workspace session

<!-- Procedure abridged here; open the source for the complete workflow. -->
1. Read the minimum relevant repository state.
2. Summarize the current objective and next action.
3. Keep the workflow read-only.
```

- The block between the `---` lines is portable frontmatter. Keep only the
  skill name and a concrete description of what it does and when to invoke it.
- Everything below is the procedure. Keep provider-specific paths, grants, and
  UI behavior out of this file.

## 2. Create the new skill — 30 sec

The directory name is the skill name:

```bash
mkdir -p .agents/skills/standup
```

Create `.agents/skills/standup/SKILL.md`:

```markdown
---
name: standup
description: Summarize the latest session and current state as a three-line standup when the user explicitly asks for a standup briefing.
---

# Standup

1. Read the latest dated file in `sessions/` and `state/current.md`.
2. Return exactly three labeled lines:
   - **Shipped** — the most important completed result.
   - **Next** — the single most important next action.
   - **Blocked** — the current blocker, or `nothing recorded`.
3. Do not modify files, infer live external data, or list lower-priority work.
```

Keep project facts in `projects/<project>/context.md` and reference that path from the procedure. Do not duplicate changing project facts inside a reusable skill.

## 3. Add optional Codex presentation metadata

Codex discovers repository skills under `.agents/skills/`. If you want explicit UI metadata, add `.agents/skills/standup/agents/openai.yaml` with a reviewed prompt that invokes the exact skill token and disables implicit invocation:

```yaml
interface:
  display_name: Standup
  short_description: Summarize repository state as a focused standup.
  default_prompt: Use $standup to summarize the latest session and current state.
policy:
  allow_implicit_invocation: false
```

Run it in Codex by explicitly invoking `$standup`.

## 4. Add an optional Claude Code adapter

Claude Code project slash commands live in `.claude/commands/`. A thin adapter points to the portable skill rather than copying its body. Create `.claude/commands/standup.md`:

```markdown
---
name: standup
description: "Summarize the latest session and current state as a focused standup"
allowed-tools: "Read, Glob"
disable-model-invocation: true
---

Read and follow `.agents/skills/standup/SKILL.md`.
```

Run it in Claude Code with `/standup`. `allowed-tools` is a pre-approval grant, not a restriction, so keep it narrow. The user-only invocation gate prevents a write-capable lifecycle command pattern from being triggered implicitly.

## 5. Validate and inspect

```bash
bash scripts/validate-all.sh
git diff -- .agents/skills/standup .claude/commands/standup.md
```

Test each host you claim. A portable file layout does not prove that another agent has equivalent discovery, invocation, permission, or tool behavior.

## 6. Add project routing only when needed

If the workflow is project-specific, add a concise route to `ROUTING.md`, for example:

```markdown
| Standup, current status, or next action | Read `state/current.md`, then use `$standup` |
```

Want it to reach your calendar, email, or Drive? Review the data and side-effect boundaries under **Optional integrations** in the [README](../README.md) before connecting a tool.
