# Skill Frontmatter & Behavior Reference

**Snapshot:** 2026-07-13, from https://code.claude.com/docs/en/skills (frontmatter reference + invocation control + lifecycle sections).
**Staleness policy:** this snapshot is pinned. If the date above is >3 months old, warn and continue — do not update it as a side effect of building a skill. The `spec-drift` CI workflow checks weekly and opens an issue when the upstream spec changes; update via a reviewed PR (or when a user explicitly asks).

## Frontmatter fields (all optional)

| Field | Use |
|-------|-----|
| `name` | Display label in listings only. The command name comes from the skill **directory name** (or the file name for `.claude/commands/` files) — not from this field, except plugin-root SKILL.md. |
| `description` | What the skill does + when to use it. Claude matches requests against this. Combined with `when_to_use`, truncated at 1,536 chars in the listing; put the key use case first. If omitted, first paragraph of the body is used. |
| `when_to_use` | Extra trigger phrases/examples, appended to description in the listing (counts toward the same cap). |
| `argument-hint` | Autocomplete hint, e.g. `[issue-number]` or `[filename] [format]`. |
| `arguments` | Named positional args for `$name` substitution. Space-separated string or YAML list; names map to positions in order. |
| `disable-model-invocation` | `true` = only the user can invoke. Removes the description from Claude's context entirely (no ambient cost), prevents preloading into subagents, and (v2.1.196+) blocks scheduled-task invocation. Default `false`. |
| `user-invocable` | `false` = hidden from the `/` menu; Claude-only background knowledge. Menu visibility only — does not block Skill-tool access. Default `true`. |
| `allowed-tools` | Tools pre-approved (no permission prompt) while the skill is active. A grant, **not** a restriction — everything else stays callable under normal permissions. Scope tightly: `Bash(git add *)`. Takes effect in project skills only after workspace trust. |
| `disallowed-tools` | Tools *removed* from the pool while active (e.g. `AskUserQuestion` for autonomous loops). Clears on the next user message. |
| `model` | Model override while active (rest of turn). Same values as `/model`, or `inherit`. |
| `effort` | Effort override: `low`/`medium`/`high`/`xhigh`/`max`. Default: inherits session. |
| `context` | `fork` = run in an isolated subagent; skill body becomes the prompt. Only for explicit tasks — guidelines-only content returns nothing useful. |
| `agent` | Subagent type when `context: fork` (`Explore`, `Plan`, `general-purpose`, or custom from `.claude/agents/`). Default `general-purpose`. Explore/Plan skip CLAUDE.md for a smaller context. |
| `hooks` | Hooks scoped to the skill's lifecycle. |
| `paths` | Glob patterns; auto-load only when working on matching files. |
| `shell` | `bash` (default) or `powershell` for `` !`cmd` `` injection. |

## String substitutions in the body

| Variable | Expands to |
|----------|-----------|
| `$ARGUMENTS` | Full argument string as typed. If absent from the body, args are appended as `ARGUMENTS: <value>`. |
| `$ARGUMENTS[N]` / `$N` | Nth argument, 0-based, shell-style quoting (`"hello world"` = one arg). |
| `$name` | Named arg declared in `arguments:` frontmatter. |
| `${CLAUDE_SESSION_ID}` | Current session ID. |
| `${CLAUDE_EFFORT}` | Active effort level (`low`/`medium`/`high`/`xhigh`/`max`) — adapt instructions to it. |
| `${CLAUDE_SKILL_DIR}` | Directory containing SKILL.md — use for bundled scripts so paths survive install location. |
| `${CLAUDE_PROJECT_DIR}` | Project root (v2.1.196+; also works inside `allowed-tools` rules). |

Escape a literal dollar with backslash: `\$1.00`.

## Dynamic context injection

`` !`command` `` at line start (or after whitespace), or a fenced ```` ```! ```` block for multi-line, runs **before** Claude sees the skill and is replaced by its output. Preprocessing, not model-executed. Disabled repo-wide by `disableSkillShellExecution`.

## Invocation × context loading

| Frontmatter | User invokes | Claude invokes | Context cost |
|--------------|--------------|----------------|--------------|
| (default) | Yes | Yes | Description always in context; body loads on invocation |
| `disable-model-invocation: true` | Yes | No | **Nothing** in context until the user invokes |
| `user-invocable: false` | No | Yes | Description always in context; body loads on invocation |

The skill listing has a context budget (~1% of the context window; least-used skills lose their descriptions first when it overflows). `/doctor` estimates the listing's cost. `skillOverrides` in settings can force a skill to `name-only` or `off` without editing its file.

## Lifecycle notes that change how you write skills

- Once invoked, the rendered body stays in context for the rest of the session and is not re-read — write **standing instructions**, not one-time steps. Re-invocation with identical content is deduped (v2.1.202+).
- After auto-compaction, each invoked skill is re-attached with its first 5,000 tokens, under a 25,000-token shared budget, most-recent first — huge skills lose their tails; re-invoke after compaction if a skill matters.
- Keep SKILL.md under 500 lines; supporting files in the skill directory (templates, examples, reference docs, scripts) load only when needed. Reference them from SKILL.md so Claude knows they exist.
- `.claude/commands/` files still work and take the same frontmatter, but skills are the recommended form (directory + supporting files). If a command and skill share a name, the skill wins.
