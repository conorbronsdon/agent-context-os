#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
source "$ROOT/scripts/python-env.sh"

fail() {
  echo "hooks: $*" >&2
  exit 1
}

SSOT_OUTPUT=$(printf '%s' '{"tool_input":{"file_path":"/tmp/context/state/current.md"}}' | \
  bash "$ROOT/.claude/hooks/ssot-guard.sh")
if ! printf '%s' "$SSOT_OUTPUT" | "$CONTEXTOS_PYTHON_CMD" -c '
import json, sys
payload = json.load(sys.stdin)
assert "current.md is updated" in payload["systemMessage"]
'; then
  echo "ssot-guard did not emit visible Claude hook JSON" >&2
  exit 1
fi

SSOT_WINDOWS_OUTPUT=$(printf '%s' '{"tool_input":{"file_path":"C:\\repo\\state\\decisions.md"}}' | \
  bash "$ROOT/.claude/hooks/ssot-guard.sh")
if ! printf '%s' "$SSOT_WINDOWS_OUTPUT" | "$CONTEXTOS_PYTHON_CMD" -c '
import json, sys
payload = json.load(sys.stdin)
assert "decisions.md is append-only" in payload["systemMessage"]
'; then
  echo "ssot-guard did not normalize a native Windows path" >&2
  exit 1
fi

MALFORMED_OUTPUT=$(printf '%s' 'not-json' | bash "$ROOT/.claude/hooks/ssot-guard.sh")
if ! printf '%s' "$MALFORMED_OUTPUT" | "$CONTEXTOS_PYTHON_CMD" -c '
import json, sys
payload = json.load(sys.stdin)
assert "malformed input" in payload["systemMessage"]
'; then
  echo "ssot-guard should surface malformed input" >&2
  exit 1
fi

TEMP_ROOT=$(mktemp -d)
trap 'rm -rf "$TEMP_ROOT"' EXIT
# Native git needs a Windows path, but MSYS PATH entries must stay POSIX or
# Windows binaries shadow the fixture stubs. Keep both forms.
if command -v cygpath >/dev/null 2>&1; then
  TEMP_ROOT_WIN=$(cygpath -m "$TEMP_ROOT")
else
  TEMP_ROOT_WIN=$TEMP_ROOT
fi

# Claude's configured SessionStart adapter must use the same current.md
# readiness predicate as start and doctor, while remaining advisory.
SESSION_REPO="$TEMP_ROOT_WIN/session-repo"
mkdir -p "$SESSION_REPO/.claude/hooks" "$SESSION_REPO/scripts" "$SESSION_REPO/state"
cp "$ROOT/.claude/hooks/session-start.sh" "$SESSION_REPO/.claude/hooks/session-start.sh"
cp "$ROOT/scripts/context-os-hook.py" "$ROOT/scripts/context-os-hook.sh" \
  "$ROOT/scripts/python-env.sh" "$SESSION_REPO/scripts/"
cp -R "$ROOT/contextos" "$SESSION_REPO/contextos"
printf '# Test workspace\n' > "$SESSION_REPO/AGENTS.md"
git -C "$SESSION_REPO" init -q -b main

printf '# Current State\n\n**Last Updated:** [DATE]\n' > "$SESSION_REPO/state/current.md"
SESSION_SETUP_OUTPUT=$(cd "$SESSION_REPO" && bash .claude/hooks/session-start.sh)
printf '%s' "$SESSION_SETUP_OUTPUT" | grep -q 'not initialized' \
  || fail "Claude session-start must fire when current.md is uninitialized"

printf '# Current State\n\n**Last Updated:** %s\n' "$(date +%F)" > "$SESSION_REPO/state/current.md"
SESSION_READY_OUTPUT=$(cd "$SESSION_REPO" && bash .claude/hooks/session-start.sh)
if printf '%s' "$SESSION_READY_OUTPUT" | grep -q 'not initialized'; then
  fail "Claude session-start fired the setup advisory for initialized state"
fi
printf '%s' "$SESSION_READY_OUTPUT" | grep -q 'Tip: Run /start' \
  || fail "Claude session-start omitted the initialized-state /start tip"

printf '\377' > "$SESSION_REPO/workspace.yaml"
SESSION_ENCODING_OUTPUT=$(cd "$SESSION_REPO" && bash .claude/hooks/session-start.sh)
printf '%s' "$SESSION_ENCODING_OUTPUT" | grep -q 'advisory hook could not run' \
  || fail "Claude session-start did not surface an unreadable workspace config"

TEST_REPO="$TEMP_ROOT_WIN/guarded-repo"
mkdir -p "$TEST_REPO/.claude/hooks" "$TEMP_ROOT/bin"
git -C "$TEMP_ROOT_WIN" init -q -b main guarded-repo
cp "$ROOT/.claude/hooks/worktree-guard.sh" "$TEST_REPO/.claude/hooks/worktree-guard.sh"
printf 'guarded-repo\r\n' > "$TEST_REPO/.claude/hooks/guarded-repos.txt"
printf '%s\n' '#!/usr/bin/env bash' 'printf "claude.exe one\\nclaude.exe two\\n"' > "$TEMP_ROOT/bin/tasklist"
chmod +x "$TEMP_ROOT/bin/tasklist"

for payload in 'not-json' '{}'; do
  set +e
  INPUT_STDERR=$(printf '%s' "$payload" | \
    PATH="$TEMP_ROOT/bin:$PATH" bash "$TEST_REPO/.claude/hooks/worktree-guard.sh" 2>&1 >/dev/null)
  INPUT_STATUS=$?
  set -e
  if [ "$INPUT_STATUS" -ne 2 ] || ! printf '%s' "$INPUT_STDERR" | grep -q "malformed or had no file path"; then
    echo "worktree-guard should fail closed for malformed or incomplete input" >&2
    exit 1
  fi
done

set +e
GUARD_STDERR=$(printf '%s' "{\"tool_input\":{\"file_path\":\"$TEST_REPO/note.md\"}}" | \
  PATH="$TEMP_ROOT/bin:$PATH" bash "$TEST_REPO/.claude/hooks/worktree-guard.sh" 2>&1 >/dev/null)
GUARD_STATUS=$?
set -e
if [ "$GUARD_STATUS" -ne 2 ] || ! printf '%s' "$GUARD_STDERR" | grep -q "Blocked: 2 Claude sessions"; then
  echo "worktree-guard did not block via stderr with exit code 2" >&2
  exit 1
fi


BACKSLASH_PATH=$(printf '%s' "$TEST_REPO/note.md" | tr '/' '\\')
BACKSLASH_PAYLOAD=$("$CONTEXTOS_PYTHON_CMD" -c '
import json, sys
print(json.dumps({"tool_input": {"file_path": sys.argv[1]}}))
' "$BACKSLASH_PATH")
set +e
WINDOWS_GUARD_STDERR=$(printf '%s' "$BACKSLASH_PAYLOAD" | \
  PATH="$TEMP_ROOT/bin:$PATH" bash "$TEST_REPO/.claude/hooks/worktree-guard.sh" 2>&1 >/dev/null)
WINDOWS_GUARD_STATUS=$?
set -e
if [ "$WINDOWS_GUARD_STATUS" -ne 2 ] || ! printf '%s' "$WINDOWS_GUARD_STDERR" | grep -q "Blocked: 2 Claude sessions"; then
  echo "worktree-guard did not normalize backslash paths or CRLF guard entries" >&2
  exit 1
fi

for hook in "$ROOT"/.claude/hooks/*.sh; do
  bash -n "$hook"
done

echo "Hook checks passed"
