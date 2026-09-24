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
# Existing entries for these names are replaced, because a flag such as /u
# (Windows to WSL only) or a missing /p would defeat the forwarding.
if [ "$(uname -s)" = Linux ] && { [ -n "${WSL_INTEROP:-}" ] || [ -n "${WSL_DISTRO_NAME:-}" ]; }; then
  _contextos_wslenv=""
  IFS=: read -r -a _contextos_wslenv_parts <<< "${WSLENV:-}"
  for _contextos_wslenv_part in ${_contextos_wslenv_parts[@]+"${_contextos_wslenv_parts[@]}"}; do
    case "${_contextos_wslenv_part%%/*}" in
      ""|PYTHONIOENCODING|PYTHONDONTWRITEBYTECODE|CONTEXTOS_CONTEXT_ROOT|CONTEXTOS_WORKING_ROOT) ;;
      *) _contextos_wslenv="${_contextos_wslenv:+$_contextos_wslenv:}$_contextos_wslenv_part" ;;
    esac
  done
  WSLENV="${_contextos_wslenv:+$_contextos_wslenv:}PYTHONIOENCODING:PYTHONDONTWRITEBYTECODE:CONTEXTOS_CONTEXT_ROOT/p:CONTEXTOS_WORKING_ROOT/p"
  unset _contextos_wslenv _contextos_wslenv_part _contextos_wslenv_parts
  export WSLENV
fi

_contextos_python_works() {
  local probe_hex prefix byte platform=""
  command -v "$1" >/dev/null 2>&1 || return 1
  # Pipe the raw bytes to od: command substitution would drop NUL bytes and
  # trailing newlines, so only a byte-level check keeps the probe exact.
  probe_hex=$(set -o pipefail
    PYTHONIOENCODING=utf-8 "$1" -c \
      'import sys; sys.version_info >= (3, 10) or sys.exit(1); sys.stdout.write(sys.platform + ":" + chr(0x2713))' \
      2>/dev/null | od -An -v -tx1 | tr -d '[:space:]'
  ) || return 1
  # Expect "<platform>:" then the UTF-8 check mark (3a e2 9c 93); the platform
  # may contain only lowercase ASCII letters and digits.
  prefix=${probe_hex%3ae29c93}
  [ -n "$prefix" ] && [ "$prefix" != "$probe_hex" ] || return 1
  while [ -n "$prefix" ]; do
    byte=${prefix:0:2}
    prefix=${prefix:2}
    case "$byte" in
      3[0-9]|6[1-9a-f]|7[0-9a]) platform="$platform$(printf "\\x$byte")" ;;
      *) return 1 ;;
    esac
  done
  CONTEXTOS_PYTHON_PLATFORM="$platform"
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

# Convert path arguments for a Windows interpreter; WSL passes arguments to
# Windows programs unmodified. Only values of the kernel's path options
# (CONTEXTOS_PATH_OPTIONS, kept equal to the CLI's type=Path options by
# tests/test-portability.sh) and positional arguments that are existing paths
# are converted, so message text such as "/note" is left alone. Sets CONTEXTOS_PYTHON_ARGS.
CONTEXTOS_PATH_OPTIONS=" --context-root --current-lock --current-source --cursor-file --input --kernel-root --lock --proposal --root --source --target --working-root --workspace-config --workspace-config-input "

_contextos_convertible_path() {
  local parent
  [ -e "$1" ] && return 0
  parent=$(dirname -- "$1")
  [ "$parent" != / ] && [ -d "$parent" ]
}

contextos_python_args() {
  local arg name value expect_path=0
  CONTEXTOS_PYTHON_ARGS=()
  for arg in "$@"; do
    if [ "$CONTEXTOS_PYTHON_PLATFORM" = win32 ]; then
      if [ "$expect_path" = 1 ]; then
        case "$arg" in
          /*) if _contextos_convertible_path "$arg"; then arg=$(contextos_python_path "$arg") || return 1; fi ;;
        esac
      else
        case "$arg" in
          --*=/*)
            name=${arg%%=*}
            value=${arg#*=}
            case "$CONTEXTOS_PATH_OPTIONS" in
              *" $name "*)
                if _contextos_convertible_path "$value"; then
                  value=$(contextos_python_path "$value") || return 1
                  arg="$name=$value"
                fi
                ;;
            esac
            ;;
          /*)
            if [ -e "$arg" ]; then arg=$(contextos_python_path "$arg") || return 1; fi
            ;;
        esac
      fi
    fi
    expect_path=0
    case "$CONTEXTOS_PATH_OPTIONS" in
      *" $arg "*) expect_path=1 ;;
    esac
    CONTEXTOS_PYTHON_ARGS+=("$arg")
  done
}
