#!/usr/bin/env python3
"""Validate the optional integration catalog and generate its Markdown view."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


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
CONFIRMATIONS = {
    "credential_setup",
    "external_install",
    "read_sensitive",
    "write",
    "write_remote",
    "publish",
    "overwrite",
    "delete",
    "arbitrary_execution",
    "oauth",
    "destructive",
}
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CAPABILITY_FIELDS = {
    "read",
    "sensitive_read",
    "write",
    "remote_write",
    "publish",
    "overwrite",
    "delete",
    "arbitrary_execution",
    "oauth",
    "destructive",
    "details",
}
CONFIRMATION_BY_CAPABILITY = {
    "sensitive_read": "read_sensitive",
    "write": "write",
    "remote_write": "write_remote",
    "publish": "publish",
    "overwrite": "overwrite",
    "delete": "delete",
    "arbitrary_execution": "arbitrary_execution",
    "oauth": "oauth",
    "destructive": "destructive",
}
RISK_TAG_BY_CAPABILITY = {
    "sensitive_read": "sensitive-read",
    "remote_write": "remote-write",
    "publish": "publish-capable",
    "overwrite": "overwrite-capable",
    "delete": "delete-capable",
    "arbitrary_execution": "arbitrary-execution",
    "oauth": "oauth",
    "destructive": "destructive-capable",
}


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
    for index, item in enumerate(value):
        require_safe_text(item, f"{location}[{index}]")
    if len(value) != len(set(value)):
        raise CatalogError(f"{location}: duplicate values are not allowed")


def require_safe_text(value: Any, location: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{location}: expected a non-empty string")
    if value != value.strip() or any(
        unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"}
        for character in value
    ):
        raise CatalogError(f"{location}: surrounding whitespace and control/format characters are not allowed")


def require_https_url(value: Any, location: str) -> None:
    require_safe_text(value, location)
    if any(character.isspace() for character in value) or any(
        character in value for character in "()|[]<>\\`"
    ):
        raise CatalogError(f"{location}: URL contains unsafe Markdown characters")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise CatalogError(f"{location}: URL is malformed") from None
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and not 1 <= port <= 65535)
        or parsed.query
        or parsed.fragment
    ):
        raise CatalogError(f"{location}: expected an HTTPS URL with a host and no credentials")


def canonical_url(value: str) -> str:
    """Normalize obvious syntactic duplicates without resolving remote URL semantics."""
    parsed = urlsplit(value)
    host = parsed.hostname.lower()
    port = f":{parsed.port}" if parsed.port and parsed.port != 443 else ""
    path = parsed.path.rstrip("/")
    return urlunsplit(("https", host + port, path, parsed.query, parsed.fragment))


def validate_catalog(catalog: Any) -> None:
    if not isinstance(catalog, dict):
        raise CatalogError("catalog: expected an object")
    require_exact_keys(catalog, {"schema_version", "integrations"}, "catalog")
    if catalog["schema_version"] != 2 or type(catalog["schema_version"]) is not int:
        raise CatalogError("catalog.schema_version: expected integer 2")
    if not isinstance(catalog["integrations"], list) or not catalog["integrations"]:
        raise CatalogError("catalog.integrations: expected a non-empty array")

    ids: set[str] = set()
    names: set[str] = set()
    source_urls: set[str] = set()
    expected = {
        "id", "name", "summary", "source_url", "kind", "supported_agents",
        "installation", "data_boundary", "capabilities", "confirmation", "risk_tags",
        "maturity", "last_verified", "evidence", "health_check", "uninstall",
    }
    for index, item in enumerate(catalog["integrations"]):
        location = f"catalog.integrations[{index}]"
        if not isinstance(item, dict):
            raise CatalogError(f"{location}: expected an object")
        require_exact_keys(item, expected, location)
        for field in ("name", "summary", "health_check"):
            require_safe_text(item[field], f"{location}.{field}")
        if any(character in item["name"] for character in "|[]"):
            raise CatalogError(f"{location}.name: Markdown table/link delimiters are not allowed")
        if not isinstance(item["id"], str) or not ID_PATTERN.fullmatch(item["id"]):
            raise CatalogError(f"{location}.id: expected a stable kebab-case ID")
        if item["id"] in ids:
            raise CatalogError(f"{location}.id: duplicate ID {item['id']!r}")
        ids.add(item["id"])
        normalized_name = re.sub(
            r"\s+", " ", unicodedata.normalize("NFKC", item["name"]).strip()
        ).casefold()
        if normalized_name in names:
            raise CatalogError(f"{location}.name: duplicate name {item['name']!r}")
        names.add(normalized_name)
        require_https_url(item["source_url"], f"{location}.source_url")
        normalized_url = canonical_url(item["source_url"])
        if normalized_url in source_urls:
            raise CatalogError(f"{location}.source_url: duplicate canonical source URL")
        source_urls.add(normalized_url)
        require_string_list(item["evidence"], f"{location}.evidence", nonempty=True)
        for evidence_index, evidence_url in enumerate(item["evidence"]):
            require_https_url(evidence_url, f"{location}.evidence[{evidence_index}]")
        if not isinstance(item["kind"], str) or item["kind"] not in KINDS:
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
        if not isinstance(installation["scope"], str) or installation["scope"] not in SCOPES:
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
        require_exact_keys(capabilities, CAPABILITY_FIELDS, f"{location}.capabilities")
        for field in CAPABILITY_FIELDS - {"details"}:
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
        require_safe_text(confirmation["notes"], f"{location}.confirmation.notes")
        if re.search(
            r"\b(?:no|without) (?:confirmation|approval|review|permission)\b|"
            r"\b(?:confirmation|approval|review|permission) (?:is |are )?not (?:needed|required)\b",
            confirmation["notes"].casefold(),
        ):
            raise CatalogError(f"{location}.confirmation.notes: may not waive structured confirmation gates")
        for capability, confirmation_name in CONFIRMATION_BY_CAPABILITY.items():
            if capabilities[capability] and confirmation_name not in confirmation["required_for"]:
                raise CatalogError(
                    f"{location}: {capability} capability requires {confirmation_name!r} confirmation"
                )
        if bool(boundary["reads"]) != capabilities["read"]:
            raise CatalogError(f"{location}: data reads and read capability must agree")
        if bool(boundary["writes"]) != capabilities["write"]:
            raise CatalogError(f"{location}: data writes and write capability must agree")
        for capability in ("remote_write", "publish", "overwrite", "delete", "arbitrary_execution"):
            if capabilities[capability] and not capabilities["write"]:
                raise CatalogError(f"{location}: {capability} capability requires write capability")
        if capabilities["publish"] and not capabilities["remote_write"]:
            raise CatalogError(f"{location}: publish capability requires remote_write capability")
        if capabilities["sensitive_read"] and not capabilities["read"]:
            raise CatalogError(f"{location}: sensitive_read capability requires read capability")
        if any(capabilities[field] for field in ("overwrite", "delete", "arbitrary_execution")) and not capabilities["destructive"]:
            raise CatalogError(f"{location}: overwrite, delete, and arbitrary_execution require destructive capability")
        if capabilities["oauth"] and not boundary["credentials"]:
            raise CatalogError(f"{location}: oauth capability requires a credential boundary")
        if installation["scope"] != "none" and "external_install" not in confirmation["required_for"]:
            raise CatalogError(f"{location}: installable entries require an external_install boundary")
        if boundary["credentials"] and "credential_setup" not in confirmation["required_for"]:
            raise CatalogError(f"{location}: credentialed entries require a credential_setup boundary")

        require_string_list(item["risk_tags"], f"{location}.risk_tags", nonempty=True)
        if not all(ID_PATTERN.fullmatch(tag) for tag in item["risk_tags"]):
            raise CatalogError(f"{location}.risk_tags: expected kebab-case tags")
        for capability, risk_tag in RISK_TAG_BY_CAPABILITY.items():
            if capabilities[capability] and risk_tag not in item["risk_tags"]:
                raise CatalogError(f"{location}: {capability} capability requires {risk_tag!r} risk tag")

        semantic_text = " ".join(
            boundary["credentials"]
            + boundary["reads"]
            + boundary["writes"]
            + capabilities["details"]
            + item["risk_tags"]
        ).casefold()
        semantic_requirements = {
            "sensitive_read": r"\btranscripts?\b|\bsensitive-read\b",
            "remote_write": r"\b(?:git|dolt) push\b|\bremote (?:sync|push|write)\b|\bunattended pushes?\b|\bpublish(?:es|ing)?\b|\bunpublish\b|\bpublicly fetchable\b|\bimmediately public\b|\b(?:sync|upload|send|push|write|copy)\b.{0,80}\b(?:cloud|remote|server|repository)\b",
            "overwrite": r"\boverwrite\b|\breplacement\b|\bfull-content\b|--force\b|\bdiscard-remote\b|\breset operations?\b",
            "delete": r"\bdelet(?:e|ion)\b|\bpurge\b|\btrash\b|\bremoval\b|\buninstall removes\b",
            "arbitrary_execution": r"\barbitrary (?:registered )?(?:command|eval|execution)\b|\barbitrary-(?:eval|execution)\b|\bshell access\b|\b(?:run|execute) any (?:javascript|js|code|command)\b|\bjavascript supplied by\b",
            "oauth": r"\boauth\b",
        }
        for capability, pattern in semantic_requirements.items():
            if re.search(pattern, semantic_text) and not capabilities[capability]:
                raise CatalogError(f"{location}: metadata describes {capability} but the typed capability is false")

        uninstall = item["uninstall"]
        if not isinstance(uninstall, dict):
            raise CatalogError(f"{location}.uninstall: expected an object")
        require_exact_keys(uninstall, {"instructions", "removes_user_data"}, f"{location}.uninstall")
        require_safe_text(uninstall["instructions"], f"{location}.uninstall.instructions")
        if type(uninstall["removes_user_data"]) is not bool:
            raise CatalogError(f"{location}.uninstall.removes_user_data: expected a boolean")
        data_loss_language = re.search(
            r"\b(?:delete|erase|wipe|destroy|purge|reset)\b.{0,80}\b(?:data|history|notes|project|vault|files|records)\b|\bremove all (?:project |user )?files\b",
            uninstall["instructions"].casefold(),
        )
        if data_loss_language and not uninstall["removes_user_data"]:
            raise CatalogError(f"{location}.uninstall: data-loss instructions require removes_user_data=true")
        if uninstall["removes_user_data"] and not (
            capabilities["delete"] and capabilities["destructive"]
        ):
            raise CatalogError(f"{location}.uninstall: user-data removal requires delete and destructive capabilities")
        if not isinstance(item["maturity"], str) or item["maturity"] not in MATURITY:
            raise CatalogError(f"{location}.maturity: unsupported maturity")
        try:
            verified_on = dt.date.fromisoformat(item["last_verified"])
        except (TypeError, ValueError):
            raise CatalogError(f"{location}.last_verified: expected YYYY-MM-DD") from None
        if verified_on > dt.date.today():
            raise CatalogError(f"{location}.last_verified: future dates are not allowed")


def yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def markdown_text(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in "`~*_[]<>|":
        escaped = escaped.replace(character, "\\" + character)
    return escaped


def markdown_paragraph(value: str) -> str:
    escaped = markdown_text(value)
    if value.startswith(("#", "-", "+")) or re.match(r"^\d+[.)]\s", value):
        return "\\" + escaped
    return escaped


def render_reference(catalog: dict[str, Any]) -> str:
    rows = []
    sections = []
    for item in sorted(catalog["integrations"], key=lambda value: value["name"].casefold()):
        caps = item["capabilities"]
        name = markdown_text(item["name"])
        rows.append(
            f"| [{name}]({item['source_url']}) | `{item['kind']}` | "
            f"{item['maturity']} | {yes_no(caps['write'])} | {yes_no(caps['remote_write'])} | "
            f"{yes_no(caps['publish'])} | {yes_no(caps['sensitive_read'])} | "
            f"{yes_no(caps['destructive'])} | {item['last_verified']} |"
        )
        agents = ", ".join(f"`{agent}`" for agent in item["supported_agents"])
        prerequisites = "; ".join(map(markdown_text, item["installation"]["prerequisites"])) or "None"
        credentials = "; ".join(map(markdown_text, item["data_boundary"]["credentials"])) or "None"
        reads = "; ".join(map(markdown_text, item["data_boundary"]["reads"])) or "None"
        writes = "; ".join(map(markdown_text, item["data_boundary"]["writes"])) or "None"
        details = "\n".join(f"- {markdown_text(detail)}" for detail in caps["details"])
        signals = ", ".join(
            name.replace("_", " ")
            for name in ("sensitive_read", "remote_write", "overwrite", "delete", "arbitrary_execution", "oauth")
            if caps[name]
        ) or "None"
        evidence = "; ".join(f"[{index + 1}]({url})" for index, url in enumerate(item["evidence"]))
        required_for = ", ".join(f"`{gate}`" for gate in item["confirmation"]["required_for"]) or "None"
        sections.append(
            f"## {name}\n\n"
            f"{markdown_paragraph(item['summary'])}\n\n"
            f"- **Supported agents:** {agents}\n"
            f"- **Install scope:** `{item['installation']['scope']}`; never automatic\n"
            f"- **Prerequisites:** {prerequisites}\n"
            f"- **Credentials:** {credentials}\n"
            f"- **Reads:** {reads}\n"
            f"- **Writes / external effects:** {writes}\n"
            f"- **Typed safety signals:** {signals}\n"
            f"- **Required confirmation gates:** {required_for}\n"
            f"- **Confirmation:** {markdown_text(item['confirmation']['notes'])}\n"
            f"- **Risk tags:** {', '.join(f'`{tag}`' for tag in item['risk_tags'])}\n"
            f"- **Evidence:** {evidence}\n"
            f"- **Health check:** {markdown_text(item['health_check'])}\n"
            f"- **Uninstall:** {markdown_text(item['uninstall']['instructions'])} "
            f"(removes user data: {yes_no(item['uninstall']['removes_user_data'])})\n\n"
            f"Capabilities and limits:\n\n{details}\n"
        )
    return (
        "<!-- Generated by scripts/integrations.py; edit integrations/catalog.json instead. -->\n"
        "# Optional integrations\n\n"
        "These add-ons are **references, not bundled dependencies**. Setup does not install, "
        "activate, authenticate, or expand permissions for any entry. Review the current source, "
        "data boundary, and side effects before opting in. `verified` means the catalog metadata "
        "was checked against the linked source on the stated date; it is not a live authentication "
        "or end-to-end test. `listed` and `experimental` are leads, not endorsements.\n\n"
        "| Integration | Kind | Maturity | Writes | Remote writes | Publishes | Sensitive reads | Destructive | Last verified |\n"
        "|---|---|---|---:|---:|---:|---:|---:|---|\n"
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
