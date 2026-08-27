#!/usr/bin/env bash
# Run every dependency-light repository check used by CI.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
source "$ROOT/scripts/python-env.sh"

COMPONENT_CHECK_ARGS=(check)
VALIDATION_PROFILE=maintainer
if [[ ${1:-} == "--workspace" ]]; then
  COMPONENT_CHECK_ARGS+=(--allow-extensible)
  VALIDATION_PROFILE=workspace
  shift
fi
if (( $# )); then
  echo "Usage: bash scripts/validate-all.sh [--workspace]" >&2
  exit 2
fi

bash scripts/validate-skills.sh
bash scripts/check-links.sh
bash scripts/check-doc-reachability.sh
bash tests/test-portability.sh
bash tests/test-hooks.sh

while IFS= read -r -d '' script; do
  bash -n "$script"
done < <(find .claude/hooks scripts tests -name '*.sh' -print0)

CONTEXTOS_VALIDATION_PROFILE="$VALIDATION_PROFILE" \
  "$CONTEXTOS_PYTHON_CMD" -m unittest discover -s tests -p 'test_*.py'
"$CONTEXTOS_PYTHON_CMD" scripts/integrations.py check
"$CONTEXTOS_PYTHON_CMD" scripts/component-manifests.py "${COMPONENT_CHECK_ARGS[@]}"
"$CONTEXTOS_PYTHON_CMD" scripts/runtime-manifests.py check

"$CONTEXTOS_PYTHON_CMD" - <<'PY'
import json
from pathlib import Path

paths = [
    Path(".claude/settings.json"),
    Path(".codex/hooks.json"),
    Path("docs/templates/workflow-parity.json"),
    Path("docs/templates/setup-payload.json"),
    Path("docs/templates/update-payload.json"),
    Path("docs/templates/end-payload.json"),
    Path("integrations/catalog.json"),
]
paths.extend(sorted(Path("runtimes").glob("*.json")))
for path in paths:
    with path.open(encoding="utf-8") as handle:
        json.load(handle)
print("JSON checks passed")
PY

echo "All validation passed"
