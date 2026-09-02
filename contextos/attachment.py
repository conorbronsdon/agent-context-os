"""External-project attachment contracts without lifecycle integration.

This module deliberately owns no CLI or filesystem writes.  It supplies the
closed, serializable records and read-only validation needed by a later
proposal/apply integration.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .primitives import SnapshotError, git_command, git_environment, is_link_like


ATTACHMENT_SCHEMA_VERSION = 1
PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
OBJECT_FORMATS = {"sha1": 40, "sha256": 64}


class AttachmentError(ValueError):
    """Raised when attachment identity, roots, or local binding are unsafe."""


@dataclass(frozen=True)
class RootRoles:
    kernel_root: Path
    context_root: Path
    working_root: Path
    colocated: bool


def _canonical_directory(value: Path | str, field: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise AttachmentError(f"{field} must be an exact absolute path")
    absolute = Path(os.path.abspath(path))
    try:
        if is_link_like(absolute):
            raise AttachmentError(f"{field} must not be a symlink or reparse point")
        resolved = absolute.resolve(strict=True)
    except (OSError, SnapshotError) as exc:
        raise AttachmentError(f"cannot resolve {field}: {exc}") from exc
    if not resolved.is_dir():
        raise AttachmentError(f"{field} must be an existing directory")
    if absolute != resolved:
        raise AttachmentError(
            f"{field} must use its canonical path without link traversal"
        )
    return resolved


def _contains(parent: Path, child: Path) -> bool:
    for candidate in (child, *child.parents):
        try:
            if os.path.samefile(parent, candidate):
                return True
        except OSError as exc:
            raise AttachmentError(
                f"cannot compare root ancestor identity: {exc}"
            ) from exc
    return False


def resolve_root_roles(
    *,
    kernel_root: Path | str,
    legacy_root: Path | str | None = None,
    context_root: Path | str | None = None,
    working_root: Path | str | None = None,
) -> RootRoles:
    """Resolve exact role roots or the explicitly colocated compatibility form.

    Split roots are exact: this function never searches upward, consults cwd,
    or infers a missing role.  The three split roles must be physically distinct
    and non-overlapping.  ``legacy_root`` intentionally preserves colocation.
    """

    kernel = _canonical_directory(kernel_root, "kernel_root")
    if legacy_root is not None:
        if context_root is not None or working_root is not None:
            raise AttachmentError(
                "legacy_root cannot be combined with context_root or working_root"
            )
        legacy = _canonical_directory(legacy_root, "legacy_root")
        return RootRoles(
            kernel_root=kernel,
            context_root=legacy,
            working_root=legacy,
            colocated=os.path.samefile(kernel, legacy),
        )
    if context_root is None or working_root is None:
        raise AttachmentError(
            "split attachment requires both context_root and working_root"
        )
    context = _canonical_directory(context_root, "context_root")
    working = _canonical_directory(working_root, "working_root")
    roles = {
        "kernel_root": kernel,
        "context_root": context,
        "working_root": working,
    }
    items = list(roles.items())
    for index, (left_name, left) in enumerate(items):
        for right_name, right in items[index + 1 :]:
            if os.path.samefile(left, right):
                raise AttachmentError(
                    f"split roles must be distinct: {left_name} and {right_name}"
                )
            if _contains(left, right) or _contains(right, left):
                raise AttachmentError(
                    f"split roles must not overlap: {left_name} and {right_name}"
                )
    return RootRoles(kernel, context, working, False)


def _git(root: Path, *arguments: str, text: bool = True) -> str | bytes:
    try:
        completed = subprocess.run(
            [*git_command(root, safe_root=root), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=git_environment(),
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = (
            exc.stderr.decode("utf-8", errors="replace").strip()
            if isinstance(exc, subprocess.CalledProcessError)
            else str(exc)
        )
        raise AttachmentError(f"cannot inspect Git repository at {root}: {detail}") from exc
    if not text:
        return completed.stdout
    try:
        return completed.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise AttachmentError(f"Git returned invalid UTF-8 for {root}") from exc


def _exact_git_root(root: Path) -> None:
    top = Path(str(_git(root, "rev-parse", "--show-toplevel")))
    try:
        exact = os.path.samefile(root, top)
    except OSError as exc:
        raise AttachmentError(f"cannot compare Git root identity: {exc}") from exc
    if not exact:
        raise AttachmentError("working_root must be the exact Git top-level directory")


def _validate_identity(value: Any, field: str = "repository_identity") -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"object_format", "anchor_commit"}:
        raise AttachmentError(
            f"{field} must contain exactly object_format and anchor_commit"
        )
    object_format = value.get("object_format")
    anchor = value.get("anchor_commit")
    if object_format not in OBJECT_FORMATS:
        raise AttachmentError(f"{field}.object_format must be sha1 or sha256")
    length = OBJECT_FORMATS[object_format]
    if (
        not isinstance(anchor, str)
        or len(anchor) != length
        or any(character not in "0123456789abcdef" for character in anchor)
    ):
        raise AttachmentError(
            f"{field}.anchor_commit must be a canonical {object_format} commit id"
        )
    return {"object_format": object_format, "anchor_commit": anchor}


def observe_git_identity(working_root: Path | str) -> dict[str, str]:
    """Create a move-stable repository identity anchored to the current commit."""

    root = _canonical_directory(working_root, "working_root")
    _exact_git_root(root)
    object_format = str(_git(root, "rev-parse", "--show-object-format"))
    head = str(_git(root, "rev-parse", "--verify", "HEAD^{commit}"))
    return _validate_identity(
        {"object_format": object_format, "anchor_commit": head}
    )


def validate_git_identity(
    working_root: Path | str, identity: Mapping[str, Any]
) -> Path:
    """Require an exact Git root whose object database contains the anchor."""

    root = _canonical_directory(working_root, "working_root")
    _exact_git_root(root)
    expected = _validate_identity(dict(identity))
    observed_format = str(_git(root, "rev-parse", "--show-object-format"))
    if observed_format != expected["object_format"]:
        raise AttachmentError("working repository object format does not match binding")
    try:
        observed = str(
            _git(root, "rev-parse", "--verify", f"{expected['anchor_commit']}^{{commit}}")
        )
    except AttachmentError as exc:
        raise AttachmentError(
            "working repository does not contain the tracked anchor commit"
        ) from exc
    if observed != expected["anchor_commit"]:
        raise AttachmentError("working repository anchor commit is not canonical")
    return root


def git_evidence(
    working_root: Path | str,
    *,
    identity: Mapping[str, Any] | None = None,
    max_commits: int = 20,
) -> dict[str, Any]:
    """Return bounded, read-only identity, status, branch, and history evidence."""

    if type(max_commits) is not int or not 0 <= max_commits <= 100:
        raise AttachmentError("max_commits must be an integer from 0 through 100")
    root = (
        validate_git_identity(working_root, identity)
        if identity is not None
        else _canonical_directory(working_root, "working_root")
    )
    _exact_git_root(root)
    repository_identity = (
        _validate_identity(dict(identity))
        if identity is not None
        else observe_git_identity(root)
    )
    head = str(_git(root, "rev-parse", "--verify", "HEAD^{commit}"))
    try:
        branch = str(_git(root, "symbolic-ref", "--quiet", "--short", "HEAD"))
    except AttachmentError:
        branch = None
    raw_status = bytes(
        _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=normal", text=False)
    )
    status_entries = []
    records = raw_status.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        # JSON/report output must remain encodable even when a POSIX repository
        # contains arbitrary path bytes. Preserve them as visible escapes.
        decoded = record.decode("utf-8", errors="backslashreplace")
        if len(decoded) < 4 or decoded[2] != " ":
            raise AttachmentError("Git returned malformed porcelain status")
        code, path = decoded[:2], decoded[3:]
        entry: dict[str, str] = {"code": code, "path": path}
        if code[0] in {"R", "C"}:
            if index >= len(records) or not records[index]:
                raise AttachmentError("Git returned truncated rename/copy status")
            entry["source_path"] = records[index].decode(
                "utf-8", errors="backslashreplace"
            )
            index += 1
        status_entries.append(entry)
    history: list[dict[str, Any]] = []
    if max_commits:
        raw_log = bytes(
            _git(
                root,
                "log",
                "-z",
                f"--max-count={max_commits}",
                "--format=%H%x00%ct%x00%s",
                text=False,
            )
        )
        fields = raw_log.split(b"\0")
        if fields and fields[-1] == b"":
            fields.pop()
        if len(fields) % 3:
            raise AttachmentError("Git returned a malformed NUL-delimited log")
        for index in range(0, len(fields), 3):
            commit_bytes, timestamp_bytes, subject_bytes = fields[index : index + 3]
            try:
                commit = commit_bytes.decode("ascii")
                timestamp = int(timestamp_bytes.decode("ascii"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise AttachmentError("Git returned malformed commit metadata") from exc
            expected_length = OBJECT_FORMATS[repository_identity["object_format"]]
            if (
                len(commit) != expected_length
                or any(character not in "0123456789abcdef" for character in commit)
            ):
                raise AttachmentError("Git returned a non-canonical history commit id")
            subject = subject_bytes.decode("utf-8", errors="replace")
            history.append(
                {"commit": commit, "committed_at_unix": timestamp, "subject": subject}
            )
    return {
        "repository_identity": repository_identity,
        "head": head,
        "branch": branch,
        "status": {"clean": not status_entries, "entries": status_entries},
        "history": history,
    }


def validate_project_id(value: Any) -> str:
    if not isinstance(value, str) or PROJECT_ID_RE.fullmatch(value) is None:
        raise AttachmentError(
            "project_id must be 1-64 lowercase letters, digits, or hyphens and start with a letter"
        )
    return value


def tracked_manifest_relative_path(project_id: str) -> str:
    project = validate_project_id(project_id)
    return f"projects/{project}/contextos.project.json"


def create_tracked_manifest(project_id: str, working_root: Path | str) -> dict[str, Any]:
    return {
        "schema_version": ATTACHMENT_SCHEMA_VERSION,
        "project_id": validate_project_id(project_id),
        "repository_identity": observe_git_identity(working_root),
    }


def validate_tracked_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "project_id",
        "repository_identity",
    }:
        raise AttachmentError(
            "tracked project manifest must contain exactly schema_version, project_id, and repository_identity"
        )
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != ATTACHMENT_SCHEMA_VERSION
    ):
        raise AttachmentError(
            f"tracked project manifest schema_version must equal {ATTACHMENT_SCHEMA_VERSION}"
        )
    return {
        "schema_version": ATTACHMENT_SCHEMA_VERSION,
        "project_id": validate_project_id(value.get("project_id")),
        "repository_identity": _validate_identity(value.get("repository_identity")),
    }


def create_local_binding(
    roles: RootRoles, manifest: Mapping[str, Any], *, bound_at: str
) -> dict[str, Any]:
    tracked = validate_tracked_manifest(dict(manifest))
    if roles.colocated:
        raise AttachmentError("external project binding requires split root roles")
    if not isinstance(bound_at, str) or not bound_at.strip() or bound_at != bound_at.strip():
        raise AttachmentError("bound_at must be a non-empty string without surrounding whitespace")
    validate_git_identity(roles.working_root, tracked["repository_identity"])
    return {
        "schema_version": ATTACHMENT_SCHEMA_VERSION,
        "bindings": {
            tracked["project_id"]: {
                "bound_at": bound_at,
                "context_root": str(roles.context_root),
                "kernel_root": str(roles.kernel_root),
                "working_root": str(roles.working_root),
                "repository_identity": tracked["repository_identity"],
            }
        },
    }


def validate_local_binding(
    value: Any, manifest: Mapping[str, Any]
) -> RootRoles:
    """Validate one project binding and return its exact live roots.

    Registries are ContextRoot-local and intentionally make no global ownership
    claim.  Two ContextRoots may bind the same logical WorkingRoot; callers must
    select one exact ContextRoot for each lifecycle invocation and receipt.
    """

    tracked = validate_tracked_manifest(dict(manifest))
    if not isinstance(value, dict) or set(value) != {"schema_version", "bindings"}:
        raise AttachmentError(
            "local binding registry must contain exactly schema_version and bindings"
        )
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != ATTACHMENT_SCHEMA_VERSION
    ):
        raise AttachmentError(
            f"local binding registry schema_version must equal {ATTACHMENT_SCHEMA_VERSION}"
        )
    bindings = value.get("bindings")
    if not isinstance(bindings, dict):
        raise AttachmentError("local binding registry bindings must be an object")
    project_id = tracked["project_id"]
    if set(bindings) != {project_id}:
        raise AttachmentError(
            "local binding registry must contain exactly the tracked project id"
        )
    entry = bindings[project_id]
    required = {
        "bound_at",
        "context_root",
        "kernel_root",
        "working_root",
        "repository_identity",
    }
    if not isinstance(entry, dict) or set(entry) != required:
        raise AttachmentError(
            "local binding entry has unsupported or missing fields"
        )
    bound_at = entry.get("bound_at")
    if not isinstance(bound_at, str) or not bound_at.strip() or bound_at != bound_at.strip():
        raise AttachmentError("local binding bound_at is invalid")
    observed_identity = _validate_identity(
        entry.get("repository_identity"), "binding.repository_identity"
    )
    if observed_identity != tracked["repository_identity"]:
        raise AttachmentError("local binding repository identity differs from tracked identity")
    roles = resolve_root_roles(
        kernel_root=entry.get("kernel_root"),
        context_root=entry.get("context_root"),
        working_root=entry.get("working_root"),
    )
    validate_git_identity(roles.working_root, tracked["repository_identity"])
    return roles
