#!/usr/bin/env bash
# Run every dependency-light repository check used by CI.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

bash scripts/validate-skills.sh
bash scripts/check-links.sh
bash tests/test-portability.sh
bash tests/test-hooks.sh

while IFS= read -r -d '' script; do
  bash -n "$script"
done < <(find .claude/hooks scripts tests -name '*.sh' -print0)

python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/integrations.py check

python3 - <<'PY'
import json
from pathlib import Path

paths = [
    Path(".claude/settings.json"),
    Path("docs/templates/workflow-parity.json"),
    Path("integrations/catalog.json"),
]
for path in paths:
    with path.open(encoding="utf-8") as handle:
        json.load(handle)
print("JSON checks passed")
PY

echo "All validation passed"
