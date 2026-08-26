from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlparse


RUNTIME_DESCRIPTOR_SCHEMA_VERSION = 2
RUNTIME_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
COMPONENT_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
EXECUTABLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
SAFE_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")

CAPABILITY_VALUES = {"native", "adapter", "advisory", "unsupported"}
CAPABILITY_KEYS = {
    "agent_skills",
    "explicit_invocation",
    "project_hooks",
    "blocking_pre_tool_hook",
    "mcp",
    "native_memory",
    "proposal_apply",
    "skill_allowlists",
    "execution_authorization",
}
SUPPORT_TIERS = {"first-class", "experimental", "compatibility", "deprecated"}
SURFACE_KINDS = {"cli", "ide", "cloud", "review", "gateway", "messaging", "environment"}
HOOK_OUTPUT_MODES = {"system-message", "allow-message"}
PROBE_PURPOSES = {"availability", "version", "native-doctor"}
INVOCATION_KEYS = {"setup", "start", "update", "end"}
TOP_LEVEL_KEYS = {
    "schema_version", "runtime", "display_name", "support_tier", "support_summary",
    "components", "install", "onboarding_doc", "surfaces", "evidence",
}
SURFACE_KEYS = {
    "kind", "support_tier", "instruction_sources", "skill_sources", "invocation",
    "capabilities", "hook_output", "binary_probes", "conformance_tests", "evidence",
}
POSITIVE_CAPABILITIES = CAPABILITY_VALUES - {"unsupported"}
EVIDENCE_CLAIMS = CAPABILITY_KEYS | {
    "hook_output", "instruction_sources", "invocation", "skill_sources", "support"
}
SOURCE_SCOPES = {"repository", "workspace", "user", "runtime"}
SOURCE_ROLES = {"canonical", "additive", "memory", "persona", "skills"}
SOURCE_KEYS = {"scope", "role", "path", "precedence"}
EVIDENCE_SOURCE_KEYS = {"id", "type", "location", "claims"}
EVIDENCE_SOURCE_TYPES = {"official", "conformance"}


class RuntimeManifestError(ValueError):
    pass


def _fail(field: str, message: str) -> None:
    raise RuntimeManifestError(f"{field}: {message}")


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


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail(field, "must be a non-empty string without surrounding whitespace")
    if any(ord(character) < 32 for character in value):
        _fail(field, "must not contain control characters")
    return value


def _nullable_string(value: Any, field: str) -> str | None:
    return None if value is None else _string(value, field)


def _enum(value: Any, allowed: set[str], field: str) -> str:
    result = _string(value, field)
    if result not in allowed:
        _fail(field, f"unsupported value {result!r}")
    return result


def _unique_strings(value: Any, field: str, *, minimum: int = 0) -> list[str]:
    if not isinstance(value, list):
        _fail(field, "must be an array")
    result = [_string(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(result) < minimum:
        _fail(field, f"must contain at least {minimum} item(s)")
    if len(result) != len(set(result)):
        _fail(field, "must not contain duplicates")
    return result


def _repo_path(root: Path, value: Any, field: str, *, must_exist: bool = True) -> str:
    raw = _string(value, field)
    if "\\" in raw:
        _fail(field, "must use repository-relative POSIX separators")
    relative = Path(raw)
    if relative.is_absolute():
        _fail(field, "must be repository-relative")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        _fail(field, "must not escape the repository")
    if must_exist and not resolved.exists():
        _fail(field, f"path does not exist: {raw}")
    return raw


def _source_reference(
    root: Path, value: Any, field: str, *, check_paths: bool
) -> None:
    source = _exact_keys(value, SOURCE_KEYS, field)
    scope = _enum(source.get("scope"), SOURCE_SCOPES, f"{field}.scope")
    _enum(source.get("role"), SOURCE_ROLES, f"{field}.role")
    path = _string(source.get("path"), f"{field}.path")
    precedence = source.get("precedence")
    if type(precedence) is not int or precedence < 0:
        _fail(f"{field}.precedence", "must be a non-negative integer")
    if scope == "repository":
        _repo_path(root, path, f"{field}.path", must_exist=check_paths)
    elif (
        PurePosixPath(path).is_absolute()
        or PureWindowsPath(path).is_absolute()
        or "\\" in path
        or ".." in PurePosixPath(path).parts
    ):
        _fail(f"{field}.path", "must be a safe logical relative path")


def _schema_string() -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "pattern": r"^(?!\s)(?:[^\x00-\x1f]*\S)$"}


def validate_runtime_manifest(
    manifest: Any, *, runtime_id: str, root: Path, today: date | None = None,
    check_paths: bool = True,
) -> dict[str, Any]:
    if runtime_id == "generic" or not RUNTIME_ID_RE.fullmatch(runtime_id):
        _fail("runtime", f"invalid or reserved runtime id {runtime_id!r}")
    document = _exact_keys(manifest, TOP_LEVEL_KEYS, "manifest")
    if document.get("schema_version") != RUNTIME_DESCRIPTOR_SCHEMA_VERSION:
        _fail("schema_version", f"must equal {RUNTIME_DESCRIPTOR_SCHEMA_VERSION}")
    if document.get("runtime") != runtime_id:
        _fail("runtime", f"must match filename stem {runtime_id!r}")

    _string(document.get("display_name"), "display_name")
    _enum(document.get("support_tier"), SUPPORT_TIERS, "support_tier")
    _string(document.get("support_summary"), "support_summary")
    components = _unique_strings(document.get("components"), "components", minimum=1)
    for index, component in enumerate(components):
        if not COMPONENT_ID_RE.fullmatch(component):
            _fail(f"components[{index}]", f"invalid component id {component!r}")

    install = _exact_keys(document.get("install"), {"mode", "next_steps"}, "install")
    _string(install.get("mode"), "install.mode")
    _unique_strings(install.get("next_steps"), "install.next_steps", minimum=1)
    _repo_path(
        root, document.get("onboarding_doc"), "onboarding_doc", must_exist=check_paths
    )

    evidence = _exact_keys(
        document.get("evidence"), {"checked_on", "tested_versions", "sources"}, "evidence"
    )
    checked_on = _string(evidence.get("checked_on"), "evidence.checked_on")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", checked_on):
        _fail("evidence.checked_on", "must use YYYY-MM-DD format")
    try:
        checked_date = date.fromisoformat(checked_on)
    except ValueError:
        _fail("evidence.checked_on", "must be an ISO-8601 date")
    if check_paths and checked_date > (today or date.today()) + timedelta(days=1):
        _fail("evidence.checked_on", "must not be more than one day in the future")

    sources = evidence.get("sources")
    if not isinstance(sources, list) or not sources:
        _fail("evidence.sources", "must be a non-empty array")
    source_claims: dict[str, tuple[str, set[str], str]] = {}
    for index, source in enumerate(sources):
        field = f"evidence.sources[{index}]"
        item = _exact_keys(source, EVIDENCE_SOURCE_KEYS, field)
        source_id = _string(item.get("id"), f"{field}.id")
        if not SAFE_ID_RE.fullmatch(source_id):
            _fail(f"{field}.id", f"invalid evidence id {source_id!r}")
        if source_id in source_claims:
            _fail("evidence.sources", f"duplicate evidence id {source_id!r}")
        source_type = _enum(item.get("type"), EVIDENCE_SOURCE_TYPES, f"{field}.type")
        location = _string(item.get("location"), f"{field}.location")
        if source_type == "official":
            parsed = urlparse(location)
            if parsed.scheme != "https" or not parsed.netloc:
                _fail(f"{field}.location", "official evidence must be an absolute HTTPS URL")
        else:
            _repo_path(root, location, f"{field}.location", must_exist=check_paths)
        claims = _unique_strings(item.get("claims"), f"{field}.claims", minimum=1)
        for claim_index, claim in enumerate(claims):
            _enum(claim, EVIDENCE_CLAIMS, f"{field}.claims[{claim_index}]")
        source_claims[source_id] = (source_type, set(claims), location)

    surfaces = document.get("surfaces")
    if not isinstance(surfaces, dict) or not surfaces:
        _fail("surfaces", "must be a non-empty object")
    if len(surfaces) != len({key.casefold() for key in surfaces}):
        _fail("surfaces", "surface ids must be unique when case-folded")

    parsed_surfaces: dict[str, dict[str, Any]] = {}
    for surface_id, raw_surface in surfaces.items():
        field = f"surfaces.{surface_id}"
        if not isinstance(surface_id, str) or not SAFE_ID_RE.fullmatch(surface_id):
            _fail("surfaces", f"invalid surface id {surface_id!r}")
        surface = _exact_keys(raw_surface, SURFACE_KEYS, field)
        _enum(surface.get("kind"), SURFACE_KINDS, f"{field}.kind")
        tier = _enum(surface.get("support_tier"), SUPPORT_TIERS, f"{field}.support_tier")
        for source_field in ("instruction_sources", "skill_sources"):
            references = surface.get(source_field)
            if not isinstance(references, list):
                _fail(f"{field}.{source_field}", "must be an array")
            seen_references: set[tuple[str, str]] = set()
            seen_precedence: set[int] = set()
            for index, reference in enumerate(references):
                reference_field = f"{field}.{source_field}[{index}]"
                _source_reference(root, reference, reference_field, check_paths=check_paths)
                identity = (reference["scope"], reference["path"])
                if identity in seen_references:
                    _fail(f"{field}.{source_field}", f"duplicate source {identity!r}")
                seen_references.add(identity)
                if reference["precedence"] in seen_precedence:
                    _fail(
                        f"{field}.{source_field}",
                        f"duplicate precedence {reference['precedence']}",
                    )
                seen_precedence.add(reference["precedence"])
        invocation = _exact_keys(surface.get("invocation"), INVOCATION_KEYS, f"{field}.invocation")
        for key, value in invocation.items():
            _nullable_string(value, f"{field}.invocation.{key}")
        capabilities = _exact_keys(surface.get("capabilities"), CAPABILITY_KEYS, f"{field}.capabilities")
        for key, value in capabilities.items():
            _enum(value, CAPABILITY_VALUES, f"{field}.capabilities.{key}")
        hook_output = surface.get("hook_output")
        if hook_output is not None:
            _enum(hook_output, HOOK_OUTPUT_MODES, f"{field}.hook_output")

        probes = surface.get("binary_probes")
        if not isinstance(probes, list):
            _fail(f"{field}.binary_probes", "must be an array")
        probe_purposes: set[str] = set()
        for index, probe in enumerate(probes):
            probe_field = f"{field}.binary_probes[{index}]"
            item = _exact_keys(probe, {"purpose", "candidates"}, probe_field)
            purpose = _enum(item.get("purpose"), PROBE_PURPOSES, f"{probe_field}.purpose")
            if purpose in probe_purposes:
                _fail(f"{field}.binary_probes", f"duplicate purpose {purpose!r}")
            probe_purposes.add(purpose)
            candidates = _unique_strings(item.get("candidates"), f"{probe_field}.candidates", minimum=1)
            for candidate_index, candidate in enumerate(candidates):
                if not EXECUTABLE_RE.fullmatch(candidate):
                    _fail(f"{probe_field}.candidates[{candidate_index}]", "invalid executable name")

        conformance_tests = _unique_strings(
            surface.get("conformance_tests"), f"{field}.conformance_tests", minimum=1
        )
        for index, conformance_test in enumerate(conformance_tests):
            _repo_path(
                root, conformance_test, f"{field}.conformance_tests[{index}]",
                must_exist=check_paths,
            )
        evidence_ids = _unique_strings(surface.get("evidence"), f"{field}.evidence", minimum=1)
        unknown_evidence = sorted(set(evidence_ids) - set(source_claims))
        if unknown_evidence:
            _fail(f"{field}.evidence", f"unknown evidence ids: {', '.join(unknown_evidence)}")
        covered = set().union(*(source_claims[item][1] for item in evidence_ids))
        required_claims = {
            key for key, value in capabilities.items() if value in POSITIVE_CAPABILITIES
        }
        required_claims.add("support")
        if surface["instruction_sources"]:
            required_claims.add("instruction_sources")
        if surface["skill_sources"]:
            required_claims.add("skill_sources")
        if any(value is not None for value in invocation.values()):
            required_claims.add("invocation")
        if hook_output is not None:
            required_claims.add("hook_output")
        missing_claims = sorted(required_claims - covered)
        if missing_claims:
            _fail(f"{field}.evidence", f"does not cover claims: {', '.join(missing_claims)}")
        for capability, value in capabilities.items():
            if value not in POSITIVE_CAPABILITIES:
                continue
            required_type = "official" if value == "native" else "conformance"
            if not any(
                source_claims[evidence_id][0] == required_type
                and capability in source_claims[evidence_id][1]
                and (
                    required_type != "conformance"
                    or source_claims[evidence_id][2] in conformance_tests
                )
                for evidence_id in evidence_ids
            ):
                _fail(
                    f"{field}.evidence",
                    f"{capability}={value} requires {required_type} evidence",
                )
        parsed_surfaces[surface_id] = {"tier": tier}

        if tier == "first-class" and any(value is None for value in invocation.values()):
            _fail(f"{field}.invocation", "first-class surfaces require all lifecycle invocations")

    tested_versions = evidence.get("tested_versions")
    if not isinstance(tested_versions, list):
        _fail("evidence.tested_versions", "must be an array")
    tested_surface_ids: set[str] = set()
    for index, tested in enumerate(tested_versions):
        field = f"evidence.tested_versions[{index}]"
        item = _exact_keys(tested, {"surface", "version"}, field)
        surface_id = _string(item.get("surface"), f"{field}.surface")
        if surface_id not in parsed_surfaces:
            _fail(f"{field}.surface", f"unknown surface {surface_id!r}")
        if surface_id in tested_surface_ids:
            _fail("evidence.tested_versions", f"duplicate surface {surface_id!r}")
        tested_surface_ids.add(surface_id)
        _string(item.get("version"), f"{field}.version")
    first_class = {
        surface_id for surface_id, item in parsed_surfaces.items() if item["tier"] == "first-class"
    }
    if missing := sorted(first_class - tested_surface_ids):
        _fail("evidence.tested_versions", f"missing first-class surfaces: {', '.join(missing)}")
    if document["support_tier"] == "first-class" and not first_class:
        _fail("support_tier", "first-class runtimes require a first-class surface")
    tier_rank = {"first-class": 0, "experimental": 1, "compatibility": 2, "deprecated": 3}
    strongest_surface_tier = min(
        (item["tier"] for item in parsed_surfaces.values()), key=tier_rank.__getitem__
    )
    if document["support_tier"] != strongest_surface_tier:
        _fail("support_tier", f"must match strongest surface tier {strongest_surface_tier!r}")
    return document


def runtime_schema_document() -> dict[str, Any]:
    text = _schema_string()
    nullable_text = {"oneOf": [text, {"type": "null"}]}
    capability_properties = {
        key: {"enum": sorted(CAPABILITY_VALUES)} for key in sorted(CAPABILITY_KEYS)
    }
    source_reference = {
        "type": "object", "additionalProperties": False, "required": sorted(SOURCE_KEYS),
        "properties": {
            "scope": {"enum": sorted(SOURCE_SCOPES)},
            "role": {"enum": sorted(SOURCE_ROLES)},
            "path": text,
            "precedence": {"type": "integer", "minimum": 0},
        },
    }
    surface = {
        "type": "object", "additionalProperties": False, "required": sorted(SURFACE_KEYS),
        "properties": {
            "kind": {"enum": sorted(SURFACE_KINDS)},
            "support_tier": {"enum": sorted(SUPPORT_TIERS)},
            "instruction_sources": {"type": "array", "uniqueItems": True, "items": source_reference},
            "skill_sources": {"type": "array", "uniqueItems": True, "items": source_reference},
            "invocation": {"type": "object", "additionalProperties": False,
                "required": sorted(INVOCATION_KEYS),
                "properties": {key: nullable_text for key in sorted(INVOCATION_KEYS)}},
            "capabilities": {"type": "object", "additionalProperties": False,
                "required": sorted(CAPABILITY_KEYS), "properties": capability_properties},
            "hook_output": {"oneOf": [{"enum": sorted(HOOK_OUTPUT_MODES)}, {"type": "null"}]},
            "binary_probes": {"type": "array", "items": {"type": "object",
                "additionalProperties": False,
                "required": ["candidates", "purpose"],
                "properties": {
                    "purpose": {"enum": sorted(PROBE_PURPOSES)},
                    "candidates": {"type": "array", "minItems": 1, "uniqueItems": True,
                        "items": {"type": "string", "pattern": EXECUTABLE_RE.pattern}},
                }}},
            "conformance_tests": {
                "type": "array", "minItems": 1, "uniqueItems": True, "items": text
            },
            "evidence": {"type": "array", "minItems": 1, "uniqueItems": True, "items": text},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$comment": (
            "Generated structural subset. contextos.runtime_schema is authoritative for "
            "repository paths, evidence coverage, dates, reserved IDs, and cross-field rules."
        ),
        "title": "Context OS runtime descriptor", "type": "object",
        "additionalProperties": False, "required": sorted(TOP_LEVEL_KEYS),
        "properties": {
            "schema_version": {"const": RUNTIME_DESCRIPTOR_SCHEMA_VERSION},
            "runtime": {"type": "string", "pattern": r"^(?!generic$)[a-z][a-z0-9-]*$"},
            "display_name": text,
            "support_tier": {"enum": sorted(SUPPORT_TIERS)},
            "support_summary": text,
            "components": {"type": "array", "minItems": 1, "uniqueItems": True,
                "items": {"type": "string", "pattern": COMPONENT_ID_RE.pattern}},
            "install": {"type": "object", "additionalProperties": False,
                "required": ["mode", "next_steps"],
                "properties": {"mode": text, "next_steps": {"type": "array", "minItems": 1,
                    "uniqueItems": True, "items": text}}},
            "onboarding_doc": text,
            "surfaces": {"type": "object", "minProperties": 1,
                "propertyNames": {"pattern": SAFE_ID_RE.pattern}, "additionalProperties": surface},
            "evidence": {"type": "object", "additionalProperties": False,
                "required": ["checked_on", "sources", "tested_versions"],
                "properties": {
                    "checked_on": {"type": "string", "format": "date"},
                    "tested_versions": {"type": "array", "items": {"type": "object",
                        "additionalProperties": False, "required": ["surface", "version"],
                        "properties": {"surface": text, "version": text}}},
                    "sources": {"type": "array", "minItems": 1, "items": {"type": "object",
                        "additionalProperties": False, "required": sorted(EVIDENCE_SOURCE_KEYS),
                        "properties": {"id": {"type": "string", "pattern": SAFE_ID_RE.pattern},
                            "type": {"enum": sorted(EVIDENCE_SOURCE_TYPES)},
                            "location": text,
                            "claims": {"type": "array", "minItems": 1, "uniqueItems": True,
                                "items": {"enum": sorted(EVIDENCE_CLAIMS)}}}}},
                }},
        },
    }
