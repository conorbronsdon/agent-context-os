from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1
PLACEHOLDER_DATE = "[DATE]"
LAST_UPDATED_RE = re.compile(r"^\*\*Last Updated:\*\*\s*(.+?)\s*$", re.MULTILINE)
REAL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SETUP_ROOTS = {"identity", "projects", "state"}
SETUP_FILES = {"ROUTING.md", "TODO.md", "CLAUDE.md", "AGENTS.md"}
RUNTIME_NAMES = {"claude", "codex", "hermes"}
CAPABILITY_VALUES = {"native", "adapter", "advisory", "unsupported"}
CAPABILITY_KEYS = {
    "agent_skills", "explicit_invocation", "project_hooks",
    "blocking_pre_tool_hook", "mcp", "native_memory", "proposal_apply",
}


class ContextOSError(RuntimeError):
    pass


@dataclass(frozen=True)
class Workspace:
    root: Path
    state_dir: Path
    sessions_dir: Path
    task_file: Path


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def file_digest(path: Path) -> str | None:
    if not path.exists():
        return None
    # Repository lifecycle files are text. Normalize checkout line endings so
    # proposal digests are stable across Windows, macOS, and Linux.
    return sha256_text(path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def parse_now(raw: str | None) -> datetime:
    if not raw:
        return utc_now()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContextOSError(f"invalid --now timestamp: {raw}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def discover_root(start: Path | None = None) -> Path:
    candidate = (start or Path.cwd()).resolve()
    for path in (candidate, *candidate.parents):
        if (path / "AGENTS.md").is_file() and (
            (path / "state").is_dir() or (path / "workspace.yaml").is_file()
        ):
            return path
    raise ContextOSError("could not find a Context OS root (AGENTS.md plus state/ or workspace.yaml)")


def _simple_workspace_yaml(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if key in {"state_dir", "sessions_dir", "task_file"} and value:
            values[key] = value
    return values


def load_workspace(root: Path) -> Workspace:
    config = _simple_workspace_yaml(root / "workspace.yaml")
    state_dir = safe_repo_path(root, config.get("state_dir", "state"))
    sessions_dir = safe_repo_path(root, config.get("sessions_dir", "sessions"))
    task_file = safe_repo_path(root, config.get("task_file", "TODO.md"))
    return Workspace(root=root, state_dir=state_dir, sessions_dir=sessions_dir, task_file=task_file)


def safe_repo_path(root: Path, raw: str) -> Path:
    relative = Path(raw)
    if relative.is_absolute():
        raise ContextOSError(f"absolute repository path is not allowed: {raw}")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ContextOSError(f"path escapes repository root: {raw}") from exc
    return resolved


def relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def ensure_text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ContextOSError(f"{field} must be a string")
    return value


def ensure_string_list(value: Any, field: str, required: bool = False) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ContextOSError(f"{field} must be a list of non-empty strings")
    return [item.strip() for item in value]


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextOSError(f"cannot read JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContextOSError(f"expected a JSON object in {path}")
    return value


def _replace_last_updated(content: str, today: str) -> tuple[str, str | None]:
    matches = LAST_UPDATED_RE.findall(content)
    if len(matches) != 1:
        raise ContextOSError("state/current.md must contain exactly one **Last Updated:** line")
    old = matches[0].strip()
    updated = LAST_UPDATED_RE.sub(f"**Last Updated:** {today}", content, count=1)
    return updated, old if REAL_DATE_RE.fullmatch(old) else None


def _newest_history_date(content: str) -> str | None:
    dates = [line.strip() for line in content.splitlines() if REAL_DATE_RE.fullmatch(line.strip())]
    return max(dates) if dates else None


def _advance_current(
    workspace: Workspace, desired: str, today: str, pending: dict[Path, str]
) -> None:
    current = workspace.state_dir / "current.md"
    history = workspace.state_dir / "current-log.md"
    updated, old_date = _replace_last_updated(desired.rstrip() + "\n", today)
    pending[current] = updated
    history_text = history.read_text(encoding="utf-8") if history.exists() else "# current.md update log\n\n"
    newest = _newest_history_date(history_text)
    if old_date and old_date != today and old_date != newest:
        marker = "# current.md update log"
        if marker not in history_text:
            raise ContextOSError("state/current-log.md is missing its required heading")
        before, after = history_text.split(marker, 1)
        pending[history] = f"{before}{marker}\n\n{old_date}\n\n{after.lstrip()}"


def _session_append(path: Path, block: str, date: str) -> str:
    if path.exists():
        existing = path.read_text(encoding="utf-8").rstrip()
        return f"{existing}\n\n{block.rstrip()}\n"
    return f"# Session — {date}\n\n{block.rstrip()}\n"


def _bullets(values: list[str], empty: str = "- None recorded") -> str:
    return "\n".join(f"- {value}" for value in values) if values else empty


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def render_update(workspace: Workspace, payload: dict[str, Any], now: datetime) -> dict[Path, str]:
    progress = ensure_string_list(payload.get("progress"), "progress", required=True)
    today, clock = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    session = workspace.sessions_dir / f"{today}.md"
    pending = {session: _session_append(session, f"## Update: {clock}\n{_bullets(progress)}", today)}
    if "current_markdown" in payload:
        _advance_current(workspace, ensure_text(payload["current_markdown"], "current_markdown"), today, pending)
    return pending


def render_end(workspace: Workspace, payload: dict[str, Any], now: datetime) -> dict[Path, str]:
    happened = ensure_string_list(payload.get("what_happened"), "what_happened", required=True)
    decisions = payload.get("decisions", [])
    if not isinstance(decisions, list):
        raise ContextOSError("decisions must be a list")
    next_time = ensure_string_list(payload.get("next_time"), "next_time")
    today, clock = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    session = workspace.sessions_dir / f"{today}.md"
    decision_bullets = []
    for index, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            raise ContextOSError(f"decisions[{index}] must be an object")
        decision_bullets.append(ensure_text(decision.get("decision"), f"decisions[{index}].decision"))
    sections = (
        f"## What happened\n{_bullets(happened)}\n\n"
        f"## Decisions\n{_bullets(decision_bullets)}\n\n"
        f"## Next time\n{_bullets(next_time)}"
    )
    if session.exists():
        sections = f"## Session {clock}\n\n{sections}"
    pending: dict[Path, str] = {session: _session_append(session, sections, today)}
    if "current_markdown" in payload:
        _advance_current(workspace, ensure_text(payload["current_markdown"], "current_markdown"), today, pending)
    for field, filename in (("blockers_markdown", "blockers.md"), ("weekly_priorities_markdown", "weekly-priorities.md")):
        if field in payload:
            pending[workspace.state_dir / filename] = ensure_text(payload[field], field).rstrip() + "\n"
    if decisions:
        decision_path = workspace.state_dir / "decisions.md"
        if not decision_path.exists():
            raise ContextOSError(f"decision log does not exist: {relative_path(workspace.root, decision_path)}")
        text = decision_path.read_text(encoding="utf-8").rstrip()
        for index, decision in enumerate(decisions):
            rationale = ensure_text(decision.get("rationale", ""), f"decisions[{index}].rationale")
            rejected = ensure_text(decision.get("rejected_alternatives", ""), f"decisions[{index}].rejected_alternatives")
            text += (
                f"\n| {today} | {_escape_table(decision_bullets[index])} | "
                f"{_escape_table(rationale)} | {_escape_table(rejected)} |"
            )
        pending[decision_path] = text + "\n"
    return pending


def _is_populated(content: str) -> bool:
    stripped = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    for raw_line in stripped.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or re.fullmatch(r"\|?[\s:|-]+\|?", line):
            continue
        value = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", line)
        if re.fullmatch(r"(?:\*\*[^*]+:\*\*\s*)?\[[^\]\n]+\][.,;:]?", value):
            continue
        return True
    return False


def render_setup(workspace: Workspace, payload: dict[str, Any], now: datetime) -> dict[Path, str]:
    files = payload.get("files")
    replace = set(ensure_string_list(payload.get("replace_populated"), "replace_populated"))
    if not isinstance(files, dict) or not files:
        raise ContextOSError("files must be a non-empty object mapping paths to content")
    pending: dict[Path, str] = {}
    for raw_path, raw_content in files.items():
        if not isinstance(raw_path, str):
            raise ContextOSError("setup file paths must be strings")
        path = safe_repo_path(workspace.root, raw_path)
        relative = relative_path(workspace.root, path)
        top = Path(relative).parts[0]
        skill_path = len(Path(relative).parts) >= 3 and Path(relative).parts[:2] == (".agents", "skills")
        if top not in SETUP_ROOTS and relative not in SETUP_FILES and not skill_path:
            raise ContextOSError(f"setup cannot write outside approved context paths: {relative}")
        content = ensure_text(raw_content, f"files[{raw_path}]").replace("{{TODAY}}", now.strftime("%Y-%m-%d"))
        if path.exists() and _is_populated(path.read_text(encoding="utf-8")) and relative not in replace:
            raise ContextOSError(f"populated file requires replace_populated approval: {relative}")
        pending[path] = content.rstrip() + "\n"
    return pending


def build_changes(
    root: Path, pending: dict[Path, str], replacement_approvals: set[str] | None = None
) -> list[dict[str, Any]]:
    changes = []
    for path in sorted(pending, key=lambda item: relative_path(root, item)):
        after = pending[path]
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        if before == after:
            continue
        rel = relative_path(root, path)
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True), after.splitlines(keepends=True),
                fromfile=f"a/{rel}", tofile=f"b/{rel}",
            )
        )
        change = {
            "path": rel,
            "before_sha256": file_digest(path),
            "after_sha256": sha256_text(after),
            "after_text": after,
            "diff": diff,
        }
        if replacement_approvals is not None:
            change["replacement_approved"] = rel in replacement_approvals
        changes.append(change)
    return changes


def proposal_id(workflow: str, now: datetime, changes: list[dict[str, Any]]) -> str:
    seed = canonical_json({"workflow": workflow, "now": now.isoformat(), "changes": changes})
    return f"{now.strftime('%Y%m%dT%H%M%S')}-{workflow}-{sha256_text(seed)[:10]}"


def create_proposal(root: Path, workflow: str, payload: dict[str, Any], now: datetime) -> tuple[Path, dict[str, Any]]:
    workspace = load_workspace(root)
    renderers = {"update": render_update, "end": render_end, "setup": render_setup}
    if workflow not in renderers:
        raise ContextOSError(f"unsupported proposal workflow: {workflow}")
    replacement_approvals = (
        set(ensure_string_list(payload.get("replace_populated"), "replace_populated"))
        if workflow == "setup" else None
    )
    changes = build_changes(
        root, renderers[workflow](workspace, payload, now), replacement_approvals
    )
    if not changes:
        raise ContextOSError("proposal has no changes")
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "workflow": workflow,
        "created_at": now.isoformat(),
        "proposal_id": proposal_id(workflow, now, changes),
        "changes": changes,
        "invariants": ["workflow-path-policy", "optimistic-file-hashes", "exact-proposal-integrity"],
    }
    if workflow in {"update", "end"} and any(change["path"].endswith("current.md") for change in changes):
        document["invariants"].extend(["single-last-updated", "same-day-history"])
    digest = sha256_text(canonical_json(document))
    document["proposal_digest"] = digest
    target = root / ".context-os" / "proposals" / f"{document['proposal_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return target, document


@contextmanager
def transaction_lock(root: Path) -> Iterator[None]:
    lock = root / ".context-os" / "apply.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ContextOSError(f"another apply is active or left a stale lock: {lock}") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def validate_proposal(document: dict[str, Any]) -> str:
    digest = document.get("proposal_digest")
    if not isinstance(digest, str):
        raise ContextOSError("proposal is missing proposal_digest")
    unsigned = dict(document)
    del unsigned["proposal_digest"]
    expected = sha256_text(canonical_json(unsigned))
    if digest != expected:
        raise ContextOSError("proposal digest does not match its contents")
    return digest


def _validate_change_path(workspace: Workspace, workflow: str, created_at: datetime, relative: str) -> None:
    parts = Path(relative).parts
    if not parts or parts[0] in {".git", ".context-os"}:
        raise ContextOSError(f"proposal path is reserved: {relative}")
    if workflow == "setup":
        allowed = (
            relative in SETUP_FILES
            or parts[0] in {"identity", "projects", "state"}
            or (len(parts) >= 3 and parts[:2] == (".agents", "skills"))
        )
    else:
        state_paths = {
            relative_path(workspace.root, workspace.state_dir / name)
            for name in ("current.md", "current-log.md")
        }
        if workflow == "end":
            state_paths.update(
                relative_path(workspace.root, workspace.state_dir / name)
                for name in ("decisions.md", "blockers.md", "weekly-priorities.md")
            )
        session_path = relative_path(
            workspace.root, workspace.sessions_dir / f"{created_at.strftime('%Y-%m-%d')}.md"
        )
        allowed = relative in state_paths or relative == session_path
    if not allowed:
        raise ContextOSError(f"{workflow} proposal cannot write path: {relative}")


def _validate_proposal_shape(root: Path, proposal: Path, document: dict[str, Any]) -> tuple[str, datetime]:
    required = {
        "schema_version", "workflow", "created_at", "proposal_id",
        "changes", "invariants", "proposal_digest",
    }
    if set(document) != required or document.get("schema_version") != SCHEMA_VERSION:
        raise ContextOSError("proposal has an invalid top-level shape")
    workflow = document.get("workflow")
    if workflow not in {"setup", "update", "end"}:
        raise ContextOSError(f"unsupported proposal workflow: {workflow}")
    proposal_id_value = ensure_text(document.get("proposal_id"), "proposal_id")
    expected_dir = (root / ".context-os" / "proposals").resolve()
    try:
        proposal.resolve().relative_to(expected_dir)
    except ValueError as exc:
        raise ContextOSError("proposal must be loaded from .context-os/proposals") from exc
    if proposal.name != f"{proposal_id_value}.json":
        raise ContextOSError("proposal filename does not match proposal_id")
    created_at = parse_now(ensure_text(document.get("created_at"), "created_at"))
    changes = document.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ContextOSError("proposal changes must be a non-empty list")
    if not isinstance(document.get("invariants"), list):
        raise ContextOSError("proposal invariants must be a list")
    workspace = load_workspace(root)
    seen: set[str] = set()
    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            raise ContextOSError(f"changes[{index}] must be an object")
        relative = ensure_text(change.get("path"), f"changes[{index}].path")
        if relative in seen:
            raise ContextOSError(f"proposal contains duplicate path: {relative}")
        seen.add(relative)
        safe_repo_path(root, relative)
        _validate_change_path(workspace, workflow, created_at, relative)
        if workflow == "setup" and change.get("replacement_approved") not in {True, False}:
            raise ContextOSError(f"setup change is missing replacement policy: {relative}")
    return workflow, created_at


def apply_proposal(root: Path, proposal: Path, confirmation: str, runtime: str) -> tuple[Path, dict[str, Any]]:
    document = read_json(proposal)
    workflow, _ = _validate_proposal_shape(root, proposal, document)
    expected_digest = validate_proposal(document)
    if confirmation != expected_digest:
        raise ContextOSError("--confirm must exactly match the proposal_digest")
    runtime_manifest(root, runtime)
    with transaction_lock(root):
        for change in document.get("changes", []):
            path = safe_repo_path(root, ensure_text(change.get("path"), "change.path"))
            if workflow == "setup" and path.exists() and _is_populated(path.read_text(encoding="utf-8")):
                if change.get("replacement_approved") is not True:
                    raise ContextOSError(f"populated file lacks replacement approval: {change['path']}")
            if file_digest(path) != change.get("before_sha256"):
                raise ContextOSError(f"refusing stale proposal; file changed: {change['path']}")
            if sha256_text(ensure_text(change.get("after_text"), "change.after_text")) != change.get("after_sha256"):
                raise ContextOSError(f"proposal after hash is invalid: {change['path']}")
        head_before = git_head(root)
        applied = []
        backups: dict[Path, bytes | None] = {}
        staged: dict[Path, Path] = {}
        staging_root = root / ".context-os" / "staging" / document["proposal_id"]
        receipt_path = root / ".context-os" / "receipts" / f"{document['proposal_id']}.json"
        receipt: dict[str, Any]
        try:
            for change in document["changes"]:
                path = safe_repo_path(root, change["path"])
                backups[path] = path.read_bytes() if path.exists() else None
                stage = staging_root / change["path"]
                stage.parent.mkdir(parents=True, exist_ok=True)
                stage.write_text(change["after_text"], encoding="utf-8", newline="\n")
                staged[path] = stage
            for change in document["changes"]:
                path = safe_repo_path(root, change["path"])
                if file_digest(path) != change.get("before_sha256"):
                    raise ContextOSError(f"refusing target changed during apply: {change['path']}")
                path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged[path], path)
                applied.append({
                    "path": change["path"],
                    "sha256_before": change["before_sha256"],
                    "sha256_after": file_digest(path),
                })
            receipt = {
                "schema_version": SCHEMA_VERSION,
                "proposal_id": document["proposal_id"],
                "proposal_digest": expected_digest,
                "approval_evidence": "host-mediated confirmation; kernel does not authenticate the human approver",
                "applied_at": utc_now().isoformat(),
                "runtime": runtime,
                "files_changed": applied,
                "git_head_before": head_before,
                "git_head_after": git_head(root),
                "invariants_checked": document.get("invariants", []),
            }
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_stage = staging_root / "receipt.json"
            receipt_stage.parent.mkdir(parents=True, exist_ok=True)
            receipt_stage.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
            os.replace(receipt_stage, receipt_path)
        except Exception as exc:
            rollback_errors = []
            for applied_change in reversed(applied):
                applied_path = safe_repo_path(root, applied_change["path"])
                try:
                    before = backups[applied_path]
                    if before is None:
                        applied_path.unlink(missing_ok=True)
                    else:
                        applied_path.write_bytes(before)
                except OSError as rollback_exc:
                    rollback_errors.append(f"{applied_change['path']}: {rollback_exc}")
            if rollback_errors:
                raise ContextOSError(
                    f"apply failed and rollback was incomplete ({'; '.join(rollback_errors)}): {exc}"
                ) from exc
            if isinstance(exc, ContextOSError):
                raise
            raise ContextOSError(f"apply failed; staged writes were rolled back: {exc}") from exc
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)
        return receipt_path, receipt


def runtime_manifest(root: Path, runtime: str) -> dict[str, Any]:
    if runtime not in RUNTIME_NAMES | {"generic"}:
        raise ContextOSError(f"unsupported runtime: {runtime}")
    manifest_path = root / "runtimes" / f"{runtime}.json"
    if not manifest_path.exists():
        if runtime == "generic":
            return {"runtime": "generic", "capabilities": {}}
        raise ContextOSError(f"missing runtime manifest: {manifest_path}")
    manifest = read_json(manifest_path)
    required = {"schema_version", "runtime", "instruction_file", "invocation", "capabilities", "install"}
    invocation = manifest.get("invocation")
    capabilities = manifest.get("capabilities")
    install = manifest.get("install")
    valid = (
        set(manifest) == required
        and manifest.get("runtime") == runtime
        and manifest.get("schema_version") == SCHEMA_VERSION
        and isinstance(manifest.get("instruction_file"), str)
        and isinstance(invocation, dict)
        and set(invocation) == {"setup", "start", "update", "end"}
        and all(isinstance(value, str) and value for value in invocation.values())
        and isinstance(capabilities, dict)
        and set(capabilities) == CAPABILITY_KEYS
        and set(capabilities.values()) <= CAPABILITY_VALUES
        and isinstance(install, dict)
        and set(install) == {"mode", "next_steps"}
        and isinstance(install.get("mode"), str)
        and isinstance(install.get("next_steps"), list)
        and all(isinstance(item, str) and item for item in install["next_steps"])
    )
    if not valid:
        raise ContextOSError(f"invalid runtime manifest: {manifest_path}")
    return manifest


def start_report(root: Path, now: datetime) -> dict[str, Any]:
    workspace = load_workspace(root)
    thresholds = {"current.md": 3, "weekly-priorities.md": 5, "blockers.md": 7}
    files: dict[str, Any] = {}
    today = now.date()
    for filename, threshold in thresholds.items():
        path = workspace.state_dir / filename
        age = None
        updated = None
        if path.exists():
            match = LAST_UPDATED_RE.search(path.read_text(encoding="utf-8"))
            if match and REAL_DATE_RE.fullmatch(match.group(1).strip()):
                updated = match.group(1).strip()
                age = (today - datetime.strptime(updated, "%Y-%m-%d").date()).days
        files[relative_path(root, path)] = {
            "exists": path.exists(), "last_updated": updated, "age_days": age,
            "stale_after_days": threshold, "stale": age is not None and age > threshold,
        }
    sessions = sorted(workspace.sessions_dir.glob("????-??-??.md"), reverse=True) if workspace.sessions_dir.exists() else []
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "state": files,
        "latest_session": relative_path(root, sessions[0]) if sessions else None,
        "task_file": relative_path(root, workspace.task_file),
        "git_head": git_head(root),
    }


def install_runtime(root: Path, runtime: str) -> tuple[Path, dict[str, Any]]:
    manifest = runtime_manifest(root, runtime)
    local = {
        "schema_version": SCHEMA_VERSION,
        "runtime": runtime,
        "installed_at": utc_now().isoformat(),
        "source_manifest_sha256": sha256_text(canonical_json(manifest)),
        "next_steps": manifest.get("install", {}).get("next_steps", []),
    }
    target = root / ".context-os" / "runtime.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(local, indent=2) + "\n", encoding="utf-8", newline="\n")
    return target, local


def doctor(root: Path, runtime: str | None = None) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    git_location = shutil.which("git")
    add("command:git", "pass" if git_location else "fail", git_location or "not found")
    add("command:python", "pass", sys.executable)
    workspace = load_workspace(root)
    required_paths = [
        root / "AGENTS.md", workspace.state_dir / "current.md",
        workspace.state_dir / "current-log.md", workspace.state_dir / "decisions.md",
    ]
    for path in required_paths:
        rel = relative_path(root, path)
        add(f"file:{rel}", "pass" if path.exists() else "fail", rel)
    selected = runtime
    local_runtime = root / ".context-os" / "runtime.json"
    if selected is None and local_runtime.exists():
        selected = read_json(local_runtime).get("runtime")
    hosts = [selected] if selected else sorted(RUNTIME_NAMES)
    for host in hosts:
        try:
            manifest = runtime_manifest(root, host)
            add(f"manifest:{host}", "pass", f"schema {manifest['schema_version']}")
        except ContextOSError as exc:
            add(f"manifest:{host}", "fail", str(exc))
    lock = root / ".context-os" / "apply.lock"
    add("transaction-lock", "warn" if lock.exists() else "pass", str(lock) if lock.exists() else "none")
    cutoff = utc_now().timestamp() - (30 * 24 * 60 * 60)
    old_artifacts = [
        path for folder in ("proposals", "receipts")
        for path in (root / ".context-os" / folder).glob("*.json")
        if path.stat().st_mtime < cutoff
    ]
    add(
        "local-artifact-retention", "warn" if old_artifacts else "pass",
        f"{len(old_artifacts)} artifacts older than 30 days" if old_artifacts else "none older than 30 days",
    )
    if selected:
        try:
            selected_manifest = runtime_manifest(root, selected)
            expected_source = sha256_text(canonical_json(selected_manifest))
            if local_runtime.exists():
                recorded_source = read_json(local_runtime).get("source_manifest_sha256")
                add(
                    "runtime-manifest-drift",
                    "pass" if recorded_source == expected_source else "warn",
                    "current" if recorded_source == expected_source else "rerun context-os install",
                )
        except ContextOSError as exc:
            add("runtime-manifest-drift", "fail", str(exc))
        binary = {"claude": "claude", "codex": "codex", "hermes": "hermes"}.get(selected)
        if binary:
            location = shutil.which(binary)
            add(f"runtime:{selected}", "pass" if location else "warn", location or "not installed")
    status = "fail" if any(item["status"] == "fail" for item in checks) else "warn" if any(item["status"] == "warn" for item in checks) else "pass"
    return {"schema_version": SCHEMA_VERSION, "status": status, "checks": checks}


def _hook_targets(payload: dict[str, Any]) -> set[str]:
    targets: set[str] = set()

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, child_key)
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str):
            if key in {"file_path", "path"} and value.strip():
                targets.add(value.strip().replace("\\", "/"))
            if key in {"command", "patch"}:
                for match in re.finditer(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$", value, re.MULTILINE):
                    targets.add(match.group(1).strip().replace("\\", "/"))

    visit(payload)
    return targets


def hook_report(root: Path, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    workspace = load_workspace(root)
    if event == "session-start":
        current = workspace.state_dir / "current.md"
        if current.exists() and PLACEHOLDER_DATE in current.read_text(encoding="utf-8"):
            findings.append({"severity": "advisory", "message": "Context OS is not initialized; run the explicit setup workflow."})
        lock = root / ".context-os" / "apply.lock"
        if lock.exists():
            findings.append({"severity": "warning", "message": f"A lifecycle apply lock exists at {lock}. Run context-os doctor before writing."})
    elif event == "pre-write":
        protected = {
            relative_path(root, workspace.state_dir / "current.md"): "Use the lifecycle proposal/apply kernel for current.md so date and history invariants are enforced.",
            relative_path(root, workspace.state_dir / "current-log.md"): "Use the lifecycle proposal/apply kernel for current-log.md so history remains consistent.",
            relative_path(root, workspace.state_dir / "decisions.md"): "Use the end-session proposal/apply kernel for append-only decision rows.",
            relative_path(root, workspace.state_dir / "blockers.md"): "Use the lifecycle proposal/apply kernel for blockers.md.",
            relative_path(root, workspace.state_dir / "weekly-priorities.md"): "Use the lifecycle proposal/apply kernel for weekly-priorities.md.",
        }
        normalized_targets = set()
        for target in _hook_targets(payload):
            candidate = Path(target)
            if candidate.is_absolute():
                try:
                    normalized_targets.add(relative_path(root, candidate))
                except ValueError:
                    continue
            else:
                normalized_targets.add(Path(target.removeprefix("./")).as_posix())
        for path, message in protected.items():
            if path in normalized_targets:
                findings.append({"severity": "advisory", "message": message})
    else:
        raise ContextOSError(f"unsupported hook event: {event}")
    return {"schema_version": SCHEMA_VERSION, "event": event, "findings": findings}
