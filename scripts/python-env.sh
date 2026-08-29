#!/usr/bin/env bash
# Resolve one working Python command for repository shell workflows.
#
# Discovery order is CONTEXTOS_PYTHON, then python3, then python. The floor is
# Python 3.10 because the kernel uses Path.write_text(newline=...).
#
# CONTEXTOS_PYTHON is an explicit instruction, not a hint: if it is set and does
# not work, this fails loudly rather than running against a different
# interpreter than the one that was asked for.

CONTEXTOS_PYTHON_CMD=""

_contextos_python_works() {
  local probe_hex
  command -v "$1" >/dev/null 2>&1 || return 1
  probe_hex=$(set -o pipefail
    PYTHONIOENCODING=utf-8 "$1" -c \
      'import sys; sys.version_info >= (3, 10) or sys.exit(1); sys.stdout.write(chr(0x2713))' \
      2>/dev/null | od -An -v -tx1 | tr -d '[:space:]'
  ) || return 1
  [ "$probe_hex" = 'e29c93' ]
}

if [ -n "${CONTEXTOS_PYTHON:-}" ]; then
  if _contextos_python_works "$CONTEXTOS_PYTHON"; then
    CONTEXTOS_PYTHON_CMD="$CONTEXTOS_PYTHON"
  else
    echo "CONTEXTOS_PYTHON is set to '$CONTEXTOS_PYTHON', which is not a working Python 3.10+ interpreter." >&2
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
  echo "Python 3.10 or newer is required. Install it as 'python3' or 'python', or set CONTEXTOS_PYTHON." >&2
  return 1 2>/dev/null || exit 1
fi

export CONTEXTOS_PYTHON_CMD
export PYTHONIOENCODING=utf-8

# Repository lifecycle commands must not create executable bytecode as a side
# effect. Besides keeping working trees clean, this lets integrity checks treat
# any new or changed .pyc file as a real mutation instead of normal operation.
export PYTHONDONTWRITEBYTECODE=1
