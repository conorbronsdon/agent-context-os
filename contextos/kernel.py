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
import tempfile
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
HOST_STATE_SCHEMA_VERSION = 1
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
    if path.is_symlink():
        raise ContextOSError(f"transaction target must not be a symlink: {path}")
    if not path.exists():
        return None
    if not path.is_file():
        raise ContextOSError(f"transaction target must be a regular file: {path}")
    return sha256_bytes(path.read_bytes())


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


def discover_root(start: Path | None = None) -> Path:
    candidate = (start or Path.cwd()).resolve()
    for path in (candidate, *candidate.parents):
        if (path / "AGENTS.md").is_file() and (
            (path / "state").is_dir() or (path / "workspace.yaml").is_file()
        ):
            return path
    raise ContextOSError("could not find a Context OS root (AGENTS.md plus state/ or workspace.yaml)")


def _reject_config_aliases(root: Path, canonical_name: str) -> None:
    identity = workspace_portable_identity(canonical_name)
    try:
        matches = [
            path.name
            for path in root.iterdir()
            if workspace_portable_identity(path.name) == identity
        ]
    except OSError as exc:
        raise ContextOSError(f"cannot inspect workspace root {root}: {exc}") from exc
    if matches and matches != [canonical_name]:
        raise ContextOSError(
            f"portable configuration filename collision for {canonical_name!r}: "
            + ", ".join(sorted(matches))
        )


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
                "message": "contextos.workspace.json is valid but not canonically rendered",
            })
        if legacy_path.exists() or legacy_path.is_symlink():
            conflicts: list[str] = []
            legacy_detail = "legacy workspace.yaml is shadowed by contextos.workspace.json"
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
                "workspace.yaml remains readable but is deprecated; preview migration "
                "with context-os workspace migrate"
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
    manifest = load_component_manifest(
        root / "components" / "manifest.json", root=root, check_paths=False
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
    manifest = load_component_manifest(
        root / "components" / "manifest.json", root=root, check_paths=False
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


def create_workspace_migration_proposal(
    root: Path,
    agents: Sequence[str],
    now: datetime,
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
    if resolution.source == "defaults":
        raise ContextOSError(
            "workspace migration requires legacy workspace.yaml; "
            "initial agent selection belongs to setup"
        )
    if resolution.source == "json" and list(agents) != list(resolution.agents or []):
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
        if current.is_symlink():
            raise ContextOSError(
                f"local artifact path must not traverse a symlink: {relative.as_posix()}"
            )
        if index < len(relative.parts) - 1 and current.exists() and not current.is_dir():
            raise ContextOSError(
                f"local artifact ancestor must be a directory: {current.relative_to(root)}"
            )


def _write_exclusive_text(path: Path, content: str, *, root: Path) -> None:
    _write_exclusive_bytes(path, content.encode("utf-8"), root=root)


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
        "invariants": ["workflow-path-policy", "optimistic-file-hashes", "exact-proposal-integrity"],
    }
    if workflow in {"update", "end"} and any(change["path"].endswith("current.md") for change in changes):
        document["invariants"].extend(["single-last-updated", "same-day-history"])
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
    if not isinstance(document.get("invariants"), list):
        raise ContextOSError("proposal invariants must be a list")
    workspace = load_workspace(root)
    seen: set[str] = set()
    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            raise ContextOSError(f"changes[{index}] must be an object")
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


def _atomic_restore_bytes(
    path: Path,
    content: bytes,
    mode: int | None,
    *,
    scratch_dir: Path | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_parent = scratch_dir or path.parent
    temporary_parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=temporary_parent,
            prefix=f".{path.name}.",
            suffix=".rollback",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = handle.name
        if mode is not None:
            os.chmod(temporary, mode)
            if os.name != "nt":
                with open(temporary, "rb") as handle:
                    os.fsync(handle.fileno())
        _fsync_directory(Path(temporary).parent)
        os.replace(temporary, path)
        temporary = None
        _fsync_directory(path.parent)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    """Persist directory entries when the host exposes directory fsync."""
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


def _mode_matches(actual: int, expected: int) -> bool:
    if os.name == "nt":
        return bool(actual & stat.S_IWRITE) == bool(expected & stat.S_IWRITE)
    return actual == expected


def _same_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


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
        os.chmod(path, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


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
    _ensure_local_directory(root, building / "backups")
    _ensure_local_directory(root, building / "publications")
    _ensure_local_directory(root, building / "forward")
    entries: list[dict[str, Any]] = []
    for index, change in enumerate(document["changes"]):
        path = safe_repo_path(root, change["path"])
        before = backups[path]
        expected_before_hash = change["before_raw_sha256"]
        if (sha256_bytes(before) if before is not None else None) != expected_before_hash:
            raise ContextOSError(f"agent transaction backup changed: {change['path']}")
        if backup_modes[path] != change["before_mode"]:
            raise ContextOSError(f"agent transaction mode changed: {change['path']}")
        backup_relative = None
        if before is not None:
            backup_relative = f"backups/{index}.bin"
            _write_exclusive_bytes(building / backup_relative, before, root=root)
        if change["action"] == "write":
            publication = building / "publications" / f"{index}.after"
            after_bytes = change["after_text"].encode("utf-8")
            if sha256_bytes(after_bytes) != change["after_raw_sha256"]:
                raise ContextOSError(
                    f"agent transaction publication changed: {change['path']}"
                )
            _write_exclusive_bytes(
                publication,
                after_bytes,
                root=root,
                mode=change["after_mode"],
            )
        entries.append({
            "path": change["path"],
            "action": change["action"],
            "owner": change["authorization"]["owner"],
            "policy": change["authorization"]["policy"],
            "existed": before is not None,
            "mode": backup_modes[path],
            "after_mode": change["after_mode"],
            "sha256_raw": sha256_bytes(before) if before is not None else None,
            "after_sha256_raw": change["after_raw_sha256"],
            "backup": backup_relative,
        })
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "workflow": AGENT_LIFECYCLE_WORKFLOW,
        "operation": document["operation"],
        "proposal_id": document["proposal_id"],
        "proposal_digest": document["proposal_digest"],
        "receipt": receipt_path.relative_to(root).as_posix(),
        "authorization": document["authorization"],
        "source_hashes": document["source_hashes"],
        "invariants": document["invariants"],
        "entries": entries,
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


def _regular_file_state(path: Path, *, label: str) -> tuple[str, int] | None:
    if not (path.exists() or _is_link_like(path)):
        return None
    if _is_link_like(path) or not path.is_file():
        raise ContextOSError(f"{label} is link-like or not a regular file: {path}")
    return sha256_bytes(path.read_bytes()), stat.S_IMODE(path.stat().st_mode)


def _publication_anchor(
    root: Path, journal: Path, index: int, entry: dict[str, Any]
) -> Path | None:
    if entry["action"] != "write":
        return None
    anchor = journal / "publications" / f"{index}.after"
    _guard_local_artifact_path(root, anchor)
    state = _regular_file_state(anchor, label="transaction publication anchor")
    if state is None or state[0] != entry["after_sha256_raw"] or not _mode_matches(
        state[1], entry["after_mode"]
    ):
        raise ContextOSError(f"invalid publication anchor for {entry['path']}")
    return anchor


def _rollback_agent_entry(
    root: Path, journal: Path, index: int, entry: dict[str, Any]
) -> None:
    """Restore one journaled target without overwriting a concurrent writer."""
    target = safe_repo_path(root, entry["path"])
    anchor = _publication_anchor(root, journal, index, entry)
    capture = journal / "forward" / f"{index}.current"
    _guard_local_artifact_path(root, capture)
    capture_state = _regular_file_state(capture, label="transaction forward capture")
    if capture_state is not None and (
        capture_state[0] != entry["sha256_raw"]
        or type(entry["mode"]) is not int
        or not _mode_matches(capture_state[1], entry["mode"])
    ):
        raise ContextOSError(f"forward capture mismatch for {entry['path']}")
    target_state = _regular_file_state(target, label="transaction rollback target")

    if entry["existed"] is False:
        if capture_state is not None:
            raise ContextOSError(f"unexpected forward capture for {entry['path']}")
        if target_state is None:
            _fsync_directory(target.parent)
            return
        if (
            anchor is None
            or not _same_file(target, anchor)
            or target_state[0] != entry["after_sha256_raw"]
            or not _mode_matches(target_state[1], entry["after_mode"])
        ):
            raise ContextOSError(
                f"rollback preserved a concurrent target: {entry['path']}"
            )
        target.unlink()
        _fsync_directory(target.parent)
        return

    if capture_state is None:
        if (
            target_state is not None
            and target_state[0] == entry["sha256_raw"]
            and type(entry["mode"]) is int
            and _mode_matches(target_state[1], entry["mode"])
        ):
            _fsync_directory(target.parent)
            return
        raise ContextOSError(
            f"rollback has no owned before-state for {entry['path']}"
        )

    if target_state is not None:
        if _same_file(target, capture):
            if (
                target_state[0] != entry["sha256_raw"]
                or not _mode_matches(target_state[1], entry["mode"])
            ):
                raise ContextOSError(f"restored target mismatch for {entry['path']}")
            _fsync_directory(target.parent)
            capture.unlink()
            _fsync_directory(capture.parent)
            return
        if (
            anchor is None
            or not _same_file(target, anchor)
            or target_state[0] != entry["after_sha256_raw"]
            or not _mode_matches(target_state[1], entry["after_mode"])
        ):
            raise ContextOSError(
                f"rollback preserved a concurrent target: {entry['path']}"
            )
        target.unlink()
        _fsync_directory(target.parent)

    _publish_exclusive(capture, target)
    _fsync_directory(target.parent)
    restored = _regular_file_state(target, label="restored transaction target")
    if (
        restored is None
        or not _same_file(target, capture)
        or restored[0] != entry["sha256_raw"]
        or not _mode_matches(restored[1], entry["mode"])
    ):
        raise ContextOSError(f"restored target mismatch for {entry['path']}")
    capture.unlink()
    _fsync_directory(capture.parent)


def _probe_rollback_publication(
    root: Path,
    target: Path,
    journal: Path,
    index: int,
    expected_hash: str,
    expected_mode: int,
) -> None:
    probe = journal / "forward" / f"{index}.preflight"
    _guard_local_artifact_path(root, probe)
    if probe.exists() or probe.is_symlink():
        raise ContextOSError(f"rollback preflight artifact already exists: {probe}")
    linked = False
    try:
        os.link(target, probe)
        linked = True
        state = _regular_file_state(probe, label="rollback preflight artifact")
        if (
            state is None
            or not _same_file(target, probe)
            or state[0] != expected_hash
            or not _mode_matches(state[1], expected_mode)
        ):
            raise ContextOSError(f"rollback preflight identity mismatch for {target}")
    except OSError as exc:
        raise ContextOSError(
            f"rollback publication is unsupported before mutating {target}: {exc}"
        ) from exc
    finally:
        if linked and (probe.exists() or probe.is_symlink()):
            probe.unlink()
            _fsync_directory(probe.parent)


def _verify_committed_agent_targets(
    root: Path, entries: Any, *, journal: Path
) -> None:
    """Retain evidence unless every committed target has its receipt-bound state."""
    expected_keys = {
        "path",
        "action",
        "owner",
        "policy",
        "existed",
        "mode",
        "after_mode",
        "sha256_raw",
        "after_sha256_raw",
        "backup",
    }
    recovery_policy = {
        "contextos.workspace.json": ("write", "workspace-config", "managed"),
        "workspace.yaml": ("delete", "legacy-workspace-config", "migration-only"),
    }
    if not isinstance(entries, list) or not entries:
        raise ContextOSError(f"agent transaction journal has no entries: {journal}")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != expected_keys:
            raise ContextOSError(f"invalid journal entry {index}: {journal}")
        relative = ensure_text(entry.get("path"), f"entries[{index}].path")
        if relative not in recovery_policy:
            raise ContextOSError(f"journal path is not recoverable: {relative}")
        action, owner, policy = recovery_policy[relative]
        if (
            entry.get("action") != action
            or entry.get("owner") != owner
            or entry.get("policy") != policy
        ):
            raise ContextOSError(f"journal ownership mismatch: {relative}")
        existed = entry.get("existed")
        mode = entry.get("mode")
        after_hash = entry.get("after_sha256_raw")
        after_mode = entry.get("after_mode")
        if type(existed) is not bool or (
            mode is not None and (type(mode) is not int or not 0 <= mode <= 0o7777)
        ):
            raise ContextOSError(f"invalid committed journal state: {relative}")
        if action == "write" and (
            not isinstance(after_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", after_hash) is None
            or type(after_mode) is not int
            or not 0 <= after_mode <= 0o7777
        ):
            raise ContextOSError(f"journal after state is invalid: {relative}")
        if action == "delete" and (after_hash is not None or after_mode is not None):
            raise ContextOSError(f"journal delete after state is invalid: {relative}")
        target = safe_repo_path(root, relative)
        _fsync_directory(target.parent)
        current_hash = raw_file_digest(target)
        if action == "delete":
            committed = current_hash is None
        else:
            # The receipt is the commit point. Once it exists, a user tool may
            # legitimately rewrite an equivalent file through a new inode. The
            # publication anchor proves ownership before commit and during
            # rollback; after commit, receipt-bound bytes and mode are the
            # durable user-facing contract.
            _publication_anchor(root, journal, index, entry)
            current_mode = (
                stat.S_IMODE(target.stat().st_mode) if target.exists() else None
            )
            committed = (
                current_hash == after_hash
                and target.exists()
                and type(current_mode) is int
                and type(after_mode) is int
                and _mode_matches(current_mode, after_mode)
            )
        if not committed:
            raise ContextOSError(
                "committed transaction target does not match its receipt; "
                f"journal retained for recovery: {relative}"
            )


def _recover_agent_journal(root: Path, journal: Path) -> None:
    _guard_local_artifact_path(root, journal)
    manifest_path = journal / "journal.json"
    _guard_local_artifact_path(root, manifest_path)
    manifest = read_json(manifest_path)
    required = {
        "schema_version",
        "workflow",
        "operation",
        "proposal_id",
        "proposal_digest",
        "receipt",
        "authorization",
        "source_hashes",
        "invariants",
        "entries",
    }
    if (
        set(manifest) != required
        or type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("workflow") != AGENT_LIFECYCLE_WORKFLOW
        or manifest.get("operation") != WORKSPACE_MIGRATION_OPERATION
        or manifest.get("proposal_id") != journal.name
    ):
        raise ContextOSError(f"invalid agent transaction journal: {journal}")
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
    if receipt.exists() or receipt.is_symlink():
        receipt_anchor = journal / "receipt.anchor"
        _guard_local_artifact_path(root, receipt_anchor)
        anchor_state = _regular_file_state(
            receipt_anchor, label="transaction receipt anchor"
        )
        receipt_state = _regular_file_state(
            receipt, label="transaction receipt"
        )
        if (
            anchor_state is None
            or receipt_state is None
            or anchor_state != receipt_state
            or not _same_file(receipt, receipt_anchor)
        ):
            raise ContextOSError(
                f"journal receipt does not match its owned anchor: {receipt}"
            )
        value = read_json(receipt)
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
            "workflow",
            "operation",
            "confirmation",
            "authorization",
        }
        expected_files = [
            {
                "action": entry["action"],
                "path": entry["path"],
                "owner": entry["owner"],
                "policy": entry["policy"],
                "sha256_before_raw": entry["sha256_raw"],
                "mode_before": entry["mode"],
                "sha256_after_raw": entry["after_sha256_raw"],
                "mode_after": entry["after_mode"],
            }
            for entry in manifest.get("entries", [])
            if isinstance(entry, dict)
        ]
        expected_authorization = {
            **manifest.get("authorization", {}),
            "inputs": [
                {"path": path, "sha256_raw": digest}
                for path, digest in manifest.get("source_hashes", {}).items()
            ],
        }
        if (
            set(value) != expected_receipt_keys
            or type(value.get("schema_version")) is not int
            or value.get("schema_version") != SCHEMA_VERSION
            or value.get("proposal_id") != manifest.get("proposal_id")
            or value.get("proposal_digest") != manifest.get("proposal_digest")
            or value.get("workflow") != AGENT_LIFECYCLE_WORKFLOW
            or value.get("operation") != WORKSPACE_MIGRATION_OPERATION
            or value.get("runtime_identity") != "self-reported"
            or not isinstance(value.get("runtime"), str)
            or value.get("confirmation")
            != {"method": "exact-digest-echo", "human_authenticated": False}
            or value.get("authorization") != expected_authorization
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
        _verify_committed_agent_targets(
            root, manifest.get("entries"), journal=journal
        )
        _fsync_directory(receipt.parent)
        if not _same_file(receipt, receipt_anchor):
            raise ContextOSError(
                f"journal receipt changed during recovery validation: {receipt}"
            )
        _discard_agent_journal(root, journal)
        staging = root / ".context-os" / "staging" / manifest["proposal_id"]
        _guard_local_artifact_path(root, staging)
        shutil.rmtree(staging, ignore_errors=True)
        return
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ContextOSError(f"agent transaction journal has no entries: {journal}")
    for index, entry in enumerate(entries):
        expected_keys = {
            "path",
            "action",
            "owner",
            "policy",
            "existed",
            "mode",
            "after_mode",
            "sha256_raw",
            "after_sha256_raw",
            "backup",
        }
        if not isinstance(entry, dict) or set(entry) != expected_keys:
            raise ContextOSError(f"invalid journal entry {index}: {journal}")
        relative = ensure_text(entry.get("path"), f"entries[{index}].path")
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
        if entry.get("owner") != allowed_owner or entry.get("policy") != allowed_policy:
            raise ContextOSError(f"journal ownership mismatch: {relative}")
        target = safe_repo_path(root, relative)
        expected_action = allowed_action
        if entry.get("action") != expected_action:
            raise ContextOSError(f"journal action mismatch: {relative}")
        after_hash = entry.get("after_sha256_raw")
        after_mode = entry.get("after_mode")
        if expected_action == "write":
            if not isinstance(after_hash, str) or not re.fullmatch(
                r"[0-9a-f]{64}", after_hash
            ) or type(after_mode) is not int or not 0 <= after_mode <= 0o7777:
                raise ContextOSError(f"journal after state is invalid: {relative}")
        elif after_hash is not None or after_mode is not None:
            raise ContextOSError(f"journal delete after state is invalid: {relative}")
        if entry.get("existed") is True:
            backup_name = ensure_text(entry.get("backup"), f"entries[{index}].backup")
            if backup_name != f"backups/{index}.bin":
                raise ContextOSError(f"journal backup path is invalid: {relative}")
            backup = journal / backup_name
            _guard_local_artifact_path(root, backup)
            content = backup.read_bytes()
            if sha256_bytes(content) != entry.get("sha256_raw"):
                raise ContextOSError(f"journal backup hash mismatch: {relative}")
            mode = entry.get("mode")
            if not isinstance(mode, int):
                raise ContextOSError(f"journal mode is invalid: {relative}")
        elif entry.get("existed") is False:
            if (
                entry.get("backup") is not None
                or entry.get("sha256_raw") is not None
                or entry.get("mode") is not None
            ):
                raise ContextOSError(f"journal absence entry is invalid: {relative}")
        else:
            raise ContextOSError(f"journal existed flag is invalid: {relative}")
        _rollback_agent_entry(root, journal, index, entry)
    _discard_agent_journal(root, journal)
    staging = root / ".context-os" / "staging" / manifest["proposal_id"]
    _guard_local_artifact_path(root, staging)
    shutil.rmtree(staging, ignore_errors=True)


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
            shutil.rmtree(journal)
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
        shutil.rmtree(disposable)
    journal.rename(disposable)
    _fsync_directory(journal.parent)
    shutil.rmtree(disposable, ignore_errors=True)
    _fsync_directory(journal.parent)


def _publish_exclusive(source: Path, destination: Path) -> None:
    """Create a no-clobber hard link; callers own durability and cleanup."""
    try:
        os.link(source, destination)
    except FileExistsError as exc:
        raise ContextOSError(
            f"refusing to overwrite concurrently created path: {destination}"
        ) from exc


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
            workflow, _ = _validate_proposal_shape(root, proposal, document)
            for change in document.get("changes", []):
                path = safe_repo_path(root, ensure_text(change.get("path"), "change.path"))
                if workflow == "setup" and path.exists() and _is_populated(path.read_text(encoding="utf-8")):
                    if change.get("replacement_approved") is not True:
                        raise ContextOSError(f"populated file lacks replacement approval: {change['path']}")
                if file_digest(path) != change.get("before_sha256"):
                    raise ContextOSError(f"refusing stale proposal; file changed: {change['path']}")
                if sha256_text(ensure_text(change.get("after_text"), "change.after_text")) != change.get("after_sha256"):
                    raise ContextOSError(f"proposal after hash is invalid: {change['path']}")
        head_before = git_head(root)
        applied = []
        backups: dict[Path, bytes | None] = {}
        backup_modes: dict[Path, int | None] = {}
        staged: dict[Path, Path] = {}
        journal_path: Path | None = None
        journal_entries: list[dict[str, Any]] = []
        receipt_published = False
        staging_root = root / ".context-os" / "staging" / document["proposal_id"]
        receipt_path = root / ".context-os" / "receipts" / f"{document['proposal_id']}.json"
        _guard_local_artifact_path(root, staging_root)
        _guard_local_artifact_path(root, receipt_path)
        if workflow == AGENT_LIFECYCLE_WORKFLOW and (
            receipt_path.exists() or receipt_path.is_symlink()
        ):
            raise ContextOSError(f"refusing to overwrite existing receipt: {receipt_path}")
        receipt: dict[str, Any]
        try:
            if workflow == AGENT_LIFECYCLE_WORKFLOW:
                if staging_root.exists():
                    if staging_root.is_symlink() or not staging_root.is_dir():
                        raise ContextOSError(
                            f"invalid agent transaction staging path: {staging_root}"
                        )
                    shutil.rmtree(staging_root)
                staging_root.mkdir(parents=True)
            for change_index, change in enumerate(document["changes"]):
                path = safe_repo_path(root, change["path"])
                backups[path] = path.read_bytes() if path.exists() else None
                backup_modes[path] = (
                    path.stat().st_mode & 0o7777 if path.exists() else None
                )
                if change.get("action", "write") == "write":
                    stage = staging_root / change["path"]
                    _guard_local_artifact_path(root, stage)
                    if workflow == AGENT_LIFECYCLE_WORKFLOW:
                        _write_exclusive_bytes(
                            stage,
                            change["after_text"].encode("utf-8"),
                            root=root,
                            mode=change["after_mode"],
                        )
                    else:
                        stage.parent.mkdir(parents=True, exist_ok=True)
                        with stage.open("wb") as handle:
                            handle.write(change["after_text"].encode("utf-8"))
                            handle.flush()
                            os.fsync(handle.fileno())
                    staged[path] = stage
            if workflow == AGENT_LIFECYCLE_WORKFLOW:
                journal_path = (
                    root / ".context-os" / "journals" / document["proposal_id"]
                )
                _create_agent_journal(
                    root, document, backups, backup_modes, receipt_path
                )
                journal_document = read_json(journal_path / "journal.json")
                journal_entries = journal_document["entries"]
                # Staging and journal construction are fallible and may take
                # long enough for an uncoordinated source edit. Rebind every
                # source and target immediately before the first mutation.
                _validate_agent_preflight(root, document)
                for change_index, change in enumerate(document["changes"]):
                    if change["before_raw_sha256"] is not None:
                        _probe_rollback_publication(
                            root,
                            safe_repo_path(root, change["path"]),
                            journal_path,
                            change_index,
                            change["before_raw_sha256"],
                            change["before_mode"],
                        )
            for change_index, change in enumerate(document["changes"]):
                path = safe_repo_path(root, change["path"])
                if workflow == AGENT_LIFECYCLE_WORKFLOW:
                    if raw_file_digest(path) != change["before_raw_sha256"]:
                        raise ContextOSError(
                            f"refusing target changed during apply: {change['path']}"
                        )
                    current_mode = (
                        stat.S_IMODE(path.stat().st_mode) if path.exists() else None
                    )
                    if current_mode != change["before_mode"]:
                        raise ContextOSError(
                            f"refusing target mode changed during apply: {change['path']}"
                        )
                    assert journal_path is not None
                    journal_entry = journal_entries[change_index]
                    applied_entry = {
                        "action": change["action"],
                        "path": change["path"],
                        "owner": change["authorization"]["owner"],
                        "policy": change["authorization"]["policy"],
                        "sha256_before_raw": change["before_raw_sha256"],
                        "mode_before": change["before_mode"],
                        "sha256_after_raw": change["after_raw_sha256"],
                        "mode_after": change["after_mode"],
                    }
                    if change["before_raw_sha256"] is not None:
                        captured = (
                            journal_path / "forward" / f"{change_index}.current"
                        )
                        _guard_local_artifact_path(root, captured)
                        if captured.exists() or captured.is_symlink():
                            raise ContextOSError(
                                f"forward transaction capture already exists: {captured}"
                            )
                        os.replace(path, captured)
                        applied.append(applied_entry)
                        _fsync_directory(path.parent)
                        _fsync_directory(captured.parent)
                        captured_state = _regular_file_state(
                            captured, label="transaction forward capture"
                        )
                        if (
                            captured_state is None
                            or captured_state[0] != change["before_raw_sha256"]
                            or not _mode_matches(
                                captured_state[1], change["before_mode"]
                            )
                        ):
                            try:
                                _publish_exclusive(captured, path)
                                _fsync_directory(path.parent)
                            except (OSError, ContextOSError) as restore_exc:
                                raise ContextOSError(
                                    "unrecognized forward capture retained; target "
                                    f"also changed: {change['path']}"
                                ) from restore_exc
                            raise ContextOSError(
                                f"refusing target changed during capture: {change['path']}"
                            )
                    if change["action"] == "write":
                        anchor = _publication_anchor(
                            root, journal_path, change_index, journal_entry
                        )
                        assert anchor is not None
                        _publish_exclusive(anchor, path)
                        if change["before_raw_sha256"] is None:
                            applied.append(applied_entry)
                        _fsync_directory(path.parent)
                    if raw_file_digest(path) != change["after_raw_sha256"]:
                        raise ContextOSError(
                            f"agent-config post-write hash is invalid: {change['path']}"
                        )
                    if (
                        change["action"] == "write"
                        and not _mode_matches(
                            stat.S_IMODE(path.stat().st_mode), change["after_mode"]
                        )
                    ):
                        raise ContextOSError(
                            f"agent-config post-write mode is invalid: {change['path']}"
                        )
                else:
                    if file_digest(path) != change.get("before_sha256"):
                        raise ContextOSError(
                            f"refusing target changed during apply: {change['path']}"
                        )
                    if change.get("action", "write") == "delete":
                        path.unlink()
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(staged[path], path)
                    applied.append({
                        "path": change["path"],
                        "sha256_before": change["before_sha256"],
                        "sha256_after": file_digest(path),
                    })
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
                "invariants_checked": document.get("invariants", []),
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
            if workflow == AGENT_LIFECYCLE_WORKFLOW:
                _ensure_local_directory(root, receipt_path.parent)
            else:
                receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_stage = staging_root / "receipt.json"
            if workflow == AGENT_LIFECYCLE_WORKFLOW:
                _write_exclusive_text(
                    receipt_stage,
                    json.dumps(receipt, indent=2) + "\n",
                    root=root,
                )
            else:
                receipt_stage.parent.mkdir(parents=True, exist_ok=True)
                receipt_stage.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
            if workflow == AGENT_LIFECYCLE_WORKFLOW and (
                receipt_path.exists() or receipt_path.is_symlink()
            ):
                raise ContextOSError(f"refusing to overwrite existing receipt: {receipt_path}")
            if workflow == AGENT_LIFECYCLE_WORKFLOW:
                assert journal_path is not None
                receipt_anchor = journal_path / "receipt.anchor"
                _guard_local_artifact_path(root, receipt_anchor)
                _publish_exclusive(receipt_stage, receipt_anchor)
                _fsync_directory(journal_path)
                _publish_exclusive(receipt_anchor, receipt_path)
                receipt_published = True
                _fsync_directory(receipt_path.parent)
                if not _same_file(receipt_anchor, receipt_path):
                    raise ContextOSError(
                        "published receipt does not match its transaction anchor"
                    )
                _verify_committed_agent_targets(
                    root, journal_entries, journal=journal_path
                )
                if not _same_file(receipt_anchor, receipt_path):
                    raise ContextOSError(
                        "published receipt changed during target verification"
                    )
            else:
                os.replace(receipt_stage, receipt_path)
            if journal_path is not None:
                try:
                    _discard_agent_journal(root, journal_path)
                except (OSError, ContextOSError):
                    # Receipt publication is the commit point. A retained valid
                    # journal is safe: the next apply validates the receipt as
                    # its commit marker and retires the journal.
                    pass
        except Exception as exc:
            if receipt_published:
                raise ContextOSError(
                    "receipt publication reached the commit point but durability "
                    f"confirmation failed; journal retained for recovery: {exc}"
                ) from exc
            rollback_errors = []
            journal_by_path = {
                entry["path"]: (index, entry)
                for index, entry in enumerate(journal_entries)
            }
            for applied_change in reversed(applied):
                applied_path = safe_repo_path(root, applied_change["path"])
                try:
                    if journal_path is not None:
                        index, journal_entry = journal_by_path[applied_change["path"]]
                        _rollback_agent_entry(
                            root, journal_path, index, journal_entry
                        )
                    else:
                        before = backups[applied_path]
                        if before is None:
                            applied_path.unlink(missing_ok=True)
                        else:
                            _atomic_restore_bytes(
                                applied_path,
                                before,
                                backup_modes[applied_path],
                            )
                except (OSError, ContextOSError, KeyError) as rollback_exc:
                    rollback_errors.append(f"{applied_change['path']}: {rollback_exc}")
            if rollback_errors:
                raise ContextOSError(
                    f"apply failed and rollback was incomplete ({'; '.join(rollback_errors)}): {exc}"
                ) from exc
            if journal_path is not None:
                _discard_agent_journal(root, journal_path)
                building = journal_path.with_name(f".{journal_path.name}.building")
                shutil.rmtree(building, ignore_errors=True)
            if isinstance(exc, ContextOSError):
                raise
            raise ContextOSError(f"apply failed; staged writes were rolled back: {exc}") from exc
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)
        return receipt_path, receipt


def runtime_ids(root: Path) -> list[str]:
    runtimes_dir = root / "runtimes"
    if not runtimes_dir.is_dir():
        return []
    identifiers = sorted(
        path.stem for path in runtimes_dir.glob("*.json")
        if path.name != "schema.json" and path.is_file()
    )
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
    manifest_path = root / "runtimes" / f"{runtime}.json"
    if not manifest_path.exists():
        raise ContextOSError(f"missing runtime manifest: {manifest_path}")
    manifest = read_json(manifest_path)
    try:
        validate_runtime_manifest(
            manifest, runtime_id=runtime, root=root, check_paths=check_paths
        )
        components = load_component_manifest(
            root / "components" / "manifest.json", root=root, check_paths=False
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
        if current.is_symlink():
            raise ContextOSError(
                f"local state path must not traverse a symlink: {relative.as_posix()}"
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
    if not path.exists() and not path.is_symlink():
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
    if not path.exists() and not path.is_symlink():
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
    root: Path, runtime: str | None = None, *, all_runtimes: bool = False
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    git_location = shutil.which("git")
    add("command:git", "pass" if git_location else "fail", git_location or "not found")
    add("command:python", "pass", sys.executable)
    try:
        workspace_resolution = resolve_workspace(root)
        workspace = workspace_resolution.workspace
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
        workspace = _workspace_from_paths(root, dict(DEFAULT_PATHS))
    required_paths = [
        root / "AGENTS.md", workspace.state_dir / "current.md",
        workspace.state_dir / "current-log.md", workspace.state_dir / "decisions.md",
    ]
    for path in required_paths:
        rel = relative_path(root, path)
        add(f"file:{rel}", "pass" if path.exists() else "fail", rel)
    initialized, initialization_files = _initialization_state(workspace, utc_now().date())
    gate = relative_path(root, workspace.state_dir / INITIALIZATION_FILE)
    add(
        "initialization-state",
        "pass" if initialized else "warn",
        "ready" if initialized else f"guided setup required; {gate} carries no real **Last Updated:** date",
    )
    unresolved = [
        path for path, item in initialization_files.items()
        if item["freshness_status"] in {"missing", "unknown", "future"}
    ]
    add(
        "state-freshness",
        "pass" if not unresolved else "warn",
        "all tracked state files carry a real date"
        if not unresolved
        else f"no usable **Last Updated:** date in: {', '.join(unresolved)}",
    )
    selected = runtime
    local_hosts: dict[str, Any] | None = None
    legacy_runtime: str | None = None
    try:
        local_hosts, legacy_runtime = _hosts_with_legacy(root)
        local_detail = f"{len(local_hosts['hosts'])} configured host(s)"
        if legacy_runtime is not None:
            local_detail += (
                f"; legacy runtime.json for {legacy_runtime!r} is readable but retained; "
                "run workspace migrate-local-runtime"
            )
        add("local-host-state", "warn" if legacy_runtime else "pass", local_detail)
    except ContextOSError as exc:
        add("local-host-state", "fail", str(exc))
    if selected is None and local_hosts is not None:
        configured_hosts = list(local_hosts["hosts"])
        if len(configured_hosts) == 1:
            selected = configured_hosts[0]
    hosts = runtime_ids(root) if all_runtimes or not selected else [selected]
    if not hosts:
        add("manifest-registry", "fail", "no runtime descriptors found")
    for host in hosts:
        try:
            manifest = runtime_manifest(root, host)
            add(f"manifest:{host}", "pass", f"schema {manifest['schema_version']}")
        except ContextOSError as exc:
            add(f"manifest:{host}", "fail", str(exc))
    lock = root / ".context-os" / "apply.lock"
    add("transaction-lock", "warn" if lock.exists() else "pass", str(lock) if lock.exists() else "none")
    journals = root / ".context-os" / "journals"
    if journals.is_symlink() or (journals.exists() and not journals.is_dir()):
        add("transaction-journals", "fail", f"invalid journal path: {journals}")
    else:
        pending_journals = list(journals.iterdir()) if journals.is_dir() else []
        add(
            "transaction-journals",
            "warn" if pending_journals else "pass",
            (
                f"{len(pending_journals)} pending journal artifact(s); confirm no "
                "apply process is active, remove a stale apply.lock if present, "
                "then rerun the approved agent-config apply to inspect and recover. "
                "If recovery reports a committed target mismatch, restore the "
                "reported path to its receipt-bound bytes and mode before rerunning; "
                "do not delete the journal as a shortcut"
            )
            if pending_journals
            else "none",
        )
    hosts_lock = root / ".context-os" / "hosts.lock"
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
    cutoff = utc_now().timestamp() - (30 * 24 * 60 * 60)
    old_artifacts = [
        path for folder in ("proposals", "receipts")
        for path in (root / ".context-os" / folder).glob("*.json")
        if path.stat().st_mtime < cutoff
    ]
    add(
        "local-artifact-retention", "warn" if old_artifacts else "pass",
        f"{len(old_artifacts)} artifacts older than 30 days" if old_artifacts else "none older than 30 days",
    )
    drift_targets = (
        [selected]
        if selected
        else list(local_hosts["hosts"])
        if local_hosts is not None
        else []
    )
    for drift_runtime in drift_targets:
        drift_name = (
            "runtime-manifest-drift"
            if len(drift_targets) == 1
            else f"runtime-manifest-drift:{drift_runtime}"
        )
        try:
            drift_manifest = runtime_manifest(root, drift_runtime)
            expected_source = sha256_text(canonical_json(drift_manifest))
            if local_hosts is not None and drift_runtime in local_hosts["hosts"]:
                recorded_source = local_hosts["hosts"][drift_runtime]["source_manifest_sha256"]
                add(
                    drift_name,
                    "pass" if recorded_source == expected_source else "warn",
                    "current" if recorded_source == expected_source else "rerun context-os install",
                )
        except ContextOSError as exc:
            add(drift_name, "fail", str(exc))
    if selected:
        selected_manifest: dict[str, Any] | None = None
        try:
            selected_manifest = runtime_manifest(root, selected)
        except ContextOSError:
            selected_manifest = None
        if selected_manifest:
            for surface_id, surface in selected_manifest["surfaces"].items():
                for probe in surface["binary_probes"]:
                    locations = {
                        candidate: shutil.which(candidate) for candidate in probe["candidates"]
                    }
                    executable = next((location for location in locations.values() if location), None)
                    check_name = f"runtime:{selected}:{surface_id}:{probe['purpose']}"
                    detail = ", ".join(
                        f"{candidate}={location or 'not installed'}"
                        for candidate, location in locations.items()
                    )
                    add(check_name, "pass" if executable else "warn", detail)
    status = "fail" if any(item["status"] == "fail" for item in checks) else "warn" if any(item["status"] == "warn" for item in checks) else "pass"
    return {"schema_version": SCHEMA_VERSION, "status": status, "checks": checks}


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
