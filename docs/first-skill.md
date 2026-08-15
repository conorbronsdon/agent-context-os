# Write your first skill in 5 minutes

A skill is a recurring task you've turned into a slash command — a short markdown file that tells Claude how to do one job, the same way every time. This starter ships a dozen (`/start`, `/end`, `/capture`, `/find-context`, and more). The fastest way to get your own is to copy one and change three things. Here's the whole thing, start to finish.

We'll turn the included `/find-context` command into a new `/standup` — "what did I do yesterday, what's next, what's blocked." Same shape, different job. Swap in whatever recurring task you keep doing by hand; the steps are identical.

> This builds a **command** (a slash command with no extra files). A full **skill** adds a `SKILL.md` under `projects/<project>/skills/` and a `CLAUDE.md` row so it loads in both Claude Code and claude.ai — see `projects/README.md` once you want that. Start with a command; promote it to a skill when you reach for it often.

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

Want it to reach your real calendar, email, or Drive? That's what MCP servers are for — see **Optional integrations** in the [README](../README.md).
