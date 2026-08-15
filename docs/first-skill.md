# Build your first portable skill

A skill is a reusable workflow with a clear trigger, inputs, procedure, output, and safety boundary. Put provider-neutral workflow logic in `.agents/skills/<name>/SKILL.md`. Add a host adapter only when that host needs its own invocation or tools.

This example builds a read-only standup skill. It reads repository state and returns a three-line briefing; it does not change files or call external services.

## 1. Create the skill directory

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

## 2. Add optional Codex presentation metadata

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

## 3. Add an optional Claude Code adapter

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

## 4. Validate and inspect

```bash
bash scripts/validate-all.sh
git diff -- .agents/skills/standup .claude/commands/standup.md
```

Test each host you claim. A portable file layout does not prove that another agent has equivalent discovery, invocation, permission, or tool behavior.

## 5. Add project routing only when needed

If the workflow is project-specific, add a concise route to `ROUTING.md`, for example:

```markdown
- Acme launch work → read `projects/acme/context.md`
```

One maintained skill used every week is more valuable than ten speculative ones. Start read-only, add writes only when the task requires them, and add a confirmation before every external or hard-to-reverse effect.
