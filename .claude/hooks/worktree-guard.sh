#!/bin/bash
# PreToolUse hook: when >1 Claude session is running, block Edit/Write to
# files that live inside the primary checkout of a guarded repo. Forces use
# of git worktrees — the reliable way to prevent file-collision drift
# between parallel sessions.
#
# The check is on the *target file path* (parsed from the tool input JSON
# on stdin), not on cwd — so a session in one repo can still edit files in
# another repo's worktree.
#
# Behavior:
#   - allow if Claude session count <= 1
#   - allow if target file is inside a git worktree (not the primary checkout)
#   - allow if target's repo basename is NOT listed in .claude/hooks/guarded-repos.txt
#   - allow if `.allow-shared-edit` exists at the target repo's root
#   - otherwise block with exit code 2 and an instruction message

# 1. Read tool input JSON from stdin to extract file_path.
INPUT=$(cat)
PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

FILE_PATH=""
if [ -n "$PYTHON_BIN" ]; then
  FILE_PATH=$(printf '%s' "$INPUT" | "$PYTHON_BIN" -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
    print(payload.get("tool_input", {}).get("file_path", ""))
except (json.JSONDecodeError, AttributeError, TypeError):
    pass
' 2>/dev/null)
fi

# If we can't determine a file path, don't block.
[ -z "$FILE_PATH" ] && exit 0

# 2. Session count. tasklist on Windows, ps elsewhere.
SESSION_COUNT=$(tasklist //FI "IMAGENAME eq claude.exe" 2>/dev/null | grep -c "^claude.exe")
if [ "$SESSION_COUNT" -eq 0 ]; then
  SESSION_COUNT=$(ps aux 2>/dev/null | grep -E "\\bclaude(\\.exe)?\\b" | grep -v grep | wc -l)
fi
[ "$SESSION_COUNT" -le 1 ] && exit 0

# 3. Find the git repo for the target file. Walk up from the file's directory
#    (works whether the file exists yet or not).
TARGET_DIR=$(dirname "$FILE_PATH")
while [ ! -d "$TARGET_DIR" ] && [ "$TARGET_DIR" != "/" ] && [ "$TARGET_DIR" != "." ]; do
  TARGET_DIR=$(dirname "$TARGET_DIR")
done
[ ! -d "$TARGET_DIR" ] && exit 0

GIT_DIR=$(git -C "$TARGET_DIR" rev-parse --git-dir 2>/dev/null) || exit 0

# 4. Inside a worktree? Allow.
case "$GIT_DIR" in
  *worktrees*) exit 0 ;;
esac

REPO_ROOT=$(git -C "$TARGET_DIR" rev-parse --show-toplevel 2>/dev/null) || exit 0
# Resolve canonical repo via git-common-dir (worktrees report their own dirname).
GIT_COMMON_DIR=$(git -C "$TARGET_DIR" rev-parse --git-common-dir 2>/dev/null)
case "$GIT_COMMON_DIR" in
  /*|[A-Za-z]:*) CANONICAL_ROOT=$(dirname "$GIT_COMMON_DIR") ;;
  *) CANONICAL_ROOT=$(cd "$TARGET_DIR/$(dirname "$GIT_COMMON_DIR")" 2>/dev/null && pwd) ;;
esac
[ -z "$CANONICAL_ROOT" ] && CANONICAL_ROOT="$REPO_ROOT"
REPO_NAME=$(basename "$CANONICAL_ROOT")

# 5. Is this repo guarded?
#    Look for guarded-repos.txt next to this script (works in worktrees too).
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
GUARD_LIST="$SCRIPT_DIR/guarded-repos.txt"
[ ! -f "$GUARD_LIST" ] && exit 0

if ! grep -v '^[[:space:]]*#' "$GUARD_LIST" | grep -v '^[[:space:]]*$' | grep -Fxq "$REPO_NAME"; then
  exit 0
fi

# 6. Escape hatch.
[ -f "$REPO_ROOT/.allow-shared-edit" ] && exit 0

# 7. Block.
{
  echo "=== WORKTREE GUARD ==="
  echo ""
  echo "Blocked: $SESSION_COUNT Claude sessions are running and the target file"
  echo "is inside the primary checkout of '$REPO_NAME':"
  echo "  $FILE_PATH"
  echo ""
  echo "Parallel edits to the same checkout cause branch-switch drift."
  echo ""
  echo "Create a worktree before editing. Example:"
  echo ""
  echo "    git -C \"$REPO_ROOT\" worktree add ../${REPO_NAME}-<task> -b claude/<task-name>"
  echo "    cd ../${REPO_NAME}-<task>"
  echo ""
  echo "Override (rare, e.g. shared state files): touch \"$REPO_ROOT/.allow-shared-edit\""
  echo ""
  echo "Or remove '$REPO_NAME' from .claude/hooks/guarded-repos.txt to disable this guard."
  echo ""
  echo "=== END WORKTREE GUARD ==="
} >&2
exit 2
