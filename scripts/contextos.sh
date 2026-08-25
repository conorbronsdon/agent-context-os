#!/usr/bin/env bash
# Run the lifecycle kernel with the repository's resolved Python interpreter.
# Use this instead of `python3 -m contextos` so hosts that expose Python 3 only
# as `python` work, and so CONTEXTOS_PYTHON is honored.
#
#   bash scripts/contextos.sh start
#   bash scripts/contextos.sh propose end --input <payload.json>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/python-env.sh"

cd "$(cd "$SCRIPT_DIR/.." && pwd)"
exec "$CONTEXTOS_PYTHON_CMD" -m contextos "$@"
