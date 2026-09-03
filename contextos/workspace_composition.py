"""Derive one deterministic component closure from workspace schema v2 intent."""

from __future__ import annotations

from typing import Any, Mapping

from .component_schema import component_closure, portable_path_identity
from .workspace_schema import LEGACY_WORKSPACE_SCHEMA_VERSION


class WorkspaceCompositionError(ValueError):
    """Raised when desired composition is internally contradictory."""


def component_ids(manifest: Mapping[str, Any]) -> list[str]:
    return sorted(
        (item["id"] for item in manifest["components"]),
        key=portable_path_identity,
    )


def runtime_required_components(
    config: Mapping[str, Any],
    manifest: Mapping[str, Any],
    runtimes: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    requested: set[str] = {"core"}
    for runtime_id in config["agents"]:
        runtime = runtimes.get(runtime_id)
        if runtime is None:
            raise WorkspaceCompositionError(
                f"workspace runtime {runtime_id!r} is unavailable"
            )
        requested.update(runtime["components"])
    return component_closure(manifest, sorted(requested, key=portable_path_identity))


def desired_component_closure(
    config: Mapping[str, Any],
    manifest: Mapping[str, Any],
    runtimes: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Return schema-v2 desired closure; reject redundant runtime components."""
    if config["schema_version"] == LEGACY_WORKSPACE_SCHEMA_VERSION:
        raise WorkspaceCompositionError(
            "schema v1 does not declare a reconstructable component closure"
        )
    composition = config["composition"]
    if composition["profile"] == "full-template":
        requested = component_ids(manifest)
    else:
        required = runtime_required_components(config, manifest, runtimes)
        redundant = sorted(
            set(composition["extras"]) & set(required), key=portable_path_identity
        )
        if redundant:
            raise WorkspaceCompositionError(
                "composition.extras duplicates runtime-required components: "
                + ", ".join(redundant)
            )
        requested = sorted(
            {"core", *required, *composition["extras"]},
            key=portable_path_identity,
        )
    return component_closure(manifest, requested)
