#!/usr/bin/env python3
"""Inventory Gemini CLI sessions and surface repeated workflow candidates.

Gemini's current JSONL recordings are append logs. This module folds metadata
updates and rewinds before analyzing the surviving conversation state. The
default report excludes free-form text, paths, tool arguments, and reasoning.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)[\"']?(?:api[_-]?key|apikey|token|password|secret|authorization)"
        r"[\"']?\s*[:=]\s*[\"']?[^\"'\s,;}]+[\"']?"
    ),
    re.compile(r"\b(?:sk|ghp|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b[A-Z0-9]{20}\b"),
    re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
)
PRIVATE_CONTENT_KEYS = {"thought", "thoughts", "thinking", "reasoning"}
VALIDATION_STATUSES = {"passed", "failed", "unknown"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a privacy-first inventory of Gemini CLI session recordings."
    )
    parser.add_argument(
        "session_dir",
        type=Path,
        help="One explicitly selected Gemini project/session directory.",
    )
    parser.add_argument("--output", type=Path, help="Write JSON here instead of stdout.")
    parser.add_argument(
        "--since",
        type=dt.date.fromisoformat,
        help="Only include sessions updated on or after YYYY-MM-DD; unknown dates are excluded.",
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=2,
        help="Minimum positively validated sessions for a workflow candidate (default: 2).",
    )
    parser.add_argument(
        "--session-id",
        action="append",
        default=[],
        help="Select a session for sensitive opt-in fields; repeat for multiple sessions.",
    )
    parser.add_argument(
        "--include-content",
        action="store_true",
        help="For --session-id selections only, include best-effort-redacted observable text. Still sensitive.",
    )
    parser.add_argument(
        "--include-summaries",
        action="store_true",
        help="For --session-id selections only, include free-form workflow summaries.",
    )
    parser.add_argument(
        "--include-paths",
        action="store_true",
        help="For --session-id selections only, include sanitized touched-path basenames.",
    )
    return parser.parse_args(argv)


def redact_text(value: str) -> str:
    """Best-effort redaction; callers must still treat returned text as sensitive."""
    redacted = value
    for index, pattern in enumerate(SECRET_PATTERNS):
        replacement = "<REDACTED_EMAIL>" if index == len(SECRET_PATTERNS) - 1 else "<REDACTED_SECRET>"
        redacted = pattern.sub(replacement, redacted)
    redacted = re.sub(r"(?<!\w)/(?:[^\s/]+/)+([^\s/]+)", r"<ABSOLUTE_PATH>/\1", redacted)
    redacted = re.sub(r"[A-Za-z]:\\(?:[^\s\\]+\\)+([^\s\\]+)", r"<ABSOLUTE_PATH>/\1", redacted)
    return redacted


def sanitize_path(value: str) -> str:
    normalized = value.replace("\\", "/").rstrip("/")
    basename = normalized.rsplit("/", 1)[-1] or "<directory>"
    return f"<PATH>/{redact_text(basename)}"


def load_records(path: Path) -> tuple[list[Any], str, list[str], str]:
    warnings: list[str] = []
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        warnings.append(f"{path.name}: recording is not valid UTF-8")
        return [], "invalid", warnings, digest
    if not text.strip():
        return [], "empty", warnings, digest

    try:
        payload = json.loads(text)
        if isinstance(payload, list):
            return payload, "json", warnings, digest
        if isinstance(payload, dict):
            return [payload], "json", warnings, digest
    except json.JSONDecodeError:
        pass

    records: list[Any] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            warnings.append(f"{path.name}:{line_number}: skipped malformed JSONL record")
    return records, "jsonl", warnings, digest


def is_message_record(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("id"), str) and value.get("type") in {
        "user",
        "gemini",
        "info",
        "error",
        "warning",
    }


def validate_scratchpad(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        return "memoryScratchpad must be a version 1 object or null"

    alias_groups = (
        (("workflowSummary", "workflow_summary"), str, "a string"),
        (("toolSequence", "tool_sequence"), list, "a string array"),
        (("touchedPaths", "touched_paths"), list, "a string array"),
    )
    for aliases, expected_type, expected_label in alias_groups:
        present = [key for key in aliases if key in value]
        for key in present:
            field = value[key]
            if not isinstance(field, expected_type) or (
                expected_type is list and not all(isinstance(item, str) for item in field)
            ):
                return f"memoryScratchpad.{key} must be {expected_label}"
        if len(present) == 2 and value[present[0]] != value[present[1]]:
            return f"memoryScratchpad aliases {present[0]} and {present[1]} conflict"

    statuses = [
        value[key]
        for key in ("validationStatus", "validation_status")
        if key in value
    ]
    if any(not isinstance(status, str) or status not in VALIDATION_STATUSES for status in statuses):
        return "memoryScratchpad.validationStatus must be passed, failed, or unknown"
    if len(statuses) == 2 and statuses[0] != statuses[1]:
        return "memoryScratchpad validation status aliases conflict"
    return None


def validate_message(value: Any) -> str | None:
    if not isinstance(value, dict):
        return "message must be an object"
    if not isinstance(value.get("id"), str) or not value["id"]:
        return "message.id must be a non-empty string"
    if value.get("type") not in {"user", "gemini", "info", "error", "warning"}:
        return "message.type is unsupported"
    if not isinstance(value.get("timestamp"), str) or not value["timestamp"]:
        return "message.timestamp must be a non-empty string"
    if "content" not in value or not isinstance(value["content"], (str, list, dict)):
        return "message.content has an unsupported shape"
    calls = value.get("toolCalls")
    if calls is not None:
        if not isinstance(calls, list):
            return "message.toolCalls must be an array"
        for call in calls:
            if not isinstance(call, dict):
                return "tool call must be an object"
            if not all(isinstance(call.get(key), str) and call[key] for key in ("id", "name", "status", "timestamp")):
                return "tool call requires string id, name, status, and timestamp"
            if not isinstance(call.get("args"), dict):
                return "tool call args must be an object"
    return None


def validate_metadata(value: dict[str, Any], *, initial: bool) -> str | None:
    if initial:
        if not isinstance(value.get("sessionId"), str) or not value["sessionId"]:
            return "initial metadata requires sessionId"
        if not isinstance(value.get("projectHash"), str) or not value["projectHash"]:
            return "initial metadata requires projectHash"
    for key in ("sessionId", "projectHash"):
        if key in value and (not isinstance(value[key], str) or not value[key]):
            return f"metadata.{key} must be a non-empty string"
    for key in ("startTime", "lastUpdated", "summary", "kind"):
        if key in value and value[key] is not None and not isinstance(value[key], str):
            return f"metadata.{key} must be a string"
    if "directories" in value and value["directories"] is not None and (
        not isinstance(value["directories"], list)
        or not all(isinstance(item, str) for item in value["directories"])
    ):
        return "metadata.directories must be a string array"
    for key in ("memoryScratchpad", "memory_scratchpad"):
        if key in value:
            problem = validate_scratchpad(value[key])
            if problem:
                return problem
    if (
        "memoryScratchpad" in value
        and "memory_scratchpad" in value
        and value["memoryScratchpad"] != value["memory_scratchpad"]
    ):
        return "metadata memory scratchpad aliases conflict"
    if "messages" in value:
        if not isinstance(value["messages"], list):
            return "metadata.messages must be an array"
        for message in value["messages"]:
            problem = validate_message(message)
            if problem:
                return problem
    return None


def validate_record(record: Any) -> str | None:
    if not isinstance(record, dict):
        return "record must be an object"
    if "$rewindTo" in record:
        if set(record) != {"$rewindTo"}:
            return "$rewindTo record has unexpected fields"
        return None if isinstance(record["$rewindTo"], str) and record["$rewindTo"] else "$rewindTo must be a non-empty string"
    if "$set" in record:
        if set(record) != {"$set"}:
            return "$set record has unexpected fields"
        if not isinstance(record["$set"], dict):
            return "$set must be an object"
        return validate_metadata(record["$set"], initial=False)
    if "id" in record or "type" in record:
        return validate_message(record)
    if "sessionId" in record or "projectHash" in record:
        return validate_metadata(record, initial=True)
    return "unrecognized record shape"


def fold_records(
    records: list[Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], bool, list[str]]:
    """Mirror Gemini's append-log fold for metadata, messages, rewinds, and checkpoints."""
    metadata: dict[str, Any] = {}
    messages: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    scratchpad_tracking = False
    scratchpad_stale = False
    schema_warnings: list[str] = []

    def put_message(message: dict[str, Any]) -> None:
        message_id = message["id"]
        if message_id not in messages:
            order.append(message_id)
        messages[message_id] = message

    def replace_messages(values: Any) -> None:
        messages.clear()
        order.clear()
        if isinstance(values, list):
            for message in values:
                if is_message_record(message):
                    put_message(message)

    for index, record in enumerate(records, start=1):
        problem = validate_record(record)
        if problem:
            schema_warnings.append(f"record {index}: {problem}")
        if not isinstance(record, dict):
            continue

        rewind_id = record.get("$rewindTo")
        if isinstance(rewind_id, str):
            if scratchpad_tracking:
                scratchpad_stale = True
            if rewind_id in order:
                start = order.index(rewind_id)
                for message_id in order[start:]:
                    messages.pop(message_id, None)
                del order[start:]
            else:
                messages.clear()
                order.clear()
            continue

        if is_message_record(record):
            if scratchpad_tracking:
                scratchpad_stale = True
            put_message(record)
            continue

        update = record.get("$set")
        if isinstance(update, dict):
            scratchpad_key = (
                "memoryScratchpad" if "memoryScratchpad" in update else "memory_scratchpad"
            )
            if scratchpad_key in update:
                scratchpad_tracking = bool(update.get(scratchpad_key))
                scratchpad_stale = False
            if "messages" in update:
                replace_messages(update.get("messages"))
            metadata.update(update)
            continue

        # Initial metadata or a whole legacy ConversationRecord.
        if isinstance(record.get("sessionId"), str):
            if "messages" in record:
                replace_messages(record.get("messages"))
            metadata.update(record)

    metadata.pop("messages", None)
    if (
        not isinstance(metadata.get("sessionId"), str)
        or not metadata["sessionId"]
        or not isinstance(metadata.get("projectHash"), str)
        or not metadata["projectHash"]
    ):
        schema_warnings.append("recording is missing required sessionId/projectHash metadata")
    return metadata, [messages[message_id] for message_id in order], scratchpad_stale, schema_warnings


def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None


def latest_timestamp(metadata: dict[str, Any], messages: list[dict[str, Any]]) -> str | None:
    for key in ("lastUpdated", "updatedAt", "updated_at"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    values = [message.get("timestamp") for message in messages if isinstance(message.get("timestamp"), str)]
    if values:
        return max(values)
    for key in ("startTime", "start_time"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def scratchpad_from(metadata: dict[str, Any]) -> dict[str, Any] | None:
    value = metadata.get("memoryScratchpad") or metadata.get("memory_scratchpad")
    return value if isinstance(value, dict) else None


def collect_tool_names(messages: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for message in messages:
        calls = message.get("toolCalls") or message.get("tool_calls")
        if not isinstance(calls, list):
            continue
        for call in calls:
            if not isinstance(call, dict):
                continue
            name = call.get("name") or call.get("toolName") or call.get("tool_name")
            if isinstance(name, str) and name:
                names.append(name)
    return names


def extract_text_parts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict):
            if any(key.lower() in PRIVATE_CONTENT_KEYS for key in map(str, part.keys())):
                continue
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    return parts


def collect_observable_text(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    observable: list[dict[str, str]] = []
    for message in messages:
        role = message.get("type")
        if role not in {"user", "gemini"}:
            continue
        parts = extract_text_parts(message.get("displayContent") or message.get("content"))
        if parts:
            observable.append({"role": role, "text": redact_text("\n".join(parts))})
    return observable


def validation_is_success(value: Any) -> bool:
    return value == "passed"


def session_summary(
    path: Path,
    *,
    selected_ids: set[str] | None = None,
    include_content: bool = False,
    include_paths: bool = False,
    include_summaries: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    records, source_format, warnings, file_digest = load_records(path)
    metadata, messages, scratchpad_stale, schema_warnings = fold_records(records)
    warnings.extend(f"{path.name}: {warning}" for warning in schema_warnings)
    scratchpad = scratchpad_from(metadata)
    raw_session_id = metadata.get("sessionId")
    session_id = str(raw_session_id or "<missing-session-id>")
    project_hash = str(metadata.get("projectHash") or "")
    is_selected = session_id in (selected_ids or set())
    recording_complete = not warnings

    scratchpad_tools: list[str] = []
    validation_status: Any = None
    workflow_summary: str | None = None
    touched_paths: list[str] = []
    if scratchpad and not scratchpad_stale and recording_complete:
        sequence = scratchpad.get("toolSequence") or scratchpad.get("tool_sequence")
        if isinstance(sequence, list):
            scratchpad_tools = [str(item) for item in sequence if isinstance(item, (str, int))]
        validation_status = scratchpad.get("validationStatus") or scratchpad.get("validation_status")
        summary = scratchpad.get("workflowSummary") or scratchpad.get("workflow_summary")
        if isinstance(summary, str) and summary.strip():
            workflow_summary = summary.strip()
        touched = scratchpad.get("touchedPaths") or scratchpad.get("touched_paths")
        if isinstance(touched, list):
            touched_paths = [str(item) for item in touched if isinstance(item, str)]

    tool_sequence = scratchpad_tools or collect_tool_names(messages)
    identity = f"{project_hash}\0{raw_session_id}" if raw_session_id else file_digest
    entry: dict[str, Any] = {
        "session_id": session_id,
        "source_file": path.name,
        "source_format": source_format,
        "updated_at": latest_timestamp(metadata, messages),
        "message_records": len(messages),
        "tool_sequence": tool_sequence,
        "validation_status": str(validation_status or "unknown").lower(),
        "validation_passed": validation_is_success(validation_status),
        "scratchpad_stale": scratchpad_stale,
        "recording_complete": recording_complete,
        "session_fingerprint": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "recording_digest": file_digest,
    }
    if include_summaries and is_selected and recording_complete and workflow_summary:
        entry["workflow_summary"] = redact_text(workflow_summary)
    if include_paths and is_selected and recording_complete:
        entry["touched_paths"] = [sanitize_path(value) for value in touched_paths]
    if include_content and is_selected and recording_complete:
        entry["observable_messages"] = collect_observable_text(messages)
    return entry, warnings


def candidate_key(session: dict[str, Any]) -> tuple[str, str] | None:
    summary = session.get("workflow_summary")
    if isinstance(summary, str) and summary:
        normalized = re.sub(r"\b\d+\b", "#", summary.lower())
        normalized = re.sub(r"\s+", " ", normalized).strip(" .:-")[:240]
        return "summary:" + normalized, summary
    tools = session.get("tool_sequence")
    if isinstance(tools, list) and tools:
        label = "Tool sequence: " + " → ".join(map(str, tools))
        return "tools:" + "|".join(str(tool).lower() for tool in tools), label
    return None


def build_candidates(sessions: list[dict[str, Any]], minimum: int) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    fingerprint_counts = collections.Counter(session["session_fingerprint"] for session in sessions)
    duplicate_fingerprints = {
        fingerprint for fingerprint, count in fingerprint_counts.items() if count > 1
    }
    for session in sessions:
        if not session["recording_complete"]:
            continue
        if session["session_fingerprint"] in duplicate_fingerprints:
            continue
        keyed = candidate_key(session)
        if not keyed:
            continue
        key, label = keyed
        group = groups.setdefault(
            key,
            {"label": label, "session_ids": [], "validated_session_ids": [], "tool_sequences": []},
        )
        group["session_ids"].append(session["session_id"])
        if session["validation_passed"]:
            group["validated_session_ids"].append(session["session_id"])
            group["tool_sequences"].append(session["tool_sequence"])

    candidates: list[dict[str, Any]] = []
    for group in groups.values():
        occurrences = len(group["session_ids"])
        validated = len(group["validated_session_ids"])
        if validated < minimum:
            continue
        sequences = collections.Counter(tuple(sequence) for sequence in group.pop("tool_sequences"))
        group.update(
            {
                "occurrences": occurrences,
                "validated_sessions": validated,
                "validation_ratio": round(validated / occurrences, 3),
                "common_tool_sequence": list(sequences.most_common(1)[0][0]) if sequences else [],
                "score": validated * 5 + round(validated / occurrences, 3) * 2,
            }
        )
        candidates.append(group)
    return sorted(candidates, key=lambda item: (-item["score"], item["label"].lower()))


def discover_files(session_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in session_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".json", ".jsonl"}
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.session_dir.is_dir():
        print(f"error: session directory does not exist: {args.session_dir}", file=sys.stderr)
        return 2
    if args.min_occurrences < 1:
        print("error: --min-occurrences must be at least 1", file=sys.stderr)
        return 2
    sensitive_opt_in = args.include_content or args.include_summaries or args.include_paths
    if sensitive_opt_in and not args.session_id:
        print(
            "error: --include-content, --include-summaries, and --include-paths require at least one --session-id",
            file=sys.stderr,
        )
        return 2

    files = discover_files(args.session_dir)
    selected_ids = set(args.session_id)
    rows: list[tuple[Path, dict[str, Any]]] = []
    warnings: list[str] = []
    id_to_paths: dict[str, list[Path]] = collections.defaultdict(list)
    for path in files:
        try:
            session, file_warnings = session_summary(path)
        except OSError as error:
            warnings.append(f"{path.name}: {error}")
            continue
        rows.append((path, session))
        id_to_paths[session["session_id"]].append(path)
        warnings.extend(file_warnings)

    if sensitive_opt_in:
        missing_ids = sorted(selected_ids - set(id_to_paths))
        if missing_ids:
            print("error: selected session IDs not found: " + ", ".join(missing_ids), file=sys.stderr)
            return 2
        duplicate_ids = sorted(session_id for session_id in selected_ids if len(id_to_paths[session_id]) != 1)
        if duplicate_ids:
            print(
                "error: selected session IDs resolve to multiple recordings: " + ", ".join(duplicate_ids),
                file=sys.stderr,
            )
            return 2
        incomplete_ids = sorted(
            session["session_id"]
            for _, session in rows
            if session["session_id"] in selected_ids and not session["recording_complete"]
        )
        if incomplete_ids:
            print(
                "error: selected recordings are incomplete or malformed: " + ", ".join(incomplete_ids),
                file=sys.stderr,
            )
            return 2

    duplicate_fingerprints = {
        fingerprint
        for fingerprint, count in collections.Counter(
            session["session_fingerprint"] for _, session in rows
        ).items()
        if count > 1
    }
    if duplicate_fingerprints:
        warnings.append(
            f"excluded {len(duplicate_fingerprints)} duplicate session identity/identities from candidate evidence"
        )

    included_rows: list[tuple[Path, dict[str, Any]]] = []
    for path, session in rows:
        if args.since:
            updated = parse_date(session.get("updated_at"))
            if updated is None:
                warnings.append(f"{path.name}: excluded because update date is unknown")
                continue
            if updated < args.since:
                continue
        included_rows.append((path, session))

    if sensitive_opt_in:
        excluded_ids = sorted(selected_ids - {session["session_id"] for _, session in included_rows})
        if excluded_ids:
            print(
                "error: selected sessions were excluded by the date boundary: " + ", ".join(excluded_ids),
                file=sys.stderr,
            )
            return 2

    # Candidate evidence is always computed from the metadata-only pass. Sensitive
    # opt-ins may add human-readable labels to selected rows, but must not alter
    # grouping, counts, or rankings.
    workflow_candidates = build_candidates(
        [session for _, session in included_rows], args.min_occurrences
    )

    if sensitive_opt_in:
        enriched_rows: list[tuple[Path, dict[str, Any]]] = []
        for path, session in included_rows:
            if session["session_id"] in selected_ids:
                session, _ = session_summary(
                    path,
                    selected_ids=selected_ids,
                    include_content=args.include_content,
                    include_paths=args.include_paths,
                    include_summaries=args.include_summaries,
                )
            enriched_rows.append((path, session))
        included_rows = enriched_rows

    sessions = [session for _, session in included_rows]

    report = {
        "schema_version": 2,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": {"session_dir_name": args.session_dir.name, "files_scanned": len(files)},
        "privacy": {
            "metadata_only": not sensitive_opt_in,
            "selected_session_count": len(selected_ids),
            "full_paths_included": False,
            "observable_content_included": args.include_content,
            "free_form_summaries_included": args.include_summaries,
            "thought_or_reasoning_included": False,
            "content_is_sensitive": sensitive_opt_in,
            "note": "Redaction is best-effort, not a guarantee. Review before sharing or committing.",
        },
        "sessions": sessions,
        "workflow_candidates": workflow_candidates,
        "warnings": warnings,
    }
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
