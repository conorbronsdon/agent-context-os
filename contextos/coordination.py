from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from contextos.kernel import ContextOSError, parse_now, sha256_text, utc_now


COORDINATION_BRANCH = "coordination"
MAX_TTL = timedelta(days=14)
DEFAULT_TTL = timedelta(days=7)
MAX_MESSAGE_BYTES = 4096
MAX_PUSH_ATTEMPTS = 5

_REMOTE_REF = f"refs/remotes/origin/{COORDINATION_BRANCH}"
_LOCAL_REF = f"refs/heads/{COORDINATION_BRANCH}"
_REMOTE_BRANCH_REF = f"refs/heads/{COORDINATION_BRANCH}"
_BOARD_PREFIX = "coordination/board/"
_CLAIMS_PREFIX = "coordination/claims/"
_OUTBOX_NAME = ".contextos-outbox"
_KINDS = {"note", "alert", "query", "handoff"}

_FILE_RE = re.compile(
    r"^(?P<stamp>\d{8}T\d{6}Z)-"
    r"(?P<suffix>[0-9a-f]{4})-"
    r"(?P<runtime>[a-z0-9]+(?:-[a-z0-9]+)*)-"
    r"(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)\.md$"
)
_RUN_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$"
)
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_REFERENCE_RE = re.compile(
    r"^(?P<commit>[0-9a-fA-F]{7,64}):"
    r"(?P<path>[^#]+?)"
    r"(?:#sha256:(?P<digest>[0-9a-fA-F]{64}))?$"
)
_SUSPICIOUS_PATTERNS = (
    ("user approved", re.compile(r"\buser\s+approved\b", re.IGNORECASE)),
    ("user authorized", re.compile(r"\buser\s+authori[sz]ed\b", re.IGNORECASE)),
    ("run this now", re.compile(r"\brun\s+this\s+now\b", re.IGNORECASE)),
    (
        "execute immediately",
        re.compile(r"\bexecute\s+immediately\b", re.IGNORECASE),
    ),
    ("urgent", re.compile(r"\burgent\b", re.IGNORECASE)),
)


def _git(
    root: Path,
    args: list[str],
    *,
    check: bool = True,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = ["git", *args]
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    try:
        result = subprocess.run(
            command,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=input_text,
            env=merged_env,
        )
    except OSError as exc:
        raise ContextOSError(f"Could not run git: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ContextOSError(
            f"Git command failed ({' '.join(command)}): {detail or 'unknown error'}"
        )
    return result


def _coerce_now(value: datetime | None) -> datetime:
    candidate: Any = utc_now() if value is None else value
    if not isinstance(candidate, datetime):
        candidate = parse_now(str(candidate))
    if candidate.tzinfo is None:
        raise ContextOSError("Coordination timestamps must be timezone-aware UTC values")
    return candidate.astimezone(timezone.utc)


def _parse_utc(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ContextOSError(f"{field} must be a UTC ISO timestamp")
    raw = value.strip()
    if raw.endswith("Z"):
        parsed_raw = raw[:-1] + "+00:00"
    else:
        parsed_raw = raw
    try:
        parsed = datetime.fromisoformat(parsed_raw)
    except ValueError as exc:
        raise ContextOSError(f"{field} must be a valid UTC ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ContextOSError(f"{field} must use UTC")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _stamp_datetime(filename: str) -> datetime:
    match = _FILE_RE.fullmatch(filename)
    if not match:
        raise ContextOSError(f"Invalid coordination filename: {filename}")
    try:
        return datetime.strptime(
            match.group("stamp"), "%Y%m%dT%H%M%SZ"
        ).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ContextOSError(
            f"Invalid timestamp in coordination filename: {filename}"
        ) from exc


def _expiry(
    supplied: str | None,
    *,
    now: datetime,
    field: str,
) -> datetime:
    value = now + DEFAULT_TTL if supplied is None else _parse_utc(supplied, field)
    if value <= now:
        raise ContextOSError(f"{field} must be later than now")
    if value > now + MAX_TTL:
        raise ContextOSError(
            f"{field} must be no more than {MAX_TTL.days} days after now"
        )
    return value


def _scalar(value: str, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContextOSError(f"{field} must be text")
    cleaned = value.strip()
    if not allow_empty and not cleaned:
        raise ContextOSError(f"{field} must not be empty")
    if "\r" in value or "\n" in value:
        raise ContextOSError(f"{field} must be a single line")
    return cleaned


def _slug(value: str, fallback: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = lowered.strip("-")[:48].rstrip("-")
    return lowered or fallback


def _runtime_slug(runtime: str) -> str:
    return _slug(_scalar(runtime, "runtime"), "runtime")


def _new_path(
    prefix: str,
    *,
    now: datetime,
    runtime: str,
    slug: str,
) -> str:
    identifier = (
        f"{_stamp(now)}-{secrets.token_hex(2)}-"
        f"{_runtime_slug(runtime)}-{_slug(slug, 'item')}"
    )
    return f"{prefix}{identifier}.md"


def _regenerate_path(path: str) -> str:
    filename = PurePosixPath(path).name
    match = re.match(r"^(\d{8}T\d{6}Z)-[0-9a-f]{4}-(.+\.md)$", filename)
    if not match:
        raise ContextOSError(f"Cannot regenerate invalid coordination ID: {filename}")
    return str(
        PurePosixPath(path).parent
        / f"{match.group(1)}-{secrets.token_hex(2)}-{match.group(2)}"
    )


def _validate_relative_path(value: str, field: str) -> str:
    if "\\" in value:
        raise ContextOSError(f"{field} must use a repository-relative POSIX path")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or value.startswith("/"):
        raise ContextOSError(f"{field} must use a repository-relative path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ContextOSError(f"{field} contains an unsafe path component")
    if re.match(r"^[A-Za-z]:", value):
        raise ContextOSError(f"{field} must not be an absolute Windows path")
    return value


def _parse_reference(value: str) -> tuple[str, str, str | None]:
    ref = _scalar(value, "re")
    match = _REFERENCE_RE.fullmatch(ref)
    if not match:
        raise ContextOSError(
            "re must be commit:path or commit:path#sha256:<64 hex characters>"
        )
    path = _validate_relative_path(match.group("path"), "re path")
    return match.group("commit"), path, match.group("digest")


def _reference_status(root: Path, value: str) -> tuple[bool, str | None]:
    try:
        commit, path, digest = _parse_reference(value)
    except ContextOSError as exc:
        return False, str(exc)

    exists = _git(
        root,
        ["cat-file", "-e", f"{commit}^{{commit}}"],
        check=False,
    )
    if exists.returncode != 0:
        return False, f"referenced commit {commit} is unavailable"

    contained = _git(
        root,
        ["for-each-ref", "--format=%(refname)", "--contains", commit, "refs/remotes/origin"],
        check=False,
    )
    if contained.returncode != 0 or not contained.stdout.strip():
        return False, f"referenced commit {commit} is not reachable from origin"

    content = _git(root, ["show", f"{commit}:{path}"], check=False)
    if content.returncode != 0:
        return False, f"referenced path {path} does not exist at {commit}"

    if digest is not None and sha256_text(content.stdout).lower() != digest.lower():
        return False, f"referenced content hash does not match for {commit}:{path}"
    return True, None


def _prepare_reference(root: Path, value: str | None) -> tuple[str | None, list[str]]:
    if value is None:
        return None, []
    _parse_reference(value)
    _git(root, ["fetch", "origin"], check=False)
    valid, reason = _reference_status(root, value)
    if not valid:
        return None, [f"Reference omitted; message is summary-only: {reason}"]
    return value.strip(), []


def _validate_task(task: str) -> str:
    value = _scalar(task, "task")
    if ":" in value:
        commit, path, digest = _parse_reference(value)
        if digest is not None:
            raise ContextOSError("claim task references must not include a content hash")
        return f"{commit}:{path}"
    if not _TASK_ID_RE.fullmatch(value) or " " in value:
        raise ContextOSError(
            "task must be a stable task ID or a commit:path reference, not free text"
        )
    _validate_relative_path(value, "task")
    return value


def _validate_owner(owner: str) -> str:
    value = _scalar(owner, "owner")
    if not _RUN_ID_RE.fullmatch(value):
        raise ContextOSError("owner must have runtime/run-id form")
    return value


def _render_frontmatter(fields: list[tuple[str, str]], body: str = "") -> str:
    lines = ["---", *(f"{key}: {value}" for key, value in fields), "---"]
    if body:
        lines.extend(["", body.rstrip()])
    return "\n".join(lines) + "\n"


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ContextOSError("missing opening frontmatter fence")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ContextOSError("missing closing frontmatter fence") from exc

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        if ":" not in line:
            raise ContextOSError(f"invalid frontmatter line: {line}")
        key, value = line.split(":", 1)
        key = key.strip()
        if not key or key in fields:
            raise ContextOSError(f"invalid or duplicate frontmatter key: {key}")
        fields[key] = value.strip()

    body_lines = lines[end + 1 :]
    if body_lines and not body_lines[0]:
        body_lines = body_lines[1:]
    return fields, "\n".join(body_lines).rstrip()


def _remote_head(root: Path) -> str | None:
    result = _git(root, ["rev-parse", "--verify", _REMOTE_REF], check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _fetch_coordination(root: Path) -> str | None:
    probe = _git(
        root,
        ["ls-remote", "--exit-code", "--heads", "origin", _REMOTE_BRANCH_REF],
        check=False,
    )
    if probe.returncode == 2:
        _git(root, ["update-ref", "-d", _REMOTE_REF], check=False)
        return None
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip()
        raise ContextOSError(
            f"Could not inspect origin/{COORDINATION_BRANCH}: "
            f"{detail or 'unknown error'}"
        )

    fetched = _git(
        root,
        [
            "fetch",
            "origin",
            f"+{_REMOTE_BRANCH_REF}:{_REMOTE_REF}",
        ],
        check=False,
    )
    if fetched.returncode != 0:
        detail = (fetched.stderr or fetched.stdout).strip()
        raise ContextOSError(
            f"Could not fetch origin/{COORDINATION_BRANCH}: "
            f"{detail or 'unknown error'}"
        )
    return _remote_head(root)


def _hash_object(root: Path, content: str) -> str:
    return _git(
        root,
        ["hash-object", "-w", "--stdin"],
        input_text=content,
    ).stdout.strip()


def _tree_blob(root: Path, commit: str, path: str) -> str | None:
    result = _git(root, ["ls-tree", commit, "--", path], check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    metadata = result.stdout.split("\t", 1)[0].split()
    if len(metadata) < 3 or metadata[1] != "blob":
        return None
    return metadata[2]


def _tree_paths(root: Path, commit: str, prefix: str) -> list[str]:
    result = _git(
        root,
        ["ls-tree", "-r", "--name-only", commit, "--", prefix],
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def _read_tree_text(root: Path, commit: str, path: str) -> str:
    result = _git(root, ["show", f"{commit}:{path}"], check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ContextOSError(
            f"Could not read {path} from coordination ref: "
            f"{detail or 'unknown error'}"
        )
    return result.stdout


def _commit_change(
    root: Path,
    *,
    parent: str | None,
    additions: dict[str, str],
    deletions: list[str],
    message: str,
    now: datetime,
) -> str:
    with tempfile.TemporaryDirectory(prefix="contextos-index-") as temporary:
        index_path = Path(temporary) / "index"
        env = {"GIT_INDEX_FILE": str(index_path.resolve())}
        if parent is None:
            _git(root, ["read-tree", "--empty"], env=env)
        else:
            _git(root, ["read-tree", parent], env=env)

        for path in deletions:
            _git(
                root,
                ["update-index", "--force-remove", "--", path],
                env=env,
            )
        for path, content in additions.items():
            blob = _hash_object(root, content)
            _git(
                root,
                ["update-index", "--add", "--cacheinfo", "100644", blob, path],
                env=env,
            )

        tree = _git(root, ["write-tree"], env=env).stdout.strip()

    date_value = now.strftime("%Y-%m-%dT%H:%M:%S +0000")
    commit_env = {
        "GIT_AUTHOR_DATE": date_value,
        "GIT_COMMITTER_DATE": date_value,
    }
    args = ["commit-tree", tree]
    if parent is not None:
        args.extend(["-p", parent])
    args.extend(["-F", "-"])
    commit = _git(
        root,
        args,
        input_text=message.rstrip() + "\n",
        env=commit_env,
    ).stdout.strip()
    _git(root, ["update-ref", _LOCAL_REF, commit])
    return commit


def _push(root: Path) -> subprocess.CompletedProcess[str]:
    return _git(
        root,
        ["push", "origin", f"{_LOCAL_REF}:{_REMOTE_BRANCH_REF}"],
        check=False,
    )


def bootstrap_board(
    root: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(root)
    current = _coerce_now(now)
    existing = _fetch_coordination(root)
    if existing is not None:
        return {
            "branch": COORDINATION_BRANCH,
            "commit": existing,
            "created": False,
            "delivered": True,
            "attempts": 0,
            "notices": [],
        }

    empty_blob = _hash_object(root, "")
    additions = {
        f"{_BOARD_PREFIX}.gitkeep": "",
        f"{_CLAIMS_PREFIX}.gitkeep": "",
    }
    commit = _commit_change(
        root,
        parent=None,
        additions=additions,
        deletions=[],
        message="Bootstrap coordination board",
        now=current,
    )
    result = _push(root)
    if result.returncode == 0:
        confirmed = _fetch_coordination(root)
        if confirmed is None:
            raise ContextOSError("Coordination bootstrap push was not visible on origin")
        return {
            "branch": COORDINATION_BRANCH,
            "commit": confirmed,
            "created": confirmed == commit,
            "delivered": True,
            "attempts": 1,
            "notices": [],
        }

    winner = _fetch_coordination(root)
    if winner is not None:
        return {
            "branch": COORDINATION_BRANCH,
            "commit": winner,
            "created": False,
            "delivered": True,
            "attempts": 1,
            "notices": ["Another writer bootstrapped the coordination ref first"],
        }

    detail = (result.stderr or result.stdout).strip()
    raise ContextOSError(
        f"Could not bootstrap origin/{COORDINATION_BRANCH}: "
        f"{detail or 'push failed'}"
    )


def _publish_change(
    root: Path,
    *,
    additions: dict[str, str],
    deletions: dict[str, str | None],
    message: str,
    now: datetime,
    collision_factory: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    working_additions = dict(additions)
    attempts = 0
    last_commit: str | None = None
    last_error = ""
    notices: list[str] = []

    for _ in range(MAX_PUSH_ATTEMPTS):
        head = _fetch_coordination(root)
        if head is None:
            raise ContextOSError("The coordination ref disappeared during publication")

        collision_count = 0
        while True:
            collision: str | None = None
            for path, content in working_additions.items():
                remote_blob = _tree_blob(root, head, path)
                if remote_blob is None:
                    continue
                local_blob = _hash_object(root, content)
                if remote_blob != local_blob:
                    collision = path
                    break
            if collision is None:
                break
            if collision_factory is None:
                return {
                    "delivered": False,
                    "commit": None,
                    "attempts": attempts,
                    "additions": working_additions,
                    "notices": notices
                    + [f"Path collision at {collision}; publication was not applied"],
                }
            collision_count += 1
            if collision_count > 32:
                raise ContextOSError("Could not generate a unique coordination ID")
            replacement = collision_factory(collision)
            if replacement == collision or replacement in working_additions:
                continue
            content = working_additions.pop(collision)
            working_additions[replacement] = content
            notices.append(
                f"ID collision at {collision}; regenerated as {replacement}"
            )

        effective_additions: dict[str, str] = {}
        for path, content in working_additions.items():
            remote_blob = _tree_blob(root, head, path)
            local_blob = _hash_object(root, content)
            if remote_blob != local_blob:
                effective_additions[path] = content

        effective_deletions: list[str] = []
        for path, expected_blob in deletions.items():
            remote_blob = _tree_blob(root, head, path)
            if remote_blob is None:
                continue
            if expected_blob is not None and remote_blob != expected_blob:
                return {
                    "delivered": False,
                    "commit": None,
                    "attempts": attempts,
                    "additions": working_additions,
                    "notices": notices
                    + [
                        f"Refused to delete changed coordination file {path}; "
                        "fetch and review it again"
                    ],
                }
            effective_deletions.append(path)

        if not effective_additions and not effective_deletions:
            return {
                "delivered": True,
                "commit": head,
                "attempts": attempts,
                "additions": working_additions,
                "notices": notices,
            }

        last_commit = _commit_change(
            root,
            parent=head,
            additions=effective_additions,
            deletions=effective_deletions,
            message=message,
            now=now,
        )
        attempts += 1
        try:
            pushed = _push(root)
            push_ok = pushed.returncode == 0
            last_error = (pushed.stderr or pushed.stdout).strip()
        except Exception as exc:  # an injected or host-level push failure
            push_ok = False
            last_error = str(exc)

        if push_ok:
            confirmed = _fetch_coordination(root)
            if confirmed is not None:
                state_ok = all(
                    _tree_blob(root, confirmed, path) == _hash_object(root, content)
                    for path, content in working_additions.items()
                ) and all(
                    _tree_blob(root, confirmed, path) is None for path in deletions
                )
                if state_ok:
                    return {
                        "delivered": True,
                        "commit": last_commit,
                        "attempts": attempts,
                        "additions": working_additions,
                        "notices": notices,
                    }

    if last_error:
        notices.append(
            f"Push was not confirmed after {attempts} attempts: {last_error}"
        )
    else:
        notices.append(f"Push was not confirmed after {attempts} attempts")
    return {
        "delivered": False,
        "commit": None,
        "attempts": attempts,
        "additions": working_additions,
        "notices": notices,
    }


def _outbox_dir(root: Path) -> Path:
    return root / _OUTBOX_NAME


def _queue_message(
    root: Path,
    *,
    path: str,
    content: str,
    runtime: str,
    now: datetime,
) -> Path:
    directory = _outbox_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "message",
        "id": PurePosixPath(path).stem,
        "path": path,
        "content": content,
        "runtime": runtime,
        "queued_at": _iso(now),
    }

    existing = [
        int(entry.name[:6])
        for entry in directory.glob("*.json")
        if entry.name[:6].isdigit()
    ]
    for sequence in range(max(existing, default=0) + 1, 1_000_000):
        candidate = directory / f"{sequence:06d}-{secrets.token_hex(4)}.json"
        try:
            with candidate.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
            return candidate
        except FileExistsError:
            continue
    raise ContextOSError("Could not allocate an outbox entry")


def _flush_outbox(
    root: Path,
    *,
    now: datetime,
) -> tuple[list[dict[str, Any]], bool, list[str]]:
    directory = _outbox_dir(root)
    if not directory.exists():
        return [], False, []

    delivered: list[dict[str, Any]] = []
    notices: list[str] = []
    for queued_file in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(queued_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            notices.append(f"Could not read queued message {queued_file.name}: {exc}")
            return delivered, True, notices

        if payload.get("type") != "message":
            notices.append(f"Unsupported outbox entry {queued_file.name}")
            return delivered, True, notices

        path = str(payload.get("path", ""))
        content = str(payload.get("content", ""))
        result = _publish_change(
            root,
            additions={path: content},
            deletions={},
            message=f"Deliver queued coordination message {PurePosixPath(path).stem}",
            now=now,
            collision_factory=_regenerate_path,
        )
        final_path = next(iter(result["additions"]))
        receipt = {
            "id": PurePosixPath(final_path).stem,
            "path": final_path,
            "commit": result["commit"],
            "delivered": result["delivered"],
            "attempts": result["attempts"],
        }
        delivered.append(receipt)
        notices.extend(result["notices"])
        if not result["delivered"]:
            payload["id"] = receipt["id"]
            payload["path"] = final_path
            queued_file.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            return delivered, True, notices
        try:
            queued_file.unlink()
        except OSError as exc:
            notices.append(
                f"Delivered {receipt['id']} but could not remove its outbox entry: {exc}"
            )
    return delivered, False, notices


def post_message(
    root: Path,
    *,
    sender: str,
    audience: str,
    kind: str,
    body: str,
    re_ref: str | None = None,
    expires: str | None = None,
    runtime: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(root)
    current = _coerce_now(now)
    sender_value = _scalar(sender, "sender")
    audience_value = _scalar(audience, "audience")
    kind_value = _scalar(kind, "kind").lower()
    runtime_value = _scalar(runtime, "runtime")
    if kind_value not in _KINDS:
        raise ContextOSError(
            f"kind must be one of: {', '.join(sorted(_KINDS))}"
        )
    if not isinstance(body, str) or not body.strip():
        raise ContextOSError("body must not be empty")

    expiry_value = _expiry(expires, now=current, field="expires")
    normalized_ref, notices = _prepare_reference(root, re_ref)

    fields = [
        ("from", sender_value),
        ("audience", audience_value),
        ("kind", kind_value),
    ]
    if normalized_ref is not None:
        fields.append(("re", normalized_ref))
    fields.append(("expires", _iso(expiry_value)))
    content = _render_frontmatter(fields, body)
    if len(content.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ContextOSError(
            f"message exceeds the {MAX_MESSAGE_BYTES}-byte whole-file limit"
        )

    path = _new_path(
        _BOARD_PREFIX,
        now=current,
        runtime=runtime_value,
        slug=body.splitlines()[0],
    )

    try:
        bootstrap_board(root, now=current)
    except ContextOSError as exc:
        queued = _queue_message(
            root,
            path=path,
            content=content,
            runtime=runtime_value,
            now=current,
        )
        return {
            "id": PurePosixPath(path).stem,
            "path": path,
            "commit": None,
            "delivered": False,
            "attempts": 0,
            "queued": str(queued),
            "flushed": [],
            "notices": notices + [f"Message queued locally: {exc}"],
        }

    flushed, blocked, flush_notices = _flush_outbox(root, now=current)
    notices.extend(flush_notices)
    if blocked:
        queued = _queue_message(
            root,
            path=path,
            content=content,
            runtime=runtime_value,
            now=current,
        )
        return {
            "id": PurePosixPath(path).stem,
            "path": path,
            "commit": None,
            "delivered": False,
            "attempts": 0,
            "queued": str(queued),
            "flushed": flushed,
            "notices": notices
            + ["Earlier queued messages remain undelivered; this message was queued"],
        }

    result = _publish_change(
        root,
        additions={path: content},
        deletions={},
        message=f"Post coordination message {PurePosixPath(path).stem}",
        now=current,
        collision_factory=_regenerate_path,
    )
    final_path = next(iter(result["additions"]))
    notices.extend(result["notices"])
    queued_path: str | None = None
    if not result["delivered"]:
        queued_path = str(
            _queue_message(
                root,
                path=final_path,
                content=content,
                runtime=runtime_value,
                now=current,
            )
        )
        notices.append("Message queued in the local outbox")

    return {
        "id": PurePosixPath(final_path).stem,
        "path": final_path,
        "commit": result["commit"],
        "delivered": result["delivered"],
        "attempts": result["attempts"],
        "queued": queued_path,
        "flushed": flushed,
        "notices": notices,
    }


def _claim_content(task: str, owner: str, lease_expires: datetime) -> str:
    return _render_frontmatter(
        [
            ("task", task),
            ("owner", owner),
            ("lease-expires", _iso(lease_expires)),
        ]
    )


def create_claim(
    root: Path,
    *,
    task: str,
    owner: str,
    lease_expires: str | None = None,
    runtime: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(root)
    current = _coerce_now(now)
    task_value = _validate_task(task)
    owner_value = _validate_owner(owner)
    runtime_value = _scalar(runtime, "runtime")
    lease_value = _expiry(
        lease_expires,
        now=current,
        field="lease-expires",
    )
    content = _claim_content(task_value, owner_value, lease_value)
    path = _new_path(
        _CLAIMS_PREFIX,
        now=current,
        runtime=runtime_value,
        slug=task_value,
    )

    bootstrap_board(root, now=current)
    result = _publish_change(
        root,
        additions={path: content},
        deletions={},
        message=f"Create coordination claim {PurePosixPath(path).stem}",
        now=current,
        collision_factory=_regenerate_path,
    )
    final_path = next(iter(result["additions"]))
    return {
        "id": PurePosixPath(final_path).stem,
        "path": final_path,
        "commit": result["commit"],
        "delivered": result["delivered"],
        "attempts": result["attempts"],
        "notices": result["notices"],
    }


def _normalize_claim_id(claim_id: str) -> str:
    value = _scalar(claim_id, "claim_id")
    if "/" in value or "\\" in value or ":" in value:
        raise ContextOSError("claim_id must be a filename ID, not a path")
    if value.endswith(".md"):
        value = value[:-3]
    if not _FILE_RE.fullmatch(value + ".md"):
        raise ContextOSError(f"Invalid claim ID: {value}")
    return value


def release_claim(
    root: Path,
    *,
    claim_id: str,
    then_claim: dict[str, Any] | None = None,
    runtime: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(root)
    current = _coerce_now(now)
    old_id = _normalize_claim_id(claim_id)
    old_path = f"{_CLAIMS_PREFIX}{old_id}.md"
    head = _fetch_coordination(root)
    if head is None:
        raise ContextOSError("The coordination board has not been bootstrapped")
    old_blob = _tree_blob(root, head, old_path)
    if old_blob is None:
        raise ContextOSError(f"Claim does not exist on origin: {old_id}")

    additions: dict[str, str] = {}
    new_path: str | None = None
    if then_claim is not None:
        if not isinstance(then_claim, dict):
            raise ContextOSError("then_claim must be an object")
        if "task" not in then_claim or "owner" not in then_claim:
            raise ContextOSError("then_claim requires task and owner")
        task_value = _validate_task(str(then_claim["task"]))
        owner_value = _validate_owner(str(then_claim["owner"]))
        supplied_lease = then_claim.get("lease_expires")
        if supplied_lease is None:
            supplied_lease = then_claim.get("lease-expires")
        if supplied_lease is not None and not isinstance(supplied_lease, str):
            raise ContextOSError("then_claim lease_expires must be text")
        lease_value = _expiry(
            supplied_lease,
            now=current,
            field="lease-expires",
        )
        new_path = _new_path(
            _CLAIMS_PREFIX,
            now=current,
            runtime=runtime,
            slug=task_value,
        )
        additions[new_path] = _claim_content(task_value, owner_value, lease_value)

    action = "Handoff" if then_claim is not None else "Release"
    result = _publish_change(
        root,
        additions=additions,
        deletions={old_path: old_blob},
        message=f"{action} coordination claim {old_id}",
        now=current,
        collision_factory=_regenerate_path if additions else None,
    )

    handoff_receipt: dict[str, Any] | None = None
    if new_path is not None:
        final_new_path = next(iter(result["additions"]))
        handoff_receipt = {
            "id": PurePosixPath(final_new_path).stem,
            "path": final_new_path,
            "commit": result["commit"],
            "delivered": result["delivered"],
            "attempts": result["attempts"],
        }

    return {
        "id": old_id,
        "path": old_path,
        "commit": result["commit"],
        "delivered": result["delivered"],
        "attempts": result["attempts"],
        "then_claim": handoff_receipt,
        "notices": result["notices"],
    }


def _commit_sequence(root: Path, head: str) -> list[str]:
    result = _git(root, ["rev-list", "--reverse", head], check=False)
    return result.stdout.splitlines() if result.returncode == 0 else []


def _added_paths_for_commits(
    root: Path,
    commits: list[str],
    prefix: str,
) -> list[tuple[str, str]]:
    added: list[tuple[str, str]] = []
    for commit in commits:
        result = _git(
            root,
            [
                "diff-tree",
                "--root",
                "--no-commit-id",
                "--name-only",
                "--diff-filter=A",
                "-r",
                commit,
                "--",
                prefix,
            ],
            check=False,
        )
        if result.returncode != 0:
            continue
        for path in result.stdout.splitlines():
            if path and not path.endswith("/.gitkeep"):
                added.append((commit, path))
    return added


def _current_claims(
    root: Path,
    head: str,
    now: datetime,
    notices: list[str],
) -> list[dict[str, Any]]:
    current_paths = set(_tree_paths(root, head, _CLAIMS_PREFIX))
    current_paths.discard(f"{_CLAIMS_PREFIX}.gitkeep")
    latest_addition: dict[str, tuple[int, str]] = {}
    commits = _commit_sequence(root, head)
    for index, (commit, path) in enumerate(
        _added_paths_for_commits(root, commits, _CLAIMS_PREFIX)
    ):
        if path in current_paths:
            latest_addition[path] = (index, commit)

    ordered_paths = sorted(
        current_paths,
        key=lambda path: (
            latest_addition.get(path, (10**12, ""))[0],
            path,
        ),
    )
    claims: list[dict[str, Any]] = []
    for path in ordered_paths:
        try:
            fields, body = _parse_frontmatter(_read_tree_text(root, head, path))
            for required in ("task", "owner", "lease-expires"):
                if required not in fields:
                    raise ContextOSError(f"missing required key '{required}'")
            lease = _parse_utc(fields["lease-expires"], "lease-expires")
        except ContextOSError as exc:
            notices.append(f"{path}: {exc}")
            continue
        claims.append(
            {
                "id": PurePosixPath(path).stem,
                "path": path,
                "task": fields["task"],
                "owner": fields["owner"],
                "lease_expires": _iso(lease),
                "stale": lease < now,
                "commit": latest_addition.get(path, (0, None))[1],
                "body": body,
            }
        )
    return claims


def _claim_order(claims: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for claim in claims:
        if not claim["stale"]:
            grouped[claim["task"]].append(claim["id"])
    return dict(grouped)


def _cursor_value(cursor_file: Path, notices: list[str]) -> str | None:
    if not cursor_file.exists():
        return None
    try:
        payload = json.loads(cursor_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        notices.append(f"Ignoring unreadable coordination cursor: {exc}")
        return None
    value = payload.get("last_seen")
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", value):
        notices.append("Ignoring invalid last_seen value in coordination cursor")
        return None
    return value


def _commits_after_cursor(
    root: Path,
    head: str,
    cursor: str | None,
    notices: list[str],
) -> list[str]:
    if cursor is None:
        return _commit_sequence(root, head)
    if cursor == head:
        return []
    ancestor = _git(
        root,
        ["merge-base", "--is-ancestor", cursor, head],
        check=False,
    )
    if ancestor.returncode != 0:
        notices.append(
            "The coordination cursor is not an ancestor of the current ref; "
            "scanning the current board"
        )
        return _commit_sequence(root, head)
    result = _git(root, ["rev-list", "--reverse", f"{cursor}..{head}"])
    return result.stdout.splitlines()


def _audience_notice(
    audience: str,
    roles: list[str] | None,
    path: str,
) -> str | None:
    if audience == "all" or _RUN_ID_RE.fullmatch(audience):
        return None
    if roles is None or audience in roles:
        return None
    return (
        f"{path}: audience '{audience}' is neither all, a known role, "
        "nor a runtime/run-id"
    )


def _write_cursor(cursor_file: Path, head: str) -> None:
    try:
        cursor_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = cursor_file.with_name(
            f".{cursor_file.name}.{secrets.token_hex(4)}.tmp"
        )
        temporary.write_text(
            json.dumps({"last_seen": head}, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(cursor_file)
    except OSError as exc:
        raise ContextOSError(f"Could not write coordination cursor: {exc}") from exc


def sync_board(
    root: Path,
    *,
    runtime: str,
    role: str,
    run_id: str,
    cursor_file: Path,
    roles: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(root)
    current = _coerce_now(now)
    runtime_value = _scalar(runtime, "runtime")
    role_value = _scalar(role, "role")
    run_value = _scalar(run_id, "run_id")
    full_run_id = run_value if "/" in run_value else f"{runtime_value}/{run_value}"
    notices: list[str] = []

    head = _fetch_coordination(root)
    if head is None:
        return {
            "commit": None,
            "previous_cursor": None,
            "messages": [],
            "claims": [],
            "claim_order": {},
            "notices": ["The coordination board has not been bootstrapped"],
        }

    cursor_path = Path(cursor_file)
    previous = _cursor_value(cursor_path, notices)
    commits = _commits_after_cursor(root, head, previous, notices)
    current_paths = set(_tree_paths(root, head, _BOARD_PREFIX))
    current_paths.discard(f"{_BOARD_PREFIX}.gitkeep")

    messages: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for commit, path in _added_paths_for_commits(root, commits, _BOARD_PREFIX):
        if path in seen_paths or path not in current_paths:
            continue
        seen_paths.add(path)
        try:
            fields, body = _parse_frontmatter(_read_tree_text(root, head, path))
            for required in ("from", "audience", "kind", "expires"):
                if required not in fields:
                    raise ContextOSError(f"missing required key '{required}'")
            expires_at = _parse_utc(fields["expires"], "expires")
        except ContextOSError as exc:
            notices.append(f"{path}: {exc}")
            continue

        audience = fields["audience"]
        audience_warning = _audience_notice(audience, roles, path)
        if audience_warning is not None:
            notices.append(audience_warning)

        if expires_at <= current:
            continue
        if audience not in {"all", role_value, run_value, full_run_id}:
            continue
        messages.append(
            {
                "id": PurePosixPath(path).stem,
                "path": path,
                "from": fields["from"],
                "audience": audience,
                "kind": fields["kind"],
                "re": fields.get("re"),
                "expires": _iso(expires_at),
                "body": body,
                "commit": commit,
            }
        )

    claims = _current_claims(root, head, current, notices)
    _write_cursor(cursor_path, head)
    return {
        "commit": head,
        "previous_cursor": previous,
        "messages": messages,
        "claims": claims,
        "claim_order": _claim_order(claims),
        "notices": notices,
    }


def _message_documents(
    root: Path,
    head: str,
    notices: list[str],
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in sorted(_tree_paths(root, head, _BOARD_PREFIX)):
        if path.endswith("/.gitkeep"):
            continue
        try:
            text = _read_tree_text(root, head, path)
            fields, body = _parse_frontmatter(text)
            expires_at = _parse_utc(fields["expires"], "expires")
            created_at = _stamp_datetime(PurePosixPath(path).name)
        except (ContextOSError, KeyError) as exc:
            notices.append(f"{path}: {exc}")
            continue
        documents.append(
            {
                "id": PurePosixPath(path).stem,
                "path": path,
                "fields": fields,
                "body": body,
                "text": text,
                "expires_at": expires_at,
                "created_at": created_at,
                "blob": _tree_blob(root, head, path),
            }
        )
    return documents


def compact_board(
    root: Path,
    *,
    apply: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(root)
    current = _coerce_now(now)
    notices: list[str] = []
    head = _fetch_coordination(root)
    if head is None:
        raise ContextOSError("The coordination board has not been bootstrapped")

    messages = _message_documents(root, head, notices)
    claims = _current_claims(root, head, current, notices)
    expired = [
        document["path"]
        for document in messages
        if document["expires_at"] < current
    ]
    stale_claims = [claim["path"] for claim in claims if claim["stale"]]
    promotion_candidates: list[str] = []
    for document in messages:
        if document["expires_at"] <= current:
            continue
        if document["fields"].get("kind") not in {"note", "alert"}:
            continue
        ttl = document["expires_at"] - document["created_at"]
        age = current - document["created_at"]
        if ttl > timedelta(0) and age > ttl / 2:
            promotion_candidates.append(document["path"])

    commit = head
    attempts = 0
    delivered = True
    if apply and expired:
        expected = {
            document["path"]: document["blob"]
            for document in messages
            if document["path"] in expired
        }
        result = _publish_change(
            root,
            additions={},
            deletions=expected,
            message=f"Compact {len(expired)} expired coordination message(s)",
            now=current,
        )
        commit = result["commit"]
        attempts = result["attempts"]
        delivered = result["delivered"]
        notices.extend(result["notices"])

    return {
        "commit": commit,
        "base_commit": head,
        "apply": apply,
        "delivered": delivered,
        "attempts": attempts,
        "expired_messages": expired,
        "stale_claims": stale_claims,
        "promotion_candidates": promotion_candidates,
        "notices": notices,
    }


def _filename_errors(path: str) -> list[str]:
    filename = PurePosixPath(path).name
    errors: list[str] = []
    if ":" in filename:
        errors.append("filename contains a colon")
    if not _FILE_RE.fullmatch(filename):
        errors.append("filename does not match the coordination ID pattern")
    return errors


def _ttl_errors(
    filename: str,
    expiry_text: str,
    field: str,
) -> list[str]:
    errors: list[str] = []
    try:
        created = _stamp_datetime(filename)
        expires_at = _parse_utc(expiry_text, field)
    except ContextOSError as exc:
        return [str(exc)]
    if expires_at <= created:
        errors.append(f"{field} is not later than the filename timestamp")
    if expires_at > created + MAX_TTL:
        errors.append(
            f"{field} exceeds the {MAX_TTL.days}-day maximum TTL "
            "from the filename timestamp"
        )
    return errors


def validate_board(
    root: Path,
    *,
    roles: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(root)
    current = _coerce_now(now)
    head = _fetch_coordination(root)
    if head is None:
        raise ContextOSError("The coordination board has not been bootstrapped")
    _git(root, ["fetch", "origin"], check=False)

    errors: list[str] = []
    warnings: list[str] = []
    seen_ids: dict[str, str] = {}
    message_reports: list[dict[str, Any]] = []
    claim_reports: list[dict[str, Any]] = []

    for prefix, document_type in (
        (_BOARD_PREFIX, "message"),
        (_CLAIMS_PREFIX, "claim"),
    ):
        for path in sorted(_tree_paths(root, head, prefix)):
            if path.endswith("/.gitkeep"):
                continue
            filename = PurePosixPath(path).name
            identifier = PurePosixPath(path).stem
            file_errors = _filename_errors(path)
            if identifier in seen_ids:
                file_errors.append(
                    f"duplicate ID also used by {seen_ids[identifier]}"
                )
            else:
                seen_ids[identifier] = path

            try:
                text = _read_tree_text(root, head, path)
            except ContextOSError as exc:
                errors.append(f"{path}: {exc}")
                continue
            if document_type == "message" and len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
                file_errors.append(
                    f"message exceeds the {MAX_MESSAGE_BYTES}-byte whole-file limit"
                )

            try:
                fields, body = _parse_frontmatter(text)
            except ContextOSError as exc:
                file_errors.append(str(exc))
                fields, body = {}, ""

            if document_type == "message":
                required = ("from", "audience", "kind", "expires")
                for key in required:
                    if key not in fields:
                        file_errors.append(f"missing required key '{key}'")
                if fields.get("kind") not in _KINDS:
                    file_errors.append(
                        f"kind must be one of: {', '.join(sorted(_KINDS))}"
                    )
                if "expires" in fields:
                    file_errors.extend(
                        _ttl_errors(filename, fields["expires"], "expires")
                    )
                if "re" in fields:
                    try:
                        _parse_reference(fields["re"])
                    except ContextOSError as exc:
                        file_errors.append(str(exc))
                    else:
                        valid_reference, reason = _reference_status(root, fields["re"])
                        if not valid_reference:
                            warnings.append(
                                f"{path}: reference degraded to summary-only: {reason}"
                            )

                audience = fields.get("audience")
                if audience is not None:
                    warning = _audience_notice(audience, roles, path)
                    if warning is not None:
                        warnings.append(warning)
                matched = [
                    label
                    for label, pattern in _SUSPICIOUS_PATTERNS
                    if pattern.search(body)
                ]
                if matched:
                    warnings.append(
                        f"{path}: suspicious imperative or authorization language: "
                        + ", ".join(matched)
                    )

                report = {
                    "id": identifier,
                    "path": path,
                    "from": fields.get("from"),
                    "audience": fields.get("audience"),
                    "kind": fields.get("kind"),
                    "expires": fields.get("expires"),
                    "body": body,
                }
                message_reports.append(report)
            else:
                required = ("task", "owner", "lease-expires")
                for key in required:
                    if key not in fields:
                        file_errors.append(f"missing required key '{key}'")
                if "task" in fields:
                    try:
                        _validate_task(fields["task"])
                    except ContextOSError as exc:
                        file_errors.append(str(exc))
                if "owner" in fields:
                    try:
                        _validate_owner(fields["owner"])
                    except ContextOSError as exc:
                        file_errors.append(str(exc))
                lease: datetime | None = None
                if "lease-expires" in fields:
                    file_errors.extend(
                        _ttl_errors(
                            filename,
                            fields["lease-expires"],
                            "lease-expires",
                        )
                    )
                    try:
                        lease = _parse_utc(
                            fields["lease-expires"],
                            "lease-expires",
                        )
                    except ContextOSError:
                        lease = None
                claim_reports.append(
                    {
                        "id": identifier,
                        "path": path,
                        "task": fields.get("task"),
                        "owner": fields.get("owner"),
                        "lease_expires": fields.get("lease-expires"),
                        "stale": lease is not None and lease < current,
                    }
                )

            errors.extend(f"{path}: {finding}" for finding in file_errors)

    order_notices: list[str] = []
    ordered_claims = _current_claims(root, head, current, order_notices)
    warnings.extend(order_notices)
    return {
        "commit": head,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "notices": list(warnings),
        "messages": message_reports,
        "claims": claim_reports,
        "claim_order": _claim_order(ordered_claims),
    }
