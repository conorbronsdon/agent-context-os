# Write your first Claude Code command in 5 minutes

A command is a recurring task exposed as a Claude Code slash command. This starter ships several (`/start`, `/end`, `/capture`, `/find-context`, and more). The fastest way to add one is to copy an existing command and change three things.

We'll turn the included `/find-context` command into a new `/standup` — "what did I do yesterday, what's next, what's blocked." Same shape, different job. Swap in whatever recurring task you keep doing by hand; the steps are identical.

> This builds a Claude Code-only command. A portable skill belongs in `.agents/skills/<name>/SKILL.md`, with a thin host adapter only when one is needed. See `projects/README.md` for the shared pattern.

## 1. Look at the one you're copying — 30 sec

Open `.claude/commands/find-context.md`. Every command has the same two parts:

```markdown
---
name: find-context
description: Find relevant context files by topic. Use when you need to load files for a topic without a slash command.
allowed-tools: Read, Glob, Grep, Bash
---

# /find-context — Find Relevant Files by Topic

## Instructions
...
```

- The block between the `---` lines is the **frontmatter**. Its `description` is what shows up when you type `/` in Claude Code, and it's the trigger Claude uses to decide when the command applies — so make it concrete.
- Everything below is the **prompt** — plain instructions, usually a short numbered list. That's the whole command.

## 2. Copy it to a new name — 30 sec

The file name *is* the command name. Copy it:

```bash
cp .claude/commands/find-context.md .claude/commands/standup.md
```

(No terminal handy? Duplicate the file in your editor and rename it.) `standup.md` becomes `/standup`. Lowercase, dashes for spaces.

## 3. Rewrite the frontmatter — 1 min

Open your new `standup.md`. Change `name` to match the file, and rewrite `description` to what this command actually does. Trim `allowed-tools` to only what the job needs:

```markdown
---
name: standup
description: Daily standup — what I shipped yesterday, what's next, what's blocked. Use at the start of a working day.
allowed-tools: Read, Glob
---
```

## 4. Rewrite the steps — 2 min

Now the body. Keep the shape — a title and a short numbered list — and put your job in it. Tell Claude what to read, what to decide, and what to hand back:

```markdown
# /standup — Daily Standup

## Instructions

1. Read the most recent file in `sessions/` and `state/current.md`.
2. Summarize in three lines:
   - **Shipped** — what got done last session.
   - **Next** — the one thing that matters most today.
   - **Blocked** — anything waiting on someone else, or say "nothing."
3. Keep it to those three lines. Don't list everything — just the top of each.
```

Two things make a command work:

- **Be specific about inputs and outputs.** "Read the most recent file in `sessions/`" beats "check my notes." A clear, specific `description` matters for the same reason — it's the trigger.
- **Say what *not* to do.** "Don't list everything — just the top of each" keeps it from rambling.

## 5. Run it — 30 sec

In Claude Code, type `/` and you'll see `standup` in the list. Run it:

```
/standup
```

If it doesn't show up yet, start a fresh session so Claude Code picks up the new file.

## 6. Validate and commit

Run the checks, then commit so your command gets a history like everything else here:

```bash
bash scripts/validate-all.sh
git add .claude/commands/standup.md && git commit -m "Add /standup command"
```

## 7. Make it a habit

One command, run daily for a week, beats ten you set up once and forget. When `/standup` feels automatic, copy it again for the next thing you keep doing by hand. When a command outgrows a single file — it needs its own context, or you want it in claude.ai too — promote it to a skill with `/skill-creator`, which scaffolds the `SKILL.md`, the command file, and the `CLAUDE.md` row for you.

---

Want it to reach your calendar, email, or Drive? Review the data and side-effect boundaries under **Optional integrations** in the [README](../README.md) before connecting a tool.
