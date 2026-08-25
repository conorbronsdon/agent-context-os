#!/usr/bin/env bash
# session-start.sh — Advisory hook for session start.
# Uses the lifecycle kernel's shared readiness predicate and nudges toward /start.
# This hook is ADVISORY — it prints reminders but never blocks (always exits 0).

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
HOOK_WRAPPER="$REPO_ROOT/scripts/context-os-hook.sh"

if [ ! -f "$HOOK_WRAPPER" ]; then
  echo "  Context OS readiness check is unavailable; scripts/context-os-hook.sh is missing."
  exit 0
fi

set +e
HOOK_OUTPUT=$(bash "$HOOK_WRAPPER" claude session-start </dev/null 2>&1)
HOOK_STATUS=$?
set -e

if [ -n "$HOOK_OUTPUT" ]; then
  printf '%s\n' "$HOOK_OUTPUT"
fi

if [ "$HOOK_STATUS" -eq 0 ] && [ -z "$HOOK_OUTPUT" ]; then
  echo ""
  echo "  Tip: Run /start for a full session briefing."
  echo ""
fi

exit 0
