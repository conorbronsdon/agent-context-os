# Example Project: Musician Promotion

This is a worked example of a project section for a musician using Claude to accelerate their promotion workflow. Replace everything in brackets with your own details.

The core workflow this covers:
1. Writing social content that sounds like you (not AI) across Instagram, TikTok, and Twitter/X
2. Drafting outreach to blogs, playlist curators, and press contacts
3. Planning release campaigns without starting from scratch every time

## Files in this example

| File | What it's for |
|------|--------------|
| `artist-context.md` | Who you are as an artist — the permanent background Claude needs |
| `promotion-strategy.md` | Current focus, platforms, goals, what's working |
| `skills/social-post/SKILL.md` | Write platform-native social posts in your voice |
| `skills/press-outreach/SKILL.md` | Draft cold pitches to blogs, playlists, and press |

## How to use this

1. Fill in `artist-context.md` and `promotion-strategy.md` first — these are the foundation everything else draws from
2. Add `projects/[your-project-name]/` to ROUTING.md so Claude knows when to load it
3. Try `/clean-ai-writing` on any draft that sounds off — the avoid-ai-writing skill works for music content too
4. Build new skills as you identify repeating tasks (e.g., writing EPK copy, drafting grant applications, creating set list announcements)

## Slash commands to add (optional)

Once you've filled in the context files, add these to the slash commands table in `CLAUDE.md`:

```
| `/social-post` | Write a platform-native social post for a new release or show |
| `/press-pitch` | Draft an outreach email to a blog, playlist, or press contact |
```

Then create a corresponding file in `.claude/commands/` for each one. The pattern is the same as `.claude/commands/start.md` — a frontmatter block declaring the skill name and which tools it needs, followed by instructions that tell Claude which skill file to load. Prompt 3 in `SETUP-PROMPTS.md` will handle this automatically if you ask for slash commands during setup.
