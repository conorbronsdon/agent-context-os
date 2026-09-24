#!/usr/bin/env bash
# Resolve one working Python command for repository shell workflows.
#
# Discovery order is CONTEXTOS_PYTHON, then python3, then python. The floor is
# Python 3.10 because the kernel uses Path.write_text(newline=...).
#
# CONTEXTOS_PYTHON is an explicit instruction, not a hint: if it is set and does
# not work, this fails loudly rather than running against a different
# interpreter than the one that was asked for.
# CONTEXTOS_PYTHON_PLATFORM records sys.platform from the same probe that
# validates the interpreter, so path conversion does not start Python again.

CONTEXTOS_PYTHON_CMD=""
CONTEXTOS_PYTHON_PLATFORM=""

# WSL passes only variables named in WSLENV to Windows programs, so a Windows
# python.exe would otherwise lose the encoding and bytecode settings below and
# the kernel's root overrides. /p translates a path value for Windows.
if [ "$(uname -s)" = Linux ] && { [ -n "${WSL_INTEROP:-}" ] || [ -n "${WSL_DISTRO_NAME:-}" ]; }; then
  for _contextos_wslenv in PYTHONIOENCODING PYTHONDONTWRITEBYTECODE CONTEXTOS_CONTEXT_ROOT/p CONTEXTOS_WORKING_ROOT/p; do
    case ":${WSLENV:-}:" in
      *":${_contextos_wslenv%%/*}:"*|*":${_contextos_wslenv%%/*}/"*) ;;
      *) WSLENV="${WSLENV:+$WSLENV:}$_contextos_wslenv" ;;
    esac
  done
  unset _contextos_wslenv
  export WSLENV
fi

_contextos_python_works() {
  local probe_output probe_hex probe_platform
  command -v "$1" >/dev/null 2>&1 || return 1
  probe_output=$(PYTHONIOENCODING=utf-8 "$1" -c \
    'import sys; sys.version_info >= (3, 10) or sys.exit(1); sys.stdout.write(sys.platform + ":" + chr(0x2713))' \
    2>/dev/null) || return 1
  case "$probe_output" in *:*) ;; *) return 1 ;; esac
  probe_platform=${probe_output%%:*}
  probe_hex=$(set -o pipefail
    printf '%s' "${probe_output#*:}" | od -An -v -tx1 | tr -d '[:space:]'
  ) || return 1
  [ -n "$probe_platform" ] && [ "$probe_hex" = 'e29c93' ] || return 1
  CONTEXTOS_PYTHON_PLATFORM="$probe_platform"
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
export CONTEXTOS_PYTHON_PLATFORM
export PYTHONIOENCODING=utf-8

# Repository lifecycle commands must not create executable bytecode as a side
# effect. Besides keeping working trees clean, this lets integrity checks treat
# any new or changed .pyc file as a real mutation instead of normal operation.
export PYTHONDONTWRITEBYTECODE=1

# Native Windows Python needs a native path from MSYS, Cygwin, or WSL.
contextos_python_path() {
  local path="$1" converter="" converted
  if [ "$CONTEXTOS_PYTHON_PLATFORM" = win32 ]; then
    case "$(uname -s)" in
      MINGW*|MSYS*|CYGWIN*)
        if command -v cygpath >/dev/null 2>&1; then converter=cygpath; fi
        ;;
      Linux)
        if command -v wslpath >/dev/null 2>&1 &&
          { [ -n "${WSL_INTEROP:-}" ] || [ -n "${WSL_DISTRO_NAME:-}" ] ||
            { [ -r /proc/version ] && grep -Eiq 'microsoft|wsl' /proc/version; }; }; then
          converter=wslpath
        fi
        ;;
    esac
  fi
  if [ -n "$converter" ]; then
    if ! converted=$("$converter" -w "$path" 2>/dev/null) || [ -z "$converted" ]; then
      printf 'contextos_python_path: %s -w failed for %q\n' "$converter" "$path" >&2
      return 1
    fi
    printf '%s\n' "$converted"
    return
  fi
  printf '%s\n' "$path"
}
