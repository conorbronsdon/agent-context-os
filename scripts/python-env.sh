#!/usr/bin/env bash
# Resolve one working Python command for repository shell workflows.
#
# Discovery order is CONTEXTOS_PYTHON, then python3, then python. The floor is
# Python 3.9 because the kernel uses str.removeprefix.
#
# CONTEXTOS_PYTHON is an explicit instruction, not a hint: if it is set and does
# not work, this fails loudly rather than running against a different
# interpreter than the one that was asked for.

CONTEXTOS_PYTHON_CMD=""

_contextos_python_works() {
  command -v "$1" >/dev/null 2>&1 &&
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1
}

if [ -n "${CONTEXTOS_PYTHON:-}" ]; then
  if _contextos_python_works "$CONTEXTOS_PYTHON"; then
    CONTEXTOS_PYTHON_CMD="$CONTEXTOS_PYTHON"
  else
    echo "CONTEXTOS_PYTHON is set to '$CONTEXTOS_PYTHON', which is not a working Python 3.9+ interpreter." >&2
    echo "Fix or unset it; an explicit interpreter is never silently replaced with another one." >&2
    unset -f _contextos_python_works
    return 1 2>/dev/null || exit 1
  fi
else
  for candidate in python3 python; do
    if _contextos_python_works "$candidate"; then
      CONTEXTOS_PYTHON_CMD="$candidate"
      break
    fi
  done
  unset candidate
fi

unset -f _contextos_python_works

if [ -z "$CONTEXTOS_PYTHON_CMD" ]; then
  echo "Python 3.9 or newer is required. Install it as 'python3' or 'python', or set CONTEXTOS_PYTHON." >&2
  return 1 2>/dev/null || exit 1
fi

export CONTEXTOS_PYTHON_CMD
