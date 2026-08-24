#!/usr/bin/env bash
# Run every dependency-light repository check used by CI.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
source "$ROOT/scripts/python-env.sh"

bash scripts/validate-skills.sh
bash scripts/check-links.sh
bash tests/test-portability.sh
bash tests/test-hooks.sh

while IFS= read -r -d '' script; do
  bash -n "$script"
done < <(find .claude/hooks scripts tests -name '*.sh' -print0)

"$CONTEXTOS_PYTHON_CMD" -m unittest discover -s tests -p 'test_*.py'
"$CONTEXTOS_PYTHON_CMD" scripts/integrations.py check

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
    Path("runtimes/schema.json"),
    Path("runtimes/claude.json"),
    Path("runtimes/codex.json"),
    Path("runtimes/hermes.json"),
]
for path in paths:
    with path.open(encoding="utf-8") as handle:
        json.load(handle)
print("JSON checks passed")
PY

echo "All validation passed"
