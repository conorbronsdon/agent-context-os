# Safety Contract

Centralized policy for actions requiring confirmation. Hooks and commands reference this file — it's the single source of truth for safety rules.

## Confirmation Required

Actions that change external state or are hard to reverse. Always confirm before executing.

| Action | Risk | Example |
|--------|------|---------|
| Send email or message | External, visible to others | Drafting and sending via Gmail/Slack MCP |
| Upload or modify shared files | External, visible to others | Google Drive uploads, shared doc edits |
| Post to social media | External, public | LinkedIn post, Substack publish |
| Modify shared data | External, shared state | Google Sheets updates, database writes |
| Create/modify calendar events | External, shared state | Rescheduling meetings |
| Delete files or directories | Destructive, hard to reverse | Removing worktrees, pruning branches |
| `git push --force` | Destructive, affects remote | Never without explicit request |
| `git reset --hard` | Destructive, loses work | Never without explicit request |
| Bulk operations (>5 items) | Amplified risk | Batch file edits, multi-file renames |
| Modify CI/CD, hooks, or infrastructure | Infrastructure change | Editing hooks, workflows, deploy configs |

## Advisory Warnings (Non-Blocking)

Actions that get a warning but proceed. Warn, don't block — this is a personal repo.

| Trigger | Hook/Mechanism | Warning |
|---------|---------------|---------|
| Edit SSOT file outside designated command | `ssot-guard.sh` | Names the correct command to use |
| 2+ concurrent sessions | `session-start.sh` | Suggests worktrees |
| Edit CLAUDE.md | Manual check | Must stay under 100 lines |

## Approval Patterns

Standard patterns commands should follow for confirmation gates:

### Draft-Review-Approve
For actions visible to others (emails, messages, posts).
1. Generate the artifact (email draft, social post)
2. Present with summary of what will happen and who will see it
3. Wait for explicit approval before executing
4. Never auto-send

### Dry-Run-Then-Live
For data sync and bulk operations.
1. Run with `--dry-run` or read-only scan first
2. Show what would change
3. Ask "proceed?" before applying

### Read-Only Default
For diagnostic and cleanup operations (`/reconcile`, `/recover`).
1. Scan and report findings
2. List proposed actions with specifics (file, line, change)
3. Only execute with explicit approval

## Design Principles

- **Advisory over blocking.** This is a personal repo. Hooks warn; they don't prevent.
- **Specificity over caution.** "Are you sure?" is not a safety mechanism. Name the action, the target, and the consequence.
- **External > local.** Sending an email is irreversible. Editing a local file is not. Weight confirmation requirements accordingly.
- **Batch amplifies risk.** One file rename is safe. Twenty file renames need a review step.

## Customizing

Add rows to the tables above as you connect more integrations (Slack, Notion, Linear, etc.). Each new external write action should get a row in the confirmation table.
