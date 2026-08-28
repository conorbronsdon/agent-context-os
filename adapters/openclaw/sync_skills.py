#!/usr/bin/env python3
"""Synchronize Context OS lifecycle skills into an OpenClaw workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / ".agents" / "skills"
SKILLS = (
    "context-end",
    "context-setup",
    "context-start",
    "context-update",
    "end",
    "setup",
    "start",
    "update",
)
MANIFEST_NAME = ".contextos-openclaw-skills.json"
MANIFEST_VERSION = 1


class SyncError(RuntimeError):
    """A synchronization safety or consistency error."""


def _is_reparse(info: os.stat_result) -> bool:
    attribute = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attribute & reparse_flag)


def _assert_plain(path: Path, *, label: str, allow_missing: bool = False) -> None:
    """Reject symlinks and Windows reparse points without following the leaf."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return
        raise SyncError(f"{label} does not exist: {path}")
    if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
        raise SyncError(f"{label} must not be a symlink or reparse point: {path}")


def _assert_existing_chain(path: Path, *, label: str) -> None:
    current = path.absolute()
    existing: list[Path] = []
    while True:
        existing.append(current)
        if current.parent == current:
            break
        current = current.parent
    for candidate in reversed(existing):
        if candidate.exists() or candidate.is_symlink():
            _assert_plain(candidate, label=label)


def _under(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_workspace(workspace: Path) -> tuple[Path, Path]:
    workspace = workspace.expanduser().absolute()
    _assert_existing_chain(workspace, label="workspace path")
    if not workspace.exists():
        raise SyncError(f"workspace does not exist: {workspace}")
    if not workspace.is_dir():
        raise SyncError(f"workspace is not a directory: {workspace}")
    workspace_resolved = workspace.resolve(strict=True)
    target_root = workspace / ".agents" / "skills"
    _assert_existing_chain(target_root, label="target path")
    # Resolve the nearest existing parent before creating anything.
    nearest = target_root
    while not nearest.exists():
        nearest = nearest.parent
    if not _under(nearest.resolve(strict=True), workspace_resolved):
        raise SyncError(f"target path escapes workspace: {target_root}")
    return workspace, target_root


def _iter_files(root: Path, *, label: str) -> Iterator[tuple[str, Path]]:
    _assert_plain(root, label=label)
    if not root.is_dir():
        raise SyncError(f"{label} is not a directory: {root}")
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        _assert_plain(current_path, label=label)
        for name in sorted(directories):
            _assert_plain(current_path / name, label=label)
        directories.sort()
        for name in sorted(files):
            path = current_path / name
            _assert_plain(path, label=label)
            if not stat.S_ISREG(path.lstat().st_mode):
                raise SyncError(f"{label} contains a non-regular file: {path}")
            yield path.relative_to(root).as_posix(), path


def _read_plain(path: Path, *, label: str) -> bytes:
    _assert_plain(path, label=label)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise SyncError(f"{label} is not a regular file: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def _inventory(root: Path, *, label: str) -> dict[str, str]:
    return {
        relative: hashlib.sha256(_read_plain(path, label=label)).hexdigest()
        for relative, path in _iter_files(root, label=label)
    }


def _source_inventory() -> dict[str, dict[str, str]]:
    _assert_existing_chain(SOURCE_ROOT, label="source path")
    result: dict[str, dict[str, str]] = {}
    for skill in SKILLS:
        result[skill] = _inventory(SOURCE_ROOT / skill, label=f"source skill {skill}")
    return result


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT,
        text=True, encoding="utf-8", errors="replace", capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise SyncError(f"could not determine source git SHA: {result.stderr.strip()}")
    return result.stdout.strip()


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists() and not path.is_symlink():
        return None
    data = _read_plain(path, label="provenance manifest")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SyncError(f"invalid provenance manifest: {error}") from error
    if not isinstance(value, dict) or value.get("schema_version") != MANIFEST_VERSION:
        raise SyncError("invalid provenance manifest schema")
    return value


def _manifest(source_sha: str, source: dict[str, dict[str, str]]) -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_VERSION,
        "source_git_sha": source_sha,
        "source_root": ".agents/skills",
        "skills": source,
    }


def check(workspace_path: Path) -> dict[str, Any]:
    workspace, target_root = _validate_workspace(workspace_path)
    source = _source_inventory()
    source_sha = _git_sha()
    manifest_path = workspace / MANIFEST_NAME
    manifest = _load_manifest(manifest_path)
    findings: list[dict[str, str]] = []
    if manifest is None:
        findings.append({"kind": "missing_manifest", "path": MANIFEST_NAME})
        recorded: dict[str, Any] = {}
    else:
        recorded = manifest.get("skills") if isinstance(manifest.get("skills"), dict) else {}
        if manifest.get("source_git_sha") != source_sha:
            findings.append({"kind": "stale_source_sha", "path": MANIFEST_NAME})
        if recorded != source:
            findings.append({"kind": "stale_source_files", "path": ".agents/skills"})

    for skill in SKILLS:
        target = target_root / skill
        if not target.exists() and not target.is_symlink():
            findings.append({"kind": "missing", "path": f".agents/skills/{skill}"})
            continue
        target_files = _inventory(target, label=f"target skill {skill}")
        expected = recorded.get(skill, {}) if isinstance(recorded, dict) else {}
        if not isinstance(expected, dict):
            expected = {}
        for relative in sorted(set(expected) - set(target_files)):
            findings.append({"kind": "missing", "path": f".agents/skills/{skill}/{relative}"})
        for relative in sorted(set(target_files) - set(expected)):
            findings.append({"kind": "extra", "path": f".agents/skills/{skill}/{relative}"})
        for relative in sorted(set(target_files) & set(expected)):
            if target_files[relative] != expected[relative]:
                findings.append({"kind": "changed", "path": f".agents/skills/{skill}/{relative}"})

    return {
        "command": "check",
        "current": not findings,
        "workspace": str(workspace),
        "source_git_sha": source_sha,
        "findings": findings,
    }


def _copy_tree(source: Path, destination: Path) -> None:
    destination.mkdir()
    for relative, source_file in _iter_files(source, label="source skill"):
        target = destination / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = _read_plain(source_file, label="source file")
        with target.open("xb") as stream:
            stream.write(data)


def _remove_created_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def sync(workspace_path: Path) -> dict[str, Any]:
    workspace, target_root = _validate_workspace(workspace_path)
    source = _source_inventory()
    source_sha = _git_sha()
    target_root.mkdir(parents=True, exist_ok=True)
    _assert_existing_chain(target_root, label="target path")
    manifest_path = workspace / MANIFEST_NAME
    _assert_plain(manifest_path, label="provenance manifest", allow_missing=True)
    old_manifest = (
        _read_plain(manifest_path, label="provenance manifest")
        if manifest_path.exists()
        else None
    )
    for skill in SKILLS:
        existing = target_root / skill
        _assert_plain(existing, label=f"target skill {skill}", allow_missing=True)
        if existing.exists():
            _inventory(existing, label=f"target skill {skill}")

    transaction = Path(tempfile.mkdtemp(prefix=".contextos-openclaw-sync-", dir=target_root))
    stage = transaction / "stage"
    backup = transaction / "backup"
    stage.mkdir()
    backup.mkdir()
    installed: list[str] = []
    backed_up: list[str] = []
    manifest_temp = workspace / f".{MANIFEST_NAME}.tmp-{os.getpid()}"
    preserve_transaction = False
    try:
        for skill in SKILLS:
            _copy_tree(SOURCE_ROOT / skill, stage / skill)
        for skill in SKILLS:
            target = target_root / skill
            _assert_plain(target, label=f"target skill {skill}", allow_missing=True)
            if target.exists():
                os.replace(target, backup / skill)
                backed_up.append(skill)
            os.replace(stage / skill, target)
            installed.append(skill)
        payload = (json.dumps(_manifest(source_sha, source), indent=2, sort_keys=True) + "\n").encode("utf-8")
        with manifest_temp.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(manifest_temp, manifest_path)
    except Exception as error:
        rollback_errors: list[str] = []
        for skill in reversed(installed):
            try:
                _remove_created_tree(target_root / skill)
            except Exception as rollback_error:  # pragma: no cover - catastrophic filesystem failure
                rollback_errors.append(str(rollback_error))
        for skill in reversed(backed_up):
            try:
                os.replace(backup / skill, target_root / skill)
            except Exception as rollback_error:  # pragma: no cover - catastrophic filesystem failure
                rollback_errors.append(str(rollback_error))
        try:
            if manifest_temp.exists():
                manifest_temp.unlink()
            if old_manifest is None:
                if manifest_path.exists():
                    manifest_path.unlink()
            else:
                restore = workspace / f".{MANIFEST_NAME}.restore-{os.getpid()}"
                restore.write_bytes(old_manifest)
                os.replace(restore, manifest_path)
        except Exception as rollback_error:  # pragma: no cover - catastrophic filesystem failure
            rollback_errors.append(str(rollback_error))
        detail = f"synchronization failed and was rolled back: {error}"
        if rollback_errors:
            detail += f"; rollback errors: {'; '.join(rollback_errors)}"
            preserve_transaction = True
            detail += f"; recovery data retained at {transaction}"
        raise SyncError(detail) from error
    finally:
        if transaction.exists() and not preserve_transaction:
            shutil.rmtree(transaction)

    return {
        "command": "sync",
        "current": True,
        "workspace": str(workspace),
        "source_git_sha": source_sha,
        "skills": list(SKILLS),
        "manifest": MANIFEST_NAME,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("sync", "check"):
        command = subparsers.add_parser(name)
        command.add_argument("--workspace", required=True, type=Path)
    return parser


def main(arguments: list[str] | None = None) -> int:
    parsed = _parser().parse_args(arguments)
    try:
        report = sync(parsed.workspace) if parsed.command == "sync" else check(parsed.workspace)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["current"] else 1
    except (OSError, SyncError) as error:
        print(json.dumps({"command": parsed.command, "current": False, "error": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
