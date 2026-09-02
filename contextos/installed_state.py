"""Validation for machine-local bundle materialization state."""

from __future__ import annotations

import re
from typing import Any


INSTALLED_STATE_SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_KEYS = {"schema_version", "bundle", "components", "plan_digest"}
BUNDLE_KEYS = {"name", "version", "sha256", "source_git_commit"}


class InstalledStateError(ValueError):
    """Raised when installed-bundle.json is malformed."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise InstalledStateError(f"{field}: must be a non-empty string")
    return value


def validate_installed_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != TOP_LEVEL_KEYS:
        raise InstalledStateError("installed bundle state has an invalid shape")
    if value.get("schema_version") != INSTALLED_STATE_SCHEMA_VERSION:
        raise InstalledStateError("installed bundle state schema_version must equal 1")
    bundle = value.get("bundle")
    if not isinstance(bundle, dict) or set(bundle) != BUNDLE_KEYS:
        raise InstalledStateError("installed bundle identity has an invalid shape")
    parsed_bundle = {
        key: _text(bundle.get(key), f"bundle.{key}")
        for key in ("name", "version")
    }
    source_git_commit = bundle.get("source_git_commit")
    if source_git_commit is not None and not isinstance(source_git_commit, str):
        raise InstalledStateError("bundle.source_git_commit must be a string or null")
    parsed_bundle["source_git_commit"] = source_git_commit
    digest = bundle.get("sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise InstalledStateError("bundle.sha256 must be a lowercase SHA-256 digest")
    parsed_bundle["sha256"] = digest
    components = value.get("components")
    if (
        not isinstance(components, list)
        or any(not isinstance(item, str) or not item for item in components)
        or len(components) != len(set(components))
    ):
        raise InstalledStateError("components must be a unique string array")
    plan_digest = value.get("plan_digest")
    if not isinstance(plan_digest, str) or not SHA256_RE.fullmatch(plan_digest):
        raise InstalledStateError("plan_digest must be a lowercase SHA-256 digest")
    return {
        "schema_version": INSTALLED_STATE_SCHEMA_VERSION,
        "bundle": parsed_bundle,
        "components": components,
        "plan_digest": plan_digest,
    }
