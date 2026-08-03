---
name: content-shipped
description: Log a completed piece of content to content/log.md. Use after publishing any post, episode, newsletter, clip, or article.
allowed-tools: Read, Edit, Bash
x-source: skills-sync/skills/content-shipped/SKILL.md
x-source-version: c0af010
---

# content-shipped — Log Shipped Content

Use after publishing anything: a blog post, social post, newsletter issue, video clip, or any other content piece.

## Instructions

### 1. Gather metadata
Ask for (or infer from context):
- **Date** — today's date (run `date +%Y-%m-%d` if not provided)
- **Type** — e.g.: `blog-post`, `linkedin-post`, `newsletter`, `video`, `episode`, `clip`, `other`
- **Title / Description** — post title, hook, or short description
- **Platform** — where it was published
- **Link** — URL if available; use `TBD` if not yet live
- **Notes** — any additional context worth remembering

### 2. Log the entry

Insert the row **immediately after the separator row** (the `|---|` line under the header) — or after the
last existing data row if the table already has some. Anchor on the separator, not
on "the last row": a fresh log has no data rows, so "after the last row" resolves to
after the *header* and puts your entry above the separator, which breaks the table:
```
| {Date} | {Type} | {Title/Description} | {Platform} | {Link} | {Notes} |
```

If your setup exposes an MCP tool that appends to the log, use it instead of
editing the file by hand.

### 3. Confirm
One line: "Logged: {type} — {title/description}"
