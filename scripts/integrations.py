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
ENTRY_DIR = ROOT / "integrations" / "entries"
REFERENCE_PATH = ROOT / "references" / "integrations.md"
COMPONENT_MANIFEST_PATH = ROOT / "components" / "manifest.json"
FRESHNESS_REVIEW_DAYS = 90
FRESHNESS_DUE_SOON_DAYS = 30
FRESHNESS_STATES = ("current", "due_soon", "stale")

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


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        return load_entry_catalog()
    with path.open(encoding="utf-8") as handle:
        catalog = json.load(handle)
    validate_catalog(catalog)
    return catalog


def load_entry_catalog(directory: Path = ENTRY_DIR) -> dict[str, Any]:
    if not directory.is_dir():
        raise CatalogError(f"entry source directory does not exist: {directory}")
    children = sorted(directory.iterdir(), key=lambda path: path.name)
    if not children:
        raise CatalogError("entry source directory must not be empty")
    entries: list[dict[str, Any]] = []
    for path in children:
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise CatalogError(
                f"entry source directory contains an unsupported path: {path.name}"
            )
        try:
            with path.open(encoding="utf-8") as handle:
                entry = json.load(handle)
        except json.JSONDecodeError as exc:
            raise CatalogError(
                f"{path.name}: invalid JSON at line {exc.lineno}, "
                f"column {exc.colno}: {exc.msg}"
            ) from exc
        if not isinstance(entry, dict):
            raise CatalogError(f"{path.name}: expected an object")
        if entry.get("id") != path.stem:
            raise CatalogError(
                f"{path.name}: filename must exactly match entry id {entry.get('id')!r}"
            )
        entries.append(entry)
    catalog = {
        "schema_version": 2,
        "integrations": sorted(entries, key=lambda item: item["id"]),
    }
    validate_catalog(catalog)
    return catalog


def render_catalog(catalog: dict[str, Any]) -> str:
    return json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"


def render_component_manifest(catalog: dict[str, Any]) -> str:
    with COMPONENT_MANIFEST_PATH.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    entry_prefix = "integrations/entries/"
    owner = next(
        (
            component
            for component in manifest.get("components", [])
            if any(
                record.get("path") == "integrations/catalog.json"
                for record in component.get("paths", [])
                if isinstance(record, dict)
            )
        ),
        None,
    )
    if owner is None:
        raise CatalogError("component manifest does not own integrations/catalog.json")
    retained = [
        record
        for record in owner["paths"]
        if not str(record.get("path", "")).startswith(entry_prefix)
    ]
    try:
        catalog_index = next(
            index
            for index, record in enumerate(retained)
            if record.get("path") == "integrations/catalog.json"
        )
    except StopIteration as exc:
        raise CatalogError(
            "component manifest owner lost integrations/catalog.json"
        ) from exc
    generated = [
        {"path": f"{entry_prefix}{item['id']}.json", "policy": "development"}
        for item in catalog["integrations"]
    ]
    owner["paths"] = retained[: catalog_index + 1] + generated + retained[catalog_index + 1 :]
    return json.dumps(manifest, indent=4, ensure_ascii=False) + "\n"


def write_generated_text(path: Path, content: str, *, newline: str) -> None:
    # Spell each artifact's established newline explicitly so Linux and Windows
    # render identical bytes instead of inheriting the host text-mode default.
    with path.open("w", encoding="utf-8", newline=newline) as handle:
        handle.write(content)


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


def parse_report_date(value: str) -> dt.date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise CatalogError("--as-of: expected YYYY-MM-DD")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise CatalogError("--as-of: expected YYYY-MM-DD") from None


def freshness_report(catalog: dict[str, Any], as_of: dt.date) -> dict[str, Any]:
    entries = []
    summary = {state: 0 for state in FRESHNESS_STATES}
    for item in sorted(catalog["integrations"], key=lambda value: value["id"]):
        try:
            verified_on = dt.date.fromisoformat(item["last_verified"])
        except (TypeError, ValueError):
            raise CatalogError(
                f"{item['id']}.last_verified: expected YYYY-MM-DD"
            ) from None
        if verified_on > as_of:
            raise CatalogError(
                f"{item['id']}.last_verified: {verified_on.isoformat()} is after "
                f"report date {as_of.isoformat()}"
            )
        suggested_next_review = verified_on + dt.timedelta(
            days=FRESHNESS_REVIEW_DAYS
        )
        days_until_review = (suggested_next_review - as_of).days
        if days_until_review <= 0:
            state = "stale"
            action = (
                "Complete a human first-party-evidence review of every catalog claim "
                "before relying on it; update metadata only after that review."
            )
        elif days_until_review <= FRESHNESS_DUE_SOON_DAYS:
            state = "due_soon"
            action = (
                "Schedule a human first-party-evidence review before the suggested "
                "next review date."
            )
        else:
            state = "current"
            action = "No immediate action; review by the suggested next review date."
        summary[state] += 1
        entries.append(
            {
                "id": item["id"],
                "evidence_urls": list(item["evidence"]),
                "last_verified": verified_on.isoformat(),
                "freshness_state": state,
                "suggested_next_review": suggested_next_review.isoformat(),
                "days_until_review": days_until_review,
                "suggested_action": action,
            }
        )
    return {
        "schema_version": 1,
        "as_of": as_of.isoformat(),
        "policy": {
            "review_after_days": FRESHNESS_REVIEW_DAYS,
            "due_soon_when_days_remaining_at_most": FRESHNESS_DUE_SOON_DAYS,
            "states": list(FRESHNESS_STATES),
        },
        "summary": summary,
        "entries": entries,
    }


def render_freshness_markdown(report: dict[str, Any]) -> str:
    rows = []
    for item in report["entries"]:
        evidence = "<br>".join(
            f"[{index + 1}]({url})"
            for index, url in enumerate(item["evidence_urls"])
        )
        rows.append(
            f"| `{item['id']}` | `{item['freshness_state']}` | "
            f"{item['last_verified']} | {item['suggested_next_review']} | "
            f"{item['days_until_review']} | {evidence} | "
            f"{item['suggested_action']} |"
        )
    policy = report["policy"]
    return (
        "# Integration evidence freshness\n\n"
        f"As of `{report['as_of']}`. Evidence becomes stale "
        f"{policy['review_after_days']} days after `last_verified`; `due_soon` "
        f"begins when {policy['due_soon_when_days_remaining_at_most']} days remain.\n\n"
        "| Entry | State | Last verified | Suggested next review | Days remaining | Evidence | Maintainer response |\n"
        "|---|---|---|---|---:|---|---|\n"
        + "\n".join(rows)
        + "\n"
    )


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
        "<!-- Generated by scripts/integrations.py; edit integrations/entries/*.json instead. -->\n"
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
        + "\n\n".join(section.rstrip("\n") for section in sections)
        + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "render", "check", "freshness"))
    parser.add_argument("--as-of", help="freshness report date in YYYY-MM-DD")
    parser.add_argument("--format", choices=("json", "markdown"))
    args = parser.parse_args(argv)
    if args.command != "freshness" and (args.as_of or args.format):
        parser.error("--as-of and --format apply only to the freshness command")
    try:
        catalog = load_catalog()
        if args.command == "freshness":
            as_of = (
                parse_report_date(args.as_of)
                if args.as_of is not None
                else dt.date.today()
            )
            report = freshness_report(catalog, as_of)
            if args.format == "markdown":
                sys.stdout.write(render_freshness_markdown(report))
            else:
                sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
            return 0
        rendered_catalog = render_catalog(catalog)
        rendered_reference = render_reference(catalog)
        rendered_components = render_component_manifest(catalog)
    except (OSError, json.JSONDecodeError, CatalogError) as error:
        print(f"integration catalog error: {error}", file=sys.stderr)
        return 1
    if args.command == "render":
        write_generated_text(CATALOG_PATH, rendered_catalog, newline="\n")
        write_generated_text(REFERENCE_PATH, rendered_reference, newline="\n")
        write_generated_text(COMPONENT_MANIFEST_PATH, rendered_components, newline="\n")
    elif args.command == "check":
        expected_outputs = (
            (CATALOG_PATH, rendered_catalog),
            (REFERENCE_PATH, rendered_reference),
            (COMPONENT_MANIFEST_PATH, rendered_components),
        )
        for path, expected in expected_outputs:
            try:
                current = path.read_bytes().decode("utf-8")
            except OSError as error:
                print(f"integration catalog error: {error}", file=sys.stderr)
                return 1
            if current != expected:
                print(
                    f"{path.relative_to(ROOT).as_posix()} is stale; run: "
                    "python3 scripts/integrations.py render",
                    file=sys.stderr,
                )
                return 1
    print(f"Integration catalog {args.command} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
