#!/usr/bin/env python3
"""Generate or verify runtime-registry artifacts from the Python contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contextos.kernel import ContextOSError, runtime_registry  # noqa: E402
from contextos.runtime_schema import runtime_schema_document  # noqa: E402


README_START = "<!-- runtime-support:start -->"
README_END = "<!-- runtime-support:end -->"


def schema_text() -> str:
    return json.dumps(runtime_schema_document(), indent=2, ensure_ascii=False) + "\n"


def support_block(registry: dict[str, dict[str, object]]) -> str:
    def cell(value: object) -> str:
        return str(value).replace("\\", "\\\\").replace("|", "\\|")

    lines = [
        README_START,
        "| Host | Tier | Support |",
        "|---|---|---|",
    ]
    for manifest in registry.values():
        if manifest["support_tier"] not in {"first-class", "experimental"}:
            continue
        lines.append(
            f"| {cell(manifest['display_name'])} | {cell(manifest['support_tier'])} | "
            f"{cell(manifest['support_summary'])} |"
        )
    lines.append(README_END)
    return "\n".join(lines)


def replace_block(readme: str, block: str) -> str:
    if readme.count(README_START) != 1 or readme.count(README_END) != 1:
        raise ContextOSError("README runtime support markers must each appear exactly once")
    before, remainder = readme.split(README_START, 1)
    _, after = remainder.split(README_END, 1)
    return before + block + after


def generated() -> tuple[str, str]:
    registry = runtime_registry(ROOT)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    return schema_text(), replace_block(readme, support_block(registry))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("generate", "check"))
    args = parser.parse_args()
    try:
        wanted_schema, wanted_readme = generated()
        targets = {
            ROOT / "runtimes" / "schema.json": wanted_schema,
            ROOT / "README.md": wanted_readme,
        }
        if args.command == "generate":
            for path, content in targets.items():
                path.write_text(content, encoding="utf-8", newline="\n")
            print("Generated runtime schema and README support table")
            return 0
        stale = [path.relative_to(ROOT).as_posix() for path, content in targets.items()
                 if not path.exists() or path.read_text(encoding="utf-8") != content]
        if stale:
            print(
                "runtime registry artifacts are stale: " + ", ".join(stale)
                + "; run scripts/runtime-manifests.py generate",
                file=sys.stderr,
            )
            return 1
        print(f"Runtime registry checks passed ({len(runtime_registry(ROOT))} descriptors)")
        return 0
    except (ContextOSError, OSError, UnicodeError, ValueError) as exc:
        print(f"runtime-manifests: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
