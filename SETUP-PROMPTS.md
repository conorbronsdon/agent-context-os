# Manual setup prompts for claude.ai

Use these prompts when claude.ai is your only available interface. Claude will draft the content, but you must review it and copy approved text into the repository yourself.

**In Claude Code:** Prefer `/setup`, which follows the shared, approval-gated workflow in `.agents/skills/context-setup/SKILL.md`.

**In claude.ai:** These prompts produce drafts. They do not create files, register commands, commit changes, or keep project knowledge synchronized.

Run them in order the first time. After that, use them whenever you need to refresh a section.

---

## Prompt 1: Fill in your identity

Builds `identity/who-i-am.md` and `identity/professional-background.md`.

```
Read identity/who-i-am.md and identity/professional-background.md so you understand the structure. Then interview me to fill them in.

Ask me the following questions one at a time — wait for my answer before moving to the next:

1. What's your name, and what do you do in one sentence?
2. What's your current role or main focus — job title, project, or however you think about it?
3. What's your relevant background? (Previous roles, experience, or context that matters)
4. What are you actively working on right now — 2 to 4 things?
5. How do you like to work? Any preferences or quirks Claude should know about?
6. What are you trying to accomplish in the next 3 months?
7. Anything personal worth knowing — location, life situation, whatever feels relevant?
8. Short bio (2-3 sentences) — how would you introduce yourself to a new contact?
9. What are your key credentials or social proof — the things that establish your credibility?
10. Where are you online? (Website, social handles, etc.)

After I've answered all of them, write the files. Use my exact words where possible — don't polish or generalize. Update the Last Updated date to today. Tell me what you wrote.
```

---

## Prompt 2: Set up your first project

The example project in this repo is built for a musician — so the questions below are tailored for that. If your project is something else entirely, skip to Prompt 3, which is generic and works for any project type.

This prompt fills in `projects/example-musician/artist-context.md` and `projects/example-musician/promotion-strategy.md`, then renames the folder to match your artist name.

```
Read projects/example-musician/artist-context.md and projects/example-musician/promotion-strategy.md so you understand the structure. Then interview me to fill them in.

Ask me the following questions one at a time — wait for my answer before moving to the next:

**About the music:**
1. What's your artist name, and how would you describe your sound in 2-3 words?
2. Describe your music more specifically — genre, key influences, what makes it distinct from others in your lane?
3. What have you released so far? (Albums, EPs, singles — just a quick list with years)
4. What's your latest release, and what are you currently working on?

**About your audience:**
5. Who listens to your music — who are your people?
6. What are your current numbers? (Spotify monthly listeners, Instagram followers, email list — ballpark is fine)
7. Where are you seeing the most traction or growth right now?

**About live:**
8. Do you tour, play locally, or both? What kinds of venues? Any upcoming shows?

**About promotion:**
9. What platforms do you focus on, and what's your current follower count on each?
10. How do you write captions — what's your voice like? Paste an example post that felt right, if you have one.
11. What have you tried for promotion that actually worked?
12. What hasn't worked or what are you done with?
13. Are you currently pitching to blogs, playlists, or press? Who are you targeting?
14. Do you work with a publicist or any PR contacts?

**Goals:**
15. What are you specifically trying to accomplish in the next 3 months?
16. Where do you want to be as an artist in 1-2 years?

After I've answered everything, do the following:
1. Rename the folder from `projects/example-musician` to `projects/[artist-name-lowercase-hyphenated]`
2. Write artist-context.md and promotion-strategy.md with my answers — use my words, not polished versions
3. Update ROUTING.md to point to the new folder name
4. Update the Last Updated dates to today
5. Tell me what changed and what to do next
```

---

## Prompt 3: Build a new project section

Use this for any project beyond music — a side business, a creative project, a job search, a content series, anything recurring where you'd want Claude to know the context.

```
I want to add a new project section to this repo. Read projects/README.md so you understand the structure, then interview me to build it out.

Ask me the following questions one at a time:

1. What's the project? Describe it in one sentence.
2. What are you trying to accomplish with it? What does success look like?
3. Who is the audience or who does this project involve? (Clients, fans, collaborators, etc.)
4. What are you currently focused on with this project? What are you NOT doing right now?
5. What decisions have already been made that Claude should know about?
6. Are there any external resources Claude should reference — links, spreadsheets, docs?
7. What tasks do you do repeatedly for this project? List them — even rough descriptions are fine.
8. Of those recurring tasks, which ones take the most time or feel the most inconsistent?

After I've answered everything:
1. Create a folder at `projects/[project-name]/`
2. Write `projects/[project-name]/context.md` with the permanent background
3. Write `projects/[project-name]/strategy.md` with goals and current focus
4. For the top 1-2 recurring tasks I mentioned, draft a provider-neutral skill for `.agents/skills/[project-name]-[task-name]/SKILL.md`; keep project facts in the project files and reference them from the skill
5. Add a line to ROUTING.md under "Project tasks" pointing to the new context file
6. Ask whether I want a Claude Code slash command for any skill; if yes, draft a thin `.claude/commands/[task-name].md` adapter and the matching `CLAUDE.md` table row
7. Update CHANGELOG.md with what was added
8. Tell me what you built and what to fill in next
```

---

## Prompt 4: Refresh your state for a new week

Run this at the start of each week to update `state/current.md` and `state/weekly-priorities.md`. Takes 2 minutes.

```
Read state/current.md and state/weekly-priorities.md. Then ask me:

1. What are the top 3 things you need to accomplish this week?
2. What are you explicitly NOT doing this week even if it comes up?
3. What does a good week look like — what would you want to have shipped or resolved by Friday?
4. Any open threads or things you're waiting on?
5. Anything that changed since last week that I should know about?

Update both files with my answers. Update the dates. Keep it terse — these files are read at the start of every session, so clarity beats completeness. Tell me what changed.
```

---

## Tips

- **Prefer `/setup` locally** in Claude Code, or `$context-setup` in Codex, so the same review gates and portable paths apply
- **Your words beat polished prose** — the prompts tell Claude to use your exact answers. Don't overthink your responses.
- **Re-run anytime** — these aren't one-time setup. Run Prompt 2 or 3 again when a project evolves significantly. Run Prompt 4 every Monday.
- **Add your own** — once you see the pattern, you can write prompts for anything. A prompt that builds your weekly review, drafts a specific type of email, or updates a specific context file on a schedule.
