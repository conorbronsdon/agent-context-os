---
name: find-context
description: Find relevant context files by topic. Use when you need to load files for a topic without a slash command, or when a task spans multiple domains.
allowed-tools: "Read, Glob, Grep"
x-source: skills-sync/commands/context.md
x-source-version: 173c978
---

# /find-context — Find Relevant Files by Topic

Find and load the right context files for any topic, even when it spans multiple domains.

## Instructions

### 1. Get the topic
The user will say `/find-context <topic>` (e.g., `/find-context auth rewrite`, `/find-context q3 planning`). This avoids colliding with Claude Code's built-in `/context` command.

### 2. Search (three strategies, in parallel)

**Tag match** — use `Grep` to search Markdown files for the topic in YAML
`tags:` frontmatter (the strongest signal—the file was explicitly categorized).

**Filename match** — `Glob` for files with the topic keyword in their name.

**Header match** — `Grep` for `# `/`## ` headings containing the topic across `.md` files. Skip `sessions/` (unless the topic is from the last 3 days), `node_modules/`, and any vendored docs.

### 3. Rank and present
Combine, deduplicate, and rank by signal strength:

1. **Tag** matches (highest — explicitly categorized)
2. **Filename** matches
3. **Header** matches (lowest — may be incidental)

Present a ranked list with the match type and line count:

```
CONTEXT FILES for "[topic]":

  [tag]  path/to/file.md — [first line or description] ([N] lines)
  [name] path/to/file.md — [first line or description] ([N] lines)
  [hdr]  path/to/file.md — [first line or description] ([N] lines)

Load all? (or specify which by number)
```

### 4. Load selected files
Read the selected files and give a one-line summary of what each contains relative to the topic. If more than 3 are selected, read only the first 30 lines of each and offer to load full content on request.

## Tag Convention

Context files (not skills or commands) can carry a `tags:` line in YAML frontmatter so `/find-context` can find them by category rather than by incidental keyword:

```yaml
---
tags: [auth, security, backend]
---
```

Tags are lowercase, short, and descriptive. Group them however fits your work — for example:
- **Domains:** the areas you work in (`backend`, `marketing`, `research`)
- **Topics:** recurring subjects (`auth`, `pricing`, `onboarding`)
- **Types:** the kind of doc (`strategy`, `reference`, `planning`)
