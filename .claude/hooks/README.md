# Claude Code Hooks

These scripts run automatically during Claude Code sessions. Most are **advisory** — they print warnings but never block. `worktree-guard.sh` is the exception: it blocks edits to a guarded repo's primary checkout when more than one Claude session is running.

The PreToolUse hooks require Python 3 to parse Claude's JSON input. Setup checks for it. The advisory hook emits a visible dependency warning if it is missing; a configured blocking guard fails closed rather than silently allowing an unsafe edit.

## Files

| Hook | Event | Purpose | Blocks? |
|------|-------|---------|---------|
| `session-start.sh` | `SessionStart` | Surfaces stale state files, inbox items, overdue TODOs | no |
| `branch-hygiene.sh` | `SessionStart` | Surfaces non-default HEAD on guarded repos (catches silent branch-switches by parallel sessions) | no |
| `ssot-guard.sh` | `PreToolUse` (Edit/Write) | Warns when editing SSOT files to prevent fact duplication | no |
| `worktree-guard.sh` | `PreToolUse` (Edit/Write) | Blocks edits to a guarded repo's primary checkout when >1 Claude session is running | **yes** |
| `guarded-repos.txt` | — | Config file listing repo basenames the parallel-session guards apply to | — |

### Parallel-session guards: when to use

Running multiple Claude Code sessions against the same repo simultaneously will eventually corrupt your tree — branch-switches happen silently, one session's `git add` lands in another session's commit, files get committed to the wrong branch. The fix is to use `git worktree` so each session gets its own checkout.

`worktree-guard.sh` enforces that pattern: once a repo is listed in `guarded-repos.txt`, editing files in its primary checkout is blocked when ≥2 Claude sessions are running. Worktrees are still free to edit. An emergency override exists via `touch .allow-shared-edit` at the repo root.

`branch-hygiene.sh` complements it: at session start, if you're on a non-default branch in a guarded repo, the hook surfaces what HEAD is and what's uncommitted. Stays quiet on freshly-created worktrees (clean tree + commit < 2 min old).

## Configuration

Hooks are enabled for the project by the checked-in `.claude/settings.json`. Personal overrides belong in `.claude/settings.local.json`. See the [Claude Code hooks docs](https://code.claude.com/docs/en/hooks) for details.

### Project settings shape

```json
{
  "hooks": {
    "SessionStart": [{
      "hooks": [
        {
          "type": "command",
          "command": "bash \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/session-start.sh"
        },
        {
          "type": "command",
          "command": "bash \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/branch-hygiene.sh"
        }
      ]
    }],
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/ssot-guard.sh"
          },
          {
            "type": "command",
            "command": "bash \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/worktree-guard.sh"
          }
        ]
      }
    ]
  }
}
```

## Enabling the parallel-session guards

1. Make the scripts executable: `chmod +x .claude/hooks/*.sh`
2. Open `.claude/hooks/guarded-repos.txt` and add the basename of each repo you want guarded (one per line).
3. The guards no-op until at least one repo is listed.

## Customizing

- Edit the stale-days threshold in `session-start.sh` (default: 3 days)
- Add your own SSOT patterns in `ssot-guard.sh`
- Add/remove repos in `guarded-repos.txt` (no script edits needed)
- Create new hooks for other events (`PreToolUse`, `PostToolUse`, etc.)
