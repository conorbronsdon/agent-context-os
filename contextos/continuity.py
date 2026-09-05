"""Read-only, source-attributed continuity views over existing kernel evidence."""

from __future__ import annotations

import re
import stat
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .attachment import RootRoles
from .kernel import (
    ContextOSError, _guard_local_state_path, _state_freshness, load_workspace,
    safe_repo_path, start_report, validate_proposal,
)
from .primitives import read_regular_file_snapshot, sha256_bytes
from .workspace_schema import strict_json_loads

MAX_BYTES = 1024 * 1024
MAX_RECEIPTS = 1000


def _display_path(raw: str) -> str:
    """Validate a receipt label without opening or resolving its historical target."""
    if (not raw or "\\" in raw or PurePosixPath(raw).is_absolute()
            or PureWindowsPath(raw).drive or any(p in {"", ".", ".."} for p in raw.split("/"))
            or any(ord(c) < 32 or ord(c) == 127 or c in '<>:"|?*' for c in raw)):
        raise ContextOSError("history path must be a canonical repository-relative label")
    return raw


def _text(root: Path, path: Path) -> str:
    _guard_local_state_path(root, path)
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ContextOSError("source must be a regular file")
    if metadata.st_size > MAX_BYTES:
        raise ContextOSError("source exceeds the 1 MiB report limit")
    raw, _ = read_regular_file_snapshot(path, subject="continuity source")
    if len(raw) > MAX_BYTES:
        raise ContextOSError("source exceeds the 1 MiB report limit")
    return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _object(root: Path, path: Path) -> dict[str, Any]:
    value = strict_json_loads(_text(root, path), source=path.name)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def briefing_report(
    root: Path, now: datetime, *, sources: list[str] | None = None,
    roles: RootRoles | None = None,
) -> dict[str, Any]:
    """Expose the fixed lifecycle sources plus explicitly selected Markdown files.

    This is a preview, not evidence that a host loaded the files. Routing prose
    is never interpreted as permission to expand the read set.
    """
    root = root.resolve()
    if len(set(sources or [])) > 24:
        raise ContextOSError("select at most 24 additional context sources")
    report = start_report(root, now, roles=roles)
    workspace = load_workspace(root)
    paths = [("ROUTING.md", "routing")]
    paths.extend((path, "session state") for path in report["state"])
    decisions = _guard_local_state_path(root, workspace.state_dir / "decisions.md")
    paths.append((decisions.as_posix(), "recent decisions"))
    if report["latest_session"]:
        paths.append((report["latest_session"], "latest session"))
    for source in sources or []:
        path = safe_repo_path(root, source)
        if path.suffix.lower() != ".md":
            raise ContextOSError("explicit context sources must be Markdown files")
        paths.append((path.relative_to(root).as_posix(), "explicit task source"))
    selected = []
    seen = set()
    for relative, reason in paths:
        if relative in seen:
            continue
        seen.add(relative)
        item: dict[str, Any] = {"path": relative, "reason": reason}
        path = root / relative
        try:
            body = _text(root, path)
            item.update(report["state"].get(relative) or _state_freshness(path, now.date(), 90))
            lines = body.splitlines()
            if reason == "recent decisions":
                rows = [line for line in lines if line.startswith("|")]
                excerpt = "\n".join(rows[-5:])
            else:
                excerpt = "\n".join(lines[:24])
            item.update({
                "sha256": sha256_bytes(body.encode("utf-8")),
                "characters": len(body), "excerpt": excerpt[:2400],
                "excerpt_truncated": excerpt != body.rstrip("\n") or len(excerpt) > 2400,
            })
        except (OSError, ValueError, ContextOSError) as exc:
            item.update({"freshness_status": "unavailable", "unavailable_reason": str(exc)})
        selected.append(item)
    report.update({
        "sources": selected,
        "source_scope": "preview of lifecycle and explicitly selected sources; not a host read log",
        "freshness_notice": "Dates are review signals, not proof that a claim is correct.",
        "writes": False,
    })
    return report


def history_report(root: Path, *, limit: int = 10, path: str | None = None, details: bool = False) -> dict[str, Any]:
    """Read local receipts; include only diffs bound to the recorded proposal.

    Receipts are local, editable evidence. Neither runtime nor approver identity
    is authenticated. Absence of a receipt never proves absence of a write.
    """
    root = root.resolve()
    if not 1 <= limit <= 100:
        raise ContextOSError("history limit must be between 1 and 100")
    selected_path = _display_path(path) if path else None
    directory = root / ".context-os" / "receipts"
    _guard_local_state_path(root, directory)
    entries, warnings = [], []
    candidates = []
    if directory.exists():
        if not directory.is_dir():
            raise ContextOSError("local receipts path must be a directory")
        for candidate in directory.iterdir():
            if candidate.suffix == ".json":
                candidates.append(candidate)
                if len(candidates) > MAX_RECEIPTS:
                    raise ContextOSError("history exceeds 1000 receipts; archive reviewed local evidence before retrying")
    for candidate in sorted(candidates):
        relative = candidate.relative_to(root).as_posix()
        try:
            _display_path(relative)
            receipt = _object(root, candidate)
            identifier = receipt.get("proposal_id")
            if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", identifier):
                raise ValueError("invalid proposal identifier")
            timestamp = receipt.get("applied_at")
            if not isinstance(timestamp, str):
                raise ValueError("missing applied_at")
            parsed = datetime.fromisoformat(timestamp)
            if parsed.tzinfo is None:
                raise ValueError("applied_at needs a timezone")
            changes = receipt.get("files_changed")
            if not isinstance(changes, list) or not changes:
                raise ValueError("missing changed files")
            files = []
            for change in changes:
                if not isinstance(change, dict) or not isinstance(change.get("path"), str):
                    raise ValueError("invalid changed file")
                # Validate spelling and containment, but never read a receipt's target.
                target = _display_path(change["path"])
                raw_hashes = "sha256_before_raw" in change
                before_key, after_key = (("sha256_before_raw", "sha256_after_raw") if raw_hashes
                                         else ("sha256_before", "sha256_after"))
                if before_key not in change or after_key not in change:
                    raise ValueError("missing change hashes")
                before, after = change[before_key], change[after_key]
                for digest in (before, after):
                    if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
                        raise ValueError("invalid change hash")
                item = {"path": target, "sha256_before": before, "sha256_after": after}
                if raw_hashes:
                    item["hash_basis"] = "raw bytes"
                files.append(item)
            if selected_path and not any(f["path"] == selected_path for f in files):
                continue
            runtime = receipt.get("runtime")
            if not isinstance(runtime, str) or not re.fullmatch(r"[a-z0-9_-]+", runtime):
                raise ValueError("invalid self-reported runtime")
            entry = {"receipt": relative, "applied_at": timestamp, "runtime": runtime,
                     "proposal_id": identifier, "files_changed": files, "proposal_status": "not requested"}
            if details:
                try:
                    proposal = _object(root, root / ".context-os" / "proposals" / f"{identifier}.json")
                    if validate_proposal(proposal) != receipt.get("proposal_digest") or proposal.get("proposal_id") != identifier:
                        raise ValueError("proposal does not match receipt")
                    proposal_changes = proposal.get("changes")
                    if not isinstance(proposal_changes, list):
                        raise ValueError("missing proposal changes")
                    expected = [(f["path"], f["sha256_before"], f["sha256_after"]) for f in files]
                    actual = [(c.get("path"), c.get("before_raw_sha256"), c.get("after_raw_sha256"))
                              if "before_raw_sha256" in c else
                              (c.get("path"), c.get("before_sha256"), c.get("after_sha256"))
                              for c in proposal_changes if isinstance(c, dict)]
                    if actual != expected:
                        raise ValueError("proposal changes do not match receipt")
                    diffs = [{"path": c["path"], "diff": c["diff"]} for c in proposal_changes
                             if not selected_path or c["path"] == selected_path]
                    if any(not isinstance(c["diff"], str) for c in diffs):
                        raise ValueError("invalid proposal diff")
                    entry.update({"proposal_status": "digest matched; local evidence", "diffs": diffs})
                except (OSError, ValueError, KeyError, ContextOSError) as exc:
                    entry["proposal_status"] = f"unavailable: {exc}"
            entries.append((parsed.timestamp(), entry))
        except (OSError, ValueError, ContextOSError) as exc:
            warnings.append({"receipt": relative, "reason": str(exc)})
    entries.sort(key=lambda item: (item[0], item[1]["receipt"]), reverse=True)
    return {"schema_version": 1, "writes": False, "entries": [item[1] for item in entries[:limit]],
            "matching_receipts": len(entries), "warnings": warnings,
            "evidence_notice": "Local receipts may be missing or edited. Runtime is self-reported; human approval is not authenticated. This is not a complete Git or host read history."}


def _quote(value: str) -> str:
    # Render file content as quoted data and remove terminal control characters.
    value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", value)
    return "\n".join("> " + line for line in value.splitlines())


def render_briefing(report: dict[str, Any]) -> str:
    lines = ["# Context briefing", "", report["source_scope"], report["freshness_notice"], ""]
    if report["next_action"]:
        lines.extend([report["next_action"], ""])
    for source in report["sources"]:
        lines.extend([f"## {source['path']}", f"Selected for: {source['reason']}. Freshness: {source['freshness_status']}."])
        if source.get("last_updated"):
            lines.append(f"Last recorded update: {source['last_updated']} ({source['age_days']} days ago).")
        if "excerpt" in source:
            lines.extend(["", _quote(source["excerpt"]), ""])
            if source["excerpt_truncated"]:
                lines.append("Excerpt only; read the source for full context.")
        else:
            lines.append(_quote(source["unavailable_reason"]))
        lines.append("")
    return "\n".join(lines)


def render_history(report: dict[str, Any]) -> str:
    lines = ["# Context change history", "", report["evidence_notice"], ""]
    if not report["entries"]:
        lines.append("No matching local receipts. Check Git history for committed changes.")
    for entry in report["entries"]:
        lines.extend([f"## {entry['applied_at']} — {entry['runtime']} (self-reported)",
                      f"Receipt: {entry['receipt']}", f"Proposal: {entry['proposal_id']}"])
        for change in entry["files_changed"]:
            lines.append(f"- {change['path']} ({change.get('hash_basis', 'normalized text')}): {change['sha256_before'] or 'absent'} → {change['sha256_after'] or 'absent'}")
        lines.append(f"Details: {entry['proposal_status']}")
        for change in entry.get("diffs", []):
            lines.extend(["", _quote(change["diff"])])
        lines.append("")
    for warning in report["warnings"]:
        lines.append(_quote(f"Skipped {warning['receipt']}: {warning['reason']}"))
    return "\n".join(lines)
