---
name: content-shipped
description: "Log a completed piece of content to content/log.md after the user confirms it was published."
allowed-tools: "Read, Edit"
disable-model-invocation: true
x-source: "skills-sync/skills/content-shipped/SKILL.md"
x-source-version: "b85d60f"
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

### 2. Add the entry to content/log.md

Append the row as the **last line of the table**.
```
| {Date} | {Type} | {Title/Description} | {Platform} | {Link} | {Notes} |
```

A fresh log has no data rows, so the table's last line is the dashed separator row —
put the first entry directly beneath it. Every later row goes beneath the previous
one. Never insert above the separator; that breaks the table.

### 3. Confirm
One line: "Logged: {type} — {title/description}"
