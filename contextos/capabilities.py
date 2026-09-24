"""Read-only capability and skill views from runtime and component metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .component_schema import component_owners, load_component_manifest
from .installed_state import validate_installed_state
from .kernel import ContextOSError, runtime_ids, runtime_manifest
from .materializer import INSTALLED_STATE_PATH
from .primitives import read_regular_file_snapshot
from .workspace_schema import load_workspace_config, strict_json_loads


NOTE = (
    "Availability is not permission or activation. Component install state describes "
    "recorded repository components, not host installation."
)


def _installed_components(root: Path) -> set[str] | None:
    path = root / INSTALLED_STATE_PATH
    if not path.exists() and not path.is_symlink():
        return None
    raw, _ = read_regular_file_snapshot(path, subject="installed bundle state")
    state = validate_installed_state(
        strict_json_loads(raw.decode("utf-8"), source=INSTALLED_STATE_PATH)
    )
    return set(state["components"])


def _selection(root: Path, requested: list[str], known: list[str], components: dict[str, Any]) -> list[str]:
    if requested:
        selected = [agent.strip() for value in requested for agent in value.split(",")]
        if any(not agent for agent in selected):
            raise ContextOSError("--agent selection must not contain empty ids")
        if len(selected) != len(set(selected)):
            raise ContextOSError("duplicate --agent id")
        unknown = sorted(set(selected) - set(known))
        if unknown:
            raise ContextOSError("unknown agent id: " + ", ".join(unknown))
        return sorted(selected)
    path = root / "contextos.workspace.json"
    if not path.exists() and not path.is_symlink():
        raise ContextOSError("no agents selected; use --agent or select agents in contextos.workspace.json")
    config, _ = load_workspace_config(
        path, root=root, known_runtime_ids=known,
        known_component_ids=[item["id"] for item in components["components"]],
    )
    if not config["agents"]:
        raise ContextOSError("no agents selected; use --agent or select agents in contextos.workspace.json")
    return config["agents"]


def _status(supported: bool, owners: set[str], installed: set[str] | None) -> str:
    if not supported:
        return "unsupported"
    if installed is None:
        return "unknown-install-state"
    if not owners.issubset(installed):
        return "not-installed"
    return "installed"


def _runtime_specific_components(agent_id: str, descriptors: dict[str, dict[str, Any]]) -> set[str]:
    shared = set().union(*(
        set(descriptor["components"])
        for other_id, descriptor in descriptors.items() if other_id != agent_id
    ))
    specific = set(descriptors[agent_id]["components"]) - shared
    if not specific:
        raise ContextOSError(f"no runtime-specific components for agent {agent_id}")
    return specific


def _capability_detail(value: str, adapter_components: set[str], installed: set[str] | None) -> dict[str, Any]:
    if value == "unsupported":
        return {"value": value, "install_state": "unsupported"}
    if value in {"native", "advisory"}:
        return {"value": value, "install_state": "host-provided"}
    return {
        "value": value,
        "install_state": _status(True, adapter_components, installed),
        "required_components": sorted(adapter_components),
    }


def capability_report(root: Path, requested: list[str]) -> dict[str, Any]:
    known = runtime_ids(root)
    components = load_component_manifest(root / "components/manifest.json", root=root, check_paths=False)
    selected = _selection(root, requested, known, components)
    owners = component_owners(components)
    installed = _installed_components(root)
    descriptors = {
        agent_id: runtime_manifest(root, agent_id, check_paths=False)
        for agent_id in known
    }
    agents: dict[str, Any] = {}
    for agent_id in selected:
        descriptor = descriptors[agent_id]
        adapter_components = _runtime_specific_components(agent_id, descriptors)
        surfaces: dict[str, Any] = {}
        for surface_id, surface in sorted(descriptor["surfaces"].items()):
            capabilities = {
                key: _capability_detail(value, adapter_components, installed)
                for key, value in sorted(surface["capabilities"].items())
            }
            skills: dict[str, Any] = {}
            if surface["capabilities"]["agent_skills"] != "unsupported":
                for source in surface["skill_sources"]:
                    # A workspace copy at this canonical path carries the same
                    # portable files. Other workspace paths have no ownership map.
                    if source["scope"] not in {"repository", "workspace"}:
                        continue
                    if source["scope"] == "workspace" and source["path"] != ".agents/skills":
                        continue
                    prefix = source["path"].rstrip("/") + "/"
                    for path, owner in sorted(owners.items()):
                        if not path.startswith(prefix) or not path.endswith("/SKILL.md"):
                            continue
                        skill_id = path[len(prefix):].split("/", 1)[0]
                        if path != f"{prefix}{skill_id}/SKILL.md":
                            continue
                        skills[skill_id] = {
                            "path": path,
                            "component": owner,
                            "portable": owner == "portable-skills",
                            "install_state": _status(True, {owner}, installed),
                        }
            surfaces[surface_id] = {
                "kind": surface["kind"],
                "support_tier": surface["support_tier"],
                "capabilities": capabilities,
                "skills": dict(sorted(skills.items())),
            }
        agents[agent_id] = {
            "display_name": descriptor["display_name"],
            "support_tier": descriptor["support_tier"],
            "surfaces": surfaces,
        }

    portable_sets = [
        {skill for surface in agent["surfaces"].values()
         for skill, detail in surface["skills"].items() if detail["portable"]}
        for agent in agents.values()
    ]
    common = sorted(set.intersection(*portable_sets)) if portable_sets else []
    values = {
        agent_id: {f"{surface_id}.{key}": detail["value"]
                   for surface_id, surface in agent["surfaces"].items()
                   for key, detail in surface["capabilities"].items()}
        for agent_id, agent in agents.items()
    }
    keys = sorted(set().union(*(set(items) for items in values.values())))
    differing = {
        key: {agent_id: items.get(key) for agent_id, items in values.items()}
        for key in keys
        if len({items.get(key) for items in values.values()}) > 1
    } if len(agents) > 1 else {}
    only = {}
    for agent_id, agent in agents.items():
        other_skills = set().union(*(
            {skill for surface in other["surfaces"].values() for skill in surface["skills"]}
            for other_id, other in agents.items() if other_id != agent_id
        ))
        own_skills = {skill for surface in agent["surfaces"].values() for skill in surface["skills"]}
        only[agent_id] = {
            "skills": sorted(own_skills - other_skills) if len(agents) > 1 else [],
            "capabilities": sorted(
                key for key, value in values[agent_id].items()
                if value != "unsupported" and all(
                    other.get(key) in {None, "unsupported"}
                    for other_id, other in values.items() if other_id != agent_id
                )
            ) if len(agents) > 1 else [],
        }
    return {
        "schema_version": 1,
        "installed_state": "present" if installed is not None else "absent",
        "agents": agents,
        "comparison": {
            "common_portable_skills": common if len(agents) > 1 else [],
            "differing_capabilities": differing,
            "per_agent_only": only,
        },
        "note": NOTE,
    }


def render_capabilities(report: dict[str, Any]) -> str:
    lines = ["Agent capabilities"]
    for agent_id, agent in report["agents"].items():
        lines.append(f"\n{agent['display_name']} ({agent_id}) - {agent['support_tier']}")
        for surface_id, surface in agent["surfaces"].items():
            lines.append(f"  {surface_id} ({surface['kind']}) - {surface['support_tier']}")
            for key, detail in surface["capabilities"].items():
                required = detail.get("required_components", [])
                gate = f" (requires {', '.join(required)})" if required else ""
                lines.append(f"    {key}: {detail['value']} [{detail['install_state']}]{gate}")
            lines.append("    skills:")
            for skill, detail in surface["skills"].items():
                lines.append(f"      {skill}: {detail['component']} [{detail['install_state']}]")
            if not surface["skills"]:
                lines.append("      (none described)")
    comparison = report["comparison"]
    lines.append("\nComparison")
    lines.append("  common portable skills: " + (", ".join(comparison["common_portable_skills"]) or "(none)"))
    lines.append("  differing capabilities:")
    for key, values in comparison["differing_capabilities"].items():
        lines.append("    " + key + ": " + ", ".join(
            f"{agent}={value if value is not None else 'absent'}" for agent, value in values.items()
        ))
    if not comparison["differing_capabilities"]:
        lines.append("    (none)")
    lines.append("  per-agent-only items:")
    for agent, detail in comparison["per_agent_only"].items():
        lines.append(f"    {agent}: skills={', '.join(detail['skills']) or '(none)'}; "
                     f"capabilities={', '.join(detail['capabilities']) or '(none)'}")
    lines.append("\nInstall states")
    lines.append("  unsupported: capability is not claimed")
    lines.append("  host-provided: native or advisory host claim; no repository component gate")
    lines.append("  installed: required repository components are recorded")
    lines.append("  not-installed: a required repository component is absent")
    lines.append("  unknown-install-state: installed-bundle.json is absent")
    lines.append("\n" + report["note"])
    return "\n".join(lines)
