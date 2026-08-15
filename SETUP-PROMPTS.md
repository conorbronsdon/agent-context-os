# Setup Prompts

Use these prompts when the native `/setup` or `$context-setup` lifecycle is unavailable, or when working in a browser host that cannot edit the repository. The agent asks questions and drafts context; you still review every file before saving or committing it.

**In Claude Code:** Prefer `/setup` from the repository directory. It reads the portable workflow, proposes a file map, and waits before replacing populated content. It never assumes a commit or push.

**In Codex:** Prefer `$context-setup` from the repository directory. It uses the same portable workflow and writes the same shared state.

**In Claude.ai:** These prompts can draft the content, but copy only reviewed output into the repository. Do not paste credentials, private exports, or context that every repository collaborator should not see.

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

After I've answered all of them, prepare the exact proposed contents for both files and show the complete file map. Do not write, save, or replace anything yet. Ask me to approve those exact two file writes. Only after I explicitly approve, write the approved content, update the Last Updated date to today, and show the resulting diff. If this host cannot edit the repository, return the reviewed content for me to copy manually.
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

After I've answered everything:
1. Propose the exact new folder name, both complete file contents, the ROUTING.md edit, and the full changed-file map. Do not write or rename anything yet.
2. Ask me first to approve the two content files and ROUTING.md edit.
3. Separately explain that renaming removes the old path and can break links, then ask me to approve that exact rename consequence.
4. Only after both approvals, make only the approved writes and rename, update the Last Updated dates, and show the resulting diff. If this host cannot edit the repository, return the reviewed files and rename instructions for me to apply manually.
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
1. Draft the complete proposed contents for `projects/[project-name]/context.md`, `strategy.md`, the top 1-2 portable skills under `.agents/skills/[skill-name]/SKILL.md`, and the exact ROUTING.md edit. If I use Claude Code, separately propose any thin `.claude/commands/` adapter without duplicating the workflow.
2. Show the full file map and exact content/diff. Do not create or edit any file yet.
3. Ask me to approve that exact batch. Only after explicit approval, create only those files and edits.
4. Run `bash scripts/validate-all.sh`, show the changed-file list and diff, and wait before any commit.
5. Tell me what was built and what to fill in next. If this host cannot edit the repository, return the reviewed batch for me to copy manually.
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

Draft the exact proposed diff for both files with updated dates. Keep it terse — these files are read at the start of every session, so clarity beats completeness. Do not write yet. Ask me to approve that exact two-file update; only then apply it and show the resulting diff. If this host cannot edit the repository, return the reviewed content for me to copy manually.
```

---

## Tips

- **Prefer the native lifecycle** — `/setup` in Claude Code or `$context-setup` in Codex keeps the workflow and safety gates current
- **Review repository visibility first** — identity and project context can be sensitive even when it contains no credentials
- **Your words beat polished prose** — the prompts tell Claude to use your exact answers. Don't overthink your responses.
- **Re-run anytime** — these aren't one-time setup. Run Prompt 2 or 3 again when a project evolves significantly. Run Prompt 4 every Monday.
- **Add your own** — once you see the pattern, you can write prompts for anything. A prompt that builds your weekly review, drafts a specific type of email, or updates a specific context file on a schedule.
