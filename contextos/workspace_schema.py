"""Canonical tracked workspace configuration and legacy migration helpers."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Sequence


WORKSPACE_SCHEMA_VERSION = 1
WORKSPACE_MODE = "full-template"
DEFAULT_TEMPLATE_VERSION = "0.12.0"
DEFAULT_TEMPLATE_SOURCE = "agent-context-os-template"
DEFAULT_PATHS = {
    "state_dir": "state",
    "sessions_dir": "sessions",
    "task_file": "TODO.md",
}
RUNTIME_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
TOP_LEVEL_KEYS = {"schema_version", "mode", "agents", "paths", "template"}
PATH_KEYS = {"state_dir", "sessions_dir", "task_file"}
TEMPLATE_KEYS = {"version", "source"}
LEGACY_KEYS = tuple(DEFAULT_PATHS)
RESERVED_AGENT_TOKENS = {"auto", "generic", "none"}
RESERVED_PATH_PARTS = {".git", ".context-os"}
WINDOWS_DEVICE_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
WINDOWS_ILLEGAL_CHARACTERS = set('<>:"|?*')


class WorkspaceConfigError(ValueError):
    """Raised when tracked workspace configuration is unsafe or ambiguous."""


@dataclass(frozen=True)
class LegacyAnalysis:
    values: dict[str, str]
    issues: tuple[str, ...]


def _fail(field: str, message: str) -> None:
    raise WorkspaceConfigError(f"{field}: {message}")


def portable_identity(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _exact_keys(value: Any, expected: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(field, "must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        _fail(field, "; ".join(details))
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail(field, "must be a non-empty string without surrounding whitespace")
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"}
        for character in value
    ):
        _fail(field, "must not contain control or format characters")
    return value


def validate_workspace_path(value: Any, field: str) -> str:
    raw = _text(value, field)
    if "\\" in raw:
        _fail(field, "must use POSIX separators")
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        _fail(field, "must be repository-relative")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _fail(field, "must be a canonical lexical path without empty, '.' or '..' segments")
    if posix.as_posix() != raw:
        _fail(field, "must be a canonical lexical POSIX path")
    portable_parts = tuple(portable_identity(part) for part in parts)
    if any(part in RESERVED_PATH_PARTS for part in portable_parts):
        _fail(field, "must not target repository metadata or local host state")
    if any(
        part.endswith((".", " "))
        or any(character in WINDOWS_ILLEGAL_CHARACTERS for character in part)
        or part.split(".", 1)[0] in WINDOWS_DEVICE_NAMES
        for part in portable_parts
    ):
        _fail(field, "must not use a Windows-aliased or illegal path segment")
    return raw


def normalize_legacy_workspace_path(value: Any, field: str) -> str:
    """Canonicalize only spellings the historical reader treated identically."""
    raw = _text(value, field)
    if "\\" in raw:
        _fail(field, "backslash semantics differ by host; use POSIX separators")
    if PurePosixPath(raw).is_absolute() or PureWindowsPath(raw).drive:
        _fail(field, "must be repository-relative")
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if not parts or ".." in parts:
        _fail(field, "cannot normalize an empty path or '..' segment losslessly")
    return validate_workspace_path("/".join(parts), field)


def _reject_path_role_collisions(paths: dict[str, str]) -> None:
    identities = {key: portable_identity(value) for key, value in paths.items()}
    if len(set(identities.values())) != len(identities):
        _fail("paths", "state_dir, sessions_dir, and task_file must be distinct")
    state_parts = identities["state_dir"].split("/")
    session_parts = identities["sessions_dir"].split("/")
    if (
        state_parts[: len(session_parts)] == session_parts
        or session_parts[: len(state_parts)] == state_parts
    ):
        _fail("paths", "state_dir and sessions_dir must not contain one another")
    task_parts = identities["task_file"].split("/")
    if (
        state_parts[: len(task_parts)] == task_parts
        or session_parts[: len(task_parts)] == task_parts
    ):
        _fail("paths", "task_file must not be an ancestor of a configured directory")


def validate_workspace_config(
    value: Any, *, known_runtime_ids: Iterable[str]
) -> dict[str, Any]:
    document = _exact_keys(value, TOP_LEVEL_KEYS, "workspace")
    if (
        type(document.get("schema_version")) is not int
        or document["schema_version"] != WORKSPACE_SCHEMA_VERSION
    ):
        _fail("schema_version", f"must equal integer {WORKSPACE_SCHEMA_VERSION}")
    if document.get("mode") != WORKSPACE_MODE:
        _fail("mode", f"must equal {WORKSPACE_MODE!r}")

    raw_agents = document.get("agents")
    if not isinstance(raw_agents, list):
        _fail("agents", "must be an array")
    known = set(known_runtime_ids)
    agents: list[str] = []
    seen: set[str] = set()
    for index, raw_agent in enumerate(raw_agents):
        agent = _text(raw_agent, f"agents[{index}]")
        if not RUNTIME_ID_RE.fullmatch(agent) or agent in RESERVED_AGENT_TOKENS:
            _fail(f"agents[{index}]", "must be a registered lowercase runtime id")
        identity = portable_identity(agent)
        if identity in seen:
            _fail("agents", f"duplicate runtime id {agent!r}")
        if agent not in known:
            _fail(f"agents[{index}]", f"unknown runtime id {agent!r}")
        seen.add(identity)
        agents.append(agent)

    raw_paths = _exact_keys(document.get("paths"), PATH_KEYS, "paths")
    paths = {
        key: validate_workspace_path(raw_paths.get(key), f"paths.{key}")
        for key in LEGACY_KEYS
    }
    _reject_path_role_collisions(paths)

    raw_template = _exact_keys(document.get("template"), TEMPLATE_KEYS, "template")
    template = {
        "version": _text(raw_template.get("version"), "template.version"),
        "source": _text(raw_template.get("source"), "template.source"),
    }
    return {
        "schema_version": WORKSPACE_SCHEMA_VERSION,
        "mode": WORKSPACE_MODE,
        "agents": sorted(agents),
        "paths": paths,
        "template": template,
    }


def render_workspace_config(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def parse_agent_selection(
    raw: str, *, known_runtime_ids: Iterable[str], allow_auto: bool = False
) -> list[str] | None:
    if not isinstance(raw, str) or not raw.strip():
        _fail("agents", "selection must not be empty")
    tokens = [token.strip() for token in raw.split(",")]
    if any(not token for token in tokens):
        _fail("agents", "selection must not contain empty tokens")
    if tokens == ["auto"]:
        if allow_auto:
            return None
        _fail("agents", "auto is local launch behavior and cannot become tracked intent")
    if "auto" in tokens:
        _fail("agents", "auto cannot be combined with runtime ids")
    if tokens == ["none"]:
        return []
    if "none" in tokens:
        _fail("agents", "none cannot be combined with runtime ids")
    probe = {
        "schema_version": WORKSPACE_SCHEMA_VERSION,
        "mode": WORKSPACE_MODE,
        "agents": tokens,
        "paths": DEFAULT_PATHS,
        "template": {
            "version": DEFAULT_TEMPLATE_VERSION,
            "source": DEFAULT_TEMPLATE_SOURCE,
        },
    }
    return validate_workspace_config(probe, known_runtime_ids=known_runtime_ids)["agents"]


def _reject_constant(value: str) -> None:
    raise WorkspaceConfigError(f"JSON constant {value!r} is not allowed")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkspaceConfigError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def strict_json_loads(raw: str, *, source: str) -> Any:
    if raw.startswith("\ufeff"):
        raise WorkspaceConfigError(f"{source}: UTF-8 BOM is not allowed")
    try:
        return json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise WorkspaceConfigError(
            f"{source}: invalid JSON at line {exc.lineno} column {exc.colno}"
        ) from exc


def load_workspace_config(
    path: Path, *, root: Path, known_runtime_ids: Iterable[str]
) -> tuple[dict[str, Any], bool]:
    if path.is_symlink():
        raise WorkspaceConfigError(f"{path.name}: must not be a symlink")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise WorkspaceConfigError(f"{path}: must remain inside the workspace") from exc
    current = root
    for part in relative.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise WorkspaceConfigError(
                f"{path.name}: must not traverse symlink {current.relative_to(root)}"
            )
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WorkspaceConfigError(f"cannot read {path}: {exc}") from exc
    document = validate_workspace_config(
        strict_json_loads(raw, source=path.name),
        known_runtime_ids=known_runtime_ids,
    )
    return document, raw == render_workspace_config(document)


def _strip_yaml_comment(raw: str) -> str:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(raw):
        if quote == '"' and escaped:
            escaped = False
            continue
        if quote == '"' and character == "\\":
            escaped = True
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            continue
        if character == "#" and quote is None:
            return raw[:index]
    return raw


def _legacy_scalar(raw: str, *, line_number: int) -> str:
    value = _strip_yaml_comment(raw).strip()
    if not value:
        raise WorkspaceConfigError(f"workspace.yaml line {line_number}: empty value")
    if value[0] in "&*![]{}|>":
        raise WorkspaceConfigError(
            f"workspace.yaml line {line_number}: unsupported YAML scalar"
        )
    if value[0] in {"'", '"'}:
        quote = value[0]
        if len(value) < 2 or value[-1] != quote:
            raise WorkspaceConfigError(
                f"workspace.yaml line {line_number}: unterminated quoted value"
            )
        if quote == "'":
            value = value[1:-1].replace("''", "'")
        else:
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise WorkspaceConfigError(
                    f"workspace.yaml line {line_number}: invalid quoted value"
                ) from exc
    return normalize_legacy_workspace_path(
        value, f"workspace.yaml line {line_number}"
    )


def analyze_legacy_workspace(text: str) -> LegacyAnalysis:
    values: dict[str, str] = {}
    issues: list[str] = []
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line[:1].isspace():
            issues.append(f"line {line_number}: nested YAML is unsupported")
            continue
        line = _strip_yaml_comment(raw_line).strip()
        if not line:
            continue
        if line.startswith("-") or ":" not in line:
            issues.append(f"line {line_number}: unsupported YAML structure")
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if key not in LEGACY_KEYS:
            issues.append(f"line {line_number}: unsupported key {key!r}")
            continue
        if key in values:
            issues.append(f"line {line_number}: duplicate key {key!r}")
            continue
        try:
            values[key] = _legacy_scalar(raw_value, line_number=line_number)
        except WorkspaceConfigError as exc:
            issues.append(str(exc))
    return LegacyAnalysis(values=values, issues=tuple(issues))


def legacy_workspace_values(text: str) -> dict[str, str]:
    """Preserve the historical permissive reader until migration is applied."""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if key in LEGACY_KEYS and value:
            values[key] = value
    return values


def workspace_schema_document() -> dict[str, Any]:
    text = {
        "type": "string",
        "minLength": 1,
        "pattern": r"^(?!\s)(?:[^\u0000-\u001f\u007f]*\S)$",
    }
    path = {
        **text,
        "pattern": r"^(?!\s)"
        r"(?![^\u0000-\u001f\u007f]*[\u0000-\u001f\u007f])"
        r"(?![A-Za-z]:)(?![/\\])(?!.*\\)"
        r"(?!.*(?:^|/)\.\.?(?:/|$))"
        r"(?!.*//)(?!.*(?:^|/)(?:\.git|\.context-os)(?:/|$))"
        r"(?:[^\u0000-\u001f\u007f]*[^\u0000-\u001f\u007f\s])$",
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$comment": (
            "Generated structural subset. contextos.workspace_schema is authoritative "
            "for runtime-registry membership, portable path safety, semantic set "
            "uniqueness, role collisions, and canonical rendering."
        ),
        "title": "Context OS tracked workspace configuration",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "mode", "agents", "paths", "template"],
        "properties": {
            "schema_version": {"const": WORKSPACE_SCHEMA_VERSION},
            "mode": {"const": WORKSPACE_MODE},
            "agents": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "pattern": RUNTIME_ID_RE.pattern},
            },
            "paths": {
                "type": "object",
                "additionalProperties": False,
                "required": list(LEGACY_KEYS),
                "properties": {key: path for key in LEGACY_KEYS},
            },
            "template": {
                "type": "object",
                "additionalProperties": False,
                "required": ["version", "source"],
                "properties": {"version": text, "source": text},
            },
        },
    }
