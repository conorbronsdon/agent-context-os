"""Deterministic closure-aware shared entry surfaces for selected workspaces."""

from __future__ import annotations

import posixpath
import re
from typing import Any, Mapping, Sequence


RELATIVE_LINK_RE = re.compile(
    r"\[[^\]]*\]\((?!https?://|mailto:|#)([^)#]+)(?:#[^)]+)?\)"
)


def _selected_runtimes(
    config: Mapping[str, Any],
    runtimes: Mapping[str, Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    return [runtimes[runtime_id] for runtime_id in config["agents"]]


def _support_table(selected: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = ["| Host | Tier | Support |", "|---|---|---|"]
    if not selected:
        lines.append(
            "| Core-only | portable | No runtime adapter is selected; use the "
            "reviewed kernel proposal/apply workflow directly. |"
        )
    for runtime in selected:
        summary = str(runtime["support_summary"]).replace("|", "\\|")
        lines.append(
            f"| {runtime['display_name']} | {runtime['support_tier']} | {summary} |"
        )
    return lines


def _readme(config: Mapping[str, Any], selected: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Context OS",
        "",
        "<!-- contextos:closure-aware-generated owner=core -->",
        "",
        "This workspace is a pinned, reconstructable Context OS composition. Durable",
        "context lives in plain Markdown; local installation state lives under",
        "`.context-os/` and is not tracked.",
        "",
        "## Selected runtime support",
        "",
        *_support_table(selected),
        "",
        "## Lifecycle",
        "",
    ]
    if selected:
        lines.extend(
            f"- {runtime['display_name']}: "
            + ", ".join(
                f"{name} `{value}`"
                for name, value in next(iter(runtime["surfaces"].values()))[
                    "invocation"
                ].items()
            )
            for runtime in selected
        )
    else:
        lines.append(
            "- Use `scripts/contextos.sh` for read-only reports and reviewed proposal/apply."
        )
    lines.extend(
        [
            "",
            "Run `bash scripts/contextos.sh doctor` to compare tracked desired closure",
            "with `.context-os/installed-bundle.json`. Reconcile only from the exact",
            "local bundle digest pinned in `contextos.workspace.json`.",
            "",
            "## Safety and configuration",
            "",
            "- [Safety contract](docs/safety-contract.md)",
            "",
            f"Profile: `{config['composition']['profile']}`.",
        ]
    )
    for runtime in selected:
        onboarding = runtime.get("onboarding_doc")
        if onboarding:
            lines.append(f"- [{runtime['display_name']} onboarding]({onboarding})")
    return "\n".join(lines) + "\n"


def _agents(selected: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Context OS",
        "",
        "<!-- contextos:closure-aware-generated owner=agents-instructions -->",
        "",
        "This repository is the durable source of truth for personal, project, and",
        "session context. Read `ROUTING.md`, keep each fact in one canonical file,",
        "and use the lifecycle kernel's reviewed proposal/apply boundary for writes.",
        "",
        "Never commit or push without explicit approval. Follow",
        "`docs/safety-contract.md` before external, destructive, credential, or",
        "permission-changing actions. Host-local memory is never shared automatically.",
        "",
        "## Selected runtimes",
        "",
    ]
    for runtime in selected:
        invocation = next(iter(runtime["surfaces"].values()))["invocation"]
        rendered = ", ".join(f"{key} `{value}`" for key, value in invocation.items())
        lines.append(f"- {runtime['display_name']}: {rendered}.")
    lines.extend(
        [
            "",
            "Run `bash scripts/contextos.sh doctor` to diagnose desired/installed drift.",
        ]
    )
    return "\n".join(lines) + "\n"


def closure_aware_files(
    config: Mapping[str, Any],
    runtimes: Mapping[str, Mapping[str, Any]],
    desired_components: Sequence[str],
    *,
    source_texts: Mapping[str, str] | None = None,
    available_paths: Sequence[str] = (),
) -> dict[str, str]:
    """Return generated entry surfaces for selected profile only."""
    if config.get("composition", {}).get("profile") != "selected":
        return {}
    selected = _selected_runtimes(config, runtimes)
    result = {"README.md": _readme(config, selected)}
    if "agents-instructions" in desired_components:
        result["AGENTS.md"] = _agents(selected)
    if source_texts is not None:
        selected_paths = set(source_texts)
        available = set(available_paths)
        for path, text in source_texts.items():
            if not path.endswith(".md") or path in result:
                continue
            kept: list[str] = []
            changed = False
            for line in text.splitlines(keepends=True):
                omitted_link = False
                for link in RELATIVE_LINK_RE.findall(line):
                    target = posixpath.normpath(
                        posixpath.join(posixpath.dirname(path), link)
                    )
                    if target in available and target not in selected_paths:
                        omitted_link = True
                        break
                if omitted_link:
                    changed = True
                else:
                    kept.append(line)
            if changed:
                result[path] = "".join(kept)
    return result
