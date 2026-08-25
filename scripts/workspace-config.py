#!/usr/bin/env python3
"""Generate or verify tracked workspace-configuration artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contextos.component_schema import write_generated_file  # noqa: E402
from contextos.kernel import ContextOSError, runtime_ids  # noqa: E402
from contextos.workspace_schema import (  # noqa: E402
    WorkspaceConfigError,
    load_workspace_config,
    workspace_schema_document,
)


CONFIG_PATH = ROOT / "workspace" / "example.json"
SCHEMA_PATH = ROOT / "workspace" / "schema.json"


def schema_text() -> str:
    return json.dumps(workspace_schema_document(), indent=2, ensure_ascii=False) + "\n"


def check() -> tuple[int, int]:
    config, canonical = load_workspace_config(
        CONFIG_PATH,
        root=ROOT,
        known_runtime_ids=runtime_ids(ROOT),
    )
    if not canonical:
        raise WorkspaceConfigError(
            "workspace/example.json is not canonical; render it canonically"
        )
    if not SCHEMA_PATH.exists() or SCHEMA_PATH.read_text(encoding="utf-8") != schema_text():
        raise WorkspaceConfigError(
            "workspace/schema.json is stale; run scripts/workspace-config.py generate"
        )
    return len(config["agents"]), len(config["paths"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate", "check"))
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            write_generated_file(SCHEMA_PATH, schema_text(), root=ROOT)
        agent_count, path_count = check()
    except (WorkspaceConfigError, ContextOSError, OSError, UnicodeError) as exc:
        print(f"workspace-config: {exc}", file=sys.stderr)
        return 1
    print(
        f"Workspace configuration {args.command} passed "
        f"({agent_count} agents, {path_count} paths)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
