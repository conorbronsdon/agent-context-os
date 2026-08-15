# Keeping claude.ai Projects in Sync

Claude Code reads this repo directly from the filesystem. claude.ai projects read from uploaded files in project knowledge. This guide covers how to set that up and keep it current — so both interfaces stay in sync with the same source of truth.

---

## The model

Think of this repo as the source. claude.ai projects are manual consumers. You upload selected files into project knowledge, but browser projects do not provide repository writes, checked-in hooks, or slash-command behavior.

When you update a file in the repo, you re-upload it to the relevant projects. That's the whole sync workflow. It's manual, but it takes about a minute per changed file — and it means you're never editing system prompts in place or guessing what version of your context a project is running.

---

## What to upload to each project

You don't need to upload everything. Upload the files that are relevant to what you do in that project.

**Every project should have:**
- `CLAUDE.md` — your identity, slash commands, and routing rules
- `ROUTING.md` — the full context routing table

**Add based on project focus:**

| Project type | Also upload |
|-------------|-------------|
| General / catch-all | `identity/who-i-am.md` |
| Writing and content | `writing/skills/avoid-ai-writing/SKILL.md` |
| A specific project (music, business, etc.) | `projects/your-project/context.md`, `projects/your-project/strategy.md` |
| Skills-heavy work | The relevant `SKILL.md` files for that work |

A focused project performs better than one loaded with every file. Claude reads what's there — more files means more noise.

---

## How to use skills in claude.ai

In Claude Code, skills run as slash commands: `/clean-ai-writing` loads the `avoid-ai-writing` skill and applies it.

In claude.ai, you don't have slash commands — but you get the same behavior by uploading the skill file. Once `writing/skills/avoid-ai-writing/SKILL.md` is in a project's knowledge, you just ask:

> "Apply the avoid-ai-writing skill to this draft."

Claude can follow provider-neutral instructions in the uploaded skill file. Host-specific tool grants, hooks, paths, and frontmatter do not carry over automatically.

Use this only for skills whose required context and tools are available in the browser project. Upload the `SKILL.md`, then reference it by name in the conversation.

---

## How to upload files

In claude.ai:
1. Open the project
2. Project knowledge → Add content → Upload files
3. Select the files you want to add

For a new project, upload your base set (CLAUDE.md, ROUTING.md, identity files) once. For skill files, upload them when you first need them in that project.

---

## Keeping projects current

When you update context files in the repo, re-upload the changed files to any claude.ai projects that use them.

The fastest way to know what to re-upload: at the end of a Claude Code session where you updated files, ask:

```
Which files did we change today that I should re-upload to my claude.ai projects?
```

Claude will give you the list. Takes about 30 seconds to do the re-uploads.

**Files that change often** (re-upload regularly):
- `state/current.md` — your active priorities
- `state/weekly-priorities.md` — weekly focus
- Project context files when a project evolves

**Files that rarely change** (re-upload only when you edit them):
- `CLAUDE.md`
- `ROUTING.md`
- `identity/who-i-am.md`
- Skill files

---

## What agility looks like in practice

Before this setup: you have three claude.ai projects, each with their own system prompt and uploaded files. You change jobs. You update one project's instructions. The other two are still running the old version. A month later you can't remember which is current.

After this setup: you update `identity/who-i-am.md` in the repo. You re-upload it to each project. All three are running the same file. You know exactly what version they're on because it's in git.

Same for skills. You improve the `avoid-ai-writing` skill — tighten the word replacement table, add a new pattern. Re-upload the file to your writing project. Done. Every project that uses it now has the updated version.

---

## One repo, multiple projects

Some people run multiple focused claude.ai projects — one for work, one for creative projects, one for a specific client or domain. This repo supports that cleanly.

Each project gets the base files plus whatever's relevant to its focus. A work project might have your career context and a specific set of work-related skills. A music project has your artist context and the social post and press outreach skills. They're all drawing from the same repo; they just get different slices of it.

When something in your identity or base context changes, you update one file and push it to every project that needs it.
