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
cp -R "$ROOT/components" "$SESSION_REPO/"
cp -R "$ROOT/runtimes" "$SESSION_REPO/"
printf '# Test workspace\n' > "$SESSION_REPO/AGENTS.md"
printf '# Test workspace\n' > "$SESSION_REPO/CLAUDE.md"
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

# Missing Git is advisory for the legacy Claude adapter: root discovery falls
# back to the current directory and the shared hook still runs.
mkdir -p "$TEMP_ROOT/bin"
printf '%s\n' '#!/usr/bin/env bash' 'exit 127' > "$TEMP_ROOT/bin/git"
chmod +x "$TEMP_ROOT/bin/git"
set +e
SESSION_NO_GIT_OUTPUT=$(cd "$SESSION_REPO" && PATH="$TEMP_ROOT/bin:$PATH" \
  bash .claude/hooks/session-start.sh)
SESSION_NO_GIT_STATUS=$?
set -e
rm "$TEMP_ROOT/bin/git"
[ "$SESSION_NO_GIT_STATUS" -eq 0 ] \
  || fail "Claude session-start returned $SESSION_NO_GIT_STATUS when Git was absent"
printf '%s' "$SESSION_NO_GIT_OUTPUT" | grep -q 'Tip: Run /start' \
  || fail "Claude session-start made Git a prerequisite instead of an advisory"

printf '\377' > "$SESSION_REPO/workspace.yaml"
SESSION_ENCODING_OUTPUT=$(cd "$SESSION_REPO" && bash .claude/hooks/session-start.sh)
printf '%s' "$SESSION_ENCODING_OUTPUT" | grep -q 'advisory hook could not run' \
  || fail "Claude session-start did not surface an unreadable workspace config"

TEST_REPO="$TEMP_ROOT_WIN/guarded-repo"
mkdir -p "$TEST_REPO/.claude/hooks" "$TEMP_ROOT/bin"
git -C "$TEMP_ROOT_WIN" init -q -b main guarded-repo
cp "$ROOT/.claude/hooks/worktree-guard.sh" "$TEST_REPO/.claude/hooks/worktree-guard.sh"
printf 'guarded-repo\r\n' > "$TEST_REPO/.claude/hooks/guarded-repos.txt"
printf 'baseline\n' > "$TEST_REPO/README.md"
git -C "$TEST_REPO" add README.md
git -C "$TEST_REPO" -c user.name=Test -c user.email=test@example.invalid commit -qm baseline
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

# One session must never block a guarded primary checkout.
printf '%s\n' '#!/usr/bin/env bash' 'printf "claude.exe one\\n"' > "$TEMP_ROOT/bin/tasklist"
set +e
printf '%s' "{\"tool_input\":{\"file_path\":\"$TEST_REPO/note.md\"}}" | \
  PATH="$TEMP_ROOT/bin:$PATH" bash "$TEST_REPO/.claude/hooks/worktree-guard.sh" >/dev/null 2>&1
ONE_SESSION_STATUS=$?
set -e
[ "$ONE_SESSION_STATUS" -eq 0 ] \
  || fail "worktree-guard fired with only one Claude session"

# The POSIX fallback must match the executable name, not helper processes or
# command-line text that merely contains the word claude.
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' > "$TEMP_ROOT/bin/tasklist"
printf '%s\n' '#!/usr/bin/env bash' \
  'printf "/usr/local/bin/claude-helper\\nclaude-monitor\\nmyclaude\\nbash\\n"' > "$TEMP_ROOT/bin/ps"
chmod +x "$TEMP_ROOT/bin/tasklist" "$TEMP_ROOT/bin/ps"
set +e
printf '%s' "{\"tool_input\":{\"file_path\":\"$TEST_REPO/note.md\"}}" | \
  PATH="$TEMP_ROOT/bin:$PATH" bash "$TEST_REPO/.claude/hooks/worktree-guard.sh" >/dev/null 2>&1
NON_CLAUDE_STATUS=$?
set -e
[ "$NON_CLAUDE_STATUS" -eq 0 ] \
  || fail "worktree-guard counted non-Claude process names"

# The same POSIX path must still fire for two exact Claude executables.
printf '%s\n' '#!/usr/bin/env bash' \
  'printf "/usr/local/bin/claude\\nclaude.exe\\n"' > "$TEMP_ROOT/bin/ps"
set +e
POSIX_GUARD_STDERR=$(printf '%s' "{\"tool_input\":{\"file_path\":\"$TEST_REPO/note.md\"}}" | \
  PATH="$TEMP_ROOT/bin:$PATH" bash "$TEST_REPO/.claude/hooks/worktree-guard.sh" 2>&1 >/dev/null)
POSIX_GUARD_STATUS=$?
set -e
if [ "$POSIX_GUARD_STATUS" -ne 2 ] || ! printf '%s' "$POSIX_GUARD_STDERR" | grep -q "Blocked: 2 Claude sessions"; then
  fail "worktree-guard POSIX fallback did not count exact Claude executables"
fi

# Two sessions do not block a repository that is absent from the guard list.
UNGUARDED_REPO="$TEMP_ROOT_WIN/unguarded-repo"
git -C "$TEMP_ROOT_WIN" init -q -b main unguarded-repo
printf '%s\n' '#!/usr/bin/env bash' 'printf "claude.exe one\\nclaude.exe two\\n"' > "$TEMP_ROOT/bin/tasklist"
set +e
printf '%s' "{\"tool_input\":{\"file_path\":\"$UNGUARDED_REPO/note.md\"}}" | \
  PATH="$TEMP_ROOT/bin:$PATH" bash "$TEST_REPO/.claude/hooks/worktree-guard.sh" >/dev/null 2>&1
UNGUARDED_STATUS=$?
set -e
[ "$UNGUARDED_STATUS" -eq 0 ] \
  || fail "worktree-guard fired for an unguarded repository"

# A real linked worktree must remain editable with two sessions.
LINKED_REPO="$TEMP_ROOT_WIN/guarded-repo-linked"
git -C "$TEST_REPO" worktree add -q -b linked-test "$LINKED_REPO"
set +e
printf '%s' "{\"tool_input\":{\"file_path\":\"$LINKED_REPO/note.md\"}}" | \
  PATH="$TEMP_ROOT/bin:$PATH" bash "$TEST_REPO/.claude/hooks/worktree-guard.sh" >/dev/null 2>&1
LINKED_STATUS=$?
set -e
[ "$LINKED_STATUS" -eq 0 ] \
  || fail "worktree-guard fired inside a real linked worktree"

# A primary checkout can legitimately use a separate Git directory whose path
# contains "worktrees". It must still block; path substrings are not identity.
SEPARATE_REPO="$TEMP_ROOT_WIN/guarded-separate"
SEPARATE_GIT_DIR="$TEMP_ROOT_WIN/worktrees-metadata/guarded-separate.git"
mkdir -p "$(dirname "$SEPARATE_GIT_DIR")"
git init -q -b main --separate-git-dir "$SEPARATE_GIT_DIR" "$SEPARATE_REPO"
printf 'guarded-separate\r\n' >> "$TEST_REPO/.claude/hooks/guarded-repos.txt"
set +e
SEPARATE_GUARD_STDERR=$(printf '%s' "{\"tool_input\":{\"file_path\":\"$SEPARATE_REPO/note.md\"}}" | \
  PATH="$TEMP_ROOT/bin:$PATH" bash "$TEST_REPO/.claude/hooks/worktree-guard.sh" 2>&1 >/dev/null)
SEPARATE_GUARD_STATUS=$?
set -e
if [ "$SEPARATE_GUARD_STATUS" -ne 2 ] || ! printf '%s' "$SEPARATE_GUARD_STDERR" | grep -q "guarded-separate"; then
  fail "worktree-guard mistook a primary checkout for a linked worktree from a path substring"
fi

prepare_precommit_repo() {
  local repo=$1
  mkdir -p "$repo/scripts"
  git -C "$repo" init -q -b main
  cp "$ROOT/scripts/pre-commit-hook.sh" "$repo/scripts/pre-commit-hook.sh"
  printf '%s\n' '#!/usr/bin/env bash' 'exit 0' > "$repo/scripts/validate-skills.sh"
}

# The filename tripwire must inspect basenames at any depth and preserve paths
# containing spaces without splitting them into separate candidates.
PRECOMMIT_BLOCK_REPO="$TEMP_ROOT_WIN/precommit-block"
prepare_precommit_repo "$PRECOMMIT_BLOCK_REPO"
mkdir -p "$PRECOMMIT_BLOCK_REPO/config" "$PRECOMMIT_BLOCK_REPO/secrets" \
  "$PRECOMMIT_BLOCK_REPO/space dir"
printf 'secret\n' > "$PRECOMMIT_BLOCK_REPO/.env"
printf 'secret\n' > "$PRECOMMIT_BLOCK_REPO/config/.env.local"
printf 'secret\n' > "$PRECOMMIT_BLOCK_REPO/secrets/token.json"
printf 'secret\n' > "$PRECOMMIT_BLOCK_REPO/space dir/credentials.json"
git -C "$PRECOMMIT_BLOCK_REPO" add -f -- .env config/.env.local \
  secrets/token.json "space dir/credentials.json"
set +e
PRECOMMIT_BLOCK_OUTPUT=$(cd "$PRECOMMIT_BLOCK_REPO" && bash scripts/pre-commit-hook.sh 2>&1)
PRECOMMIT_BLOCK_STATUS=$?
set -e
[ "$PRECOMMIT_BLOCK_STATUS" -eq 1 ] \
  || fail "pre-commit secret tripwire did not block nested and spaced secret filenames"
for blocked_path in .env config/.env.local secrets/token.json "space dir/credentials.json"; do
  printf '%s' "$PRECOMMIT_BLOCK_OUTPUT" | grep -Fq "BLOCKED: $blocked_path looks like a secrets file" \
    || fail "pre-commit secret tripwire omitted $blocked_path"
done

# Deletions must remain possible, and ordinary filenames that merely contain a
# secret-looking name must not fire the basename rules.
PRECOMMIT_SAFE_REPO="$TEMP_ROOT_WIN/precommit-safe"
prepare_precommit_repo "$PRECOMMIT_SAFE_REPO"
printf 'tracked secret\n' > "$PRECOMMIT_SAFE_REPO/token.json"
git -C "$PRECOMMIT_SAFE_REPO" add -f -- token.json
git -C "$PRECOMMIT_SAFE_REPO" -c user.name=Test -c user.email=test@example.invalid \
  commit -qm baseline
rm "$PRECOMMIT_SAFE_REPO/token.json"
mkdir -p "$PRECOMMIT_SAFE_REPO/config" "$PRECOMMIT_SAFE_REPO/notes with spaces"
printf 'safe\n' > "$PRECOMMIT_SAFE_REPO/config/credentials.json.example"
printf 'safe\n' > "$PRECOMMIT_SAFE_REPO/notes with spaces/token.json.md"
printf 'safe\n' > "$PRECOMMIT_SAFE_REPO/client-secret.txt"
git -C "$PRECOMMIT_SAFE_REPO" add -A -- token.json config/credentials.json.example \
  "notes with spaces/token.json.md" client-secret.txt
PRECOMMIT_SAFE_OUTPUT=$(cd "$PRECOMMIT_SAFE_REPO" && bash scripts/pre-commit-hook.sh 2>&1) \
  || fail "pre-commit secret tripwire blocked a deletion or near-miss filename"
printf '%s' "$PRECOMMIT_SAFE_OUTPUT" | grep -Fq 'Pre-commit checks passed' \
  || fail "pre-commit hook omitted its success result for safe staged paths"

# A rename into a secret basename is an addition at the destination and must
# still fire even though the source is removed.
PRECOMMIT_RENAME_REPO="$TEMP_ROOT_WIN/precommit-rename"
prepare_precommit_repo "$PRECOMMIT_RENAME_REPO"
printf 'ordinary\n' > "$PRECOMMIT_RENAME_REPO/settings.json"
git -C "$PRECOMMIT_RENAME_REPO" add settings.json
git -C "$PRECOMMIT_RENAME_REPO" -c user.name=Test -c user.email=test@example.invalid \
  commit -qm baseline
mkdir -p "$PRECOMMIT_RENAME_REPO/nested"
git -C "$PRECOMMIT_RENAME_REPO" mv settings.json nested/token.json
set +e
PRECOMMIT_RENAME_OUTPUT=$(cd "$PRECOMMIT_RENAME_REPO" && bash scripts/pre-commit-hook.sh 2>&1)
PRECOMMIT_RENAME_STATUS=$?
set -e
if [ "$PRECOMMIT_RENAME_STATUS" -ne 1 ] || \
  ! printf '%s' "$PRECOMMIT_RENAME_OUTPUT" | grep -Fq \
    'BLOCKED: nested/token.json looks like a secrets file'; then
  fail "pre-commit secret tripwire did not block a rename into a secret basename"
fi

# A staged type change still modifies a secret basename and must not disappear
# when deletions are excluded from the diff filter.
PRECOMMIT_TYPECHANGE_REPO="$TEMP_ROOT_WIN/precommit-typechange"
prepare_precommit_repo "$PRECOMMIT_TYPECHANGE_REPO"
mkdir -p "$PRECOMMIT_TYPECHANGE_REPO/nested"
printf 'ordinary\n' > "$PRECOMMIT_TYPECHANGE_REPO/nested/token.json"
git -C "$PRECOMMIT_TYPECHANGE_REPO" add -f -- nested/token.json
git -C "$PRECOMMIT_TYPECHANGE_REPO" -c user.name=Test -c user.email=test@example.invalid \
  commit -qm baseline
TYPECHANGE_BLOB=$(printf 'link-target\n' | \
  git -C "$PRECOMMIT_TYPECHANGE_REPO" hash-object -w --stdin)
git -C "$PRECOMMIT_TYPECHANGE_REPO" update-index \
  --cacheinfo 120000,"$TYPECHANGE_BLOB",nested/token.json
set +e
PRECOMMIT_TYPECHANGE_OUTPUT=$(cd "$PRECOMMIT_TYPECHANGE_REPO" && \
  bash scripts/pre-commit-hook.sh 2>&1)
PRECOMMIT_TYPECHANGE_STATUS=$?
set -e
if [ "$PRECOMMIT_TYPECHANGE_STATUS" -ne 1 ] || \
  ! printf '%s' "$PRECOMMIT_TYPECHANGE_OUTPUT" | grep -Fq \
    'BLOCKED: nested/token.json looks like a secrets file'; then
  fail "pre-commit secret tripwire did not block a secret basename type change"
fi

# Context warnings use the same NUL-safe staged-path transport.
PRECOMMIT_CONTEXT_REPO="$TEMP_ROOT_WIN/precommit-context"
prepare_precommit_repo "$PRECOMMIT_CONTEXT_REPO"
mkdir -p "$PRECOMMIT_CONTEXT_REPO/identity"
seq 301 > "$PRECOMMIT_CONTEXT_REPO/identity/large context.md"
git -C "$PRECOMMIT_CONTEXT_REPO" add "identity/large context.md"
PRECOMMIT_CONTEXT_OUTPUT=$(cd "$PRECOMMIT_CONTEXT_REPO" && bash scripts/pre-commit-hook.sh 2>&1) \
  || fail "pre-commit hook blocked a large context warning fixture"
printf '%s' "$PRECOMMIT_CONTEXT_OUTPUT" | grep -Fq \
  'identity/large context.md is 301 lines' \
  || fail "pre-commit context warning split a staged path containing spaces"

for hook in "$ROOT"/.claude/hooks/*.sh; do
  bash -n "$hook"
done

echo "Hook checks passed"
