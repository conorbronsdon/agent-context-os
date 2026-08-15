# Example Project: Musician Promotion

This is a worked example of a project section for a musician using coding agents to accelerate a promotion workflow. Replace everything in brackets with your own details.

The core workflow this covers:
1. Writing social content that sounds like you (not AI) across Instagram, TikTok, and Twitter/X
2. Drafting outreach to blogs, playlist curators, and press contacts
3. Planning release campaigns without starting from scratch every time

## Files in this example

| File | What it's for |
|------|--------------|
| `artist-context.md` | Who you are as an artist — the permanent background Claude needs |
| `promotion-strategy.md` | Current focus, platforms, goals, what's working |
| `workflow-examples/social-post/SKILL.md` | Reference workflow for platform-native social posts |
| `workflow-examples/press-outreach/SKILL.md` | Reference workflow for cold pitches to blogs, playlists, and press |

## How to use this

1. Fill in `artist-context.md` and `promotion-strategy.md` first — these are the foundation everything else draws from
2. Add `projects/[your-project-name]/` to `ROUTING.md` so supported agents know when to load it
3. Apply `writing/skills/avoid-ai-writing/SKILL.md` to any draft that sounds off
4. Copy a useful reference workflow to `.agents/skills/<unique-name>/SKILL.md`, replace the sample paths, and build new skills as repeated tasks become clear

The files under `workflow-examples/` are not active or auto-discovered. They use portable frontmatter and keep context dependencies in the body.

## Claude Code slash commands (optional)

Once you've filled in the context files, add these to the slash commands table in `CLAUDE.md`:

```
| `/social-post` | Write a platform-native social post for a new release or show |
| `/press-pitch` | Draft an outreach email to a blog, playlist, or press contact |
```

Then create a thin corresponding file in `.claude/commands/` for each one. The adapter may declare narrowly scoped Claude tools and should route to the canonical skill under `.agents/skills/`. Prompt 3 in `SETUP-PROMPTS.md` can draft this adapter when requested.
