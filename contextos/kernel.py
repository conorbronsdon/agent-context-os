from __future__ import annotations

import difflib
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Sequence

from .component_schema import (
    ComponentManifestError,
    component_closure,
    component_owners,
    load_component_manifest,
    portable_path_identity,
    resolved_component_paths,
    workspace_path_owner,
    write_generated_file,
)
from .runtime_schema import (
    RUNTIME_ID_RE,
    RuntimeManifestError,
    validate_runtime_manifest,
)
from .workspace_schema import (
    DEFAULT_PATHS,
    DEFAULT_TEMPLATE_SOURCE,
    DEFAULT_TEMPLATE_VERSION,
    WORKSPACE_MODE,
    WORKSPACE_SCHEMA_VERSION,
    WorkspaceConfigError,
    analyze_legacy_workspace,
    legacy_workspace_values,
    load_workspace_config,
    normalize_legacy_workspace_path,
    portable_identity as workspace_portable_identity,
    render_workspace_config,
    strict_json_loads,
    validate_workspace_config,
    validate_workspace_path,
)


SCHEMA_VERSION = 1
TRANSACTION_JOURNAL_VERSION = 2
HOST_STATE_SCHEMA_VERSION = 1
EVIDENCE_STALE_AFTER_DAYS = 90
AGENT_LIFECYCLE_WORKFLOW = "agent-config"
WORKSPACE_MIGRATION_OPERATION = "workspace-migrate"
LOCAL_ARTIFACT_MODE = 0o600
NEW_CONTENT_MODE = 0o666 if os.name == "nt" else 0o644
PROPOSAL_ID_RE = re.compile(
    r"^\d{8}T\d{6}-(?:setup|update|end|agent-config)-[0-9a-f]{10}$"
)
AGENT_MIGRATION_INVARIANTS = [
    "agent-workflow-path-policy",
    "component-ownership-closed",
    "portable-path-collisions",
    "exact-raw-file-hashes",
    "source-hash-revalidation",
    "exact-proposal-integrity",
    "atomic-replacement-and-rollback",
]
CONTENT_BASE_INVARIANTS = [
    "workflow-path-policy",
    "optimistic-file-hashes",
    "exact-proposal-integrity",
]
CONTENT_FRESHNESS_INVARIANTS = ["single-last-updated", "same-day-history"]
PLACEHOLDER_DATE = "[DATE]"
LAST_UPDATED_RE = re.compile(r"^\*\*Last Updated:\*\*\s*(.+?)\s*$", re.MULTILINE)
REAL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SETUP_ROOTS = {"identity", "projects", "state"}
SETUP_FILES = {"ROUTING.md", "TODO.md", "CLAUDE.md", "AGENTS.md"}
STATE_THRESHOLDS = {"current.md": 3, "weekly-priorities.md": 5, "blockers.md": 7}
INITIALIZATION_FILE = "current.md"
SETUP_NEXT_ACTION = (
    "Run the explicit setup workflow (bash scripts/setup.sh, then the $context-setup "
    "skill) before starting a session."
)
class ContextOSError(RuntimeError):
    pass


@dataclass(frozen=True)
class Workspace:
    root: Path
    state_dir: Path
    sessions_dir: Path
    task_file: Path


@dataclass(frozen=True)
class WorkspaceResolution:
    workspace: Workspace
    config: dict[str, Any] | None
    source: str
    agents: tuple[str, ...] | None
    notices: tuple[dict[str, str], ...]
    canonical: bool | None


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def file_digest(path: Path) -> str | None:
    if not path.exists():
        return None
    # Repository lifecycle files are text. Normalize checkout line endings so
    # proposal digests are stable across Windows, macOS, and Linux.
    return sha256_text(path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n"))


def raw_file_digest(path: Path) -> str | None:
    if _is_link_like(path):
        raise ContextOSError(f"transaction target must not be link-like: {path}")
    if not path.exists():
        return None
    return sha256_bytes(_read_regular_file_snapshot(path))


def _read_regular_file_snapshot(path: Path) -> bytes:
    """Read one no-follow snapshot and verify the pathname still names it."""
    if _is_link_like(path):
        raise ContextOSError(f"transaction target must not be link-like: {path}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ContextOSError(f"cannot open transaction target snapshot {path}: {exc}") from exc
    try:
        metadata_before = os.fstat(descriptor)
        if not stat.S_ISREG(metadata_before.st_mode):
            raise ContextOSError(f"transaction target must be a regular file: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        current = os.stat(path, follow_symlinks=False)
        metadata_after = os.fstat(descriptor)
        fingerprint_before = (
            metadata_before.st_mode,
            metadata_before.st_size,
            metadata_before.st_mtime_ns,
            metadata_before.st_ctime_ns,
        )
        fingerprint_after = (
            metadata_after.st_mode,
            metadata_after.st_size,
            metadata_after.st_mtime_ns,
            metadata_after.st_ctime_ns,
        )
        if (
            not stat.S_ISREG(current.st_mode)
            or not os.path.samestat(metadata_before, current)
            or not os.path.samestat(metadata_before, metadata_after)
            or fingerprint_before != fingerprint_after
        ):
            raise ContextOSError(f"transaction target changed during snapshot: {path}")
        return b"".join(chunks)
    except OSError as exc:
        raise ContextOSError(f"transaction target changed during snapshot: {path}") from exc
    finally:
        os.close(descriptor)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def parse_now(raw: str | None) -> datetime:
    if not raw:
        return utc_now()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContextOSError(f"invalid --now timestamp: {raw}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def _is_link_like(path: Path) -> bool:
    """Recognize symlinks and Windows reparse points without following them."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ContextOSError(f"cannot inspect path without following links {path}: {exc}") from exc
    reparse_tag = getattr(metadata, "st_reparse_tag", 0)
    link_tags = {
        getattr(stat, "IO_REPARSE_TAG_SYMLINK", -1),
        getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -2),
    }
    return stat.S_ISLNK(metadata.st_mode) or reparse_tag in link_tags


def _same_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError as exc:
        raise ContextOSError(
            f"cannot compare transaction path identity for {left} and {right}: {exc}"
        ) from exc


def _config_filename_identity(value: str) -> str:
    # Windows aliases trailing spaces and periods even when a POSIX checkout can
    # contain them, so discovery must reject those names portably.
    return workspace_portable_identity(value).rstrip(" .")


def discover_root(start: Path | None = None) -> Path:
    raw_start = (start or Path.cwd()).absolute()
    if _config_filename_identity(raw_start.name) == _config_filename_identity(
        "contextos.workspace.json"
    ):
        # Treat a marker passed directly as a marker in its lexical parent. Do
        # not resolve it first: it may be a dangling link or Windows junction.
        if not raw_start.exists() and not _is_link_like(raw_start):
            raise ContextOSError(f"root discovery start path does not exist: {raw_start}")
        candidate = raw_start.parent
    else:
        if not raw_start.exists():
            raise ContextOSError(f"root discovery start path does not exist: {raw_start}")
        if raw_start.is_file():
            candidate = raw_start.parent
        elif raw_start.is_dir():
            candidate = raw_start
        else:
            raise ContextOSError(
                f"root discovery start path is not a directory or file: {raw_start}"
            )

    # A link may be an ordinary internal repository path. Reject it only when
    # resolving the start would escape the nearest lexical repository boundary.
    # Do not treat `.git` reached through the link itself as lexical ownership;
    # that preserves common `~/current -> repo` entrypoints.
    lexical_boundary: Path | None = None
    for lexical in (candidate, *candidate.parents):
        if _is_link_like(lexical):
            continue
        git_marker = lexical / ".git"
        if git_marker.exists() or _is_link_like(git_marker):
            lexical_boundary = lexical
            break
    resolved_candidate = candidate.resolve()
    if lexical_boundary is not None:
        try:
            resolved_candidate.relative_to(lexical_boundary.resolve())
        except ValueError as exc:
            raise ContextOSError(
                "root discovery start path must not escape repository boundary "
                f"{lexical_boundary}: {candidate}"
            ) from exc
    candidate = resolved_candidate

    for index, path in enumerate((candidate, *candidate.parents)):
        # The tracked JSON marker is authoritative at the nearest candidate.
        marker = path / "contextos.workspace.json"
        marker_present = marker.exists() or _is_link_like(marker)
        legacy_present = (path / "AGENTS.md").is_file() and (
            (path / "state").is_dir() or (path / "workspace.yaml").is_file()
        )
        git_marker = path / ".git"
        boundary_present = git_marker.exists() or _is_link_like(git_marker)

        # Directory enumeration is needed only where a marker/root is actually
        # plausible, plus the explicit start directory for alias-only controls.
        # Intermediate traverse-only directories and unrelated outer ancestors
        # remain compatible with legacy discovery.
        if index == 0 or marker_present or legacy_present or boundary_present:
            _reject_config_aliases(path, "contextos.workspace.json")

        if marker_present:
            if _is_link_like(marker):
                raise ContextOSError(
                    "invalid tracked workspace configuration: "
                    "contextos.workspace.json must not be a symlink or reparse point"
                )
            if not marker.is_file():
                raise ContextOSError(
                    "invalid tracked workspace configuration: "
                    "contextos.workspace.json must be a regular file"
                )
            try:
                load_workspace_config(
                    marker,
                    root=path,
                    known_runtime_ids=runtime_ids(path),
                )
            except WorkspaceConfigError as exc:
                raise ContextOSError(
                    f"invalid tracked workspace configuration: {exc}"
                ) from exc
            return path

        # Preserve the original legacy compound marker for existing clones.
        if legacy_present:
            return path

        # A nested repository without its own Context OS marker must not be
        # captured by an outer repository. Check the candidate before stopping
        # so a marker at a worktree or submodule root still wins.
        if boundary_present:
            raise ContextOSError(
                "could not find a Context OS root before repository boundary: "
                f"{path}"
            )

    raise ContextOSError(
        "could not find a Context OS root "
        "(contextos.workspace.json, or legacy AGENTS.md plus state/ or workspace.yaml)"
    )


def _reject_config_aliases(root: Path, canonical_name: str) -> None:
    identity = _config_filename_identity(canonical_name)
    try:
        matches = [
            path.name
            for path in root.iterdir()
            if _config_filename_identity(path.name) == identity
        ]
    except OSError as exc:
        raise ContextOSError(f"cannot inspect workspace root {root}: {exc}") from exc
    if matches and matches != [canonical_name]:
        raise ContextOSError(
            f"portable configuration filename collision for {canonical_name!r}: "
            + ", ".join(sorted(matches))
        )


def _legacy_repo_path(root: Path, raw: str, field: str) -> Path:
    relative = Path(raw)
    if relative.is_absolute():
        raise ContextOSError(f"legacy workspace.yaml {field} must be repository-relative")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ContextOSError(
            f"legacy workspace.yaml {field} escapes the repository root: {raw!r}"
        ) from exc
    return resolved


def _workspace_from_paths(
    root: Path, paths: dict[str, str], *, legacy: bool = False
) -> Workspace:
    def resolve(key: str) -> Path:
        if legacy:
            return _legacy_repo_path(root, paths[key], key)
        return safe_repo_path(root, paths[key])

    return Workspace(
        root=root,
        state_dir=resolve("state_dir"),
        sessions_dir=resolve("sessions_dir"),
        task_file=resolve("task_file"),
    )


def resolve_workspace(root: Path) -> WorkspaceResolution:
    _reject_config_aliases(root, "contextos.workspace.json")
    _reject_config_aliases(root, "workspace.yaml")
    json_path = root / "contextos.workspace.json"
    legacy_path = root / "workspace.yaml"
    notices: list[dict[str, str]] = []
    if json_path.exists() or json_path.is_symlink():
        try:
            config, canonical = load_workspace_config(
                json_path,
                root=root,
                known_runtime_ids=runtime_ids(root),
            )
        except WorkspaceConfigError as exc:
            raise ContextOSError(f"invalid tracked workspace configuration: {exc}") from exc
        if not canonical:
            notices.append({
                "code": "workspace-json-noncanonical",
                "message": (
                    "contextos.workspace.json is valid but not canonically rendered; "
                    "preview the same-agent repair with bash scripts/contextos.sh "
                    f"workspace migrate --agents {','.join(config['agents']) or 'none'}, "
                    "then create its reviewed proposal with bash scripts/contextos.sh "
                    f"workspace propose-migration --agents "
                    f"{','.join(config['agents']) or 'none'}"
                ),
            })
        if legacy_path.exists() or legacy_path.is_symlink():
            conflicts: list[str] = []
            legacy_detail = (
                "legacy workspace.yaml is shadowed by contextos.workspace.json; "
                "retire it through bash scripts/contextos.sh workspace "
                f"propose-migration --agents {','.join(config['agents']) or 'none'}"
            )
            if legacy_path.is_symlink():
                legacy_detail += "; legacy file must not be a symlink"
            else:
                try:
                    legacy_text = legacy_path.read_text(encoding="utf-8-sig")
                    legacy = analyze_legacy_workspace(legacy_text)
                    for key, value in legacy.values.items():
                        if config["paths"][key] != value:
                            conflicts.append(
                                f"{key}: JSON={config['paths'][key]!r}, YAML={value!r}"
                            )
                    if legacy.issues:
                        legacy_detail += "; legacy issues: " + "; ".join(legacy.issues)
                    if conflicts:
                        legacy_detail += "; conflicts: " + "; ".join(conflicts)
                except (OSError, UnicodeError) as exc:
                    legacy_detail += f"; legacy file cannot be read: {exc}"
            notices.append({"code": "legacy-workspace-shadowed", "message": legacy_detail})
        return WorkspaceResolution(
            workspace=_workspace_from_paths(root, config["paths"]),
            config=config,
            source="json",
            agents=tuple(config["agents"]),
            notices=tuple(notices),
            canonical=canonical,
        )

    values = dict(DEFAULT_PATHS)
    source = "defaults"
    if legacy_path.exists() or legacy_path.is_symlink():
        if legacy_path.is_symlink():
            raise ContextOSError("legacy workspace.yaml must not be a symlink")
        try:
            legacy_text = legacy_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise ContextOSError(f"cannot read legacy workspace.yaml: {exc}") from exc
        values.update(legacy_workspace_values(legacy_text))
        source = "legacy-yaml"
        notices.append({
            "code": "legacy-workspace",
            "message": (
                "workspace.yaml remains readable but is deprecated; choose the intended "
                "agent set and preview migration with bash scripts/contextos.sh workspace "
                "migrate --agents <comma-separated-runtime-ids|none>, then create its "
                "reviewed proposal with bash scripts/contextos.sh workspace "
                "propose-migration --agents <the-same-selection>"
            ),
        })
    else:
        notices.append({
            "code": "workspace-defaults",
            "message": (
                "no tracked workspace configuration; legacy default paths are active "
                "and agent intent is unknown"
            ),
        })
    return WorkspaceResolution(
        # Repositories without tracked configuration use the same historical
        # path semantics as workspace.yaml. Tight path rules begin only after
        # a canonical JSON configuration is explicitly adopted.
        workspace=_workspace_from_paths(root, values, legacy=True),
        config=None,
        source=source,
        agents=None,
        notices=tuple(notices),
        canonical=None,
    )


def load_workspace(root: Path) -> Workspace:
    return resolve_workspace(root).workspace


def safe_repo_path(root: Path, raw: str) -> Path:
    try:
        relative = validate_workspace_path(raw, "workspace path")
    except WorkspaceConfigError as exc:
        raise ContextOSError(str(exc)) from exc
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    current = root
    for part in PurePosixPath(relative).parts:
        current /= part
        if _is_link_like(current):
            raise ContextOSError(
                f"workspace path must not traverse a symlink or reparse point: {raw}"
            )
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ContextOSError(f"path escapes repository root: {raw}") from exc
    return resolved


def workspace_resolution_report(root: Path) -> dict[str, Any]:
    resolution = resolve_workspace(root)
    workspace = resolution.workspace
    return {
        "schema_version": SCHEMA_VERSION,
        "source": resolution.source,
        "agents": list(resolution.agents) if resolution.agents is not None else None,
        "mode": resolution.config["mode"] if resolution.config else None,
        "paths": {
            "state_dir": relative_path(root, workspace.state_dir),
            "sessions_dir": relative_path(root, workspace.sessions_dir),
            "task_file": relative_path(root, workspace.task_file),
        },
        "template": resolution.config["template"] if resolution.config else None,
        "canonical": resolution.canonical,
        "notices": list(resolution.notices),
    }


def plan_workspace_migration(
    root: Path,
    agents: Sequence[str],
    *,
    template_version: str | None = None,
    template_source: str | None = None,
) -> dict[str, Any]:
    _reject_config_aliases(root, "contextos.workspace.json")
    _reject_config_aliases(root, "workspace.yaml")
    known = runtime_ids(root)
    json_path = root / "contextos.workspace.json"
    legacy_path = root / "workspace.yaml"
    current_text = ""
    source = "defaults"
    paths = dict(DEFAULT_PATHS)
    existing: dict[str, Any] | None = None

    if json_path.exists() or json_path.is_symlink():
        resolution = resolve_workspace(root)
        if resolution.config is None:
            raise ContextOSError("tracked JSON resolution did not return configuration")
        existing = resolution.config
        current_text = json_path.read_text(encoding="utf-8")
        source = "json"
        paths = dict(existing["paths"])
        requested = set(agents)
        configured = set(existing["agents"])
        if requested != configured and not configured.issubset(requested):
            raise ContextOSError(
                "workspace migration will not shrink or replace configured agents; "
                "use the future explicit disable lifecycle"
            )
    elif legacy_path.exists() or legacy_path.is_symlink():
        if legacy_path.is_symlink():
            raise ContextOSError("legacy workspace.yaml must not be a symlink")
        try:
            legacy_text = legacy_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise ContextOSError(f"cannot read legacy workspace.yaml: {exc}") from exc
        analysis = analyze_legacy_workspace(legacy_text)
        effective = legacy_workspace_values(legacy_text)
        if analysis.issues:
            raise ContextOSError(
                "legacy workspace.yaml cannot be migrated losslessly: "
                + "; ".join(analysis.issues)
            )
        try:
            normalized_effective = {
                key: normalize_legacy_workspace_path(
                    value, f"workspace.yaml {key}"
                )
                for key, value in effective.items()
            }
        except WorkspaceConfigError as exc:
            raise ContextOSError(
                "legacy workspace.yaml cannot be migrated losslessly: " + str(exc)
            ) from exc
        if analysis.values != normalized_effective:
            raise ContextOSError(
                "legacy workspace.yaml cannot be migrated losslessly: strict migration "
                "interpretation differs from the historical reader"
            )
        paths.update(analysis.values)
        source = "legacy-yaml"

    candidate = {
        "schema_version": WORKSPACE_SCHEMA_VERSION,
        "mode": WORKSPACE_MODE,
        "agents": list(agents),
        "paths": paths,
        "template": {
            "version": (
                template_version
                if template_version is not None
                else existing["template"]["version"]
                if existing is not None
                else DEFAULT_TEMPLATE_VERSION
            ),
            "source": (
                template_source
                if template_source is not None
                else existing["template"]["source"]
                if existing is not None
                else DEFAULT_TEMPLATE_SOURCE
            ),
        },
    }
    try:
        config = validate_workspace_config(candidate, known_runtime_ids=known)
    except WorkspaceConfigError as exc:
        raise ContextOSError(f"invalid workspace migration target: {exc}") from exc
    try:
        _workspace_from_paths(root, config["paths"])
    except ContextOSError as exc:
        raise ContextOSError(
            f"workspace migration target cannot be activated safely: {exc}"
        ) from exc
    target_text = render_workspace_config(config)
    action = "noop" if current_text == target_text else "update" if existing else "add"
    diff = "" if action == "noop" else "".join(difflib.unified_diff(
        current_text.splitlines(keepends=True),
        target_text.splitlines(keepends=True),
        fromfile="a/contextos.workspace.json",
        tofile="b/contextos.workspace.json",
    ))
    notices = [
        "preview only; no tracked file was written",
        "auto and local runtime detection never populate tracked agents",
    ]
    if source == "legacy-yaml":
        notices.append(
            "workspace.yaml remains unchanged until a later transaction applies migration"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "writes": False,
        "source": source,
        "target": "contextos.workspace.json",
        "action": action,
        "config": config,
        "content": target_text,
        "diff": diff,
        "notices": notices,
    }


def _agent_lifecycle_authorization(
    root: Path, operation: str, relative: str
) -> dict[str, str]:
    if operation != WORKSPACE_MIGRATION_OPERATION:
        raise ContextOSError(f"unsupported agent lifecycle operation: {operation}")
    expected = {
        "contextos.workspace.json": {
            "kind": "workspace-config",
            "owner": "workspace-config",
            "policy": "managed",
        },
        "workspace.yaml": {
            "kind": "legacy-config",
            "owner": "legacy-workspace-config",
            "policy": "migration-only",
        },
    }
    if relative not in expected:
        raise ContextOSError(
            f"{operation} cannot mutate unowned or component path: {relative}"
        )
    _reject_config_aliases(root, relative)
    safe_repo_path(root, relative)
    component_path = safe_repo_path(root, "components/manifest.json")
    manifest = load_component_manifest(
        component_path, root=root, check_paths=False
    )
    declared_owner = workspace_path_owner(manifest, relative)
    if declared_owner != expected[relative]["owner"]:
        raise ContextOSError(
            f"agent lifecycle owner mismatch for {relative}: {declared_owner!r}"
        )
    return expected[relative]


def _agent_source_paths(root: Path) -> list[str]:
    paths = [
        "components/manifest.json",
        "workspace/schema.json",
        "runtimes/schema.json",
    ]
    paths.extend(f"runtimes/{runtime}.json" for runtime in runtime_ids(root))
    if (root / "contextos.workspace.json").exists():
        paths.append("contextos.workspace.json")
    return sorted(paths, key=workspace_portable_identity)


def _agent_source_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in _agent_source_paths(root):
        path = safe_repo_path(root, relative)
        digest = raw_file_digest(path)
        if digest is None:
            raise ContextOSError(f"agent lifecycle source is missing: {relative}")
        result[relative] = digest
    return result


def _selection_components(root: Path, agents: Sequence[str]) -> list[str]:
    component_path = safe_repo_path(root, "components/manifest.json")
    manifest = load_component_manifest(
        component_path, root=root, check_paths=False
    )
    requested: set[str] = {"core"}
    for runtime in agents:
        requested.update(runtime_manifest(root, runtime, check_paths=False)["components"])
    return component_closure(manifest, sorted(requested))


def _agent_change(
    root: Path,
    operation: str,
    relative: str,
    *,
    action: str,
    after_text: str | None,
) -> dict[str, Any]:
    authorization = _agent_lifecycle_authorization(root, operation, relative)
    path = safe_repo_path(root, relative)
    if path.exists() and not path.is_file():
        raise ContextOSError(f"transaction target must be a regular file: {relative}")
    before_bytes = path.read_bytes() if path.exists() else None
    before_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    if action == "write":
        if not isinstance(after_text, str):
            raise ContextOSError(f"write action requires text content: {relative}")
        after_bytes = after_text.encode("utf-8")
        after_mode = before_mode if before_mode is not None else NEW_CONTENT_MODE
    elif action == "delete":
        if after_text is not None or before_bytes is None:
            raise ContextOSError(f"delete action requires an existing file: {relative}")
        after_bytes = None
        after_mode = None
    else:
        raise ContextOSError(f"unsupported agent lifecycle action: {action}")
    before_text = (
        before_bytes.decode("utf-8-sig") if before_bytes is not None else ""
    )
    rendered_after = after_text or ""
    diff = "".join(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            rendered_after.splitlines(keepends=True),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        )
    )
    return {
        "path": relative,
        "action": action,
        "authorization": authorization,
        "before_raw_sha256": (
            sha256_bytes(before_bytes) if before_bytes is not None else None
        ),
        "before_mode": before_mode,
        "after_raw_sha256": (
            sha256_bytes(after_bytes) if after_bytes is not None else None
        ),
        "after_mode": after_mode,
        "after_text": after_text,
        "diff": diff,
    }


def _create_workspace_config_proposal(
    root: Path,
    agents: Sequence[str],
    now: datetime,
    *,
    allow_initial: bool,
    allow_agent_expansion: bool,
) -> tuple[Path | None, dict[str, Any] | None]:
    target = root / "contextos.workspace.json"
    target_content: str | None = None
    if target.exists() or target.is_symlink():
        raw_file_digest(target)
        try:
            target_content = target.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise ContextOSError(
                "transaction target must contain valid UTF-8: "
                "contextos.workspace.json"
            ) from exc
    resolution = resolve_workspace(root)
    if resolution.source == "defaults" and not allow_initial:
        raise ContextOSError(
            "workspace migration requires legacy workspace.yaml; "
            "initial agent selection belongs to setup"
        )
    if (
        resolution.source == "json"
        and list(agents) != list(resolution.agents or [])
        and not allow_agent_expansion
    ):
        raise ContextOSError(
            "workspace migration cannot change an existing agent set; "
            "use the agent lifecycle"
        )
    preview = plan_workspace_migration(root, agents)
    changes: list[dict[str, Any]] = []
    if target_content != preview["content"]:
        changes.append(
            _agent_change(
                root,
                WORKSPACE_MIGRATION_OPERATION,
                "contextos.workspace.json",
                action="write",
                after_text=preview["content"],
            )
        )
    legacy = root / "workspace.yaml"
    if legacy.exists() or legacy.is_symlink():
        changes.append(
            _agent_change(
                root,
                WORKSPACE_MIGRATION_OPERATION,
                "workspace.yaml",
                action="delete",
                after_text=None,
            )
        )
    if not changes:
        return None, None
    workflow = AGENT_LIFECYCLE_WORKFLOW
    before_agents = (
        list(resolution.agents) if resolution.agents is not None else None
    )
    after_agents = list(preview["config"]["agents"])
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "workflow": workflow,
        "operation": WORKSPACE_MIGRATION_OPERATION,
        "created_at": now.isoformat(),
        "proposal_id": proposal_id(workflow, now, changes),
        "changes": changes,
        "authorization": {
            "policy": "agent-config-v1",
            "before_agents": before_agents,
            "after_agents": after_agents,
            "before_components": (
                _selection_components(root, before_agents)
                if before_agents is not None
                else None
            ),
            "after_components": _selection_components(root, after_agents),
        },
        "source_hashes": _agent_source_hashes(root),
        "source_git_head": git_head(root),
        "invariants": list(AGENT_MIGRATION_INVARIANTS),
    }
    document["proposal_digest"] = sha256_text(canonical_json(document))
    proposal_path = (
        root / ".context-os" / "proposals" / f"{document['proposal_id']}.json"
    )
    _write_exclusive_text(
        proposal_path,
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        root=root,
    )
    return proposal_path, document


def create_workspace_migration_proposal(
    root: Path,
    agents: Sequence[str],
    now: datetime,
) -> tuple[Path | None, dict[str, Any] | None]:
    return _create_workspace_config_proposal(
        root,
        agents,
        now,
        allow_initial=False,
        allow_agent_expansion=False,
    )


def create_workspace_setup_proposal(
    root: Path,
    requested_agents: Sequence[str],
    now: datetime,
) -> tuple[Path | None, dict[str, Any] | None]:
    """Create an additive setup proposal without inferring tracked intent."""
    requested_config = validate_workspace_config(
        {
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "mode": WORKSPACE_MODE,
            "agents": list(requested_agents),
            "paths": dict(DEFAULT_PATHS),
            "template": {
                "version": DEFAULT_TEMPLATE_VERSION,
                "source": DEFAULT_TEMPLATE_SOURCE,
            },
        },
        known_runtime_ids=runtime_ids(root),
    )
    resolution = resolve_workspace(root)
    configured = set(resolution.agents or ())
    selected = sorted(configured | set(requested_config["agents"]))
    return _create_workspace_config_proposal(
        root,
        selected,
        now,
        allow_initial=True,
        allow_agent_expansion=True,
    )


def relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def ensure_text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ContextOSError(f"{field} must be a string")
    return value


def ensure_string_list(value: Any, field: str, required: bool = False) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ContextOSError(f"{field} must be a list of non-empty strings")
    return [item.strip() for item in value]


def read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        value = strict_json_loads(raw, source=str(path))
    except (OSError, WorkspaceConfigError) as exc:
        raise ContextOSError(f"cannot read JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContextOSError(f"expected a JSON object in {path}")
    return value


def _json_object_from_bytes(raw: bytes, *, source: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        value = strict_json_loads(text, source=source)
    except (UnicodeDecodeError, WorkspaceConfigError) as exc:
        raise ContextOSError(f"cannot read JSON from {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContextOSError(f"expected a JSON object in {source}")
    return value


def _replace_last_updated(
    content: str, today: str, label: str = "lifecycle state"
) -> tuple[str, str | None]:
    matches = LAST_UPDATED_RE.findall(content)
    if len(matches) != 1:
        raise ContextOSError(f"{label} must contain exactly one **Last Updated:** line")
    old = matches[0].strip()
    updated = LAST_UPDATED_RE.sub(f"**Last Updated:** {today}", content, count=1)
    return updated, old if REAL_DATE_RE.fullmatch(old) else None


def _newest_history_date(content: str) -> str | None:
    dates = [line.strip() for line in content.splitlines() if REAL_DATE_RE.fullmatch(line.strip())]
    return max(dates) if dates else None


def _advance_current(
    workspace: Workspace, desired: str, today: str, pending: dict[Path, str]
) -> None:
    current = workspace.state_dir / "current.md"
    history = workspace.state_dir / "current-log.md"
    updated, old_date = _replace_last_updated(
        desired.rstrip() + "\n", today, "state/current.md"
    )
    pending[current] = updated
    history_text = history.read_text(encoding="utf-8") if history.exists() else "# current.md update log\n\n"
    newest = _newest_history_date(history_text)
    if old_date and old_date != today and old_date != newest:
        marker = "# current.md update log"
        if marker not in history_text:
            raise ContextOSError("state/current-log.md is missing its required heading")
        before, after = history_text.split(marker, 1)
        pending[history] = f"{before}{marker}\n\n{old_date}\n\n{after.lstrip()}"


def _advance_dated_state(path: Path, desired: str, today: str, required: bool = True) -> str:
    label = path.as_posix()
    normalized = desired.rstrip() + "\n"
    matches = LAST_UPDATED_RE.findall(normalized)
    if len(matches) > 1:
        raise ContextOSError(f"{label} must contain at most one **Last Updated:** line")
    if matches:
        updated, _ = _replace_last_updated(normalized, today, label)
        return updated

    # Workspaces created before freshness metadata was added should upgrade on
    # their next lifecycle write instead of failing setup or session end.
    lines = normalized.splitlines()
    if not lines or not lines[0].startswith("# "):
        # Setup stamps reviewed content opportunistically; a lifecycle write to a
        # file the kernel already owns must not silently skip the timestamp.
        if not required:
            return normalized
        raise ContextOSError(
            f"{label} must begin with a level-one heading when adding **Last Updated:**"
        )
    insert_at = 1
    if path.name == "weekly-priorities.md":
        for index, line in enumerate(lines[1:], start=1):
            if line.startswith("**Week of:**"):
                insert_at = index + 1
                break
    before = "\n".join(lines[:insert_at]).rstrip()
    after = "\n".join(lines[insert_at:]).strip()
    suffix = f"\n\n{after}\n" if after else "\n"
    return f"{before}\n\n**Last Updated:** {today}{suffix}"


def _session_append(path: Path, block: str, date: str) -> str:
    if path.exists():
        existing = path.read_text(encoding="utf-8").rstrip()
        return f"{existing}\n\n{block.rstrip()}\n"
    return f"# Session — {date}\n\n{block.rstrip()}\n"


def _bullets(values: list[str], empty: str = "- None recorded") -> str:
    return "\n".join(f"- {value}" for value in values) if values else empty


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def render_update(workspace: Workspace, payload: dict[str, Any], now: datetime) -> dict[Path, str]:
    progress = ensure_string_list(payload.get("progress"), "progress", required=True)
    today, clock = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    session = workspace.sessions_dir / f"{today}.md"
    pending = {session: _session_append(session, f"## Update: {clock}\n{_bullets(progress)}", today)}
    if "current_markdown" in payload:
        _advance_current(workspace, ensure_text(payload["current_markdown"], "current_markdown"), today, pending)
    return pending


def render_end(workspace: Workspace, payload: dict[str, Any], now: datetime) -> dict[Path, str]:
    happened = ensure_string_list(payload.get("what_happened"), "what_happened", required=True)
    decisions = payload.get("decisions", [])
    if not isinstance(decisions, list):
        raise ContextOSError("decisions must be a list")
    next_time = ensure_string_list(payload.get("next_time"), "next_time")
    today, clock = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    session = workspace.sessions_dir / f"{today}.md"
    decision_bullets = []
    for index, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            raise ContextOSError(f"decisions[{index}] must be an object")
        decision_bullets.append(ensure_text(decision.get("decision"), f"decisions[{index}].decision"))
    sections = (
        f"## What happened\n{_bullets(happened)}\n\n"
        f"## Decisions\n{_bullets(decision_bullets)}\n\n"
        f"## Next time\n{_bullets(next_time)}"
    )
    if session.exists():
        sections = f"## Session {clock}\n\n{sections}"
    pending: dict[Path, str] = {session: _session_append(session, sections, today)}
    if "current_markdown" in payload:
        _advance_current(workspace, ensure_text(payload["current_markdown"], "current_markdown"), today, pending)
    for field, filename in (("blockers_markdown", "blockers.md"), ("weekly_priorities_markdown", "weekly-priorities.md")):
        if field in payload:
            path = workspace.state_dir / filename
            pending[path] = _advance_dated_state(
                path, ensure_text(payload[field], field), today
            )
    if decisions:
        decision_path = workspace.state_dir / "decisions.md"
        if not decision_path.exists():
            raise ContextOSError(f"decision log does not exist: {relative_path(workspace.root, decision_path)}")
        text = decision_path.read_text(encoding="utf-8").rstrip()
        for index, decision in enumerate(decisions):
            rationale = ensure_text(decision.get("rationale", ""), f"decisions[{index}].rationale")
            rejected = ensure_text(decision.get("rejected_alternatives", ""), f"decisions[{index}].rejected_alternatives")
            text += (
                f"\n| {today} | {_escape_table(decision_bullets[index])} | "
                f"{_escape_table(rationale)} | {_escape_table(rejected)} |"
            )
        pending[decision_path] = text + "\n"
    return pending


def _is_populated(content: str) -> bool:
    stripped = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    for raw_line in stripped.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or re.fullmatch(r"\|?[\s:|-]+\|?", line):
            continue
        value = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", line)
        if re.fullmatch(r"(?:\*\*[^*]+:\*\*\s*)?\[[^\]\n]+\][.,;:]?", value):
            continue
        return True
    return False


def render_setup(workspace: Workspace, payload: dict[str, Any], now: datetime) -> dict[Path, str]:
    files = payload.get("files")
    replace = set(ensure_string_list(payload.get("replace_populated"), "replace_populated"))
    if not isinstance(files, dict) or not files:
        raise ContextOSError("files must be a non-empty object mapping paths to content")
    today = now.strftime("%Y-%m-%d")
    # Setup owns the freshness line on the state files start/doctor read, so a
    # completed setup reports as initialized without relying on the agent to
    # hand-write **Last Updated:** into reviewed content.
    dated_state = {workspace.state_dir / filename for filename in STATE_THRESHOLDS}
    pending: dict[Path, str] = {}
    for raw_path, raw_content in files.items():
        if not isinstance(raw_path, str):
            raise ContextOSError("setup file paths must be strings")
        path = safe_repo_path(workspace.root, raw_path)
        relative = relative_path(workspace.root, path)
        top = Path(relative).parts[0]
        skill_path = len(Path(relative).parts) >= 3 and Path(relative).parts[:2] == (".agents", "skills")
        if top not in SETUP_ROOTS and relative not in SETUP_FILES and not skill_path:
            raise ContextOSError(f"setup cannot write outside approved context paths: {relative}")
        content = ensure_text(raw_content, f"files[{raw_path}]").replace("{{TODAY}}", today)
        if path.exists() and _is_populated(path.read_text(encoding="utf-8")) and relative not in replace:
            raise ContextOSError(f"populated file requires replace_populated approval: {relative}")
        if path in dated_state:
            content = _advance_dated_state(path, content, today, required=False)
        pending[path] = content.rstrip() + "\n"
    return pending


def build_changes(
    root: Path, pending: dict[Path, str], replacement_approvals: set[str] | None = None
) -> list[dict[str, Any]]:
    changes = []
    for path in sorted(pending, key=lambda item: relative_path(root, item)):
        after = pending[path]
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        if before == after:
            continue
        rel = relative_path(root, path)
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True), after.splitlines(keepends=True),
                fromfile=f"a/{rel}", tofile=f"b/{rel}",
            )
        )
        change = {
            "path": rel,
            "before_sha256": file_digest(path),
            "after_sha256": sha256_text(after),
            "after_text": after,
            "diff": diff,
        }
        if replacement_approvals is not None:
            change["replacement_approved"] = rel in replacement_approvals
        changes.append(change)
    return changes


def _content_invariants(workflow: str, changes: Sequence[dict[str, Any]]) -> list[str]:
    invariants = list(CONTENT_BASE_INVARIANTS)
    if workflow in {"update", "end"} and any(
        isinstance(change, dict)
        and isinstance(change.get("path"), str)
        and change["path"].endswith("current.md")
        for change in changes
    ):
        invariants.extend(CONTENT_FRESHNESS_INVARIANTS)
    return invariants


def _content_change_diff(root: Path, relative: str, after_text: str) -> str:
    path = safe_repo_path(root, relative)
    before_text = path.read_text(encoding="utf-8") if path.exists() else ""
    return "".join(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        )
    )


def _validate_content_semantics(
    root: Path,
    workflow: str,
    created_at: datetime,
    changes: Sequence[dict[str, Any]],
) -> None:
    if "single-last-updated" not in _content_invariants(workflow, changes):
        return
    workspace = load_workspace(root)
    current_relative = relative_path(root, workspace.state_dir / "current.md")
    history_relative = relative_path(root, workspace.state_dir / "current-log.md")
    changes_by_path = {change["path"]: change for change in changes}
    current_change = changes_by_path.get(current_relative)
    if current_change is None:
        raise ContextOSError("content freshness invariants require current.md")

    today = created_at.strftime("%Y-%m-%d")
    after_dates = LAST_UPDATED_RE.findall(current_change["after_text"])
    if len(after_dates) != 1 or after_dates[0].strip() != today:
        raise ContextOSError(
            "single-last-updated invariant failed for " + current_relative
        )

    current_path = safe_repo_path(root, current_relative)
    before_text = current_path.read_text(encoding="utf-8") if current_path.exists() else ""
    before_dates = LAST_UPDATED_RE.findall(before_text)
    if len(before_dates) != 1:
        raise ContextOSError(
            "same-day-history invariant requires one prior Last Updated date"
        )
    prior_date = before_dates[0].strip()
    history_path = safe_repo_path(root, history_relative)
    history_before = (
        history_path.read_text(encoding="utf-8")
        if history_path.exists()
        else "# current.md update log\n\n"
    )
    history_change = changes_by_path.get(history_relative)
    needs_history = (
        REAL_DATE_RE.fullmatch(prior_date) is not None
        and prior_date != today
        and prior_date != _newest_history_date(history_before)
    )
    if not needs_history:
        if history_change is not None:
            raise ContextOSError(
                "same-day-history invariant rejects an unexpected history change"
            )
        return
    marker = "# current.md update log"
    if marker not in history_before:
        raise ContextOSError("state/current-log.md is missing its required heading")
    before_marker, after_marker = history_before.split(marker, 1)
    expected_history = (
        f"{before_marker}{marker}\n\n{prior_date}\n\n{after_marker.lstrip()}"
    )
    if history_change is None or history_change["after_text"] != expected_history:
        raise ContextOSError("same-day-history invariant failed")


def proposal_id(workflow: str, now: datetime, changes: list[dict[str, Any]]) -> str:
    seed = canonical_json({"workflow": workflow, "now": now.isoformat(), "changes": changes})
    return f"{now.strftime('%Y%m%dT%H%M%S')}-{workflow}-{sha256_text(seed)[:10]}"


def _guard_local_artifact_path(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ContextOSError(f"local artifact path escapes workspace: {path}") from exc
    if not relative.parts or relative.parts[0] != ".context-os":
        raise ContextOSError(f"local artifact must remain below .context-os: {path}")
    if any(part in {".", ".."} for part in relative.parts):
        raise ContextOSError(f"local artifact path has a dot segment: {path}")
    current = root
    for index, part in enumerate(relative.parts):
        if current.exists():
            try:
                aliases = [
                    child.name
                    for child in current.iterdir()
                    if workspace_portable_identity(child.name)
                    == workspace_portable_identity(part)
                ]
            except OSError as exc:
                raise ContextOSError(f"cannot inspect local artifact path: {exc}") from exc
            if aliases and aliases != [part]:
                raise ContextOSError(
                    f"portable local artifact collision for {part!r}: "
                    + ", ".join(sorted(aliases))
                )
        current /= part
        if _is_link_like(current):
            raise ContextOSError(
                "local artifact path must not traverse a symlink or reparse point: "
                f"{relative.as_posix()}"
            )
        if index < len(relative.parts) - 1 and current.exists() and not current.is_dir():
            raise ContextOSError(
                f"local artifact ancestor must be a directory: {current.relative_to(root)}"
            )


def _write_exclusive_text(path: Path, content: str, *, root: Path) -> None:
    _write_exclusive_bytes(path, content.encode("utf-8"), root=root)


def _fsync_directory(path: Path) -> None:
    """Persist a directory entry where the host exposes POSIX directory fsync."""
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        unsupported = {
            errno.EBADF,
            errno.EINVAL,
            getattr(errno, "ENOTSUP", errno.EINVAL),
            getattr(errno, "EOPNOTSUPP", errno.EINVAL),
        }
        if exc.errno not in unsupported:
            raise


def create_proposal(root: Path, workflow: str, payload: dict[str, Any], now: datetime) -> tuple[Path, dict[str, Any]]:
    workspace = load_workspace(root)
    renderers = {"update": render_update, "end": render_end, "setup": render_setup}
    if workflow not in renderers:
        raise ContextOSError(f"unsupported proposal workflow: {workflow}")
    replacement_approvals = (
        set(ensure_string_list(payload.get("replace_populated"), "replace_populated"))
        if workflow == "setup" else None
    )
    changes = build_changes(
        root, renderers[workflow](workspace, payload, now), replacement_approvals
    )
    if not changes:
        raise ContextOSError("proposal has no changes")
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "workflow": workflow,
        "created_at": now.isoformat(),
        "proposal_id": proposal_id(workflow, now, changes),
        "changes": changes,
        "invariants": _content_invariants(workflow, changes),
    }
    digest = sha256_text(canonical_json(document))
    document["proposal_digest"] = digest
    target = root / ".context-os" / "proposals" / f"{document['proposal_id']}.json"
    _write_exclusive_text(
        target,
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        root=root,
    )
    return target, document


@contextmanager
def transaction_lock(root: Path) -> Iterator[None]:
    lock = root / ".context-os" / "apply.lock"
    _guard_local_artifact_path(root, lock)
    _ensure_local_directory(root, lock.parent)
    try:
        descriptor = os.open(
            lock,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            LOCAL_ARTIFACT_MODE,
        )
    except FileExistsError as exc:
        raise ContextOSError(f"another apply is active or left a stale lock: {lock}") from exc
    try:
        try:
            os.write(descriptor, f"pid={os.getpid()}\n".encode())
            os.chmod(lock, LOCAL_ARTIFACT_MODE)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(lock.parent)
        yield
    finally:
        lock.unlink(missing_ok=True)
        _fsync_directory(lock.parent)


def git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def validate_proposal(document: dict[str, Any]) -> str:
    digest = document.get("proposal_digest")
    if not isinstance(digest, str):
        raise ContextOSError("proposal is missing proposal_digest")
    unsigned = dict(document)
    del unsigned["proposal_digest"]
    expected = sha256_text(canonical_json(unsigned))
    if digest != expected:
        raise ContextOSError("proposal digest does not match its contents")
    return digest


def _validate_change_path(workspace: Workspace, workflow: str, created_at: datetime, relative: str) -> None:
    parts = Path(relative).parts
    if not parts or parts[0] in {".git", ".context-os"}:
        raise ContextOSError(f"proposal path is reserved: {relative}")
    if workflow == "setup":
        allowed = (
            relative in SETUP_FILES
            or parts[0] in {"identity", "projects", "state"}
            or (len(parts) >= 3 and parts[:2] == (".agents", "skills"))
        )
    else:
        state_paths = {
            relative_path(workspace.root, workspace.state_dir / name)
            for name in ("current.md", "current-log.md")
        }
        if workflow == "end":
            state_paths.update(
                relative_path(workspace.root, workspace.state_dir / name)
                for name in ("decisions.md", "blockers.md", "weekly-priorities.md")
            )
        session_path = relative_path(
            workspace.root, workspace.sessions_dir / f"{created_at.strftime('%Y-%m-%d')}.md"
        )
        allowed = relative in state_paths or relative == session_path
    if not allowed:
        raise ContextOSError(f"{workflow} proposal cannot write path: {relative}")


def _validate_agent_proposal_shape(
    root: Path, document: dict[str, Any]
) -> tuple[str, datetime]:
    required = {
        "schema_version",
        "workflow",
        "operation",
        "created_at",
        "proposal_id",
        "changes",
        "authorization",
        "source_hashes",
        "source_git_head",
        "invariants",
        "proposal_digest",
    }
    if set(document) != required:
        raise ContextOSError("agent-config proposal has an invalid top-level shape")
    operation = document.get("operation")
    if operation != WORKSPACE_MIGRATION_OPERATION:
        raise ContextOSError(f"unsupported agent lifecycle operation: {operation}")
    created_at = parse_now(ensure_text(document.get("created_at"), "created_at"))
    changes = document.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ContextOSError("agent-config proposal changes must be a non-empty list")
    expected_change_keys = {
        "path",
        "action",
        "authorization",
        "before_raw_sha256",
        "before_mode",
        "after_raw_sha256",
        "after_mode",
        "after_text",
        "diff",
    }
    seen: dict[str, str] = {}
    after_config: dict[str, Any] | None = None
    paths: list[str] = []
    for index, change in enumerate(changes):
        if not isinstance(change, dict) or set(change) != expected_change_keys:
            raise ContextOSError(f"agent-config changes[{index}] has an invalid shape")
        relative = ensure_text(change.get("path"), f"changes[{index}].path")
        identity = workspace_portable_identity(relative)
        if identity in seen:
            raise ContextOSError(
                f"agent-config proposal has a portable duplicate path: "
                f"{seen[identity]} and {relative}"
            )
        seen[identity] = relative
        paths.append(relative)
        expected_authorization = _agent_lifecycle_authorization(
            root, operation, relative
        )
        if change.get("authorization") != expected_authorization:
            raise ContextOSError(f"agent-config authorization mismatch: {relative}")
        action = change.get("action")
        expected_action = (
            "write" if relative == "contextos.workspace.json" else "delete"
        )
        if action != expected_action:
            raise ContextOSError(
                f"agent-config action mismatch for {relative}: {action!r}"
            )
        before_hash = change.get("before_raw_sha256")
        before_mode = change.get("before_mode")
        after_hash = change.get("after_raw_sha256")
        after_mode = change.get("after_mode")
        if before_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", str(before_hash)):
            raise ContextOSError(f"invalid raw before hash: {relative}")
        if (before_hash is None) != (before_mode is None) or (
            before_mode is not None
            and (type(before_mode) is not int or not 0 <= before_mode <= 0o7777)
        ):
            raise ContextOSError(f"invalid before mode: {relative}")
        if action == "write":
            after_text = ensure_text(change.get("after_text"), "change.after_text")
            if not isinstance(after_hash, str) or after_hash != sha256_bytes(
                after_text.encode("utf-8")
            ):
                raise ContextOSError(f"invalid raw after hash: {relative}")
            expected_after_mode = (
                before_mode if before_mode is not None else NEW_CONTENT_MODE
            )
            if after_mode != expected_after_mode:
                raise ContextOSError(f"invalid after mode: {relative}")
            try:
                after_config = validate_workspace_config(
                    strict_json_loads(after_text, source=relative),
                    known_runtime_ids=runtime_ids(root),
                )
            except WorkspaceConfigError as exc:
                raise ContextOSError(f"invalid proposed workspace config: {exc}") from exc
            if after_text != render_workspace_config(after_config):
                raise ContextOSError("proposed workspace config must be canonical")
        elif (
            change.get("after_text") is not None
            or after_hash is not None
            or after_mode is not None
        ):
            raise ContextOSError(f"delete action must not carry after content: {relative}")
    if paths not in (["contextos.workspace.json"], ["workspace.yaml"], [
        "contextos.workspace.json", "workspace.yaml"
    ]):
        raise ContextOSError("workspace migration has an invalid ordered path set")

    resolution = resolve_workspace(root)
    if after_config is None:
        if resolution.source != "json" or resolution.config is None or not resolution.canonical:
            raise ContextOSError(
                "workspace.yaml deletion requires an existing canonical JSON configuration"
            )
        after_config = resolution.config
    before_agents = list(resolution.agents) if resolution.agents is not None else None
    after_agents = list(after_config["agents"])
    expected_authorization = {
        "policy": "agent-config-v1",
        "before_agents": before_agents,
        "after_agents": after_agents,
        "before_components": (
            _selection_components(root, before_agents)
            if before_agents is not None
            else None
        ),
        "after_components": _selection_components(root, after_agents),
    }
    if document.get("authorization") != expected_authorization:
        raise ContextOSError("agent-config proposal authorization evidence is stale or invalid")

    source_hashes = document.get("source_hashes")
    if not isinstance(source_hashes, dict) or list(source_hashes) != _agent_source_paths(root):
        raise ContextOSError("agent-config proposal source path set is stale or invalid")
    for relative, digest in source_hashes.items():
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContextOSError(f"invalid agent-config source hash: {relative}")
    source_git_head = document.get("source_git_head")
    if source_git_head is not None and not isinstance(source_git_head, str):
        raise ContextOSError("source_git_head must be a string or null")
    if document.get("invariants") != AGENT_MIGRATION_INVARIANTS:
        raise ContextOSError("agent-config proposal invariants are invalid")
    return operation, created_at


def _validate_proposal_shape(root: Path, proposal: Path, document: dict[str, Any]) -> tuple[str, datetime]:
    workflow = document.get("workflow")
    if workflow == AGENT_LIFECYCLE_WORKFLOW:
        operation, created_at = _validate_agent_proposal_shape(root, document)
        workflow_value = AGENT_LIFECYCLE_WORKFLOW
    else:
        operation = "content-lifecycle"
        workflow_value = workflow
    required = {
        "schema_version", "workflow", "created_at", "proposal_id",
        "changes", "invariants", "proposal_digest",
    }
    if workflow != AGENT_LIFECYCLE_WORKFLOW and (
        set(document) != required or document.get("schema_version") != SCHEMA_VERSION
    ):
        raise ContextOSError("proposal has an invalid top-level shape")
    if (
        type(document.get("schema_version")) is not int
        or document.get("schema_version") != SCHEMA_VERSION
    ):
        raise ContextOSError("proposal has an unsupported schema version")
    if workflow not in {"setup", "update", "end", AGENT_LIFECYCLE_WORKFLOW}:
        raise ContextOSError(f"unsupported proposal workflow: {workflow}")
    proposal_id_value = ensure_text(document.get("proposal_id"), "proposal_id")
    if not PROPOSAL_ID_RE.fullmatch(proposal_id_value):
        raise ContextOSError("proposal_id has an invalid format")
    expected_dir = (root / ".context-os" / "proposals").resolve()
    try:
        proposal.resolve().relative_to(expected_dir)
    except ValueError as exc:
        raise ContextOSError("proposal must be loaded from .context-os/proposals") from exc
    if proposal.name != f"{proposal_id_value}.json":
        raise ContextOSError("proposal filename does not match proposal_id")
    if workflow != AGENT_LIFECYCLE_WORKFLOW:
        created_at = parse_now(ensure_text(document.get("created_at"), "created_at"))
    changes = document.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ContextOSError("proposal changes must be a non-empty list")
    if workflow != AGENT_LIFECYCLE_WORKFLOW and document.get(
        "invariants"
    ) != _content_invariants(workflow, changes):
        raise ContextOSError("content proposal invariants are invalid")
    workspace = load_workspace(root)
    seen: set[str] = set()
    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            raise ContextOSError(f"changes[{index}] must be an object")
        if workflow != AGENT_LIFECYCLE_WORKFLOW:
            expected_change_keys = {
                "path",
                "before_sha256",
                "after_sha256",
                "after_text",
                "diff",
            }
            if workflow == "setup":
                expected_change_keys.add("replacement_approved")
            if set(change) != expected_change_keys:
                raise ContextOSError(
                    f"changes[{index}] has an invalid content change shape"
                )
            before_digest = change.get("before_sha256")
            if before_digest is not None and (
                not isinstance(before_digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", before_digest)
            ):
                raise ContextOSError(f"changes[{index}].before_sha256 is invalid")
            after_digest = change.get("after_sha256")
            if not isinstance(after_digest, str) or not re.fullmatch(
                r"[0-9a-f]{64}", after_digest
            ):
                raise ContextOSError(f"changes[{index}].after_sha256 is invalid")
            ensure_text(change.get("after_text"), f"changes[{index}].after_text")
            ensure_text(change.get("diff"), f"changes[{index}].diff")
        relative = ensure_text(change.get("path"), f"changes[{index}].path")
        if relative in seen:
            raise ContextOSError(f"proposal contains duplicate path: {relative}")
        seen.add(relative)
        safe_repo_path(root, relative)
        if workflow != AGENT_LIFECYCLE_WORKFLOW:
            _validate_change_path(workspace, workflow, created_at, relative)
        if workflow == "setup" and change.get("replacement_approved") not in {True, False}:
            raise ContextOSError(f"setup change is missing replacement policy: {relative}")
    return workflow_value, created_at


def _validate_agent_preflight(root: Path, document: dict[str, Any]) -> None:
    if document.get("source_git_head") != git_head(root):
        raise ContextOSError("refusing stale agent-config proposal; git HEAD changed")
    # Targets are also authorization inputs (the current workspace configuration
    # determines the before-agent closure). Check them first so a target-only
    # byte change is reported as target drift rather than the less actionable
    # source-drift category.
    for change in document["changes"]:
        relative = change["path"]
        _agent_lifecycle_authorization(root, document["operation"], relative)
        path = safe_repo_path(root, relative)
        if raw_file_digest(path) != change["before_raw_sha256"]:
            raise ContextOSError(
                f"refusing stale agent-config proposal; target changed: {relative}"
            )
        current_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
        if current_mode != change["before_mode"]:
            raise ContextOSError(
                f"refusing stale agent-config proposal; target mode changed: {relative}"
            )
        if change["action"] == "write" and sha256_bytes(
            change["after_text"].encode("utf-8")
        ) != change["after_raw_sha256"]:
            raise ContextOSError(f"agent-config after hash is invalid: {relative}")
        expected = _agent_change(
            root,
            document["operation"],
            relative,
            action=change["action"],
            after_text=change["after_text"],
        )
        if change["diff"] != expected["diff"]:
            raise ContextOSError(f"agent-config displayed diff is invalid: {relative}")
        if (
            change["before_mode"] != expected["before_mode"]
            or change["after_mode"] != expected["after_mode"]
        ):
            raise ContextOSError(f"agent-config mode plan is invalid: {relative}")
    if list(document["source_hashes"]) != _agent_source_paths(root):
        raise ContextOSError("refusing stale agent-config proposal; source path set changed")
    for relative, expected in document["source_hashes"].items():
        if raw_file_digest(safe_repo_path(root, relative)) != expected:
            raise ContextOSError(
                f"refusing stale agent-config proposal; source changed: {relative}"
            )


def _ensure_local_directory(root: Path, path: Path) -> None:
    """Create a local-state directory and durably anchor each new ancestor."""
    _guard_local_artifact_path(root, path)
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        if current == root:
            break
        current = current.parent
    path.mkdir(parents=True, exist_ok=True)
    for created in reversed(missing):
        _fsync_directory(created)
        _fsync_directory(created.parent)


def _windows_unlink_readonly(path: Path) -> None:
    """Delete one Windows name without changing a shared inode's attributes."""
    import ctypes
    from ctypes import wintypes

    delete_access = 0x00010000
    share_all = 0x00000001 | 0x00000002 | 0x00000004
    open_existing = 3
    open_reparse_point = 0x00200000
    backup_semantics = 0x02000000
    file_disposition_info_ex = 21
    disposition_delete = 0x00000001
    disposition_posix_semantics = 0x00000002
    disposition_ignore_readonly = 0x00000010

    class FileDispositionInfoEx(ctypes.Structure):
        _fields_ = [("flags", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    set_file_information = kernel32.SetFileInformationByHandle
    set_file_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    set_file_information.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    raw = os.path.abspath(path)
    if raw.startswith(("\\\\?\\", "\\\\.\\")):
        pass
    elif raw.startswith("\\\\"):
        raw = "\\\\?\\UNC\\" + raw[2:]
    else:
        raw = "\\\\?\\" + raw
    handle = create_file(
        raw,
        delete_access,
        share_all,
        None,
        open_existing,
        open_reparse_point | backup_semantics,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        disposition = FileDispositionInfoEx(
            disposition_delete
            | disposition_posix_semantics
            | disposition_ignore_readonly
        )
        if not set_file_information(
            handle,
            file_disposition_info_ex,
            ctypes.byref(disposition),
            ctypes.sizeof(disposition),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        close_handle(handle)


def _unlink_readonly_artifact(path: Path) -> None:
    """Unlink a local artifact without mutating a shared hard-link inode."""
    try:
        path.unlink()
        return
    except PermissionError:
        if os.name != "nt":
            raise
    try:
        _windows_unlink_readonly(path)
        return
    except OSError as exc:
        unsupported_disposition_errors = {1, 50, 87}
        if getattr(exc, "winerror", None) not in unsupported_disposition_errors:
            raise ContextOSError(
                f"cannot atomically remove read-only transaction artifact {path}: {exc}"
            ) from exc
        try:
            metadata = path.lstat()
        except OSError as inspect_exc:
            raise ContextOSError(
                f"cannot inspect read-only transaction artifact {path}: {inspect_exc}"
            ) from inspect_exc
        if (
            _is_link_like(path)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
        ):
            raise ContextOSError(
                "filesystem cannot safely remove a read-only transaction artifact "
                f"without changing a shared inode: {path}; use a Windows NTFS "
                "workspace with FileDispositionInfoEx support"
            ) from exc
        original_mode = metadata.st_mode & 0o7777
        os.chmod(path, original_mode | stat.S_IWRITE)
        try:
            path.unlink()
        except OSError as unlink_exc:
            if path.exists() and not _is_link_like(path):
                os.chmod(path, original_mode)
            raise ContextOSError(
                f"cannot remove read-only transaction artifact {path}: {unlink_exc}"
            ) from unlink_exc


def _rmtree_readonly_artifacts(
    path: Path,
    *,
    ignore_errors: bool = False,
) -> None:
    """Remove a local tree without widening attributes on shared files."""

    def handle_exception(
        function: Any, failed_path: str, exception: BaseException
    ) -> None:
        if os.name != "nt" or not isinstance(exception, PermissionError):
            raise exception
        failed = Path(failed_path)
        try:
            failed_stat = failed.lstat()
        except FileNotFoundError:
            return
        if (
            stat.S_ISREG(failed_stat.st_mode)
            or stat.S_ISLNK(failed_stat.st_mode)
            or _is_link_like(failed)
        ):
            _unlink_readonly_artifact(failed)
            return
        original_mode = failed_stat.st_mode & 0o7777
        os.chmod(failed, original_mode | stat.S_IWRITE)
        try:
            function(failed_path)
        except FileNotFoundError:
            pass
        except OSError:
            if failed.exists() and not _is_link_like(failed):
                os.chmod(failed, original_mode)
            raise

    def handle_error(function: Any, failed_path: str, error: Any) -> None:
        handle_exception(function, failed_path, error[1])

    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=handle_exception)
        else:
            shutil.rmtree(path, onerror=handle_error)
    except (OSError, ContextOSError):
        if not ignore_errors:
            raise


def _write_exclusive_bytes(
    path: Path,
    content: bytes,
    *,
    root: Path,
    mode: int = LOCAL_ARTIFACT_MODE,
) -> None:
    _guard_local_artifact_path(root, path)
    if type(mode) is not int or not 0 <= mode <= 0o7777:
        raise ContextOSError(f"invalid local artifact mode for {path}: {mode!r}")
    _ensure_local_directory(root, path.parent)
    try:
        descriptor = os.open(
            path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
            mode,
        )
    except FileExistsError as exc:
        raise ContextOSError(f"refusing to overwrite local artifact: {path}") from exc
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while creating local artifact")
            view = view[written:]
        if os.name != "nt" and hasattr(os, "fchmod"):
            os.fchmod(descriptor, mode)
        else:
            os.chmod(path, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _transaction_slot(ordinal: int, relative: str) -> str:
    identity = workspace_portable_identity(relative)
    return f"{ordinal:04d}-{sha256_text(identity)[:16]}"


def _create_agent_journal(
    root: Path,
    document: dict[str, Any],
    backups: dict[Path, bytes | None],
    backup_modes: dict[Path, int | None],
    receipt_path: Path,
) -> Path:
    journal = root / ".context-os" / "journals" / document["proposal_id"]
    _guard_local_artifact_path(root, journal)
    if journal.exists() or journal.is_symlink():
        raise ContextOSError(f"agent transaction journal already exists: {journal}")
    building = journal.with_name(f".{journal.name}.building")
    _guard_local_artifact_path(root, building)
    if building.exists() or building.is_symlink():
        raise ContextOSError(f"agent transaction journal build already exists: {building}")
    workflow = document["workflow"]
    entries: list[dict[str, Any]] = []
    for index, change in enumerate(document["changes"]):
        path = safe_repo_path(root, change["path"])
        before = backups[path]
        slot = _transaction_slot(index, change["path"])
        backup_relative = None
        if before is not None:
            backup_relative = f"backups/{slot}.bin"
            _write_exclusive_bytes(building / backup_relative, before, root=root)
        if workflow == AGENT_LIFECYCLE_WORKFLOW:
            action = change["action"]
            owner = change["authorization"]["owner"]
            policy = change["authorization"]["policy"]
            after_raw = change["after_raw_sha256"]
            receipt_entry = {
                "action": action,
                "path": change["path"],
                "owner": owner,
                "policy": policy,
                "sha256_before_raw": change["before_raw_sha256"],
                "sha256_after_raw": after_raw,
            }
        else:
            action = "write"
            owner = None
            policy = None
            after_raw = sha256_bytes(change["after_text"].encode("utf-8"))
            receipt_entry = {
                "path": change["path"],
                "sha256_before": change["before_sha256"],
                "sha256_after": change["after_sha256"],
            }
        after_mode = (
            change["after_mode"]
            if workflow == AGENT_LIFECYCLE_WORKFLOW
            else backup_modes[path]
            if backup_modes[path] is not None
            else NEW_CONTENT_MODE
        )
        entries.append({
            "ordinal": index,
            "slot": slot,
            "path": change["path"],
            "action": action,
            "owner": owner,
            "policy": policy,
            "existed": before is not None,
            "mode": backup_modes[path],
            "after_mode": after_mode,
            "before_sha256_raw": sha256_bytes(before) if before is not None else None,
            "after_sha256_raw": after_raw,
            "backup": backup_relative,
            "receipt_entry": receipt_entry,
        })
    backup_directory = building / "backups"
    if backup_directory.is_dir():
        _fsync_directory(backup_directory)
    manifest = {
        "journal_version": TRANSACTION_JOURNAL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "workflow": workflow,
        "operation": document.get("operation", "content-lifecycle"),
        "created_at": document["created_at"],
        "proposal_id": document["proposal_id"],
        "proposal_digest": document["proposal_digest"],
        "receipt": receipt_path.relative_to(root).as_posix(),
        "invariants": document["invariants"],
        "entries": entries,
        "agent_evidence": (
            {
                "authorization": document["authorization"],
                "source_hashes": document["source_hashes"],
            }
            if workflow == AGENT_LIFECYCLE_WORKFLOW
            else None
        ),
    }
    _write_exclusive_text(
        building / "journal.json",
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        root=root,
    )
    _fsync_directory(building)
    try:
        building.rename(journal)
    except FileExistsError as exc:
        raise ContextOSError(
            f"agent transaction journal already exists: {journal}"
        ) from exc
    _fsync_directory(journal.parent)
    _fsync_directory(journal.parent.parent)
    return journal


def _recover_agent_journal(
    root: Path, journal: Path, *, allow_foreign_receipt_rollback: bool = False
) -> None:
    _guard_local_artifact_path(root, journal)
    manifest_path = journal / "journal.json"
    _guard_local_artifact_path(root, manifest_path)
    manifest = read_json(manifest_path)
    required = {
        "journal_version",
        "schema_version",
        "workflow",
        "operation",
        "created_at",
        "proposal_id",
        "proposal_digest",
        "receipt",
        "invariants",
        "entries",
        "agent_evidence",
    }
    workflow = manifest.get("workflow")
    if (
        set(manifest) != required
        or type(manifest.get("journal_version")) is not int
        or manifest.get("journal_version") != TRANSACTION_JOURNAL_VERSION
        or type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") != SCHEMA_VERSION
        or workflow not in {"setup", "update", "end", AGENT_LIFECYCLE_WORKFLOW}
        or manifest.get("proposal_id") != journal.name
        or not isinstance(manifest.get("proposal_id"), str)
        or PROPOSAL_ID_RE.fullmatch(manifest["proposal_id"]) is None
        or not isinstance(manifest.get("proposal_digest"), str)
        or re.fullmatch(r"[0-9a-f]{64}", manifest["proposal_digest"]) is None
    ):
        raise ContextOSError(f"invalid transaction journal: {journal}")
    created_at = parse_now(ensure_text(manifest.get("created_at"), "created_at"))
    if workflow == AGENT_LIFECYCLE_WORKFLOW:
        if manifest.get("operation") != WORKSPACE_MIGRATION_OPERATION:
            raise ContextOSError(f"invalid agent transaction journal: {journal}")
        evidence = manifest.get("agent_evidence")
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"authorization", "source_hashes"}
            or not isinstance(evidence.get("authorization"), dict)
            or not isinstance(evidence.get("source_hashes"), dict)
            or manifest.get("invariants") != AGENT_MIGRATION_INVARIANTS
        ):
            raise ContextOSError(f"invalid agent transaction evidence: {journal}")
    else:
        if (
            manifest.get("operation") != "content-lifecycle"
            or manifest.get("agent_evidence") is not None
        ):
            raise ContextOSError(f"invalid content transaction journal: {journal}")
    entries = manifest.get("entries")
    expected_entry_keys = {
        "ordinal",
        "slot",
        "path",
        "action",
        "owner",
        "policy",
        "existed",
        "mode",
        "after_mode",
        "before_sha256_raw",
        "after_sha256_raw",
        "backup",
        "receipt_entry",
    }
    if not isinstance(entries, list) or not entries:
        raise ContextOSError(f"transaction journal has no entries: {journal}")
    workspace = load_workspace(root) if workflow != AGENT_LIFECYCLE_WORKFLOW else None
    seen_paths: set[str] = set()
    seen_slots: set[str] = set()
    recovered: list[tuple[dict[str, Any], Path, bytes | None, int | None]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != expected_entry_keys:
            raise ContextOSError(f"invalid journal entry {index}: {journal}")
        if type(entry.get("ordinal")) is not int or entry.get("ordinal") != index:
            raise ContextOSError(f"invalid journal entry ordinal {index}: {journal}")
        for key in ("slot", "path", "action"):
            if not isinstance(entry.get(key), str):
                raise ContextOSError(f"invalid journal entry {index}: {journal}")
        relative = entry["path"]
        slot = entry["slot"]
        if (
            slot != _transaction_slot(index, relative)
            or relative in seen_paths
            or slot in seen_slots
        ):
            raise ContextOSError(f"journal slot identity mismatch for {relative}")
        seen_paths.add(relative)
        seen_slots.add(slot)
        target = safe_repo_path(root, relative)
        if type(entry.get("existed")) is not bool:
            raise ContextOSError(f"invalid journal entry {index}: {journal}")
        mode = entry.get("mode")
        if mode is not None and (type(mode) is not int or not 0 <= mode <= 0o7777):
            raise ContextOSError(f"invalid journal entry {index}: {journal}")
        after_mode = entry.get("after_mode")
        if after_mode is not None and (
            type(after_mode) is not int or not 0 <= after_mode <= 0o7777
        ):
            raise ContextOSError(f"invalid journal after mode {index}: {journal}")
        for key in ("before_sha256_raw", "after_sha256_raw"):
            digest = entry.get(key)
            if digest is not None and (
                not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            ):
                raise ContextOSError(f"invalid journal entry {index}: {journal}")
        if entry.get("backup") is not None and not isinstance(
            entry.get("backup"), str
        ):
            raise ContextOSError(f"invalid journal entry {index}: {journal}")
        receipt_entry = entry.get("receipt_entry")
        if workflow == AGENT_LIFECYCLE_WORKFLOW:
            recovery_policy = {
                "contextos.workspace.json": ("write", "workspace-config", "managed"),
                "workspace.yaml": (
                    "delete",
                    "legacy-workspace-config",
                    "migration-only",
                ),
            }
            if relative not in recovery_policy:
                raise ContextOSError(f"journal path is not recoverable: {relative}")
            allowed_action, allowed_owner, allowed_policy = recovery_policy[relative]
            if (
                entry.get("action") != allowed_action
                or entry.get("owner") != allowed_owner
                or entry.get("policy") != allowed_policy
            ):
                raise ContextOSError(f"journal ownership mismatch: {relative}")
            expected_receipt_entry = {
                "action": allowed_action,
                "path": relative,
                "owner": allowed_owner,
                "policy": allowed_policy,
                "sha256_before_raw": entry.get("before_sha256_raw"),
                "sha256_after_raw": entry.get("after_sha256_raw"),
            }
        else:
            assert workspace is not None
            _validate_change_path(workspace, workflow, created_at, relative)
            if entry.get("action") != "write" or entry.get("owner") is not None or entry.get("policy") is not None:
                raise ContextOSError(f"invalid content journal entry: {relative}")
            expected_receipt_entry = receipt_entry
            if (
                not isinstance(receipt_entry, dict)
                or set(receipt_entry) != {"path", "sha256_before", "sha256_after"}
                or receipt_entry.get("path") != relative
            ):
                raise ContextOSError(f"invalid content receipt entry: {relative}")
            for key in ("sha256_before", "sha256_after"):
                digest = receipt_entry.get(key)
                if digest is not None and (
                    not isinstance(digest, str)
                    or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                ):
                    raise ContextOSError(f"invalid content receipt hash: {relative}")
        if receipt_entry != expected_receipt_entry:
            raise ContextOSError(f"journal receipt entry mismatch: {relative}")
        after_hash = entry.get("after_sha256_raw")
        if entry["action"] == "write":
            if not isinstance(after_hash, str) or type(after_mode) is not int:
                raise ContextOSError(f"journal after hash is invalid: {relative}")
        elif after_hash is not None or after_mode is not None:
            raise ContextOSError(f"journal delete after hash is invalid: {relative}")
        if entry["existed"]:
            backup_name = entry.get("backup")
            if backup_name != f"backups/{slot}.bin":
                raise ContextOSError(f"journal backup path is invalid: {relative}")
            backup = journal / backup_name
            _guard_local_artifact_path(root, backup)
            if _is_link_like(backup) or (backup.exists() and not backup.is_file()):
                raise ContextOSError(f"journal backup is not a regular file: {relative}")
            try:
                content = backup.read_bytes()
            except (OSError, UnicodeError) as exc:
                raise ContextOSError(
                    f"cannot read journal backup for {relative}: {exc}"
                ) from exc
            if sha256_bytes(content) != entry.get("before_sha256_raw"):
                raise ContextOSError(f"journal backup hash mismatch: {relative}")
            if type(mode) is not int:
                raise ContextOSError(f"journal mode is invalid: {relative}")
            if workflow != AGENT_LIFECYCLE_WORKFLOW:
                try:
                    logical_before = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
                except UnicodeDecodeError as exc:
                    raise ContextOSError(
                        f"content journal backup is not UTF-8: {relative}"
                    ) from exc
                if sha256_text(logical_before) != receipt_entry["sha256_before"]:
                    raise ContextOSError(
                        f"content journal logical before hash mismatch: {relative}"
                    )
        else:
            if entry.get("backup") is not None or entry.get("before_sha256_raw") is not None or mode is not None:
                raise ContextOSError(f"journal absence entry is invalid: {relative}")
            content = None
            mode = None
        if workflow != AGENT_LIFECYCLE_WORKFLOW:
            if content is None and receipt_entry["sha256_before"] is not None:
                raise ContextOSError(
                    f"content journal absence hash mismatch: {relative}"
                )
            if entry["after_sha256_raw"] != receipt_entry["sha256_after"]:
                raise ContextOSError(
                    f"content journal raw after hash mismatch: {relative}"
                )
        recovered.append((entry, target, content, mode))

    if workflow != AGENT_LIFECYCLE_WORKFLOW and manifest.get("invariants") != _content_invariants(
        workflow, [entry["receipt_entry"] for entry in entries]
    ):
        raise ContextOSError(f"invalid content transaction invariants: {journal}")

    receipt_relative = ensure_text(manifest.get("receipt"), "receipt")
    receipt_parts = PurePosixPath(receipt_relative).parts
    if (
        len(receipt_parts) != 3
        or receipt_parts[:2] != (".context-os", "receipts")
        or receipt_parts[2] != f"{manifest['proposal_id']}.json"
    ):
        raise ContextOSError(f"invalid journal receipt path: {receipt_relative}")
    receipt = root.joinpath(*receipt_parts)
    _guard_local_artifact_path(root, receipt)
    commit_path = journal / "commit.json"
    receipt_anchor = journal / "receipt.anchor"
    _guard_local_artifact_path(root, commit_path)
    _guard_local_artifact_path(root, receipt_anchor)
    receipt_present = receipt.exists() or receipt.is_symlink()
    foreign_receipt = False
    if receipt_present and allow_foreign_receipt_rollback:
        if _is_link_like(receipt) or not receipt.is_file():
            foreign_receipt = True
        elif (
            _is_link_like(commit_path)
            or not commit_path.is_file()
            or _is_link_like(receipt_anchor)
            or not receipt_anchor.is_file()
            or not _same_file(receipt, receipt_anchor)
        ):
            foreign_receipt = True
        else:
            candidate_commit = read_json(commit_path)
            foreign_receipt = (
                not isinstance(candidate_commit, dict)
                or candidate_commit.get("receipt_sha256_raw")
                != sha256_bytes(receipt_anchor.read_bytes())
            )
    if receipt_present and not foreign_receipt:
        if _is_link_like(receipt) or not receipt.is_file():
            raise ContextOSError(f"transaction receipt is not a regular file: {receipt}")
        if _is_link_like(commit_path) or not commit_path.is_file():
            raise ContextOSError(f"transaction receipt has no durable commit record: {receipt}")
        if (
            _is_link_like(receipt_anchor)
            or not receipt_anchor.is_file()
            or not _same_file(receipt, receipt_anchor)
        ):
            raise ContextOSError(
                f"transaction receipt does not match its durable anchor: {receipt}"
            )
        commit = read_json(commit_path)
        receipt_bytes = receipt_anchor.read_bytes()
        expected_commit = {
            "schema_version": SCHEMA_VERSION,
            "proposal_id": manifest["proposal_id"],
            "proposal_digest": manifest["proposal_digest"],
            "receipt_sha256_raw": sha256_bytes(receipt_bytes),
        }
        if commit != expected_commit:
            raise ContextOSError(f"transaction receipt commit hash mismatch: {receipt}")
        value = _json_object_from_bytes(receipt_bytes, source=str(receipt))
        expected_receipt_keys = {
            "schema_version",
            "proposal_id",
            "proposal_digest",
            "approval_evidence",
            "applied_at",
            "runtime",
            "runtime_identity",
            "files_changed",
            "git_head_before",
            "git_head_after",
            "invariants_checked",
        }
        if workflow == AGENT_LIFECYCLE_WORKFLOW:
            expected_receipt_keys.update(
                {"workflow", "operation", "confirmation", "authorization"}
            )
        expected_files = [entry["receipt_entry"] for entry in entries]
        if (
            set(value) != expected_receipt_keys
            or type(value.get("schema_version")) is not int
            or value.get("schema_version") != SCHEMA_VERSION
            or value.get("proposal_id") != manifest.get("proposal_id")
            or value.get("proposal_digest") != manifest.get("proposal_digest")
            or value.get("runtime_identity") != "self-reported"
            or not isinstance(value.get("runtime"), str)
            or value.get("approval_evidence")
            != "host-mediated confirmation; kernel does not authenticate the human approver"
            or value.get("files_changed") != expected_files
            or value.get("invariants_checked") != manifest.get("invariants")
            or not isinstance(value.get("applied_at"), str)
            or value.get("git_head_before") is not None
            and not isinstance(value.get("git_head_before"), str)
            or value.get("git_head_after") is not None
            and not isinstance(value.get("git_head_after"), str)
        ):
            raise ContextOSError(
                f"journal receipt is not a valid commit marker: {receipt}"
            )
        if workflow == AGENT_LIFECYCLE_WORKFLOW:
            evidence = manifest["agent_evidence"]
            expected_authorization = {
                **evidence["authorization"],
                "inputs": [
                    {"path": path, "sha256_raw": digest}
                    for path, digest in evidence["source_hashes"].items()
                ],
            }
            if (
                value.get("workflow") != AGENT_LIFECYCLE_WORKFLOW
                or value.get("operation") != WORKSPACE_MIGRATION_OPERATION
                or value.get("confirmation")
                != {"method": "exact-digest-echo", "human_authenticated": False}
                or value.get("authorization") != expected_authorization
            ):
                raise ContextOSError(
                    f"journal receipt is not a valid agent commit marker: {receipt}"
                )
        for entry, target, _content, _mode in recovered:
            if entry["action"] == "delete":
                if target.exists() or _is_link_like(target):
                    raise ContextOSError(
                        "committed transaction target was recreated after deletion: "
                        f"{target}; review it and remove it only if safe, then retry "
                        "the approved apply without deleting the journal"
                    )
                _fsync_directory(target.parent)
                continue
            publication_anchor = _validated_publication_anchor(
                root,
                journal,
                slot=entry["slot"],
                expected_hash=entry["after_sha256_raw"],
            )
            if publication_anchor is None:
                raise ContextOSError(
                    f"committed transaction has no publication anchor: {target}"
                )
            target_hash = raw_file_digest(target)
            target_mode = (
                target.stat().st_mode & 0o7777 if target.exists() else None
            )
            if (
                target_hash != entry["after_sha256_raw"]
                or target_mode != entry["after_mode"]
            ):
                raise ContextOSError(
                    "committed transaction target does not match receipt-bound "
                    f"bytes and mode: {target}; restore it from {publication_anchor} "
                    f"with mode {entry['after_mode']:#o}, then retry the approved "
                    "apply without deleting the journal"
                )
            _fsync_directory(target.parent)
        _fsync_directory(receipt.parent)
        if (
            sha256_bytes(receipt_anchor.read_bytes())
            != commit["receipt_sha256_raw"]
            or not _same_file(receipt, receipt_anchor)
        ):
            raise ContextOSError(
                f"transaction receipt changed during recovery validation: {receipt}"
            )
        _discard_agent_journal(root, journal)
        staging = root / ".context-os" / "staging" / manifest["proposal_id"]
        _guard_local_artifact_path(root, staging)
        _rmtree_readonly_artifacts(
            staging,
            ignore_errors=True,
        )
        return
    if commit_path.exists() or commit_path.is_symlink():
        if _is_link_like(commit_path) or not commit_path.is_file():
            raise ContextOSError(f"invalid transaction commit record: {commit_path}")
        commit = read_json(commit_path)
        if (
            not isinstance(commit, dict)
            or set(commit)
            != {"schema_version", "proposal_id", "proposal_digest", "receipt_sha256_raw"}
            or commit.get("schema_version") != SCHEMA_VERSION
            or commit.get("proposal_id") != manifest["proposal_id"]
            or commit.get("proposal_digest") != manifest["proposal_digest"]
            or not isinstance(commit.get("receipt_sha256_raw"), str)
            or re.fullmatch(r"[0-9a-f]{64}", commit["receipt_sha256_raw"]) is None
        ):
            raise ContextOSError(f"invalid transaction commit record: {commit_path}")
    for entry, target, content, mode in recovered:
        publication_anchor = _validated_publication_anchor(
            root,
            journal,
            slot=entry["slot"],
            expected_hash=entry["after_sha256_raw"],
        )
        forward_capture = _adopt_forward_capture(
            root,
            target,
            content,
            mode,
            entry["after_sha256_raw"],
            publication_anchor,
            journal=journal,
            slot=entry["slot"],
        )
        _restore_transaction_target(
            root,
            target,
            content,
            mode,
            entry["after_sha256_raw"],
            publication_anchor,
            work_dir=journal / "rollback",
            slot=entry["slot"],
        )
        if forward_capture is not None:
            target_digest = raw_file_digest(target)
            if (
                content is None
                or mode is None
                or target_digest != sha256_bytes(content)
                or target.stat().st_mode & 0o7777 != mode
            ):
                raise ContextOSError(
                    f"forward capture cannot be retired before exact restoration: {target}"
                )
            _unlink_readonly_artifact(forward_capture)
            _fsync_directory(forward_capture.parent)
    _discard_agent_journal(root, journal)
    staging = root / ".context-os" / "staging" / manifest["proposal_id"]
    _guard_local_artifact_path(root, staging)
    _rmtree_readonly_artifacts(
        staging,
        ignore_errors=True,
    )


def _recover_pending_agent_journals(root: Path) -> None:
    journals = root / ".context-os" / "journals"
    _guard_local_artifact_path(root, journals)
    if not journals.exists():
        return
    if not journals.is_dir():
        raise ContextOSError(".context-os/journals must be a directory")
    for journal in sorted(journals.iterdir(), key=lambda path: path.name.casefold()):
        if journal.is_symlink() or not journal.is_dir():
            raise ContextOSError(f"invalid agent transaction journal path: {journal}")
        if journal.name.startswith(".") and journal.name.endswith(
            (".building", ".discard")
        ):
            # Repository targets are never touched until a complete journal is
            # atomically promoted out of the build namespace.
            _rmtree_readonly_artifacts(journal)
            continue
        _recover_agent_journal(root, journal)


def _discard_agent_journal(root: Path, journal: Path) -> None:
    """Atomically move a completed journal into a disposable namespace."""
    _guard_local_artifact_path(root, journal)
    if not journal.exists():
        return
    disposable = journal.with_name(f".{journal.name}.discard")
    _guard_local_artifact_path(root, disposable)
    if disposable.exists():
        if disposable.is_symlink() or not disposable.is_dir():
            raise ContextOSError(f"invalid disposable journal path: {disposable}")
        _rmtree_readonly_artifacts(disposable)
    journal.rename(disposable)
    _fsync_directory(journal.parent)
    _rmtree_readonly_artifacts(
        disposable,
        ignore_errors=True,
    )
    _fsync_directory(journal.parent)


def _publish_exclusive(source: Path, destination: Path) -> None:
    """Create a no-clobber hard link; the caller owns durability and cleanup."""
    try:
        os.link(source, destination)
    except FileExistsError as exc:
        raise ContextOSError(
            f"refusing to overwrite concurrently created path: {destination}"
        ) from exc
    except OSError as exc:
        raise ContextOSError(
            "filesystem does not support atomic no-clobber publication for "
            f"{destination}: {exc}"
        ) from exc


def _prepare_publication_anchor(
    root: Path,
    journal: Path,
    source: Path,
    *,
    slot: str,
    expected_hash: str,
) -> Path:
    """Durably bind a write to an inode before publishing it to the workspace."""
    directory = journal / "publications"
    _guard_local_artifact_path(root, directory)
    directory.mkdir(parents=True, exist_ok=True)
    _fsync_directory(directory.parent)
    anchor = directory / f"{slot}.after"
    _guard_local_artifact_path(root, anchor)
    if anchor.exists() or anchor.is_symlink():
        raise ContextOSError(f"publication anchor already exists: {anchor}")
    _publish_exclusive(source, anchor)
    _fsync_directory(directory)
    if raw_file_digest(anchor) != expected_hash or not _same_file(source, anchor):
        raise ContextOSError(f"publication anchor identity mismatch: {anchor}")
    return anchor


def _validated_publication_anchor(
    root: Path,
    journal: Path,
    *,
    slot: str,
    expected_hash: str | None,
) -> Path | None:
    anchor = journal / "publications" / f"{slot}.after"
    _guard_local_artifact_path(root, anchor)
    present = anchor.exists() or _is_link_like(anchor)
    if expected_hash is None:
        if present:
            raise ContextOSError(f"unexpected publication anchor: {anchor}")
        return None
    if not present:
        return None
    if _is_link_like(anchor) or not anchor.is_file():
        raise ContextOSError(f"publication anchor is link-like or non-file: {anchor}")
    if raw_file_digest(anchor) != expected_hash:
        raise ContextOSError(f"publication anchor hash mismatch: {anchor}")
    return anchor


def _probe_rollback_publication(
    root: Path, target: Path, *, work_dir: Path, slot: str
) -> None:
    """Prove rollback hard-link support before the first repository mutation."""
    _guard_local_artifact_path(root, work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    _fsync_directory(work_dir.parent)
    probe = work_dir / f"{slot}.preflight"
    _guard_local_artifact_path(root, probe)
    if probe.exists() or probe.is_symlink():
        raise ContextOSError(f"rollback preflight artifact already exists for {target}")
    linked = False
    try:
        os.link(target, probe)
        linked = True
        if not _same_file(target, probe):
            raise ContextOSError(f"rollback preflight identity mismatch for {target}")
    except OSError as exc:
        raise ContextOSError(
            f"rollback publication is unsupported before mutating {target}: {exc}"
        ) from exc
    finally:
        if linked and (probe.exists() or probe.is_symlink()):
            _unlink_readonly_artifact(probe)
            _fsync_directory(probe.parent)


def _capture_transaction_before(
    root: Path,
    target: Path,
    expected_before: bytes,
    expected_mode: int,
    *,
    journal: Path,
    slot: str,
) -> Path:
    """Move a target into its durable forward slot and verify what was moved."""
    forward_dir = journal / "forward"
    _guard_local_artifact_path(root, forward_dir)
    forward_dir.mkdir(parents=True, exist_ok=True)
    _fsync_directory(forward_dir.parent)
    capture = forward_dir / f"{slot}.before"
    _guard_local_artifact_path(root, capture)
    if capture.exists() or capture.is_symlink():
        raise ContextOSError(f"forward transaction capture already exists for {target}")
    os.replace(target, capture)
    _fsync_directory(capture.parent)
    _fsync_directory(target.parent)
    if _is_link_like(capture) or not capture.is_file():
        raise ContextOSError(f"forward transaction captured a non-file target: {target}")
    captured = capture.read_bytes()
    captured_mode = capture.stat().st_mode & 0o7777
    if captured != expected_before or captured_mode != expected_mode:
        try:
            _publish_exclusive(capture, target)
            _fsync_directory(target.parent)
        except (OSError, ContextOSError) as exc:
            raise ContextOSError(
                f"unrecognized forward capture retained at {capture}; target also changed"
            ) from exc
        raise ContextOSError(
            f"unrecognized forward capture restored at {target}; journal retained for review"
        )
    return capture


def _adopt_forward_capture(
    root: Path,
    target: Path,
    before: bytes | None,
    mode: int | None,
    expected_after_hash: str | None,
    publication_anchor: Path | None,
    *,
    journal: Path,
    slot: str,
) -> Path | None:
    """Resume or validate the durable before-state captured during publication."""
    capture = journal / "forward" / f"{slot}.before"
    _guard_local_artifact_path(root, capture)
    if not (capture.exists() or capture.is_symlink()):
        return None
    if before is None or mode is None:
        raise ContextOSError(f"unexpected forward capture for absent target: {target}")
    if _is_link_like(capture) or not capture.is_file():
        raise ContextOSError(f"forward capture is link-like or non-file for {target}")
    if capture.read_bytes() != before or capture.stat().st_mode & 0o7777 != mode:
        raise ContextOSError(f"forward capture does not match journal backup: {target}")
    target_present = target.exists() or _is_link_like(target)
    if target_present and (_is_link_like(target) or not target.is_file()):
        raise ContextOSError(f"forward recovery found a non-file target: {target}")
    if not target_present:
        _publish_exclusive(capture, target)
        _fsync_directory(target.parent)
        _unlink_readonly_artifact(capture)
        _fsync_directory(capture.parent)
        return None
    target_digest = sha256_bytes(target.read_bytes())
    target_mode = target.stat().st_mode & 0o7777
    if target_digest == sha256_bytes(before) and target_mode == mode:
        _unlink_readonly_artifact(capture)
        _fsync_directory(capture.parent)
        return None
    if (
        target_digest != expected_after_hash
        or publication_anchor is None
        or not _same_file(target, publication_anchor)
    ):
        raise ContextOSError(
            f"forward target/capture ambiguity for {target}; both were retained"
        )
    return capture


def _restore_transaction_target(
    root: Path,
    target: Path,
    before: bytes | None,
    mode: int | None,
    expected_after_hash: str | None,
    publication_anchor: Path | None,
    *,
    work_dir: Path,
    slot: str,
) -> None:
    """Idempotently restore one path without overwriting a concurrent writer."""
    _guard_local_artifact_path(root, work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    local_root = root / ".context-os"
    current_directory = work_dir
    while current_directory != local_root:
        _fsync_directory(current_directory.parent)
        current_directory = current_directory.parent
    capture = work_dir / f"{slot}.current"
    restore = work_dir / f"{slot}.before"
    restore_building = work_dir / f".{slot}.before.building"
    probe = work_dir / f"{slot}.probe"
    _guard_local_artifact_path(root, capture)
    _guard_local_artifact_path(root, restore)
    _guard_local_artifact_path(root, restore_building)
    _guard_local_artifact_path(root, probe)

    before_hash = sha256_bytes(before) if before is not None else None

    def artifact_digest(path: Path, label: str) -> str | None:
        present = path.exists() or _is_link_like(path)
        if not present:
            return None
        if _is_link_like(path) or not path.is_file():
            raise ContextOSError(
                f"rollback {label} is link-like or non-file for {target}: {path}"
            )
        return sha256_bytes(path.read_bytes())

    def exact_before(path: Path, digest: str | None) -> bool:
        if before is None:
            return digest is None
        if digest != before_hash or not path.is_file():
            return False
        return mode is not None and path.stat().st_mode & 0o7777 == mode

    def remove_artifact(path: Path) -> None:
        if path.exists() or path.is_symlink():
            _unlink_readonly_artifact(path)
            _fsync_directory(path.parent)

    def publish(source: Path, *, remove_source: bool = True) -> None:
        _publish_exclusive(source, target)
        _fsync_directory(target.parent)
        if remove_source:
            _unlink_readonly_artifact(source)
            _fsync_directory(source.parent)

    if restore_building.exists() or _is_link_like(restore_building):
        if _is_link_like(restore_building) or not restore_building.is_file():
            raise ContextOSError(
                f"rollback restore build artifact is ambiguous for {target}: "
                f"{restore_building}"
            )
        _unlink_readonly_artifact(restore_building)
        _fsync_directory(restore_building.parent)

    def publish_before() -> None:
        if before is None:
            return
        restore_digest = artifact_digest(restore, "restore payload")
        if restore_digest is None:
            if mode is None:
                raise ContextOSError(f"rollback restore mode is missing for {target}")
            _write_exclusive_bytes(
                restore_building,
                before,
                root=root,
                mode=mode,
            )
            _publish_exclusive(restore_building, restore)
            _fsync_directory(restore.parent)
            _unlink_readonly_artifact(restore_building)
            _fsync_directory(restore_building.parent)
        elif not exact_before(restore, restore_digest):
            raise ContextOSError(f"rollback restore payload mismatch for {target}")
        publish(restore)

    if probe.exists() or probe.is_symlink():
        if (
            _is_link_like(probe)
            or not probe.is_file()
            or not target.is_file()
            or not _same_file(probe, target)
        ):
            raise ContextOSError(f"rollback capability probe is ambiguous for {target}")
        remove_artifact(probe)

    capture_digest = artifact_digest(capture, "capture")
    restore_digest = artifact_digest(restore, "restore payload")
    if restore_digest is not None and not exact_before(restore, restore_digest):
        raise ContextOSError(f"rollback restore payload mismatch for {target}")

    target_present = target.exists() or _is_link_like(target)
    if target_present and (_is_link_like(target) or not target.is_file()):
        raise ContextOSError(
            f"refusing rollback of a link-like or non-file target: {target}"
        )
    target_digest = sha256_bytes(target.read_bytes()) if target_present else None

    if capture_digest is not None:
        if not target_present:
            if capture_digest == expected_after_hash:
                if publication_anchor is None or not _same_file(
                    capture, publication_anchor
                ):
                    raise ContextOSError(
                        f"rollback capture has no publication ownership proof for {target}"
                    )
                if before is None:
                    remove_artifact(capture)
                else:
                    publish_before()
                    remove_artifact(capture)
                return
            if capture_digest == before_hash and before is not None:
                if mode is not None and capture.stat().st_mode & 0o7777 != mode:
                    raise ContextOSError(f"rollback capture mode mismatch for {target}")
                publish(capture)
                return
            try:
                publish(capture, remove_source=False)
            except (OSError, ContextOSError) as exc:
                raise ContextOSError(
                    f"concurrent edit retained at {capture}; target changed during rollback"
                ) from exc
            raise ContextOSError(
                f"unrecognized concurrent edit restored at {target}; rollback requires review"
            )

        if exact_before(target, target_digest):
            if capture_digest not in {before_hash, expected_after_hash}:
                raise ContextOSError(
                    f"unrecognized rollback capture retained for {target}: {capture}"
                )
            if (
                capture_digest == expected_after_hash
                and (
                    publication_anchor is None
                    or not _same_file(capture, publication_anchor)
                )
            ):
                raise ContextOSError(
                    f"rollback capture has no publication ownership proof for {target}"
                )
            remove_artifact(capture)
            remove_artifact(restore)
            return
        if _same_file(target, capture):
            raise ContextOSError(
                f"rollback target and capture remain unresolved for {target}"
            )
        raise ContextOSError(
            f"rollback target/capture ambiguity for {target}; both were retained"
        )

    if restore_digest is not None:
        if not target_present:
            publish(restore)
            return
        if exact_before(target, target_digest):
            remove_artifact(restore)
            return
        raise ContextOSError(
            f"rollback target/restore ambiguity for {target}; both were retained"
        )

    if not target_present:
        if expected_after_hash is None:
            publish_before()
            return
        if before is None:
            return
        raise ContextOSError(
            f"refusing rollback after an unrecognized concurrent delete: {target}"
        )

    if exact_before(target, target_digest):
        return
    if target_digest != expected_after_hash:
        raise ContextOSError(
            f"refusing to replace an unrecognized post-crash edit or concurrent edit at {target}"
        )
    if publication_anchor is None or not _same_file(target, publication_anchor):
        raise ContextOSError(
            f"refusing rollback without publication ownership proof at {target}"
        )

    try:
        os.link(target, probe)
        if not _same_file(target, probe):
            raise ContextOSError(f"rollback capability probe identity mismatch for {target}")
    except FileExistsError as exc:
        raise ContextOSError(f"rollback capability probe already exists for {target}") from exc
    except OSError as exc:
        raise ContextOSError(
            f"rollback publication is unsupported before moving {target}: {exc}"
        ) from exc
    remove_artifact(probe)
    os.replace(target, capture)
    _fsync_directory(capture.parent)
    _fsync_directory(target.parent)
    _restore_transaction_target(
        root,
        target,
        before,
        mode,
        expected_after_hash,
        publication_anchor,
        work_dir=work_dir,
        slot=slot,
    )


def apply_proposal(root: Path, proposal: Path, confirmation: str, runtime: str) -> tuple[Path, dict[str, Any]]:
    _guard_local_artifact_path(root, proposal)
    document = read_json(proposal)
    is_agent_workflow = document.get("workflow") == AGENT_LIFECYCLE_WORKFLOW
    if is_agent_workflow:
        workflow = AGENT_LIFECYCLE_WORKFLOW
    else:
        workflow, _ = _validate_proposal_shape(root, proposal, document)
    expected_digest = validate_proposal(document)
    if confirmation != expected_digest:
        raise ContextOSError("--confirm must exactly match the proposal_digest")
    validate_execution_runtime(root, runtime)
    with transaction_lock(root):
        # A completed crash journal has priority over every later lifecycle
        # operation, including generic content proposals.
        _recover_pending_agent_journals(root)
        if workflow == AGENT_LIFECYCLE_WORKFLOW:
            receipt_candidate = root / ".context-os" / "receipts" / proposal.name
            _guard_local_artifact_path(root, receipt_candidate)
            if receipt_candidate.exists() or receipt_candidate.is_symlink():
                raise ContextOSError(
                    f"refusing to replay proposal with existing receipt: {receipt_candidate}"
                )
            workflow, _ = _validate_proposal_shape(root, proposal, document)
            _validate_agent_preflight(root, document)
        else:
            workflow, created_at = _validate_proposal_shape(root, proposal, document)
            for change in document.get("changes", []):
                path = safe_repo_path(root, ensure_text(change.get("path"), "change.path"))
                if workflow == "setup" and path.exists() and _is_populated(path.read_text(encoding="utf-8")):
                    if change.get("replacement_approved") is not True:
                        raise ContextOSError(f"populated file lacks replacement approval: {change['path']}")
                if file_digest(path) != change.get("before_sha256"):
                    raise ContextOSError(f"refusing stale proposal; file changed: {change['path']}")
                if sha256_text(ensure_text(change.get("after_text"), "change.after_text")) != change.get("after_sha256"):
                    raise ContextOSError(f"proposal after hash is invalid: {change['path']}")
                expected_diff = _content_change_diff(
                    root,
                    change["path"],
                    change["after_text"],
                )
                if change["diff"] != expected_diff:
                    raise ContextOSError(
                        f"content proposal displayed diff is invalid: {change['path']}"
                    )
            _validate_content_semantics(
                root,
                workflow,
                created_at,
                document["changes"],
            )
        head_before = git_head(root)
        applied = []
        backups: dict[Path, bytes | None] = {}
        backup_modes: dict[Path, int | None] = {}
        rollback_slots: dict[Path, str] = {}
        staged: dict[Path, Path] = {}
        publication_anchors: dict[Path, Path] = {}
        journal_path: Path | None = None
        receipt_published = False
        staging_root = root / ".context-os" / "staging" / document["proposal_id"]
        receipt_path = root / ".context-os" / "receipts" / f"{document['proposal_id']}.json"
        _guard_local_artifact_path(root, staging_root)
        _guard_local_artifact_path(root, receipt_path)
        if receipt_path.exists() or receipt_path.is_symlink():
            raise ContextOSError(f"refusing to overwrite existing receipt: {receipt_path}")
        receipt: dict[str, Any]
        try:
            if staging_root.exists():
                if staging_root.is_symlink() or not staging_root.is_dir():
                    raise ContextOSError(
                        f"invalid transaction staging path: {staging_root}"
                    )
                _rmtree_readonly_artifacts(
                    staging_root,
                )
            staging_root.mkdir(parents=True)
            for change_index, change in enumerate(document["changes"]):
                path = safe_repo_path(root, change["path"])
                backups[path] = path.read_bytes() if path.exists() else None
                backup_modes[path] = (
                    path.stat().st_mode & 0o7777 if path.exists() else None
                )
                rollback_slots[path] = _transaction_slot(change_index, change["path"])
                if change.get("action", "write") == "write":
                    stage = staging_root / change["path"]
                    _guard_local_artifact_path(root, stage)
                    target_mode = (
                        change["after_mode"]
                        if workflow == AGENT_LIFECYCLE_WORKFLOW
                        else backup_modes[path]
                        if backup_modes[path] is not None
                        else NEW_CONTENT_MODE
                    )
                    _write_exclusive_bytes(
                        stage,
                        change["after_text"].encode("utf-8"),
                        root=root,
                        mode=target_mode,
                    )
                    staged[path] = stage
            journal_path = (
                root / ".context-os" / "journals" / document["proposal_id"]
            )
            _create_agent_journal(
                root, document, backups, backup_modes, receipt_path
            )
            for change in document["changes"]:
                if change.get("action", "write") != "write":
                    continue
                path = safe_repo_path(root, change["path"])
                expected_after_raw = (
                    change["after_raw_sha256"]
                    if workflow == AGENT_LIFECYCLE_WORKFLOW
                    else sha256_bytes(change["after_text"].encode("utf-8"))
                )
                publication_anchors[path] = _prepare_publication_anchor(
                    root,
                    journal_path,
                    staged[path],
                    slot=rollback_slots[path],
                    expected_hash=expected_after_raw,
                )
            for path, before in backups.items():
                if before is not None:
                    _probe_rollback_publication(
                        root,
                        path,
                        work_dir=journal_path / "preflight",
                        slot=rollback_slots[path],
                    )
            if workflow == AGENT_LIFECYCLE_WORKFLOW:
                # Staging and journal construction are fallible and may take
                # long enough for an uncoordinated source edit. Rebind every
                # source and target immediately before the first mutation.
                _validate_agent_preflight(root, document)
            for change in document["changes"]:
                path = safe_repo_path(root, change["path"])
                if workflow == AGENT_LIFECYCLE_WORKFLOW:
                    if raw_file_digest(path) != change["before_raw_sha256"]:
                        raise ContextOSError(
                            f"refusing target changed during apply: {change['path']}"
                        )
                elif file_digest(path) != change.get("before_sha256"):
                    raise ContextOSError(f"refusing target changed during apply: {change['path']}")
                before = backups[path]
                if before is not None:
                    before_mode = backup_modes[path]
                    if before_mode is None:
                        raise ContextOSError(
                            f"transaction backup mode is missing: {change['path']}"
                        )
                    _capture_transaction_before(
                        root,
                        path,
                        before,
                        before_mode,
                        journal=journal_path,
                        slot=rollback_slots[path],
                    )
                if change.get("action", "write") == "delete":
                    if workflow != AGENT_LIFECYCLE_WORKFLOW:
                        raise ContextOSError(
                            f"content lifecycle cannot delete paths: {change['path']}"
                        )
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    _publish_exclusive(publication_anchors[path], path)
                if workflow == AGENT_LIFECYCLE_WORKFLOW:
                    # Record the successful mutation before any fallible
                    # verification so in-process rollback covers it, while a
                    # failed no-clobber create does not claim another writer's
                    # destination as ours.
                    applied.append({
                        "action": change["action"],
                        "path": change["path"],
                        "owner": change["authorization"]["owner"],
                        "policy": change["authorization"]["policy"],
                        "sha256_before_raw": change["before_raw_sha256"],
                        "sha256_after_raw": change["after_raw_sha256"],
                    })
                    if raw_file_digest(path) != change["after_raw_sha256"]:
                        raise ContextOSError(
                            f"agent-config post-write hash is invalid: {change['path']}"
                        )
                    expected_mode = change["after_mode"]
                    if (
                        change["action"] == "write"
                        and path.stat().st_mode & 0o7777 != expected_mode
                    ):
                        raise ContextOSError(
                            f"agent-config post-write mode is invalid: {change['path']}"
                        )
                else:
                    expected_after_raw = sha256_bytes(
                        change["after_text"].encode("utf-8")
                    )
                    content_snapshot = _read_regular_file_snapshot(path)
                    try:
                        logical_snapshot = content_snapshot.decode("utf-8").replace(
                            "\r\n", "\n"
                        ).replace("\r", "\n")
                    except UnicodeDecodeError as exc:
                        raise ContextOSError(
                            f"content post-write bytes are not UTF-8: {change['path']}"
                        ) from exc
                    if (
                        sha256_bytes(content_snapshot) != expected_after_raw
                        or sha256_text(logical_snapshot) != change["after_sha256"]
                    ):
                        raise ContextOSError(
                            f"content post-write hash is invalid: {change['path']}"
                        )
                    expected_mode = (
                        backup_modes[path]
                        if backup_modes[path] is not None
                        else NEW_CONTENT_MODE
                    )
                    if path.stat().st_mode & 0o7777 != expected_mode:
                        raise ContextOSError(
                            f"content post-write mode is invalid: {change['path']}"
                        )
                    applied.append({
                        "path": change["path"],
                        "sha256_before": change["before_sha256"],
                        "sha256_after": change["after_sha256"],
                    })
                _fsync_directory(path.parent)
            receipt = {
                "schema_version": SCHEMA_VERSION,
                "proposal_id": document["proposal_id"],
                "proposal_digest": expected_digest,
                "approval_evidence": "host-mediated confirmation; kernel does not authenticate the human approver",
                "applied_at": utc_now().isoformat(),
                "runtime": runtime,
                "runtime_identity": "self-reported",
                "files_changed": applied,
                "git_head_before": head_before,
                "git_head_after": git_head(root),
                "invariants_checked": (
                    list(AGENT_MIGRATION_INVARIANTS)
                    if workflow == AGENT_LIFECYCLE_WORKFLOW
                    else _content_invariants(workflow, document["changes"])
                ),
            }
            if workflow == AGENT_LIFECYCLE_WORKFLOW:
                receipt.update({
                    "workflow": workflow,
                    "operation": document["operation"],
                    "confirmation": {
                        "method": "exact-digest-echo",
                        "human_authenticated": False,
                    },
                    "authorization": {
                        **document["authorization"],
                        "inputs": [
                            {"path": path, "sha256_raw": digest}
                            for path, digest in document["source_hashes"].items()
                        ],
                    },
                })
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            _fsync_directory(receipt_path.parent.parent)
            receipt_stage = staging_root / "receipt.json"
            _write_exclusive_text(
                receipt_stage,
                json.dumps(receipt, indent=2) + "\n",
                root=root,
            )
            receipt_bytes = receipt_stage.read_bytes()
            commit_path = journal_path / "commit.json"
            _write_exclusive_text(
                commit_path,
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "proposal_id": document["proposal_id"],
                        "proposal_digest": expected_digest,
                        "receipt_sha256_raw": sha256_bytes(receipt_bytes),
                    },
                    indent=2,
                )
                + "\n",
                root=root,
            )
            receipt_anchor = journal_path / "receipt.anchor"
            _publish_exclusive(receipt_stage, receipt_anchor)
            _fsync_directory(journal_path)
            if receipt_path.exists() or receipt_path.is_symlink():
                raise ContextOSError(f"refusing to overwrite existing receipt: {receipt_path}")
            _publish_exclusive(receipt_anchor, receipt_path)
            receipt_published = True
            _fsync_directory(receipt_path.parent)
            if (
                _is_link_like(receipt_path)
                or not receipt_path.is_file()
                or sha256_bytes(receipt_anchor.read_bytes())
                != sha256_bytes(receipt_bytes)
                or not _same_file(receipt_path, receipt_anchor)
            ):
                raise ContextOSError(
                    f"receipt changed before transaction commit: {receipt_path}"
                )
            try:
                _discard_agent_journal(root, journal_path)
            except (OSError, ContextOSError):
                # Receipt publication is the commit point. A retained valid
                # journal is safe: the next apply validates the exact receipt
                # commit hash and retires the journal.
                pass
        except Exception as exc:
            if receipt_published:
                raise ContextOSError(
                    "apply reached the receipt commit point; state and recovery "
                    f"artifacts were retained after a durability error: {exc}"
                ) from exc
            rollback_errors = []
            if journal_path is not None and journal_path.is_dir():
                try:
                    _recover_agent_journal(
                        root,
                        journal_path,
                        allow_foreign_receipt_rollback=True,
                    )
                except (OSError, ContextOSError) as rollback_exc:
                    rollback_errors.append(str(rollback_exc))
            if rollback_errors:
                raise ContextOSError(
                    f"apply failed and rollback was incomplete ({'; '.join(rollback_errors)}): {exc}"
                ) from exc
            if journal_path is not None and journal_path.exists():
                _discard_agent_journal(root, journal_path)
                building = journal_path.with_name(f".{journal_path.name}.building")
                _rmtree_readonly_artifacts(
                    building,
                    ignore_errors=True,
                )
            if isinstance(exc, ContextOSError):
                if applied:
                    raise ContextOSError(
                        f"apply failed; staged writes were rolled back: {exc}"
                    ) from exc
                raise
            raise ContextOSError(f"apply failed; staged writes were rolled back: {exc}") from exc
        finally:
            _rmtree_readonly_artifacts(
                staging_root,
                ignore_errors=True,
            )
        return receipt_path, receipt


def runtime_ids(root: Path) -> list[str]:
    runtimes_dir = root / "runtimes"
    if _is_link_like(runtimes_dir):
        raise ContextOSError(
            f"runtime registry must not be a symlink or reparse point: {runtimes_dir}"
        )
    if not runtimes_dir.exists():
        return []
    if not runtimes_dir.is_dir():
        raise ContextOSError(f"runtime registry must be a directory: {runtimes_dir}")
    identifiers = []
    for path in runtimes_dir.glob("*.json"):
        if path.name == "schema.json":
            continue
        if _is_link_like(path):
            raise ContextOSError(
                f"runtime manifest must not be a symlink or reparse point: {path}"
            )
        if not path.is_file():
            raise ContextOSError(f"runtime manifest must be a regular file: {path}")
        identifiers.append(path.stem)
    identifiers.sort()
    if len(identifiers) != len({identifier.casefold() for identifier in identifiers}):
        raise ContextOSError("runtime manifest filenames collide when case-folded")
    return identifiers


def runtime_manifest(
    root: Path, runtime: str, *, check_paths: bool = True
) -> dict[str, Any]:
    """Load a runtime and its required core component contract.

    ``check_paths=False`` skips maintainer evidence/path existence checks, but
    structural component and ownership validation remains an operational
    invariant for hooks and proposal application.
    """
    if not isinstance(runtime, str) or runtime == "generic" or not RUNTIME_ID_RE.fullmatch(runtime):
        raise ContextOSError(f"invalid runtime id: {runtime}")
    manifest_path = safe_repo_path(root, f"runtimes/{runtime}.json")
    if not manifest_path.exists():
        raise ContextOSError(f"missing runtime manifest: {manifest_path}")
    manifest = read_json(manifest_path)
    try:
        validate_runtime_manifest(
            manifest, runtime_id=runtime, root=root, check_paths=check_paths
        )
        component_path = safe_repo_path(root, "components/manifest.json")
        components = load_component_manifest(
            component_path, root=root, check_paths=False
        )
        selected = set(component_closure(components, manifest["components"]))
        owners = component_owners(components)
        required_paths = {
            f"runtimes/{runtime}.json",
            manifest["onboarding_doc"],
        }
        for surface in manifest["surfaces"].values():
            required_paths.update(surface["conformance_tests"])
            required_paths.update(
                source["path"]
                for source in surface["instruction_sources"] + surface["skill_sources"]
                if source["scope"] == "repository"
            )
        required_paths.update(
            source["location"]
            for source in manifest["evidence"]["sources"]
            if source["type"] == "conformance"
        )
        for required_path in sorted(required_paths):
            required_identity = portable_path_identity(required_path.rstrip("/"))
            matching_owners = {
                owner for owned_path, owner in owners.items()
                if portable_path_identity(owned_path) == required_identity
                or portable_path_identity(owned_path).startswith(required_identity + "/")
            }
            if not matching_owners:
                raise ComponentManifestError(
                    f"runtime {runtime!r} references unowned path {required_path!r}"
                )
            if not matching_owners.intersection(selected):
                raise ComponentManifestError(
                    f"runtime {runtime!r} requires {required_path!r}, owned only by "
                    f"unselected components {sorted(matching_owners)!r}"
                )
    except (RuntimeManifestError, ComponentManifestError, OSError, UnicodeError) as exc:
        raise ContextOSError(f"invalid runtime manifest: {manifest_path} ({exc})") from exc
    return manifest


def validate_execution_runtime(root: Path, runtime: str) -> None:
    if runtime != "generic":
        runtime_manifest(root, runtime, check_paths=False)


def runtime_registry(root: Path) -> dict[str, dict[str, Any]]:
    return {runtime: runtime_manifest(root, runtime) for runtime in runtime_ids(root)}


def runtime_surface(manifest: dict[str, Any], surface_id: str | None = None) -> dict[str, Any]:
    surfaces = manifest.get("surfaces", {})
    if surface_id is not None and surface_id not in surfaces:
        raise ContextOSError(
            f"runtime {manifest.get('runtime', 'unknown')} has no surface {surface_id!r}"
        )
    selected = surface_id or ("cli" if "cli" in surfaces else None)
    if selected is None and len(surfaces) == 1:
        selected = next(iter(surfaces))
    if selected not in surfaces:
        raise ContextOSError(
            f"runtime {manifest.get('runtime', 'unknown')} requires an explicit surface"
        )
    return surfaces[selected]


def runtime_hook_payload(
    manifest: dict[str, Any], messages: list[str], surface_id: str | None = None
) -> dict[str, str] | None:
    hook_output = runtime_surface(manifest, surface_id).get("hook_output")
    return render_hook_payload(hook_output, messages)


def render_hook_payload(
    hook_output: str | None, messages: list[str]
) -> dict[str, str] | None:
    message = "\n".join(messages)
    if hook_output is None:
        return None
    if hook_output == "system-message":
        return {"systemMessage": message} if message else None
    return {"action": "allow", "message": message}


def _state_freshness(path: Path, today: date, threshold: int) -> dict[str, Any]:
    updated = None
    age = None
    if path.exists():
        try:
            match = LAST_UPDATED_RE.search(path.read_text(encoding="utf-8"))
            if match and REAL_DATE_RE.fullmatch(match.group(1).strip()):
                candidate = match.group(1).strip()
                parsed = datetime.strptime(candidate, "%Y-%m-%d").date()
                updated = candidate
                age = (today - parsed).days
        except (OSError, UnicodeError, ValueError):
            # Diagnostics and advisory hooks must report unreadable or invalid
            # state as unknown rather than crashing on the file they diagnose.
            pass
    if not path.exists():
        status = "missing"
    elif age is None:
        status = "unknown"
    elif age < 0:
        status = "future"
    elif age > threshold:
        status = "stale"
    else:
        status = "fresh"
    return {
        "exists": path.exists(),
        "last_updated": updated,
        "age_days": age,
        "stale_after_days": threshold,
        "freshness_status": status,
        "stale": None if age is None or age < 0 else age > threshold,
    }


def _is_initialized(workspace: Workspace, today: date | None = None) -> bool:
    """Single readiness predicate shared by start, doctor, and the session hook.

    Only current.md gates readiness. weekly-priorities.md and blockers.md are
    legitimately left at their shipped template by users who have neither, so
    requiring a real date on all three would report an initialized workspace as
    needing setup forever. Their freshness is still reported separately.
    """
    current = workspace.state_dir / INITIALIZATION_FILE
    freshness = _state_freshness(
        current,
        today if today is not None else utc_now().date(),
        STATE_THRESHOLDS[INITIALIZATION_FILE],
    )
    return freshness["freshness_status"] in {"fresh", "stale"}


def _initialization_state(
    workspace: Workspace, today: date
) -> tuple[bool, dict[str, dict[str, Any]]]:
    state = {
        relative_path(workspace.root, workspace.state_dir / filename): _state_freshness(
            workspace.state_dir / filename, today, threshold
        )
        for filename, threshold in STATE_THRESHOLDS.items()
    }
    return _is_initialized(workspace, today), state


def start_report(root: Path, now: datetime) -> dict[str, Any]:
    workspace = load_workspace(root)
    initialized, files = _initialization_state(workspace, now.date())
    sessions = sorted(workspace.sessions_dir.glob("????-??-??.md"), reverse=True) if workspace.sessions_dir.exists() else []
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "initialized": initialized,
        "next_action": None if initialized else SETUP_NEXT_ACTION,
        "state": files,
        "latest_session": relative_path(root, sessions[0]) if sessions else None,
        "task_file": relative_path(root, workspace.task_file),
        "git_head": git_head(root),
    }


def _guard_local_state_path(root: Path, path: Path) -> None:
    current = root
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ContextOSError(f"local state path escapes workspace: {path}") from exc
    for part in relative.parts:
        current /= part
        if _is_link_like(current):
            raise ContextOSError(
                "local state path must not traverse a symlink or reparse point: "
                f"{relative.as_posix()}"
            )


def _local_json(path: Path, *, root: Path) -> dict[str, Any]:
    _guard_local_state_path(root, path)
    try:
        raw = path.read_text(encoding="utf-8")
        value = strict_json_loads(raw, source=path.name)
    except (OSError, UnicodeError, WorkspaceConfigError) as exc:
        raise ContextOSError(f"cannot read local state {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContextOSError(f"local state {path} must contain a JSON object")
    return value


def _host_entry(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {
        "installed_at", "source_manifest_sha256"
    }:
        raise ContextOSError(
            f"{field} must contain exactly installed_at and source_manifest_sha256"
        )
    installed_at = value.get("installed_at")
    source = value.get("source_manifest_sha256")
    if not isinstance(installed_at, str) or not installed_at.strip():
        raise ContextOSError(f"{field}.installed_at must be a non-empty string")
    if not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{64}", source):
        raise ContextOSError(f"{field}.source_manifest_sha256 must be a SHA-256 digest")
    return {"installed_at": installed_at, "source_manifest_sha256": source}


def _read_hosts_state(root: Path) -> dict[str, Any]:
    path = root / ".context-os" / "hosts.json"
    _guard_local_state_path(root, path)
    if not path.exists() and not _is_link_like(path):
        return {"schema_version": HOST_STATE_SCHEMA_VERSION, "hosts": {}}
    value = _local_json(path, root=root)
    if set(value) != {"schema_version", "hosts"}:
        raise ContextOSError("hosts.json must contain exactly schema_version and hosts")
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != HOST_STATE_SCHEMA_VERSION
    ):
        raise ContextOSError(
            f"hosts.json schema_version must equal {HOST_STATE_SCHEMA_VERSION}"
        )
    raw_hosts = value.get("hosts")
    if not isinstance(raw_hosts, dict):
        raise ContextOSError("hosts.json hosts must be an object")
    hosts: dict[str, dict[str, str]] = {}
    for runtime, raw_entry in raw_hosts.items():
        if (
            not isinstance(runtime, str)
            or not RUNTIME_ID_RE.fullmatch(runtime)
            or runtime in {"auto", "generic", "none"}
        ):
            raise ContextOSError(f"hosts.json contains invalid runtime id {runtime!r}")
        hosts[runtime] = _host_entry(raw_entry, f"hosts.{runtime}")
    return {
        "schema_version": HOST_STATE_SCHEMA_VERSION,
        "hosts": {runtime: hosts[runtime] for runtime in sorted(hosts)},
    }


def _read_legacy_runtime_state(root: Path) -> tuple[str, dict[str, str]] | None:
    path = root / ".context-os" / "runtime.json"
    _guard_local_state_path(root, path)
    if not path.exists() and not _is_link_like(path):
        return None
    value = _local_json(path, root=root)
    allowed = {
        "schema_version", "runtime", "installed_at",
        "source_manifest_sha256", "next_steps",
    }
    required = allowed - {"next_steps"}
    if not required.issubset(value) or set(value) - allowed:
        raise ContextOSError(
            "runtime.json has unsupported or missing legacy fields"
        )
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ContextOSError("runtime.json schema_version must equal 1")
    runtime = value.get("runtime")
    if (
        not isinstance(runtime, str)
        or not RUNTIME_ID_RE.fullmatch(runtime)
        or runtime in {"auto", "generic", "none"}
    ):
        raise ContextOSError("runtime.json runtime must be a lowercase runtime id")
    if "next_steps" in value and (
        not isinstance(value["next_steps"], list)
        or any(not isinstance(item, str) for item in value["next_steps"])
    ):
        raise ContextOSError("runtime.json next_steps must be an array of strings")
    return runtime, _host_entry(
        {
            "installed_at": value.get("installed_at"),
            "source_manifest_sha256": value.get("source_manifest_sha256"),
        },
        "runtime.json",
    )


def _hosts_with_legacy(root: Path) -> tuple[dict[str, Any], str | None]:
    state = _read_hosts_state(root)
    legacy = _read_legacy_runtime_state(root)
    if legacy is None:
        return state, None
    runtime, entry = legacy
    existing = state["hosts"].get(runtime)
    if existing is not None and existing != entry:
        raise ContextOSError(
            f"runtime.json conflicts with hosts.json entry for {runtime!r}"
        )
    state["hosts"][runtime] = entry
    state["hosts"] = {
        runtime_id: state["hosts"][runtime_id]
        for runtime_id in sorted(state["hosts"])
    }
    return state, runtime


def _render_hosts_state(state: dict[str, Any]) -> str:
    return json.dumps(state, indent=2, ensure_ascii=False) + "\n"


@contextmanager
def host_state_lock(root: Path) -> Iterator[None]:
    lock = root / ".context-os" / "hosts.lock"
    _guard_local_state_path(root, lock)
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ContextOSError(
            f"another local host-state update is active or left a stale lock: {lock}"
        ) from exc
    try:
        try:
            os.write(descriptor, f"pid={os.getpid()}\n".encode())
        finally:
            os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def _migrate_legacy_runtime_state_unlocked(
    root: Path,
) -> tuple[Path, dict[str, Any], bool, str | None]:
    target = root / ".context-os" / "hosts.json"
    state, migrated_runtime = _hosts_with_legacy(root)
    wanted = _render_hosts_state(state)
    current = None
    if target.exists() or target.is_symlink():
        _guard_local_state_path(root, target)
        try:
            current = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ContextOSError(f"cannot read local state {target}: {exc}") from exc
    host_state_changed = current != wanted and (
        current is not None or migrated_runtime is not None
    )
    if host_state_changed:
        try:
            write_generated_file(target, wanted, root=root)
        except (ComponentManifestError, OSError) as exc:
            raise ContextOSError(f"cannot write local host state: {exc}") from exc
    if migrated_runtime is not None:
        legacy_path = root / ".context-os" / "runtime.json"
        try:
            legacy_path.unlink()
        except OSError as exc:
            raise ContextOSError(
                "local host state is authoritative, but legacy runtime.json "
                f"cleanup failed: {exc}"
            ) from exc
    changed = host_state_changed or migrated_runtime is not None
    return target, state, changed, migrated_runtime


def migrate_legacy_runtime_state(
    root: Path,
) -> tuple[Path, dict[str, Any], bool, str | None]:
    with host_state_lock(root):
        return _migrate_legacy_runtime_state_unlocked(root)


def install_runtime(root: Path, runtime: str) -> tuple[Path, dict[str, Any]]:
    manifest = runtime_manifest(root, runtime)
    with host_state_lock(root):
        _, _, _, migrated_runtime = _migrate_legacy_runtime_state_unlocked(root)
        state = _read_hosts_state(root)
        source = sha256_text(canonical_json(manifest))
        existing = state["hosts"].get(runtime)
        if existing is not None and existing["source_manifest_sha256"] == source:
            installed_at = existing["installed_at"]
        else:
            installed_at = utc_now().isoformat()
        state["hosts"][runtime] = {
            "installed_at": installed_at,
            "source_manifest_sha256": source,
        }
        state["hosts"] = {
            runtime_id: state["hosts"][runtime_id]
            for runtime_id in sorted(state["hosts"])
        }
        target = root / ".context-os" / "hosts.json"
        wanted = _render_hosts_state(state)
        current = None
        if target.exists() or target.is_symlink():
            _guard_local_state_path(root, target)
            try:
                current = target.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise ContextOSError(f"cannot read local host state: {exc}") from exc
        host_state_changed = current != wanted
        if host_state_changed:
            try:
                write_generated_file(target, wanted, root=root)
            except (ComponentManifestError, OSError) as exc:
                raise ContextOSError(f"cannot write local host state: {exc}") from exc
    local = {
        "schema_version": HOST_STATE_SCHEMA_VERSION,
        "runtime": runtime,
        "installed_at": installed_at,
        "source_manifest_sha256": source,
        "next_steps": manifest.get("install", {}).get("next_steps", []),
        "legacy_runtime_migrated": migrated_runtime,
        "legacy_runtime_retained": False,
        "host_state_changed": host_state_changed,
    }
    return target, local


def doctor(
    root: Path,
    runtime: str | None = None,
    *,
    all_runtimes: bool = False,
    today: date | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    if runtime is not None and all_runtimes:
        raise ContextOSError("doctor runtime selection and --all are mutually exclusive")

    checks: list[dict[str, str]] = []
    effective_today = today or utc_now().date()

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    git_location = shutil.which("git")
    add("command:git", "pass" if git_location else "fail", git_location or "not found")
    add("command:python", "pass", sys.executable)

    workspace_source = "invalid"
    configured_agents: tuple[str, ...] | None = None
    workspace_valid = False
    try:
        workspace_resolution = resolve_workspace(root)
        workspace = workspace_resolution.workspace
        workspace_source = workspace_resolution.source
        configured_agents = workspace_resolution.agents
        workspace_valid = True
        workspace_status = (
            "pass"
            if workspace_resolution.source == "json" and not workspace_resolution.notices
            else "warn"
        )
        detail = workspace_resolution.source
        if workspace_resolution.notices:
            detail += "; " + "; ".join(
                notice["message"] for notice in workspace_resolution.notices
            )
        add("workspace-config", workspace_status, detail)
    except ContextOSError as exc:
        add("workspace-config", "fail", str(exc))
        # Keep diagnostics total even when the default path itself is the
        # malformed link that made workspace resolution fail.
        workspace = Workspace(
            root=root,
            state_dir=root / DEFAULT_PATHS["state_dir"],
            sessions_dir=root / DEFAULT_PATHS["sessions_dir"],
            task_file=root / DEFAULT_PATHS["task_file"],
        )

    # Provider-specific instruction files belong to their runtime components,
    # not the neutral core readiness gate.
    required_paths = [
        workspace.state_dir / "current.md",
        workspace.state_dir / "current-log.md",
        workspace.state_dir / "decisions.md",
    ]
    freshness_paths = [
        workspace.state_dir / filename for filename in STATE_THRESHOLDS
    ]
    state_path_errors: dict[Path, str] = {}
    for path in dict.fromkeys([*required_paths, *freshness_paths]):
        try:
            _guard_local_state_path(root, path)
        except ContextOSError as exc:
            state_path_errors[path] = str(exc)
    for path in required_paths:
        rel = path.relative_to(root).as_posix()
        error = state_path_errors.get(path)
        add(
            f"file:{rel}",
            "fail" if error else "pass" if path.exists() else "warn",
            error or rel,
        )
    unsafe_freshness = [
        path.relative_to(root).as_posix()
        for path in freshness_paths
        if path in state_path_errors
    ]
    gate = (workspace.state_dir / INITIALIZATION_FILE).relative_to(root).as_posix()
    if unsafe_freshness:
        add(
            "initialization-state",
            "warn",
            "guided setup required; unsafe state path(s): "
            + ", ".join(unsafe_freshness),
        )
        add(
            "state-freshness",
            "warn",
            "cannot inspect unsafe state path(s): " + ", ".join(unsafe_freshness),
        )
    else:
        initialized, initialization_files = _initialization_state(
            workspace, effective_today
        )
        add(
            "initialization-state",
            "pass" if initialized else "warn",
            "ready"
            if initialized
            else f"guided setup required; {gate} carries no real **Last Updated:** date",
        )
        unresolved = [
            path
            for path, item in initialization_files.items()
            if item["freshness_status"] in {"missing", "unknown", "future"}
        ]
        add(
            "state-freshness",
            "pass" if not unresolved else "warn",
            "all tracked state files carry a real date"
            if not unresolved
            else f"no usable **Last Updated:** date in: {', '.join(unresolved)}",
        )

    local_hosts = {"schema_version": HOST_STATE_SCHEMA_VERSION, "hosts": {}}
    local_hosts_valid = False
    legacy_runtime: str | None = None
    try:
        local_hosts, legacy_runtime = _hosts_with_legacy(root)
        local_hosts_valid = True
        local_detail = f"{len(local_hosts['hosts'])} configured host(s)"
        if legacy_runtime is not None:
            local_detail += (
                f"; legacy runtime.json for {legacy_runtime!r} is readable but retained; "
                "run bash scripts/contextos.sh workspace migrate-local-runtime"
            )
        add("local-host-state", "warn" if legacy_runtime else "pass", local_detail)
    except ContextOSError as exc:
        add("local-host-state", "fail", str(exc))

    try:
        registry_ids = runtime_ids(root)
    except ContextOSError as exc:
        registry_ids = []
        add("manifest-registry", "fail", str(exc))

    if all_runtimes:
        scope = "maintainer-all"
        validation_ids = list(registry_ids)
    elif runtime is not None:
        scope = "runtime"
        validation_ids = [runtime]
    elif workspace_valid and configured_agents is not None:
        scope = "profile"
        validation_ids = list(configured_agents)
    elif not workspace_valid:
        scope = "invalid"
        validation_ids = []
    else:
        scope = "legacy"
        configured_hosts = list(local_hosts["hosts"])
        validation_ids = (
            configured_hosts if len(configured_hosts) == 1 else list(registry_ids)
        )

    if not registry_ids and not (scope == "profile" and not validation_ids):
        if not any(item["name"] == "manifest-registry" for item in checks):
            add("manifest-registry", "fail", "no runtime descriptors found")
    elif not any(item["name"] == "manifest-registry" for item in checks):
        add(
            "manifest-registry",
            "pass",
            f"{len(registry_ids)} shipped descriptor(s); {len(validation_ids)} in validation scope",
        )

    component_inventory: dict[str, Any] | None = None
    try:
        component_path = safe_repo_path(root, "components/manifest.json")
        component_inventory = load_component_manifest(
            component_path, root=root, check_paths=False
        )
        add("component-inventory", "pass", "structurally valid")
    except (ContextOSError, ComponentManifestError, OSError, UnicodeError) as exc:
        add("component-inventory", "fail", str(exc))

    if scope == "profile" and not validation_ids and component_inventory is not None:
        try:
            missing_managed: list[str] = []
            for record in resolved_component_paths(component_inventory, ["core"]):
                if record["policy"] != "managed":
                    continue
                materialized_path = record["path"]
                lexical_target = root
                traverses_link = False
                for part in PurePosixPath(materialized_path).parts:
                    lexical_target /= part
                    if _is_link_like(lexical_target):
                        traverses_link = True
                        break
                if traverses_link:
                    missing_managed.append(materialized_path)
                    continue
                try:
                    target = safe_repo_path(root, materialized_path)
                except ContextOSError:
                    missing_managed.append(materialized_path)
                    continue
                if not target.is_file() or _is_link_like(target):
                    missing_managed.append(materialized_path)
            add(
                "components:core",
                "fail" if missing_managed else "pass",
                (
                    f"{len(missing_managed)} managed path(s) missing or unsafe: "
                    + ", ".join(missing_managed[:3])
                )
                if missing_managed
                else "managed core materialized",
            )
        except (ComponentManifestError, ContextOSError, OSError) as exc:
            add("components:core", "fail", str(exc))

    report_ids = (
        [runtime]
        if scope == "runtime" and runtime is not None
        else list(registry_ids)
        if scope == "maintainer-all"
        else sorted(
            set(registry_ids)
            | set(configured_agents or ())
            | set(local_hosts["hosts"])
        )
    )
    validation_set = set(validation_ids)
    runtime_reports: dict[str, Any] = {}
    for runtime_id in report_ids:
        if scope == "maintainer-all":
            role = "maintainer"
        elif scope == "runtime" and runtime_id == runtime:
            role = "explicit"
        elif configured_agents is not None:
            role = "configured" if runtime_id in configured_agents else "inert"
        elif runtime_id in local_hosts["hosts"]:
            role = "legacy-local"
        elif runtime_id in validation_set:
            role = "legacy"
        else:
            role = "inert"
        scoped = runtime_id in validation_set
        configuration_status = (
            "configured"
            if configured_agents is not None and runtime_id in configured_agents
            else "unconfigured"
            if configured_agents is not None
            else "unknown"
        )

        manifest: dict[str, Any] | None = None
        manifest_error: str | None = None
        try:
            manifest = runtime_manifest(root, runtime_id, check_paths=False)
            if scoped:
                add(
                    f"manifest:{runtime_id}",
                    "pass",
                    f"schema {manifest['schema_version']}",
                )
        except ContextOSError as exc:
            manifest_error = str(exc)
            if scoped:
                add(f"manifest:{runtime_id}", "fail", manifest_error)

        if manifest is not None and scope in {"runtime", "maintainer-all"}:
            try:
                validate_runtime_manifest(
                    manifest,
                    runtime_id=runtime_id,
                    root=root,
                    today=effective_today,
                    check_paths=True,
                )
                add(f"runtime-paths:{runtime_id}", "pass", "referenced paths exist")
            except (RuntimeManifestError, OSError, UnicodeError) as exc:
                add(f"runtime-paths:{runtime_id}", "fail", str(exc))

        component_report: dict[str, Any]
        if manifest is None or component_inventory is None:
            component_report = {
                "status": "unknown",
                "closure": [],
                "missing_paths": [],
            }
        else:
            try:
                closure = component_closure(
                    component_inventory, manifest["components"]
                )
                records = resolved_component_paths(
                    component_inventory,
                    manifest["components"],
                    include_development=scope == "maintainer-all",
                )
                missing_paths: list[str] = []
                missing_by_policy: dict[str, list[str]] = {
                    "managed": [],
                    "seed": [],
                    "development": [],
                }
                present_count = 0
                # Workspace paths have already passed lexical containment or
                # come from the fixed diagnostic fallback. Do not resolve them
                # here: resolution would follow the malformed link doctor is
                # trying to report and could escape before the link scan below.
                effective_state_root = workspace.state_dir.relative_to(root).as_posix()
                effective_sessions_root = (
                    workspace.sessions_dir.relative_to(root).as_posix()
                )
                effective_task_file = workspace.task_file.relative_to(root).as_posix()
                for record in records:
                    materialized_path = record["path"]
                    if record["policy"] == "seed":
                        seed_roots = (
                            (DEFAULT_PATHS["state_dir"], effective_state_root),
                            (
                                DEFAULT_PATHS["sessions_dir"],
                                effective_sessions_root,
                            ),
                        )
                        for default_root, effective_root in seed_roots:
                            if materialized_path == default_root or materialized_path.startswith(
                                default_root + "/"
                            ):
                                materialized_path = effective_root + materialized_path[
                                    len(default_root) :
                                ]
                                break
                        if materialized_path == DEFAULT_PATHS["task_file"]:
                            materialized_path = effective_task_file
                    lexical_target = root
                    traverses_link = False
                    for part in PurePosixPath(materialized_path).parts:
                        lexical_target /= part
                        if _is_link_like(lexical_target):
                            traverses_link = True
                            break
                    if traverses_link:
                        missing_paths.append(materialized_path)
                        missing_by_policy[record["policy"]].append(materialized_path)
                        continue
                    try:
                        target = safe_repo_path(root, materialized_path)
                    except ContextOSError:
                        missing_paths.append(materialized_path)
                        missing_by_policy[record["policy"]].append(materialized_path)
                        continue
                    if target.is_file() and not _is_link_like(target):
                        present_count += 1
                    else:
                        missing_paths.append(materialized_path)
                        missing_by_policy[record["policy"]].append(materialized_path)
                component_status = (
                    "materialized"
                    if not missing_paths
                    else "absent"
                    if present_count == 0
                    else "partial"
                )
                component_report = {
                    "status": component_status,
                    "closure": closure,
                    "missing_paths": missing_paths,
                    "missing_by_policy": missing_by_policy,
                }
                if scoped:
                    blocking_missing = (
                        missing_paths
                        if scope == "maintainer-all"
                        else missing_by_policy["managed"]
                        if scope in {"profile", "runtime"}
                        else []
                    )
                    materialization_status = (
                        "fail"
                        if blocking_missing
                        else "warn"
                        if component_status != "materialized"
                        else "pass"
                    )
                    add(
                        f"components:{runtime_id}",
                        materialization_status,
                        "materialized"
                        if component_status == "materialized"
                        else (
                            f"{component_status}; {len(missing_paths)} missing; "
                            f"first: {', '.join(missing_paths[:5])}"
                        ),
                    )
            except (ComponentManifestError, ContextOSError) as exc:
                component_report = {
                    "status": "invalid",
                    "closure": [],
                    "missing_paths": [],
                    "detail": str(exc),
                }
                if scoped:
                    add(f"components:{runtime_id}", "fail", str(exc))

        probe_reports: list[dict[str, Any]] = []
        availability_results: list[bool] = []
        conformance_tests: set[str] = set()
        if manifest is not None:
            for surface_id, surface in manifest["surfaces"].items():
                conformance_tests.update(surface["conformance_tests"])
                for probe in surface["binary_probes"]:
                    locations = {
                        candidate: shutil.which(candidate)
                        for candidate in probe["candidates"]
                    }
                    resolved = any(locations.values())
                    if probe["purpose"] == "availability":
                        availability_results.append(resolved)
                    probe_reports.append(
                        {
                            "surface": surface_id,
                            "purpose": probe["purpose"],
                            "candidates": locations,
                            "resolved": resolved,
                            "executed": False,
                        }
                    )
                    if scoped:
                        detail = "resolution only; not executed; " + ", ".join(
                            f"{candidate}={location or 'not installed'}"
                            for candidate, location in locations.items()
                        )
                        add(
                            f"runtime:{runtime_id}:{surface_id}:{probe['purpose']}",
                            "pass" if resolved else "warn",
                            detail,
                        )
        availability_status = (
            "available"
            if availability_results and all(availability_results)
            else "mixed"
            if any(availability_results)
            else "unavailable"
            if availability_results
            else "unknown"
        )

        host_entry = local_hosts["hosts"].get(runtime_id) if local_hosts_valid else None
        onboarding_status = (
            "unknown"
            if not local_hosts_valid
            else "configured"
            if host_entry is not None
            else "not-configured"
        )
        if not local_hosts_valid:
            drift_status = "unknown"
        elif host_entry is None:
            drift_status = "not-recorded"
        elif manifest is None:
            drift_status = "unknown"
        else:
            expected_source = sha256_text(canonical_json(manifest))
            drift_status = (
                "current"
                if host_entry["source_manifest_sha256"] == expected_source
                else "drifted"
            )

        evidence = manifest.get("evidence") if manifest is not None else None
        if evidence is None:
            evidence_report = {
                "status": "invalid",
                "checked_on": None,
                "age_days": None,
                "stale_after_days": EVIDENCE_STALE_AFTER_DAYS,
            }
        else:
            checked_on = evidence["checked_on"]
            checked_date = date.fromisoformat(checked_on)
            evidence_age = (effective_today - checked_date).days
            evidence_status = (
                "future"
                if evidence_age < -1
                else "stale"
                if evidence_age > EVIDENCE_STALE_AFTER_DAYS
                else "fresh"
            )
            evidence_report = {
                "status": evidence_status,
                "checked_on": checked_on,
                "age_days": evidence_age,
                "stale_after_days": EVIDENCE_STALE_AFTER_DAYS,
            }

        if scoped and manifest is not None:
            add(
                f"runtime-onboarding:{runtime_id}",
                "pass" if onboarding_status == "configured" else "warn",
                onboarding_status,
            )
            if evidence_report["status"] in {"stale", "future", "invalid"}:
                add(
                    f"runtime-evidence:{runtime_id}",
                    (
                        "fail"
                        if evidence_report["status"] == "invalid"
                        or (
                            evidence_report["status"] == "future"
                            and scope == "maintainer-all"
                        )
                        else "warn"
                    ),
                    f"{evidence_report['status']}; checked_on={evidence_report['checked_on']}",
                )

        runtime_reports[runtime_id] = {
            "role": role,
            "configuration": {
                "status": configuration_status,
                "inert": (
                    configuration_status == "unconfigured"
                    if configuration_status != "unknown"
                    else None
                ),
                "validation_scope": scoped,
            },
            "support": {
                "status": "supported" if manifest is not None else "invalid-descriptor",
                "tier": manifest["support_tier"] if manifest is not None else None,
                "summary": manifest["support_summary"] if manifest is not None else manifest_error,
            },
            "components": component_report,
            "customization": {
                "status": "not-verifiable",
                "reason": "owned-file base hashes require the immutable bundle lock",
            },
            "local_availability": {
                "status": availability_status,
                "probes": probe_reports,
            },
            "local_onboarding": {
                "status": onboarding_status,
                "installed_at": host_entry["installed_at"] if host_entry else None,
            },
            "descriptor_drift": {"status": drift_status},
            "conformance": {
                "status": "declared" if manifest is not None else "invalid",
                "tests": sorted(conformance_tests),
                "executed": False,
            },
            "evidence": evidence_report,
        }

    drift_targets = [
        runtime_id
        for runtime_id in validation_ids
        if runtime_id in local_hosts["hosts"]
    ]
    if scope == "legacy" and len(local_hosts["hosts"]) != 1:
        drift_targets = list(local_hosts["hosts"])
    for drift_runtime in drift_targets:
        drift_name = (
            "runtime-manifest-drift"
            if len(drift_targets) == 1
            else f"runtime-manifest-drift:{drift_runtime}"
        )
        drift_status = runtime_reports.get(drift_runtime, {}).get(
            "descriptor_drift", {}
        ).get("status", "unknown")
        add(
            drift_name,
            "pass" if drift_status == "current" else "warn",
            "current"
            if drift_status == "current"
            else "rerun bash scripts/contextos.sh install --runtime " + drift_runtime,
        )

    lock = root / ".context-os" / "apply.lock"
    try:
        _guard_local_state_path(root, lock)
        add(
            "transaction-lock",
            "warn" if lock.exists() else "pass",
            str(lock) if lock.exists() else "none",
        )
    except ContextOSError as exc:
        add("transaction-lock", "fail", str(exc))
    journals = root / ".context-os" / "journals"
    try:
        _guard_local_state_path(root, journals)
        if _is_link_like(journals) or (journals.exists() and not journals.is_dir()):
            raise ContextOSError(f"invalid journal path: {journals}")
        pending_journals = list(journals.iterdir()) if journals.is_dir() else []
        add(
            "transaction-journals",
            "warn" if pending_journals else "pass",
            (
                f"{len(pending_journals)} pending journal artifact(s); confirm no "
                "apply process is active, remove a stale apply.lock if present, "
                "then rerun the approved proposal apply to inspect and recover. "
                "If recovery reports a committed target mismatch, restore the "
                "reported path to its receipt-bound bytes and mode before rerunning; "
                "do not delete the journal as a shortcut"
            )
            if pending_journals
            else "none",
        )
    except (ContextOSError, OSError) as exc:
        add("transaction-journals", "fail", str(exc))
    hosts_lock = root / ".context-os" / "hosts.lock"
    try:
        _guard_local_state_path(root, hosts_lock)
        add(
            "host-state-lock",
            "warn" if hosts_lock.exists() else "pass",
            (
                f"stale or active lock at {hosts_lock}; remove it only after confirming "
                "no install or migration is running"
            )
            if hosts_lock.exists()
            else "none",
        )
    except ContextOSError as exc:
        add("host-state-lock", "fail", str(exc))
    cutoff = utc_now().timestamp() - (30 * 24 * 60 * 60)
    old_artifacts: list[Path] = []
    artifact_warnings: list[str] = []
    artifact_directory_failures: list[str] = []
    for folder in ("proposals", "receipts"):
        artifact_dir = root / ".context-os" / folder
        try:
            _guard_local_state_path(root, artifact_dir)
            if _is_link_like(artifact_dir) or (
                artifact_dir.exists() and not artifact_dir.is_dir()
            ):
                artifact_directory_failures.append(
                    f"invalid artifact directory: {folder}"
                )
                continue
            candidates = list(artifact_dir.glob("*.json"))
        except (ContextOSError, OSError) as exc:
            artifact_directory_failures.append(f"cannot inspect {folder}: {exc}")
            continue
        for path in candidates:
            try:
                if _is_link_like(path):
                    artifact_warnings.append(
                        f"link-like artifact ignored: {folder}/{path.name}"
                    )
                elif path.is_file() and path.stat().st_mtime < cutoff:
                    old_artifacts.append(path)
            except (ContextOSError, OSError) as exc:
                artifact_warnings.append(
                    f"cannot inspect {folder}/{path.name}: {exc}"
                )
    retention_details = []
    if old_artifacts:
        retention_details.append(f"{len(old_artifacts)} artifacts older than 30 days")
    if artifact_warnings:
        retention_details.append(
            f"{len(artifact_warnings)} invalid or unreadable artifact(s); "
            + "; ".join(artifact_warnings[:3])
        )
    if artifact_directory_failures:
        retention_details.append("; ".join(artifact_directory_failures[:2]))
    add(
        "local-artifact-retention",
        "fail"
        if artifact_directory_failures
        else "warn"
        if retention_details
        else "pass",
        "; ".join(retention_details) if retention_details else "none older than 30 days",
    )

    status = (
        "fail"
        if any(item["status"] == "fail" for item in checks)
        else "warn"
        if any(item["status"] == "warn" for item in checks)
        else "pass"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "scope": scope,
        "workspace": {
            "source": workspace_source,
            "configured_agents": (
                list(configured_agents) if configured_agents is not None else None
            ),
        },
        "runtimes": runtime_reports,
        "checks": checks,
    }


def _hook_targets(payload: dict[str, Any]) -> set[str]:
    targets: set[str] = set()

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, child_key)
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str):
            if key in {"file_path", "path"} and value.strip():
                targets.add(value.strip().replace("\\", "/"))
            if key in {"command", "patch"}:
                for match in re.finditer(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$", value, re.MULTILINE):
                    targets.add(match.group(1).strip().replace("\\", "/"))

    visit(payload)
    return targets


def hook_report(root: Path, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    workspace = load_workspace(root)
    if event == "session-start":
        if not _is_initialized(workspace):
            findings.append({"severity": "advisory", "message": f"Context OS is not initialized. {SETUP_NEXT_ACTION}"})
        lock = root / ".context-os" / "apply.lock"
        if lock.exists():
            findings.append({"severity": "warning", "message": f"A lifecycle apply lock exists at {lock}. Run context-os doctor before writing."})
    elif event == "pre-write":
        protected = {
            relative_path(root, workspace.state_dir / "current.md"): "Use the lifecycle proposal/apply kernel for current.md so date and history invariants are enforced.",
            relative_path(root, workspace.state_dir / "current-log.md"): "Use the lifecycle proposal/apply kernel for current-log.md so history remains consistent.",
            relative_path(root, workspace.state_dir / "decisions.md"): "Use the end-session proposal/apply kernel for append-only decision rows.",
            relative_path(root, workspace.state_dir / "blockers.md"): "Use the lifecycle proposal/apply kernel for blockers.md.",
            relative_path(root, workspace.state_dir / "weekly-priorities.md"): "Use the lifecycle proposal/apply kernel for weekly-priorities.md.",
        }
        normalized_targets = set()
        for target in _hook_targets(payload):
            candidate = Path(target)
            if candidate.is_absolute():
                try:
                    normalized_targets.add(relative_path(root, candidate))
                except ValueError:
                    continue
            else:
                normalized_targets.add(Path(target.removeprefix("./")).as_posix())
        for path, message in protected.items():
            if path in normalized_targets:
                findings.append({"severity": "advisory", "message": message})
    else:
        raise ContextOSError(f"unsupported hook event: {event}")
    return {"schema_version": SCHEMA_VERSION, "event": event, "findings": findings}
