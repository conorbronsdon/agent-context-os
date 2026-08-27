"""Authoritative validation for the repository component inventory."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Sequence


COMPONENT_MANIFEST_SCHEMA_VERSION = 1
COMPONENT_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
PATH_POLICIES = {"managed", "seed", "development"}
TOP_LEVEL_KEYS = {
    "schema_version", "extensible_paths", "extensible_roots", "components",
}
COMPONENT_KEYS = {"id", "description", "depends_on", "paths"}
PATH_KEYS = {"path", "policy"}
RESERVED_OWNERSHIP_PATHS = {
    ".claude/settings.local.json", "repo_map.md", ".env", ".env.local",
}
RESERVED_OWNERSHIP_ROOTS = {
    ".git", ".context-os", "__pycache__", ".vscode", ".idea", ".appledouble",
    "node_modules",
}
WINDOWS_DEVICE_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
WINDOWS_ILLEGAL_CHARACTERS = set('<>:"|?*')


class ComponentManifestError(ValueError):
    """Raised when a component manifest violates the repository contract."""


def _fail(field: str, message: str) -> None:
    raise ComponentManifestError(f"{field}: {message}")


def _exact_keys(value: Any, expected: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(field, "must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unknown:
            details.append(f"unknown {', '.join(unknown)}")
        _fail(field, "; ".join(details))
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail(field, "must be a non-empty string without surrounding whitespace")
    if any(unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"}
           for character in value):
        _fail(field, "must not contain control or format characters")
    return value


def _identity(value: str) -> str:
    """Return the portable identity used for IDs and repository paths."""
    return unicodedata.normalize("NFC", value).casefold()


portable_path_identity = _identity


def _safe_posix_path(value: Any, field: str) -> str:
    raw = _text(value, field)
    if "\\" in raw:
        _fail(field, "must use POSIX separators")
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        _fail(field, "must be repository-relative")
    if any(part in {"", ".", ".."} for part in raw.split("/")):
        _fail(field, "must be a canonical lexical path without empty, '.' or '..' segments")
    if posix.as_posix() != raw:
        _fail(field, "must be a canonical lexical POSIX path")
    return raw


def _ownership_path(value: Any, field: str) -> str:
    raw = _safe_posix_path(value, field)
    parts = PurePosixPath(raw).parts
    portable_parts = tuple(_identity(part) for part in parts)
    if any(
        part.endswith((".", " "))
        or any(character in WINDOWS_ILLEGAL_CHARACTERS for character in part)
        or part.split(".", 1)[0] in WINDOWS_DEVICE_NAMES
        for part in portable_parts
    ):
        _fail(field, "must not use a Windows-aliased or illegal path segment")
    return _reserved_ownership_path(raw, field)


def _reserved_ownership_path(raw: str, field: str) -> str:
    """Reject secret and generated-state names without enforcing host portability."""
    portable = _identity(raw)
    portable_parts = tuple(_identity(part) for part in PurePosixPath(raw).parts)
    if (portable in RESERVED_OWNERSHIP_PATHS
            or portable.endswith("/.ds_store") or portable == ".ds_store"
            or portable.endswith("/.lsoverride") or portable == ".lsoverride"
            or any(part in RESERVED_OWNERSHIP_ROOTS for part in portable_parts)
            or any(part.startswith(".env") for part in portable_parts)
            or portable.endswith((
                ".pyc", ".pyo", ".pyd", ".log", ".pem", ".key", ".swp", ".swo",
            ))):
        _fail(field, "must not claim local, generated-on-demand, secret, or ignored state")
    return raw


def _string_array(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        _fail(field, "must be an array")
    return [_text(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _reject_normalized_duplicates(values: Iterable[tuple[str, str]], field: str) -> None:
    seen: dict[str, str] = {}
    for value, location in values:
        key = _identity(value)
        if key in seen:
            _fail(field, f"duplicate values after Unicode NFC case-folding: {seen[key]!r} and {value!r}")
        seen[key] = value


def _reject_prefix_conflicts(paths: Sequence[tuple[str, str]], field: str) -> None:
    ordered = sorted(
        ((_identity(path).split("/"), path, location) for path, location in paths),
        key=lambda item: item[0],
    )
    for left, right in zip(ordered, ordered[1:]):
        left_parts, left_path, _ = left
        right_parts, right_path, _ = right
        if len(left_parts) < len(right_parts) and right_parts[:len(left_parts)] == left_parts:
            _fail(field, f"prefix conflict between {left_path!r} and {right_path!r}")


def _check_regular_file(
    root: Path, relative: str, field: str, *, allow_missing: bool = False,
) -> None:
    root_resolved = root.resolve()
    candidate = root / Path(*PurePosixPath(relative).parts)
    current = root
    for part in PurePosixPath(relative).parts:
        current /= part
        if current.is_symlink():
            _fail(field, f"must not be a symlink or traverse one: {relative}")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        if allow_missing:
            return
        _fail(field, f"path does not exist: {relative}")
    except OSError:
        _fail(field, f"path does not exist: {relative}")
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        _fail(field, f"must not escape the repository: {relative}")
    try:
        mode = candidate.lstat().st_mode
    except OSError:
        _fail(field, f"path does not exist: {relative}")
    if not stat.S_ISREG(mode):
        _fail(field, f"must name a regular file: {relative}")


def write_generated_file(path: Path, content: str, *, root: Path) -> None:
    """Atomically replace a generated file without following repository symlinks."""
    root_resolved = root.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError:
        _fail("generated_path", f"escapes repository: {path}")
    current = root
    for part in relative.parts[:-1]:
        current /= part
        if current.is_symlink():
            _fail("generated_path", f"traverses a symlink: {current.relative_to(root)}")
    if path.is_symlink():
        _fail("generated_path", f"must not be a symlink: {relative}")
    if path.exists() and not path.is_file():
        _fail("generated_path", f"must be a regular file: {relative}")
    try:
        path.parent.resolve().relative_to(root_resolved)
    except ValueError:
        _fail("generated_path", "must remain inside repository")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_name = handle.name
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def validate_component_manifest(
    manifest: Any, *, root: Path, check_paths: bool = True,
    allow_missing_seed: bool = False,
) -> dict[str, Any]:
    """Validate and return a component manifest.

    Path comparison is lexical, Unicode-NFC-normalized, and case-insensitive so
    a manifest cannot be valid on one supported filesystem and ambiguous on
    another.
    """
    document = _exact_keys(manifest, TOP_LEVEL_KEYS, "manifest")
    if (type(document.get("schema_version")) is not int
            or document["schema_version"] != COMPONENT_MANIFEST_SCHEMA_VERSION):
        _fail("schema_version", f"must equal integer {COMPONENT_MANIFEST_SCHEMA_VERSION}")

    roots_value = document.get("extensible_roots")
    if not isinstance(roots_value, list):
        _fail("extensible_roots", "must be an array")
    extensible_roots = [
        _ownership_path(item, f"extensible_roots[{index}]")
        for index, item in enumerate(roots_value)
    ]
    _reject_normalized_duplicates(
        ((path, f"extensible_roots[{index}]") for index, path in enumerate(extensible_roots)),
        "extensible_roots",
    )
    _reject_prefix_conflicts(
        [(path, f"extensible_roots[{index}]") for index, path in enumerate(extensible_roots)],
        "extensible_roots",
    )

    paths_value = document.get("extensible_paths")
    if not isinstance(paths_value, list):
        _fail("extensible_paths", "must be an array")
    extensible_paths = [
        _ownership_path(item, f"extensible_paths[{index}]")
        for index, item in enumerate(paths_value)
    ]
    _reject_normalized_duplicates(
        ((path, f"extensible_paths[{index}]") for index, path in enumerate(extensible_paths)),
        "extensible_paths",
    )
    _reject_prefix_conflicts(
        [(path, f"extensible_paths[{index}]") for index, path in enumerate(extensible_paths)],
        "extensible_paths",
    )

    raw_components = document.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        _fail("components", "must be a non-empty array")

    component_ids: list[tuple[str, str]] = []
    all_paths: list[tuple[str, str]] = []
    parsed_components: list[dict[str, Any]] = []
    for index, raw_component in enumerate(raw_components):
        field = f"components[{index}]"
        component = _exact_keys(raw_component, COMPONENT_KEYS, field)
        component_id = _text(component.get("id"), f"{field}.id")
        if not COMPONENT_ID_RE.fullmatch(component_id):
            _fail(f"{field}.id", "must be a lowercase kebab-case component id")
        _text(component.get("description"), f"{field}.description")
        dependencies = _string_array(component.get("depends_on"), f"{field}.depends_on")
        _reject_normalized_duplicates(
            ((dependency, f"{field}.depends_on[{dependency_index}]")
             for dependency_index, dependency in enumerate(dependencies)),
            f"{field}.depends_on",
        )

        raw_paths = component.get("paths")
        if not isinstance(raw_paths, list) or not raw_paths:
            _fail(f"{field}.paths", "must be a non-empty array")
        for path_index, raw_path in enumerate(raw_paths):
            path_field = f"{field}.paths[{path_index}]"
            path_entry = _exact_keys(raw_path, PATH_KEYS, path_field)
            path = _ownership_path(path_entry.get("path"), f"{path_field}.path")
            policy = _text(path_entry.get("policy"), f"{path_field}.policy")
            if policy not in PATH_POLICIES:
                _fail(f"{path_field}.policy", f"unsupported value {policy!r}")
            all_paths.append((path, f"{path_field}.path"))
            if check_paths:
                _check_regular_file(
                    root, path, f"{path_field}.path",
                    allow_missing=allow_missing_seed and policy == "seed",
                )
        component_ids.append((component_id, f"{field}.id"))
        parsed_components.append(component)

    _reject_normalized_duplicates(component_ids, "components")
    _reject_normalized_duplicates(all_paths, "components.paths")
    _reject_prefix_conflicts(all_paths, "components.paths")
    owned_identities = {_identity(path) for path, _ in all_paths}
    overlapping_extensions = sorted(
        path for path in extensible_paths if _identity(path) in owned_identities
    )
    if overlapping_extensions:
        _fail(
            "extensible_paths",
            "must not also be component-owned: " + ", ".join(overlapping_extensions),
        )

    ids_by_identity = {_identity(component_id): component_id for component_id, _ in component_ids}
    graph: dict[str, list[str]] = {}
    for index, component in enumerate(parsed_components):
        component_id = component["id"]
        component_key = _identity(component_id)
        dependencies: list[str] = []
        for dependency_index, dependency in enumerate(component["depends_on"]):
            dependency_key = _identity(dependency)
            dependency_field = f"components[{index}].depends_on[{dependency_index}]"
            if dependency_key == component_key:
                _fail(dependency_field, "component must not depend on itself")
            if dependency_key not in ids_by_identity:
                _fail(dependency_field, f"unknown component {dependency!r}")
            dependencies.append(dependency_key)
        graph[component_key] = dependencies

    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(component_key: str) -> None:
        if state.get(component_key) == 2:
            return
        if state.get(component_key) == 1:
            start = stack.index(component_key)
            cycle = stack[start:] + [component_key]
            _fail("components.depends_on", "dependency cycle: " + " -> ".join(
                ids_by_identity[item] for item in cycle
            ))
        state[component_key] = 1
        stack.append(component_key)
        for dependency_key in sorted(graph[component_key]):
            visit(dependency_key)
        stack.pop()
        state[component_key] = 2

    for component_key in sorted(graph):
        visit(component_key)
    return document


def load_component_manifest(
    path: Path, *, root: Path | None = None, check_paths: bool = True,
    allow_missing_seed: bool = False,
) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            manifest = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ComponentManifestError(
            f"invalid JSON in {path}: line {exc.lineno} column {exc.colno}"
        ) from exc
    except OSError as exc:
        raise ComponentManifestError(
            f"cannot read component manifest {path}: {exc.strerror or exc}"
        ) from exc
    return validate_component_manifest(
        manifest, root=root if root is not None else path.parent.parent,
        check_paths=check_paths,
        allow_missing_seed=allow_missing_seed,
    )


def component_closure(manifest: Any, component_ids: Sequence[str]) -> list[str]:
    """Return a stable dependency-first closure for the requested components."""
    document = validate_component_manifest(manifest, root=Path("."), check_paths=False)
    requested = [_text(item, f"component_ids[{index}]")
                 for index, item in enumerate(component_ids)]
    _reject_normalized_duplicates(
        ((item, f"component_ids[{index}]") for index, item in enumerate(requested)),
        "component_ids",
    )
    components = {_identity(item["id"]): item for item in document["components"]}
    unknown = sorted(item for item in requested if _identity(item) not in components)
    if unknown:
        _fail("component_ids", f"unknown components: {', '.join(unknown)}")

    result: list[str] = []
    included: set[str] = set()

    def include(component_key: str) -> None:
        if component_key in included:
            return
        component = components[component_key]
        for dependency in sorted(component["depends_on"], key=_identity):
            include(_identity(dependency))
        included.add(component_key)
        result.append(component["id"])

    for requested_id in sorted(requested, key=_identity):
        include(_identity(requested_id))
    return result


def component_owners(manifest: Any) -> dict[str, str]:
    """Return exact repository paths mapped to their single component owner."""
    document = validate_component_manifest(manifest, root=Path("."), check_paths=False)
    return {
        path_entry["path"]: component["id"]
        for component in document["components"]
        for path_entry in component["paths"]
    }


def resolved_component_paths(
    manifest: Any, component_ids: Sequence[str], *, include_development: bool = False,
) -> list[dict[str, str]]:
    """Resolve selected components to deterministic, single-owner path records."""
    document = validate_component_manifest(manifest, root=Path("."), check_paths=False)
    selected = set(component_closure(document, component_ids))
    records = [
        {
            "owner": component["id"],
            "path": path_entry["path"],
            "policy": path_entry["policy"],
        }
        for component in document["components"]
        if component["id"] in selected
        for path_entry in component["paths"]
        if include_development or path_entry["policy"] != "development"
    ]
    return sorted(records, key=lambda item: _identity(item["path"]))


# The short name is convenient to callers resolving install selections.
dependency_closure = component_closure


def component_schema_document() -> dict[str, Any]:
    """Return the generated JSON Schema structural subset of this contract."""
    text = {
        "type": "string",
        "minLength": 1,
        "pattern": r"^(?!\s)(?:[^\u0000-\u001f\u007f]*\S)$",
    }
    path_entry = {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(PATH_KEYS),
        "properties": {
            "path": text,
            "policy": {"enum": sorted(PATH_POLICIES)},
        },
    }
    component = {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(COMPONENT_KEYS),
        "properties": {
            "id": {"type": "string", "pattern": COMPONENT_ID_RE.pattern},
            "description": text,
            "depends_on": {
                "type": "array", "uniqueItems": True, "items": text,
            },
            "paths": {
                "type": "array", "minItems": 1, "uniqueItems": True,
                "items": path_entry,
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$comment": (
            "Generated structural subset. contextos.component_schema is authoritative "
            "for lexical path safety, portable Unicode identity, filesystem checks, "
            "dependency graph rules, and tracked-file coverage."
        ),
        "title": "Context OS component manifest",
        "type": "object",
        "additionalProperties": False,
        "required": sorted(TOP_LEVEL_KEYS),
        "properties": {
            "schema_version": {"const": COMPONENT_MANIFEST_SCHEMA_VERSION},
            "extensible_paths": {
                "type": "array", "uniqueItems": True, "items": text,
            },
            "extensible_roots": {
                "type": "array", "uniqueItems": True, "items": text,
            },
            "components": {
                "type": "array", "minItems": 1, "uniqueItems": True,
                "items": component,
            },
        },
    }


def unclassified_tracked_paths(
    manifest: Any, tracked_paths: Iterable[str], *, root: Path,
    allow_extensible: bool = False,
) -> list[str]:
    """Return tracked files without an exact owner.

    Maintainer checks are strict. Operational callers may explicitly allow new
    user files below extensible roots without weakening the release inventory.
    """
    document = validate_component_manifest(manifest, root=root, check_paths=False)
    classified = {
        _identity(path_entry["path"])
        for component in document["components"]
        for path_entry in component["paths"]
    }
    extensible = [tuple(_identity(path).split("/"))
                  for path in document["extensible_roots"]]
    extensible_paths = {_identity(path) for path in document["extensible_paths"]}
    seen: dict[str, str] = {}
    missing: list[str] = []
    for index, value in enumerate(tracked_paths):
        path = _safe_posix_path(value, f"tracked_paths[{index}]")
        key = _identity(path)
        if key in seen:
            _fail("tracked_paths", f"portable path collision: {seen[key]!r} and {path!r}")
        seen[key] = path
        if key in classified:
            continue
        parts = tuple(key.split("/"))
        if allow_extensible and (
            key in extensible_paths
            or any(parts[:len(prefix)] == prefix for prefix in extensible)
        ):
            _reserved_ownership_path(path, f"tracked_paths[{index}]")
            continue
        _ownership_path(path, f"tracked_paths[{index}]")
        missing.append(path)
    return sorted(missing, key=_identity)


def untracked_owned_paths(
    manifest: Any, tracked_paths: Iterable[str], *, root: Path,
    allow_missing_seed: bool = False,
) -> list[str]:
    """Return owned catalog paths that are absent from the Git source set."""
    document = validate_component_manifest(manifest, root=root, check_paths=False)
    tracked = {
        _identity(_safe_posix_path(path, f"tracked_paths[{index}]"))
        for index, path in enumerate(tracked_paths)
    }
    return sorted(
        (
            path_entry["path"]
            for component in document["components"]
            for path_entry in component["paths"]
            if not (allow_missing_seed and path_entry["policy"] == "seed")
            if _identity(path_entry["path"]) not in tracked
        ),
        key=_identity,
    )
