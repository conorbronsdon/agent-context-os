---
name: capture
description: Triage raw notes from inbox/ into the correct repo locations. Use when you drop unstructured content and need it routed.
allowed-tools: Read, Write, Edit, Glob, Bash
x-source: skills-sync/commands/capture.md
x-source-version: 40f7149
---

# /capture — Triage Inbox

Read everything in `inbox/`, classify each item, propose where it goes, and route it only after you approve.

## Instructions

### 1. Scan inbox
Read every file in `inbox/` (skip `README.md` and `.gitkeep`). If nothing else is there, say so and stop.

### 2. Classify each item
For each item, determine its type and destination:

| Content type | Destination | Action |
|---|---|---|
| Task / TODO | `TODO.md` | Append to the appropriate section |
| Decision or conclusion | `state/decisions.md` | Add as a new entry (newest first) |
| Blocker | `state/blockers.md` | Add with context |
| Priority change | `state/current.md` | Update priorities |
| Writing idea or draft | project skill dir, or keep in `inbox/` | Move if ready, keep if raw |
| Reference link or note | relevant context file | Append to the appropriate section |
| ⚠️ Secret (password, PIN, seed phrase, recovery code, API key) | **NEVER commit to the repo** | Flag it for the user's password manager; quarantine outside git |
| Unknown / multi-category | ask the user | Don't guess — present 1–2 options |

### 3. Present the triage plan (don't act yet)
Before moving anything, show the plan and wait for approval:

```
INBOX TRIAGE — [N] items found

1. [filename] → [destination] — [brief reason]
2. [filename] → [destination] — [brief reason]

[If any item is unclear:]
? [filename] — [description]. Suggested: [destination]. Correct?

Apply all? (or specify changes)
```

**Do not move or edit files until the user approves.**

### 4. Execute (after approval)
- Route each item to its destination (append to existing files, or create new ones)
- Delete the source file from `inbox/` (keep `README.md` and `.gitkeep`)

### 5. Confirm

```
Triaged [N] items:
  → TODO.md: "Set up monitoring dashboard"
  → state/decisions.md: "Chose Postgres over MongoDB"
inbox/ is clean.
```

## Design Principles

- **Propose, don't act.** Always show the triage plan first; route only after approval.
- **Bias toward existing files.** Append to `TODO.md`, `state/decisions.md`, etc. rather than creating new files when the content fits.
- **Ask when unsure.** If an item could go several places, ask. One wrong routing is worse than a five-second question.
- **No orphans.** Everything gets routed or explicitly deferred — nothing stays in `inbox/` after a run.
- **Never commit secrets.** Passwords, PINs, seed phrases, recovery codes, and API keys never go into the repo. Flag them for the password manager and quarantine outside git.
- **Delete-bias for one-off notes.** Many captured notes (bookmarks, dead ideas, one-off to-dos) are better deleted than filed. Ask "what happens if this is lost?" before creating a home for it.
