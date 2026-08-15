#!/usr/bin/env bash
# ssot-guard.sh — Advisory hook for PreToolUse (Edit, Write).
# Warns when editing files that are Single Source of Truth (SSOT) for specific data,
# reminding you to update the canonical location instead of duplicating facts.
#
# Customize the patterns below for your repo's SSOT rules.
# This hook is ADVISORY — it prints warnings but never blocks (always exits 0).

set -euo pipefail

# Claude Code sends hook data as JSON on stdin. Keep the argument and
# CLAUDE_FILE_PATH fallbacks for direct/manual use.
FILE_PATH="${1:-${CLAUDE_FILE_PATH:-}}"

if [ -z "$FILE_PATH" ] && [ ! -t 0 ]; then
  INPUT=$(cat)
  PYTHON_BIN=""
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  fi

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
fi

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# ── Define SSOT patterns ──────────────────────────────────────────────────────
# Add your own patterns here. Format: file glob → reminder message.

case "$FILE_PATH" in
  */state/current.md)
    echo "Reminder: current.md is updated by /end and /update commands. Manual edits are fine but will be overwritten next session close."
    ;;
  */state/decisions.md)
    echo "Reminder: decisions.md is append-only. Don't edit past entries — add new ones at the top."
    ;;
  # Example: protect a metrics file
  # */analytics/metrics.md)
  #   echo "Reminder: metrics.md is the SSOT for numbers. Update here, not in other docs."
  #   ;;
esac

exit 0
