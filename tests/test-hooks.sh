#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)

SSOT_OUTPUT=$(printf '%s' '{"tool_input":{"file_path":"/tmp/context/state/current.md"}}' | \
  bash "$ROOT/.claude/hooks/ssot-guard.sh")
if ! printf '%s' "$SSOT_OUTPUT" | grep -q "current.md is updated"; then
  echo "ssot-guard did not parse Claude hook JSON" >&2
  exit 1
fi

MALFORMED_OUTPUT=$(printf '%s' 'not-json' | bash "$ROOT/.claude/hooks/ssot-guard.sh")
if [ -n "$MALFORMED_OUTPUT" ]; then
  echo "ssot-guard should no-op for malformed input" >&2
  exit 1
fi

TEMP_ROOT=$(mktemp -d)
trap 'rm -rf "$TEMP_ROOT"' EXIT
TEST_REPO="$TEMP_ROOT/guarded-repo"
mkdir -p "$TEST_REPO/.claude/hooks" "$TEMP_ROOT/bin"
git -C "$TEMP_ROOT" init -q -b main guarded-repo
cp "$ROOT/.claude/hooks/worktree-guard.sh" "$TEST_REPO/.claude/hooks/worktree-guard.sh"
printf '%s\n' 'guarded-repo' > "$TEST_REPO/.claude/hooks/guarded-repos.txt"
printf '%s\n' '#!/usr/bin/env bash' 'printf "claude.exe one\\nclaude.exe two\\n"' > "$TEMP_ROOT/bin/tasklist"
chmod +x "$TEMP_ROOT/bin/tasklist"

set +e
GUARD_STDERR=$(printf '%s' "{\"tool_input\":{\"file_path\":\"$TEST_REPO/note.md\"}}" | \
  PATH="$TEMP_ROOT/bin:$PATH" bash "$TEST_REPO/.claude/hooks/worktree-guard.sh" 2>&1 >/dev/null)
GUARD_STATUS=$?
set -e
if [ "$GUARD_STATUS" -ne 2 ] || ! printf '%s' "$GUARD_STDERR" | grep -q "Blocked: 2 Claude sessions"; then
  echo "worktree-guard did not block via stderr with exit code 2" >&2
  exit 1
fi

for hook in "$ROOT"/.claude/hooks/*.sh; do
  bash -n "$hook"
done

echo "Hook checks passed"
