---
name: skill-creator
description: Generate a new skill from a plain-language description — decides invocation control, arguments, and context cost, then scaffolds, validates, and tests it
x-source: skills-sync/skills/skill-creator/SKILL.md
x-source-version: d66f695
---
<!-- x-source: agent-skill-builder/SKILL.md @ dfe7aa2 -->

# skill-builder — Skills That Don't Rot

Takes a plain-language description of a task and produces a ready-to-ship agent skill. The design goal is skills that are cheap in ambient context and current with the skill spec — most skill generators fail on exactly those two axes: they don't know about `arguments`/`argument-hint`, never suggest `disable-model-invocation`, and write bloated descriptions that tax every session.

## Modes

Parse $ARGUMENTS for a mode; default to `new` when the input is a description.

- **`new <description>`** — scaffold a skill from scratch (the flow below).
- **`review <path>`** — audit an existing SKILL.md against steps 1–3's decision points and run the validator (step 4). Report findings; don't rewrite unless asked.
- **`migrate <path>`** — convert a legacy `.claude/commands/*.md` file into a skill directory: carry the frontmatter over, apply the review checklist, and place supporting content in the directory.

## Before You Start

Read [references/claude-code-frontmatter.md](references/claude-code-frontmatter.md) — a **pinned, dated snapshot** of the skill frontmatter spec, argument substitutions, and context-loading behavior.

Staleness policy: if the snapshot date is more than 3 months old, **warn the user and continue with the pinned snapshot**. Do not re-fetch or modify the reference mid-generation — updating the spec is a maintenance operation (agent-skill-builder's `spec-drift` CI watches for it), not a side effect of building a skill. Only update the snapshot when the user explicitly asks.

Also read the host repo's `CLAUDE.md` and existing skills — avoid duplicating a skill that already exists, and match local conventions.

## Instructions

### 1. Clarify the skill

Ask (or infer from context):

- **Target runtime**: Claude Code (default — full frontmatter feature set) or the portable [Agent Skills](https://agentskills.io) core (`name` + `description` only; keep Claude-specific fields out or document them as optional extensions).
- **Name**: lowercase, hyphenated. In Claude Code the **directory name** under `.claude/skills/` is the command you type; frontmatter `name` is only a display label.
- **Who invokes it** — the most important design decision:
  - **User-only** (side effects, or timing the user controls: publish, send, deploy, log) → `disable-model-invocation: true`. Bonus: the description is then *not* loaded into every session — zero ambient context cost.
  - **Claude-only** (background knowledge, not an action) → `user-invocable: false`.
  - **Both** (default) → the description must carry the trigger keywords, and it becomes a permanent per-session context cost. Make it earn that.
- **Arguments**: does the user pass input on the command line? If yes: set `argument-hint`, and consume `$ARGUMENTS` (or `$0`/`$1`, or named `arguments:`) in the body. Don't make the model guess what the trailing text means.
- **Input/Output**: what does it read (files, MCP data, live command output), what does it produce?
- **Tools**: `allowed-tools` is a *pre-approval grant* (no permission prompts while active), not a restriction — scope entries tightly, e.g. `Bash(git add *)` not `Bash`. Use `disallowed-tools` to actually remove tools.
- **Where it runs**: inline (default — shares conversation context) or `context: fork` + `agent:` for isolated, self-contained tasks. Fork only works when the body is an explicit task, not reference guidelines.
- **Data at load time**: use dynamic context injection (`` !`command` `` at line start) to inline live data (a diff, a status file) before the model reads the skill.
- Only set `model`/`effort` overrides with a specific reason. Use `paths:` for skills scoped to certain files.

### 2. Write the description — the context-budget step

- 1–2 sentences, key use case first, third person, containing the words the user would actually say. Target ~250 chars; the listing truncates at 1,536.
- Detail, steps, and edge cases go in the **body** — the body loads only on invocation, so it's nearly free until used. Never pad the description to be "thorough"; that's the anti-pattern that bloats every session.
- If `disable-model-invocation: true`, the model never sees the description — write it for the human scanning the `/` menu, and keep it short.

### 3. Draft the SKILL.md

Frontmatter template — include only the fields this skill needs (all are optional; see the [reference](references/claude-code-frontmatter.md) for the full table):

```yaml
---
name: [skill-name]
description: [1-2 sentences, triggers first]
argument-hint: "[expected args, e.g. [issue-number] [format]]"   # only if it takes arguments
disable-model-invocation: true    # only for user-triggered workflows
allowed-tools: [tightly-scoped grants]   # only if prompts would be annoying
---
```

Body structure: short purpose line, "When to Use" bullets, numbered step-by-step instructions, explicit output format.

**Quality checklist:**
- [ ] Steps, not paragraph prose; each step names the tool or command
- [ ] Output format defined, not left ambiguous
- [ ] Instructions written as *standing rules* — skill content stays in context for the rest of the session, so "do X once" phrasing goes stale; "always X when Y" doesn't
- [ ] Body under 500 lines; long reference material moved to supporting files in the skill directory, linked from SKILL.md
- [ ] No hardcoded IDs, paths, or credentials — use config files, env vars, or `${CLAUDE_SKILL_DIR}` for bundled scripts
- [ ] Confirmation gate on anything that changes external state (git push, API calls, file deletes)

### 4. Validate

If agent-skill-builder is available locally, run its validator against the generated skill directory:

```bash
python3 <agent-skill-builder>/scripts/validate_skill.py <path-to-skill-dir>
```

It machine-checks what the checklist above describes: frontmatter parses, unknown keys, description budget, `$ARGUMENTS`/`argument-hint` pairing, unscoped `Bash` grants, side-effect commands on model-invocable skills, broken relative links, missing referenced files, body length. Report its output verbatim (PASS/FAIL plus warnings) as part of your deliverable. If Python isn't available, walk the checklist manually and say so.

### 5. Install it

**Before writing anything, check the target path is clear.** If `<install-dir>/<skill-name>/SKILL.md` already exists, stop and show the user the existing file — a skill with that name is already installed. Confirm an overwrite or pick a different name; never clobber an existing SKILL.md silently. (`review` mode is the right tool for improving one that already exists.)

For Claude Code: `.claude/skills/<skill-name>/SKILL.md` is the whole installation — the directory name becomes the command, supporting files live alongside, and changes hot-reload within a session. No routing stub or registry edit is needed. (`.claude/commands/` files still work, but they're the legacy form — that's what `migrate` mode is for.)

Then follow whatever conventions the host repo has: a changelog entry, a command table in CLAUDE.md, a routing doc. Check before assuming none exist.

### 6. Test before shipping

- Confirm it's listed: ask `What skills are available?` (or check `/skills`).
- Invoke it directly (`/name` with realistic arguments) and check the output matches the spec.
- If model-invocable: in a *fresh* session, phrase a matching request naturally and confirm it triggers — then phrase a near-miss and confirm it stays quiet. Leftover authoring context masks trigger gaps, so fresh session matters.
- For skills worth hardening, offer the official eval loop: `/plugin install skill-creator@claude-plugins-official` runs with/without-skill benchmarks and description tuning. (That plugin evaluates output quality; this skill designs and validates structure — they compose.)

### 7. Present for review

Show the SKILL.md, the validator output, and any wiring changes in labeled fenced code blocks. Ask: "Want me to save these, or make any changes first?"

## Tips for Good Skills

- **Be specific over flexible.** A skill that does one thing well beats one that tries to handle every edge case.
- **Spend context deliberately.** Every model-invocable description is loaded into every session. The body is free until invoked. Put things on the right side of that line.
- **Gate destructive actions.** Anything that changes external state should require explicit approval — and consider `disable-model-invocation: true` so the model can't decide to run it because the code "looks ready."
- **Reference, don't duplicate.** If a skill needs data from a file, read the file — don't copy its contents into the skill.
