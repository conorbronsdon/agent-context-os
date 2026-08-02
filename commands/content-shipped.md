---
name: content-shipped
description: Log a completed piece of content to content/log.md. Use after publishing any post, episode, newsletter, clip, or article.
allowed-tools: Read, Edit
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

Append a row to `content/log.md`:
```
| {Date} | {Type} | {Title/Description} | {Platform} | {Link} | {Notes} |
```

If an MCP tool like `content_log_add` is available, use it instead.

### 3. Confirm
One line: "Logged: {type} — {title/description}"
