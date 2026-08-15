#!/usr/bin/env python3
"""Validate the local memory binding and /dream proposal artifacts.

The slash commands are prose, so the safety-critical filesystem checks live
here.  This helper intentionally accepts only a small, explicit proposal
surface: no path separators in memory filenames, no symlinked binding/artifact
components, no remotes or unrelated changes in the memory git repository,
reserved control files for structural actions, no proposal collisions, and no
empty evidence.
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
CURATOR_ACTIONS = {
    "rot": {"modify", "archive", "flag"},
    "merge": {"merge", "flag"},
    "split": {"split", "flag"},
    "lint": {"modify", "archive", "flag"},
}
CONTROL_FILES = {"MEMORY.md", "ARCHIVE.md"}
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


def run_git_paths(args: list[str], *, cwd: Path) -> set[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return {
            item.decode("utf-8")
            for item in completed.stdout.split(b"\0")
            if item
        }
    except (subprocess.CalledProcessError, UnicodeError) as exc:
        detail = getattr(exc, "stderr", b"")
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        raise ValidationError(f"cannot inspect memory git changes: {str(detail).strip()}") from exc


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


def changed_memory_paths(memory_dir: Path) -> set[str]:
    return set().union(
        run_git_paths(["diff", "--name-only", "-z"], cwd=memory_dir),
        run_git_paths(["diff", "--cached", "--name-only", "-z"], cwd=memory_dir),
        run_git_paths(
            ["ls-files", "--others", "--exclude-standard", "-z"], cwd=memory_dir
        ),
    )


def validate_memory_binding(repo: Path, *, require_clean: bool = False) -> dict[str, str]:
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
    if require_clean:
        dirty = changed_memory_paths(memory_dir)
        if dirty:
            raise ValidationError(
                "memory git repository must be clean; review or snapshot these paths first: "
                + ", ".join(sorted(dirty))
            )
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


def safe_detail_filename(
    value: Any,
    *,
    memory_dir: Path,
    label: str,
    require_existing: bool = False,
    require_absent: bool = False,
) -> str:
    filename = safe_memory_filename(
        value,
        memory_dir=memory_dir,
        label=label,
        require_existing=require_existing,
        require_absent=require_absent,
    )
    if filename in CONTROL_FILES:
        raise ValidationError(f"{label} must be a detail file, not a memory control file")
    return filename


def safe_relative_change(value: Any, *, memory_dir: Path, label: str) -> str:
    if not isinstance(value, str) or not value or CONTROL.search(value):
        raise ValidationError(f"{label} must be a non-empty path without control characters")
    path = Path(value)
    if (
        path.is_absolute()
        or "\\" in value
        or value != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValidationError(f"{label} must be a canonical relative path")
    candidate = memory_dir / path
    ensure_inside(memory_dir, candidate, label)
    ensure_no_symlink_components(candidate, memory_dir, label)
    return path.as_posix()


def require_allowed_changes(memory_dir: Path, allowed: set[str]) -> set[str]:
    changed = changed_memory_paths(memory_dir)
    unexpected = changed - allowed
    if unexpected:
        raise ValidationError(
            "memory git has changes outside the reviewed allowlist: "
            + ", ".join(sorted(unexpected))
        )
    return changed


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
    if CONTROL.search(proposal["id"]):
        raise ValidationError(f"proposal {index}: id must be a single safe line")
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


def require_single_line_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or CONTROL.search(value):
        raise ValidationError(f"{label} must be a non-empty single-line string")
    return value


def validate_proposal(proposal: Any, index: int, *, memory_dir: Path) -> None:
    if not isinstance(proposal, dict):
        raise ValidationError(f"proposal {index}: must be an object")
    action = validate_common(proposal, index)

    if action in {"modify", "flag"}:
        safe_memory_filename(
            proposal["target"],
            memory_dir=memory_dir,
            label=f"proposal {index} target",
            require_existing=True,
        )
    if action == "archive":
        safe_detail_filename(
            proposal["target"],
            memory_dir=memory_dir,
            label=f"proposal {index} target",
            require_existing=True,
        )
    if action == "split":
        original_target = safe_detail_filename(
            proposal["target"],
            memory_dir=memory_dir,
            label=f"proposal {index} target",
            require_existing=True,
        )
    else:
        original_target = None
    if action == "add":
        safe_detail_filename(
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
                safe_detail_filename(
                    target,
                    memory_dir=memory_dir,
                    label=f"proposal {index} targets[{target_index}]",
                    require_existing=True,
                )
            )
        if len(set(normalized_targets)) != len(normalized_targets):
            raise ValidationError(f"proposal {index}: merge targets must be unique")
        survivor = safe_detail_filename(
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
            or not index_changes["remove"]
            or any(
                not isinstance(item, str) or not item.strip() or CONTROL.search(item)
                for item in index_changes["remove"]
            )
            or not isinstance(index_changes["add"], str)
            or not index_changes["add"].strip()
            or CONTROL.search(index_changes["add"])
        ):
            raise ValidationError(f"proposal {index}: index_changes must contain string remove[] and add")
        if len(set(index_changes["remove"])) != len(index_changes["remove"]):
            raise ValidationError(f"proposal {index}: index_changes.remove must be unique")
        tombstones = proposal.get("archive_tombstones")
        if not isinstance(tombstones, list) or not tombstones:
            raise ValidationError(f"proposal {index}: archive_tombstones must be an array")
        if any(
            not isinstance(item, str) or not item.strip() or CONTROL.search(item)
            for item in tombstones
        ):
            raise ValidationError(f"proposal {index}: archive_tombstones must be non-empty strings")
        expected_tombstones = len(normalized_targets) - int(survivor in normalized_targets)
        if len(tombstones) != expected_tombstones:
            raise ValidationError(
                f"proposal {index}: archive_tombstones must contain one row per absorbed target"
            )
        if type(proposal.get("net_index_lines")) is not int:
            raise ValidationError(f"proposal {index}: net_index_lines must be an integer")
        if proposal["net_index_lines"] != 1 - len(index_changes["remove"]):
            raise ValidationError(
                f"proposal {index}: net_index_lines must match the proposed index changes"
            )
        require_string_fields(proposal, index, {"merged_body"})
    elif action == "split":
        results = proposal["result_files"]
        if not isinstance(results, list) or len(results) < 2:
            raise ValidationError(f"proposal {index}: result_files must contain 2+ files")
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
                safe_detail_filename(
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
            require_single_line_string(
                result["index_line"],
                f"proposal {index} result_files[{result_index}].index_line",
            )
        if len(set(result_names)) != len(result_names):
            raise ValidationError(f"proposal {index}: result file names must be unique")
        require_string_fields(proposal, index, {"original_index_line"})
        require_single_line_string(
            proposal["original_index_line"], f"proposal {index} original_index_line"
        )
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
        if action == "archive":
            require_single_line_string(
                proposal["archive_reason"], f"proposal {index} archive_reason"
            )
        if action == "add":
            require_single_line_string(
                proposal["index_line"], f"proposal {index} index_line"
            )


def proposal_mutation_claims(proposal: dict[str, Any]) -> set[str]:
    action = proposal["action"]
    if action in {"modify", "archive", "add"}:
        return {proposal["target"]}
    if action == "merge":
        return set(proposal["targets"]) | {proposal["survivor"]}
    if action == "split":
        return {proposal["target"]} | {
            result["name"] for result in proposal["result_files"]
        }
    return set()


def validate_proposals(
    path: Path, *, memory_dir: Path, artifact_timestamp: str
) -> int:
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
        ran_at = datetime.strptime(data["ran_at"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValidationError("proposals.json ran_at must match YYYY-MM-DDTHH:MM:SSZ") from exc
    artifact_time = datetime.strptime(artifact_timestamp, "%Y-%m-%dT%H-%M-%SZ")
    if ran_at != artifact_time:
        raise ValidationError("proposals.json ran_at must match its artifact directory timestamp")
    if "inputs_summary" in data and not isinstance(data["inputs_summary"], dict):
        raise ValidationError("proposals.json inputs_summary must be an object")
    if "skipped" in data and not isinstance(data["skipped"], list):
        raise ValidationError("proposals.json skipped must be an array")
    proposals = data.get("proposals")
    if not isinstance(proposals, list):
        raise ValidationError("proposals.json must contain a proposals array")
    ids: set[str] = set()
    mutation_claims: set[str] = set()
    curator = data["curator"]
    for index, proposal in enumerate(proposals):
        validate_proposal(proposal, index, memory_dir=memory_dir)
        if proposal["action"] not in CURATOR_ACTIONS[curator]:
            raise ValidationError(
                f"proposal {index}: action {proposal['action']!r} is not allowed for curator {curator!r}"
            )
        if proposal["id"] in ids:
            raise ValidationError(f"proposal {index}: duplicate proposal id {proposal['id']!r}")
        ids.add(proposal["id"])

        claims = proposal_mutation_claims(proposal)
        overlap = claims & mutation_claims
        mutation_claims |= claims
        if overlap:
            raise ValidationError(
                f"proposal {index}: mutation target collides with another proposal: {sorted(overlap)}"
            )
    return len(proposals)


def cmd_resolve(_: argparse.Namespace) -> dict[str, Any]:
    return validate_memory_binding(Path.cwd(), require_clean=True)


def cmd_artifact(args: argparse.Namespace) -> dict[str, Any]:
    binding = validate_memory_binding(
        Path.cwd(), require_clean=not args.for_commit
    )
    memory_dir = Path(binding["memory_dir"])
    ts, path = resolve_artifact(memory_dir, args.timestamp, for_create=args.for_create)
    result: dict[str, Any] = {**binding, "timestamp": ts, "dream_dir": str(path)}
    if not args.for_create:
        result["proposal_count"] = validate_proposals(
            path / "proposals.json", memory_dir=memory_dir, artifact_timestamp=ts
        )
    if args.for_commit:
        require_regular_file(path / "inputs.json", "inputs.json")
        artifact_paths = {
            f".dreams/{ts}/inputs.json",
            f".dreams/{ts}/proposals.json",
            f".dreams/{ts}/REPORT.md",
        }
        changed = require_allowed_changes(memory_dir, artifact_paths)
        if changed != artifact_paths:
            raise ValidationError(
                "new dream artifact must change exactly inputs.json, proposals.json, and REPORT.md"
            )
        result["changed_paths"] = sorted(changed)
    return result


def cmd_changes(args: argparse.Namespace) -> dict[str, Any]:
    binding = validate_memory_binding(Path.cwd(), require_clean=False)
    memory_dir = Path(binding["memory_dir"])
    allowed = {
        safe_relative_change(
            value, memory_dir=memory_dir, label=f"allow[{index}]"
        )
        for index, value in enumerate(args.allow)
    }
    if not allowed:
        raise ValidationError("changes requires at least one reviewed --allow path")
    changed = require_allowed_changes(memory_dir, allowed)
    if not changed:
        raise ValidationError("memory git has no reviewed changes to commit")
    omitted = allowed - changed
    if omitted:
        raise ValidationError(
            "reviewed allowlist includes paths that did not change: "
            + ", ".join(sorted(omitted))
        )
    return {**binding, "changed_paths": sorted(changed), "allowed_paths": sorted(allowed)}


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
    artifact.add_argument(
        "--for-commit",
        action="store_true",
        help="validate a newly written artifact and reject unrelated memory changes",
    )

    changes = subcommands.add_parser(
        "changes", help="reject memory changes outside an exact reviewed allowlist"
    )
    changes.add_argument(
        "--allow", action="append", default=[], help="reviewed memory-relative path"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "resolve":
            result = cmd_resolve(args)
        elif args.command == "artifact":
            if args.for_create and args.for_commit:
                raise ValidationError("--for-create and --for-commit are mutually exclusive")
            result = cmd_artifact(args)
        elif args.command == "changes":
            result = cmd_changes(args)
        else:  # pragma: no cover - argparse prevents this.
            parser.error("unknown command")
    except ValidationError as exc:
        print(f"validate-memory: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
