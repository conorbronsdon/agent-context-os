#!/usr/bin/env bash
# Resolve one working Python 3 command for repository shell workflows.
# CONTEXTOS_PYTHON may name an explicit interpreter path or command.

CONTEXTOS_PYTHON_CMD=""
python_candidates=()
if [ -n "${CONTEXTOS_PYTHON:-}" ]; then
  python_candidates+=("$CONTEXTOS_PYTHON")
fi
python_candidates+=(python3 python)

for candidate in "${python_candidates[@]}"; do
  if command -v "$candidate" >/dev/null 2>&1 &&
    "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)' >/dev/null 2>&1; then
    CONTEXTOS_PYTHON_CMD="$candidate"
    break
  fi
done
unset python_candidates candidate

if [ -z "$CONTEXTOS_PYTHON_CMD" ]; then
  echo "Python 3 is required. Install it as 'python3' or 'python', or set CONTEXTOS_PYTHON." >&2
  return 1 2>/dev/null || exit 1
fi

export CONTEXTOS_PYTHON_CMD
