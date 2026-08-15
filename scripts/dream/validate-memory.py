#!/usr/bin/env python3
"""Validate the local memory binding and /dream proposal artifacts.

The slash commands are prose, so the safety-critical filesystem checks live
here.  This helper intentionally accepts only a small, explicit proposal
surface: no path separators in memory filenames, no symlinked binding/artifact
components, no remotes in the memory git repository, and no empty evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")
MEMORY_FILE = re.compile(r"^(?:MEMORY|ARCHIVE|[a-z][A-Za-z0-9_-]*)\.md$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
COMMON_FIELDS = {"id", "action", "reasoning", "evidence", "confidence"}
ALLOWED_ACTIONS = {"modify", "archive", "merge", "split", "add", "flag"}
ALLOWED_CONFIDENCE = {"high", "medium", "low", "flag"}
SHIPPED_CURATORS = {"rot", "merge", "split", "lint"}
ALLOWED_TOP_LEVEL = {"curator", "ran_at", "inputs_summary", "proposals", "skipped"}
REQUIRED_TOP_LEVEL = {"curator", "ran_at", "proposals"}
ACTION_FIELDS = {
    "modify": {"target", "current_excerpt", "proposed_excerpt", "check"},
    "archive": {"target", "current_excerpt", "proposed_excerpt", "archive_reason", "check"},
    "merge": {
        "targets",
        "survivor",
        "merged_body",
        "index_changes",
        "archive_tombstones",
        "net_index_lines",
    },
    "split": {"target", "original_index_line", "result_files"},
    "add": {"target", "proposed_content", "index_line", "check"},
    "flag": {"target", "concern", "current_excerpt", "proposed_excerpt", "check"},
}
REQUIRED_ACTION_FIELDS = {
    "modify": {"target", "current_excerpt", "proposed_excerpt"},
    "archive": {"target", "archive_reason"},
    "merge": {
        "targets",
        "survivor",
        "merged_body",
        "index_changes",
        "archive_tombstones",
        "net_index_lines",
    },
    "split": {"target", "original_index_line", "result_files"},
    "add": {"target", "proposed_content", "index_line"},
    "flag": {"target", "concern"},
}


class ValidationError(ValueError):
    """A user-facing validation failure."""


def run_git(args: list[str], *, cwd: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ValidationError(f"git {' '.join(args)} failed: {detail}") from exc
    return completed.stdout.strip()


def repository_identity(repo: Path) -> str:
    common_dir = run_git(
        ["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=repo
    )
    resolved = Path(common_dir).resolve(strict=True)
    return str(resolved)


def read_single_line(path: Path, label: str) -> str:
    if path.is_symlink():
        raise ValidationError(f"{label} must not be a symlink: {path}")
    if not path.is_file():
        raise ValidationError(f"{label} must be a regular file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValidationError(f"cannot read {label}: {exc}") from exc
    lines = text.splitlines()
    if len(lines) != 1 or not lines[0].strip() or text != f"{lines[0]}\n":
        raise ValidationError(f"{label} must contain exactly one non-empty line")
    return lines[0]


def require_regular_file(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ValidationError(f"{label} must not be a symlink: {path}")
    if not path.is_file():
        raise ValidationError(f"{label} must be a regular file: {path}")


def require_canonical_directory(raw: str, label: str) -> Path:
    if CONTROL.search(raw):
        raise ValidationError(f"{label} contains a control character")
    path = Path(raw)
    if not path.is_absolute():
        raise ValidationError(f"{label} must be absolute")
    if path.is_symlink():
        raise ValidationError(f"{label} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValidationError(f"{label} must resolve to an existing directory: {exc}") from exc
    if str(path) != str(resolved):
        raise ValidationError(f"{label} must be canonical with no '..' or symlinks")
    if not resolved.is_dir():
        raise ValidationError(f"{label} must be an existing directory")
    return resolved


def ensure_inside(base: Path, child: Path, label: str) -> Path:
    resolved_child = child.resolve(strict=False)
    try:
        os.path.commonpath([str(base), str(resolved_child)])
    except ValueError as exc:
        raise ValidationError(f"{label} escapes memory directory") from exc
    if os.path.commonpath([str(base), str(resolved_child)]) != str(base):
        raise ValidationError(f"{label} escapes memory directory")
    return resolved_child


def ensure_no_symlink_components(path: Path, stop_at: Path, label: str) -> None:
    current = stop_at
    for part in path.relative_to(stop_at).parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValidationError(f"{label} contains a symlink component: {current}")


def validate_memory_binding(repo: Path) -> dict[str, str]:
    repo = repo.resolve(strict=True)
    identity = repository_identity(repo)
    binding = repo / ".context-os" / "memory-directory"
    memory_dir = require_canonical_directory(
        read_single_line(binding, ".context-os/memory-directory"),
        ".context-os/memory-directory",
    )

    marker = memory_dir / ".context-os-repository"
    marker_value = read_single_line(marker, "memory repository marker")
    if marker_value != identity:
        raise ValidationError(
            "memory repository marker does not match this repository identity"
        )
    require_regular_file(memory_dir / "MEMORY.md", "memory index")

    memory_top = Path(
        run_git(["rev-parse", "--show-toplevel"], cwd=memory_dir)
    ).resolve(strict=True)
    if memory_top != memory_dir:
        raise ValidationError("memory directory must be its own git top-level")
    if run_git(["remote"], cwd=memory_dir):
        raise ValidationError("memory git repository must not have remotes")
    return {"memory_dir": str(memory_dir), "repository_identity": identity}


def safe_memory_filename(
    value: Any,
    *,
    memory_dir: Path,
    label: str,
    require_existing: bool = False,
    require_absent: bool = False,
) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{label} must be a non-empty string")
    if CONTROL.search(value) or "/" in value or "\\" in value:
        raise ValidationError(f"{label} must be a plain memory filename")
    if value in {".", ".."} or value.startswith(".") or ".." in Path(value).parts:
        raise ValidationError(f"{label} must not be hidden or relative")
    if not MEMORY_FILE.fullmatch(value):
        raise ValidationError(f"{label} must be a safe .md memory filename")
    candidate = memory_dir / value
    if candidate.is_symlink():
        raise ValidationError(f"{label} must not point at a symlink")
    if require_existing:
        if not candidate.is_file():
            raise ValidationError(f"{label} must be an existing memory file")
    if require_absent and candidate.exists():
        raise ValidationError(f"{label} must not already exist")
    target = ensure_inside(memory_dir, candidate, label)
    if target.exists() and target.is_symlink():
        raise ValidationError(f"{label} must not point at a symlink")
    return value


def valid_timestamp(value: str) -> bool:
    if not TIMESTAMP.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H-%M-%SZ")
    except ValueError:
        return False
    return True


def dreams_root(memory_dir: Path) -> Path:
    candidate = memory_dir / ".dreams"
    if candidate.is_symlink():
        raise ValidationError("dreams root contains a symlink component")
    root = ensure_inside(memory_dir, candidate, "dreams root")
    ensure_no_symlink_components(root, memory_dir, "dreams root")
    return root


def resolve_artifact(memory_dir: Path, ts: str, *, for_create: bool) -> tuple[str, Path]:
    root = dreams_root(memory_dir)
    if ts == "latest":
        if for_create:
            raise ValidationError("latest cannot be used when creating an artifact")
        if not root.is_dir():
            raise ValidationError("no .dreams directory exists")
        candidates = [
            child.name
            for child in root.iterdir()
            if child.is_dir() and not child.is_symlink() and valid_timestamp(child.name)
        ]
        if not candidates:
            raise ValidationError("no valid dream artifacts exist")
        ts = sorted(candidates)[-1]
    elif not valid_timestamp(ts):
        raise ValidationError("dream timestamp must match YYYY-MM-DDTHH-MM-SSZ")

    path = ensure_inside(memory_dir, root / ts, "dream artifact")
    ensure_no_symlink_components(path, memory_dir, "dream artifact")
    if for_create:
        if path.exists():
            raise ValidationError(f"dream artifact already exists: {ts}")
        return ts, path

    if path.is_symlink() or not path.is_dir():
        raise ValidationError(f"dream artifact must be an existing directory: {ts}")
    require_regular_file(path / "proposals.json", "proposals.json")
    require_regular_file(path / "REPORT.md", "REPORT.md")
    return ts, path


def validate_common(proposal: dict[str, Any], index: int) -> str:
    missing = COMMON_FIELDS - set(proposal)
    if missing:
        raise ValidationError(f"proposal {index}: missing fields {sorted(missing)}")
    action = proposal["action"]
    if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
        raise ValidationError(f"proposal {index}: unknown action {action!r}")
    missing = REQUIRED_ACTION_FIELDS[action] - set(proposal)
    if missing:
        raise ValidationError(f"proposal {index}: missing {action} fields {sorted(missing)}")
    allowed = COMMON_FIELDS | ACTION_FIELDS[action]
    extra = set(proposal) - allowed
    if extra:
        raise ValidationError(f"proposal {index}: unknown fields {sorted(extra)}")
    for field in ("id", "reasoning"):
        if not isinstance(proposal[field], str) or not proposal[field].strip():
            raise ValidationError(f"proposal {index}: {field} must be non-empty")
    evidence = proposal["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValidationError(f"proposal {index}: evidence must be a non-empty array")
    if any(not isinstance(item, str) or not item.strip() for item in evidence):
        raise ValidationError(f"proposal {index}: every evidence item must be non-empty")
    confidence = proposal["confidence"]
    if not isinstance(confidence, str) or confidence not in ALLOWED_CONFIDENCE:
        raise ValidationError(f"proposal {index}: unsupported confidence {confidence!r}")
    return action


def require_string_fields(
    proposal: dict[str, Any],
    index: int,
    fields: set[str],
    *,
    allow_empty: set[str] | None = None,
) -> None:
    allow_empty = allow_empty or set()
    for field in fields:
        if field in proposal and not isinstance(proposal[field], str):
            raise ValidationError(f"proposal {index}: {field} must be a string")
        if field in proposal and field not in allow_empty and not proposal[field].strip():
            raise ValidationError(f"proposal {index}: {field} must be a non-empty string")


def validate_proposal(proposal: Any, index: int, *, memory_dir: Path) -> None:
    if not isinstance(proposal, dict):
        raise ValidationError(f"proposal {index}: must be an object")
    action = validate_common(proposal, index)

    if action in {"modify", "archive", "flag"}:
        safe_memory_filename(
            proposal["target"],
            memory_dir=memory_dir,
            label=f"proposal {index} target",
            require_existing=True,
        )
    if action == "split":
        original_target = safe_memory_filename(
            proposal["target"],
            memory_dir=memory_dir,
            label=f"proposal {index} target",
            require_existing=True,
        )
    else:
        original_target = None
    if action == "add":
        safe_memory_filename(
            proposal["target"],
            memory_dir=memory_dir,
            label=f"proposal {index} target",
            require_absent=True,
        )
    if action == "merge":
        targets = proposal["targets"]
        if not isinstance(targets, list) or len(targets) < 2:
            raise ValidationError(f"proposal {index}: merge targets must contain 2+ files")
        normalized_targets = []
        for target_index, target in enumerate(targets):
            normalized_targets.append(
                safe_memory_filename(
                    target,
                    memory_dir=memory_dir,
                    label=f"proposal {index} targets[{target_index}]",
                    require_existing=True,
                )
            )
        if len(set(normalized_targets)) != len(normalized_targets):
            raise ValidationError(f"proposal {index}: merge targets must be unique")
        survivor = safe_memory_filename(
            proposal["survivor"],
            memory_dir=memory_dir,
            label=f"proposal {index} survivor",
            require_existing=proposal["survivor"] in normalized_targets,
            require_absent=proposal["survivor"] not in normalized_targets,
        )
        index_changes = proposal.get("index_changes")
        if not isinstance(index_changes, dict):
            raise ValidationError(f"proposal {index}: index_changes must be an object")
        if set(index_changes) != {"remove", "add"}:
            raise ValidationError(f"proposal {index}: index_changes fields must be remove and add")
        if (
            not isinstance(index_changes["remove"], list)
            or any(not isinstance(item, str) or not item.strip() for item in index_changes["remove"])
            or not isinstance(index_changes["add"], str)
            or not index_changes["add"].strip()
        ):
            raise ValidationError(f"proposal {index}: index_changes must contain string remove[] and add")
        tombstones = proposal.get("archive_tombstones")
        if not isinstance(tombstones, list) or not tombstones:
            raise ValidationError(f"proposal {index}: archive_tombstones must be an array")
        if any(not isinstance(item, str) or not item.strip() for item in tombstones):
            raise ValidationError(f"proposal {index}: archive_tombstones must be non-empty strings")
        if type(proposal.get("net_index_lines")) is not int:
            raise ValidationError(f"proposal {index}: net_index_lines must be an integer")
        require_string_fields(proposal, index, {"merged_body"})
    elif action == "split":
        results = proposal["result_files"]
        if not isinstance(results, list) or not results:
            raise ValidationError(f"proposal {index}: result_files must be a non-empty array")
        result_names = []
        for result_index, result in enumerate(results):
            if not isinstance(result, dict):
                raise ValidationError(
                    f"proposal {index}: result_files[{result_index}] must be an object"
                )
            expected = {"name", "purpose", "index_line", "body"}
            if set(result) != expected:
                raise ValidationError(
                    f"proposal {index}: result_files[{result_index}] fields must be {sorted(expected)}"
                )
            result_names.append(
                safe_memory_filename(
                    result["name"],
                    memory_dir=memory_dir,
                    label=f"proposal {index} result_files[{result_index}].name",
                    require_existing=result["name"] == original_target,
                    require_absent=result["name"] != original_target,
                )
            )
            for field in ("purpose", "index_line", "body"):
                if not isinstance(result[field], str) or not result[field].strip():
                    raise ValidationError(
                        f"proposal {index}: result_files[{result_index}].{field} must be non-empty"
                    )
        if len(set(result_names)) != len(result_names):
            raise ValidationError(f"proposal {index}: result file names must be unique")
        require_string_fields(proposal, index, {"original_index_line"})
    elif action == "modify":
        require_string_fields(
            proposal,
            index,
            {"current_excerpt", "proposed_excerpt", "check"},
            allow_empty={"proposed_excerpt"},
        )
    else:
        require_string_fields(
            proposal,
            index,
            {
                "current_excerpt",
                "proposed_excerpt",
                "archive_reason",
                "proposed_content",
                "index_line",
                "concern",
                "check",
            },
            allow_empty={"proposed_excerpt"},
        )


def validate_proposals(path: Path, *, memory_dir: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot parse proposals.json: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("proposals.json must be a top-level object")
    missing = REQUIRED_TOP_LEVEL - set(data)
    if missing:
        raise ValidationError(f"proposals.json is missing fields {sorted(missing)}")
    extra = set(data) - ALLOWED_TOP_LEVEL
    if extra:
        raise ValidationError(f"proposals.json has unknown top-level fields {sorted(extra)}")
    if not isinstance(data["curator"], str) or data["curator"] not in SHIPPED_CURATORS:
        raise ValidationError("proposals.json curator must name a shipped curator")
    if not isinstance(data["ran_at"], str):
        raise ValidationError("proposals.json ran_at must be a UTC timestamp string")
    try:
        datetime.strptime(data["ran_at"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValidationError("proposals.json ran_at must match YYYY-MM-DDTHH:MM:SSZ") from exc
    if "inputs_summary" in data and not isinstance(data["inputs_summary"], dict):
        raise ValidationError("proposals.json inputs_summary must be an object")
    if "skipped" in data and not isinstance(data["skipped"], list):
        raise ValidationError("proposals.json skipped must be an array")
    proposals = data.get("proposals")
    if not isinstance(proposals, list):
        raise ValidationError("proposals.json must contain a proposals array")
    for index, proposal in enumerate(proposals):
        validate_proposal(proposal, index, memory_dir=memory_dir)
    return len(proposals)


def cmd_resolve(_: argparse.Namespace) -> dict[str, Any]:
    return validate_memory_binding(Path.cwd())


def cmd_artifact(args: argparse.Namespace) -> dict[str, Any]:
    binding = validate_memory_binding(Path.cwd())
    memory_dir = Path(binding["memory_dir"])
    ts, path = resolve_artifact(memory_dir, args.timestamp, for_create=args.for_create)
    result: dict[str, Any] = {**binding, "timestamp": ts, "dream_dir": str(path)}
    if not args.for_create:
        result["proposal_count"] = validate_proposals(path / "proposals.json", memory_dir=memory_dir)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("resolve", help="validate and print the memory binding")

    artifact = subcommands.add_parser("artifact", help="validate or allocate a dream artifact")
    artifact.add_argument("timestamp", help="YYYY-MM-DDTHH-MM-SSZ or latest")
    artifact.add_argument(
        "--for-create",
        action="store_true",
        help="validate a new timestamp path without requiring files to exist",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "resolve":
            result = cmd_resolve(args)
        elif args.command == "artifact":
            result = cmd_artifact(args)
        else:  # pragma: no cover - argparse prevents this.
            parser.error("unknown command")
    except ValidationError as exc:
        print(f"validate-memory: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
