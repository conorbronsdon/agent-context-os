#!/usr/bin/env bash
# POSIX hook entry point. Wraps context-os-hook.py with the repository's
# resolved Python interpreter so hosts that expose Python 3 only as `python`
# still get lifecycle advisories.
#
#   bash scripts/context-os-hook.sh codex session-start

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/python-env.sh"

exec "$CONTEXTOS_PYTHON_CMD" "$SCRIPT_DIR/context-os-hook.py" "$@"
