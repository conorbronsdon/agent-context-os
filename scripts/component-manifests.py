#!/usr/bin/env python3
"""Validate the component inventory and its coverage of tracked files."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "components" / "manifest.json"
sys.path.insert(0, str(ROOT))

from contextos.component_schema import (  # noqa: E402
    ComponentManifestError,
    component_schema_document,
    load_component_manifest,
    unclassified_tracked_paths,
    untracked_owned_paths,
    write_generated_file,
)


SCHEMA_PATH = ROOT / "components" / "schema.json"


def schema_text() -> str:
    return json.dumps(component_schema_document(), indent=2, ensure_ascii=False) + "\n"


def git_tracked_paths(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip() \
            if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise ComponentManifestError(f"git ls-files failed: {detail}") from None
    try:
        decoded = result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ComponentManifestError(f"git ls-files returned a non-UTF-8 path: {exc}") from None
    if decoded and not decoded.endswith("\0"):
        raise ComponentManifestError("git ls-files -z returned an unterminated path")
    paths = decoded.rstrip("\0").split("\0") if decoded else []
    # An unresolved index can list one pathname once per stage. Preserve
    # distinct spellings so portable collisions still fail, but collapse exact
    # stage duplicates before applying the source-set contract.
    return list(dict.fromkeys(paths))


def check(
    root: Path = ROOT, manifest_path: Path | None = None,
    schema_path: Path | None = None,
    *, allow_extensible: bool = False,
) -> tuple[int, int]:
    manifest_path = manifest_path or root / "components" / "manifest.json"
    schema_path = schema_path or root / "components" / "schema.json"
    manifest = load_component_manifest(
        manifest_path,
        root=root,
        check_paths=True,
        allow_missing_seed=allow_extensible,
    )
    if (not schema_path.exists()
            or schema_path.read_text(encoding="utf-8") != schema_text()):
        raise ComponentManifestError(
            "components/schema.json is stale; run scripts/component-manifests.py generate"
        )
    tracked = git_tracked_paths(root)
    missing = unclassified_tracked_paths(
        manifest, tracked, root=root, allow_extensible=allow_extensible
    )
    if missing:
        preview = ", ".join(missing[:20])
        if len(missing) > 20:
            preview += f", ... ({len(missing) - 20} more)"
        raise ComponentManifestError(f"unclassified tracked paths: {preview}")
    untracked_owned = untracked_owned_paths(
        manifest, tracked, root=root, allow_missing_seed=allow_extensible
    )
    if untracked_owned:
        preview = ", ".join(untracked_owned[:20])
        if len(untracked_owned) > 20:
            preview += f", ... ({len(untracked_owned) - 20} more)"
        raise ComponentManifestError(f"owned paths are not tracked by git: {preview}")
    path_count = sum(len(component["paths"]) for component in manifest["components"])
    return len(manifest["components"]), path_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate", "check"))
    parser.add_argument(
        "--allow-extensible",
        action="store_true",
        help=(
            "allow unowned tracked files below declared extensible roots; "
            "use only when validating a personalized workspace"
        ),
    )
    args = parser.parse_args(argv)
    if args.command != "check" and args.allow_extensible:
        parser.error("--allow-extensible is only valid with check")
    try:
        if args.command == "generate":
            # Validate structure before writing. Full path and coverage checks run
            # after the schema has been bootstrapped because it inventories itself.
            load_component_manifest(MANIFEST_PATH, root=ROOT, check_paths=False)
            write_generated_file(SCHEMA_PATH, schema_text(), root=ROOT)
            component_count, path_count = check()
        else:
            component_count, path_count = check(
                allow_extensible=args.allow_extensible
            )
    except (ComponentManifestError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"component-manifests: {exc}", file=sys.stderr)
        return 1
    print(
        f"Component manifest {args.command} passed ({component_count} components, "
        f"{path_count} exact paths)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
