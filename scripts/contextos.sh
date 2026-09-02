#!/usr/bin/env bash
# Run the lifecycle kernel with the repository's resolved Python interpreter.
# The script parent is the trusted KernelRoot.  Execute Python from that root so
# an attached WorkingRoot cannot shadow standard-library imports; split-root
# invocations bind the application explicitly with --working-root.  When no
# split-root options are supplied the CLI retains v0.12 colocated compatibility.
# Use this instead of `python3 -m contextos` so hosts that expose Python 3 only
# as `python` work, and so CONTEXTOS_PYTHON is honored.
#
#   bash scripts/contextos.sh start
#   bash scripts/contextos.sh propose end --input <payload.json>

set -euo pipefail

SCRIPT_DIR="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SCRIPT_DIR/python-env.sh"

KERNEL_ROOT="$(cd -P -- "$SCRIPT_DIR/.." && pwd -P)"
cd "$KERNEL_ROOT"
exec "$CONTEXTOS_PYTHON_CMD" -c \
  'import runpy, sys; sys.path.insert(0, sys.argv.pop(1)); runpy.run_module("contextos", run_name="__main__")' \
  "$KERNEL_ROOT" --kernel-root "$KERNEL_ROOT" "$@"
