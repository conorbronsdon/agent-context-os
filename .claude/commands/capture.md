---
name: capture
description: "Triage raw inbox notes into reviewed repository destinations without deleting their sources."
allowed-tools: "Read, Write, Edit, Glob"
disable-model-invocation: true
x-source: "skills-sync/commands/capture.md"
x-source-version: "40f7149"
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
| Writing idea or draft | relevant project context/draft file, or keep in `inbox/` | Move if ready, keep if raw |
| Reference link or note | relevant context file | Append to the appropriate section |
| ⚠️ Secret (password, PIN, seed phrase, recovery code, API key) | **NEVER commit to the repo** | Name the source file without reproducing its value; leave it in place and direct the user to move/remove it securely themselves |
| Unknown / multi-category | ask the user | Don't guess — present 1–2 options |

### 3. Present the triage plan (don't act yet)
Before moving anything, show the plan and wait for approval:

```
INBOX TRIAGE — [N] items found

1. [filename] → [destination] — [brief reason]
   Destination write: [append/create and exact excerpt]
   Source disposition: remains at inbox/[filename] until a separate user action
2. [filename] → [destination] — [brief reason]
   Destination write: [append/create and exact excerpt]
   Source disposition: remains at inbox/[filename] until a separate user action

[If any item is unclear:]
? [filename] — [description]. Suggested: [destination]. Correct?

Apply these destination writes? (or specify changes)
```

**Do not move or edit files until the user approves.**

### 4. Execute destination writes (after approval)
- Route each approved item to its named destination (append to existing files, or create new ones).
- Re-read each destination and verify the approved content is present before reporting success.
- Do not delete, move, truncate, or overwrite any source in `inbox/`.
- For a suspected secret, do not reproduce, copy, or relocate its value. Name only the source path and ask the user to move it to their password manager or delete it with a user-chosen secure action.

### 5. Offer source cleanup separately

List each source path whose destination was verified. Explain that removal discards the inbox copy and that this command has not removed it. Ask whether the user wants manual cleanup instructions for exact named files. Never interpret approval of the destination writes as approval to delete their sources.

### 6. Confirm

```
Triaged [N] items:
  → TODO.md: "Set up monitoring dashboard"
  → state/decisions.md: "Chose Postgres over MongoDB"
Destination writes verified. Source inbox files remain until you remove them explicitly.
```

## Design Principles

- **Propose, don't act.** Always show the triage plan first; route only after approval.
- **Bias toward existing files.** Append to `TODO.md`, `state/decisions.md`, etc. rather than creating new files when the content fits.
- **Ask when unsure.** If an item could go several places, ask. One wrong routing is worse than a five-second question.
- **No silent cleanup.** Everything gets routed or explicitly deferred, but source removal is a separate, named user action.
- **Never commit or relocate secrets.** Passwords, PINs, seed phrases, recovery codes, and API keys never go into a destination. Leave the source in place and let the user choose the secure handling path.
- **Question one-off notes.** Many bookmarks, dead ideas, and one-off to-dos may not deserve a durable destination. Ask "what happens if this is lost?" before creating a home, but never turn that judgment into implicit deletion.
