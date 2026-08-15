#!/usr/bin/env python3
"""Validate the optional integration catalog and generate its Markdown view."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "integrations" / "catalog.json"
REFERENCE_PATH = ROOT / "references" / "integrations.md"

KINDS = {
    "mcp_server",
    "skill_catalog",
    "workspace_template",
    "resource_catalog",
    "local_workspace",
    "editor_guide",
    "agent_extension",
    "connector",
}
AGENTS = {"claude_code", "codex", "gemini_cli", "cursor", "opencode", "generic"}
SCOPES = {"none", "project", "user", "project_or_user"}
MATURITY = {"verified", "listed", "experimental"}
CONFIRMATIONS = {"credential_setup", "external_install", "write", "publish", "destructive"}
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class CatalogError(ValueError):
    pass


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        catalog = json.load(handle)
    validate_catalog(catalog)
    return catalog


def require_exact_keys(value: dict[str, Any], expected: set[str], location: str) -> None:
    missing = expected - set(value)
    extra = set(value) - expected
    if missing or extra:
        raise CatalogError(
            f"{location}: key mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
        )


def require_string_list(value: Any, location: str, *, nonempty: bool = False) -> None:
    if not isinstance(value, list) or (nonempty and not value):
        raise CatalogError(f"{location}: expected {'a non-empty ' if nonempty else ''}array")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise CatalogError(f"{location}: every item must be a non-empty string")
    if len(value) != len(set(value)):
        raise CatalogError(f"{location}: duplicate values are not allowed")


def validate_catalog(catalog: Any) -> None:
    if not isinstance(catalog, dict):
        raise CatalogError("catalog: expected an object")
    require_exact_keys(catalog, {"schema_version", "integrations"}, "catalog")
    if catalog["schema_version"] != 1 or type(catalog["schema_version"]) is not int:
        raise CatalogError("catalog.schema_version: expected integer 1")
    if not isinstance(catalog["integrations"], list):
        raise CatalogError("catalog.integrations: expected an array")

    ids: set[str] = set()
    names: set[str] = set()
    expected = {
        "id", "name", "summary", "source_url", "kind", "supported_agents",
        "installation", "data_boundary", "capabilities", "confirmation", "risk_tags",
        "maturity", "last_verified", "health_check", "uninstall",
    }
    for index, item in enumerate(catalog["integrations"]):
        location = f"catalog.integrations[{index}]"
        if not isinstance(item, dict):
            raise CatalogError(f"{location}: expected an object")
        require_exact_keys(item, expected, location)
        for field in ("name", "summary", "health_check", "uninstall"):
            if not isinstance(item[field], str) or not item[field].strip():
                raise CatalogError(f"{location}.{field}: expected a non-empty string")
        if not isinstance(item["id"], str) or not ID_PATTERN.fullmatch(item["id"]):
            raise CatalogError(f"{location}.id: expected a stable kebab-case ID")
        if item["id"] in ids:
            raise CatalogError(f"{location}.id: duplicate ID {item['id']!r}")
        ids.add(item["id"])
        normalized_name = item["name"].casefold()
        if normalized_name in names:
            raise CatalogError(f"{location}.name: duplicate name {item['name']!r}")
        names.add(normalized_name)
        if not isinstance(item["source_url"], str) or not item["source_url"].startswith("https://"):
            raise CatalogError(f"{location}.source_url: expected an HTTPS URL")
        if item["kind"] not in KINDS:
            raise CatalogError(f"{location}.kind: unsupported integration kind")
        require_string_list(item["supported_agents"], f"{location}.supported_agents", nonempty=True)
        if not set(item["supported_agents"]) <= AGENTS:
            raise CatalogError(f"{location}.supported_agents: unsupported agent")

        installation = item["installation"]
        if not isinstance(installation, dict):
            raise CatalogError(f"{location}.installation: expected an object")
        require_exact_keys(installation, {"automatic", "scope", "prerequisites"}, f"{location}.installation")
        if installation["automatic"] is not False:
            raise CatalogError(f"{location}.installation.automatic: must remain false")
        if installation["scope"] not in SCOPES:
            raise CatalogError(f"{location}.installation.scope: unsupported scope")
        require_string_list(installation["prerequisites"], f"{location}.installation.prerequisites")

        boundary = item["data_boundary"]
        if not isinstance(boundary, dict):
            raise CatalogError(f"{location}.data_boundary: expected an object")
        require_exact_keys(boundary, {"credentials", "reads", "writes"}, f"{location}.data_boundary")
        for field in ("credentials", "reads", "writes"):
            require_string_list(boundary[field], f"{location}.data_boundary.{field}")

        capabilities = item["capabilities"]
        if not isinstance(capabilities, dict):
            raise CatalogError(f"{location}.capabilities: expected an object")
        require_exact_keys(capabilities, {"read", "write", "publish", "destructive", "details"}, f"{location}.capabilities")
        for field in ("read", "write", "publish", "destructive"):
            if type(capabilities[field]) is not bool:
                raise CatalogError(f"{location}.capabilities.{field}: expected a boolean")
        require_string_list(capabilities["details"], f"{location}.capabilities.details", nonempty=True)

        confirmation = item["confirmation"]
        if not isinstance(confirmation, dict):
            raise CatalogError(f"{location}.confirmation: expected an object")
        require_exact_keys(confirmation, {"required_for", "notes"}, f"{location}.confirmation")
        require_string_list(confirmation["required_for"], f"{location}.confirmation.required_for")
        if not set(confirmation["required_for"]) <= CONFIRMATIONS:
            raise CatalogError(f"{location}.confirmation.required_for: unsupported boundary")
        if not isinstance(confirmation["notes"], str) or not confirmation["notes"].strip():
            raise CatalogError(f"{location}.confirmation.notes: expected a non-empty string")
        for capability in ("write", "publish", "destructive"):
            if capabilities[capability] and capability not in confirmation["required_for"]:
                raise CatalogError(f"{location}: {capability} capability requires an explicit confirmation boundary")
        if installation["scope"] != "none" and "external_install" not in confirmation["required_for"]:
            raise CatalogError(f"{location}: installable entries require an external_install boundary")
        if boundary["credentials"] and "credential_setup" not in confirmation["required_for"]:
            raise CatalogError(f"{location}: credentialed entries require a credential_setup boundary")

        require_string_list(item["risk_tags"], f"{location}.risk_tags", nonempty=True)
        if item["maturity"] not in MATURITY:
            raise CatalogError(f"{location}.maturity: unsupported maturity")
        try:
            dt.date.fromisoformat(item["last_verified"])
        except (TypeError, ValueError):
            raise CatalogError(f"{location}.last_verified: expected YYYY-MM-DD") from None


def yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def render_reference(catalog: dict[str, Any]) -> str:
    rows = []
    sections = []
    for item in sorted(catalog["integrations"], key=lambda value: value["name"].casefold()):
        caps = item["capabilities"]
        rows.append(
            f"| [{item['name']}]({item['source_url']}) | `{item['kind']}` | "
            f"{item['maturity']} | {yes_no(caps['write'])} | {yes_no(caps['publish'])} | "
            f"{yes_no(caps['destructive'])} | {item['last_verified']} |"
        )
        agents = ", ".join(f"`{agent}`" for agent in item["supported_agents"])
        prerequisites = "; ".join(item["installation"]["prerequisites"]) or "None"
        credentials = "; ".join(item["data_boundary"]["credentials"]) or "None"
        reads = "; ".join(item["data_boundary"]["reads"]) or "None"
        writes = "; ".join(item["data_boundary"]["writes"]) or "None"
        details = "\n".join(f"- {detail}" for detail in caps["details"])
        sections.append(
            f"## {item['name']}\n\n"
            f"{item['summary']}\n\n"
            f"- **Supported agents:** {agents}\n"
            f"- **Install scope:** `{item['installation']['scope']}`; never automatic\n"
            f"- **Prerequisites:** {prerequisites}\n"
            f"- **Credentials:** {credentials}\n"
            f"- **Reads:** {reads}\n"
            f"- **Writes / external effects:** {writes}\n"
            f"- **Confirmation:** {item['confirmation']['notes']}\n"
            f"- **Risk tags:** {', '.join(f'`{tag}`' for tag in item['risk_tags'])}\n"
            f"- **Health check:** {item['health_check']}\n"
            f"- **Uninstall:** {item['uninstall']}\n\n"
            f"Capabilities and limits:\n\n{details}\n"
        )
    return (
        "<!-- Generated by scripts/integrations.py; edit integrations/catalog.json instead. -->\n"
        "# Optional integrations\n\n"
        "These add-ons are **references, not bundled dependencies**. Setup does not install, "
        "activate, authenticate, or expand permissions for any entry. Review the current source, "
        "data boundary, and side effects before opting in. `listed` and `experimental` do not mean "
        "the integration has been verified end to end.\n\n"
        "| Integration | Kind | Maturity | Writes | Publishes | Destructive | Last verified |\n"
        "|---|---|---|---:|---:|---:|---|\n"
        + "\n".join(rows)
        + "\n\n"
        + "\n\n".join(sections)
        + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "render", "check"))
    args = parser.parse_args(argv)
    try:
        catalog = load_catalog()
        rendered = render_reference(catalog)
    except (OSError, json.JSONDecodeError, CatalogError) as error:
        print(f"integration catalog error: {error}", file=sys.stderr)
        return 1
    if args.command == "render":
        REFERENCE_PATH.write_text(rendered, encoding="utf-8")
    elif args.command == "check":
        try:
            current = REFERENCE_PATH.read_text(encoding="utf-8")
        except OSError as error:
            print(f"integration catalog error: {error}", file=sys.stderr)
            return 1
        if current != rendered:
            print("references/integrations.md is stale; run: python3 scripts/integrations.py render", file=sys.stderr)
            return 1
    print(f"Integration catalog {args.command} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
