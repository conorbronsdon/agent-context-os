#!/usr/bin/env python3
"""Inventory Gemini CLI sessions and surface repeated workflow candidates.

The default report is metadata-only: it excludes message bodies, reasoning,
tool arguments, and full paths. Observable message content is opt-in.
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
from typing import Any, Iterable


SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\b(?:sk|ghp|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b"),
)
PRIVATE_CONTENT_KEYS = {"thought", "thoughts", "thinking", "reasoning"}


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
        help="Only include sessions updated on or after YYYY-MM-DD.",
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=2,
        help="Minimum sessions for a workflow candidate (default: 2).",
    )
    parser.add_argument(
        "--include-content",
        action="store_true",
        help="Include redacted observable user/assistant text. Never includes thought/reasoning fields.",
    )
    parser.add_argument(
        "--include-paths",
        action="store_true",
        help="Include sanitized touched-path basenames. Full paths are never emitted.",
    )
    return parser.parse_args(argv)


def redact_text(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("<REDACTED_SECRET>", redacted)
    redacted = re.sub(r"(?<!\w)/(?:[^\s/]+/)+([^\s/]+)", r"<ABSOLUTE_PATH>/\1", redacted)
    redacted = re.sub(r"[A-Za-z]:\\(?:[^\s\\]+\\)+([^\s\\]+)", r"<ABSOLUTE_PATH>/\1", redacted)
    return redacted


def sanitize_path(value: str) -> str:
    normalized = value.replace("\\", "/").rstrip("/")
    basename = normalized.rsplit("/", 1)[-1] or "<directory>"
    return f"<PATH>/{redact_text(basename)}"


def iter_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for key, child in value.items():
            if str(key).lower() not in PRIVATE_CONTENT_KEYS:
                yield from iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_dicts(child)


def load_records(path: Path) -> tuple[list[Any], str, list[str]]:
    warnings: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    stripped = text.lstrip()
    if not stripped:
        return [], "empty", warnings

    try:
        payload = json.loads(text)
        if isinstance(payload, list):
            return payload, "json", warnings
        if isinstance(payload, dict):
            records = payload.get("records") or payload.get("messages")
            if isinstance(records, list):
                metadata = {key: value for key, value in payload.items() if key not in {"records", "messages"}}
                return [metadata, *records], "json", warnings
            return [payload], "json", warnings
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
    return records, "jsonl", warnings


def first_string(objects: Iterable[dict[str, Any]], keys: tuple[str, ...]) -> str | None:
    for obj in objects:
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def collect_timestamps(objects: Iterable[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for obj in objects:
        for key in ("timestamp", "updatedAt", "updated_at", "startTime", "start_time"):
            value = obj.get(key)
            if isinstance(value, str) and value:
                values.append(value)
    return values


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


def collect_scratchpads(objects: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    scratchpads: list[dict[str, Any]] = []
    for obj in objects:
        value = obj.get("memoryScratchpad") or obj.get("memory_scratchpad")
        if isinstance(value, dict):
            scratchpads.append(value)
    return scratchpads


def collect_tool_names(objects: Iterable[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for obj in objects:
        for key in ("toolCalls", "tool_calls"):
            calls = obj.get(key)
            if isinstance(calls, list):
                for call in calls:
                    if isinstance(call, dict):
                        name = call.get("name") or call.get("toolName") or call.get("tool_name")
                        if isinstance(name, str) and name:
                            names.append(name)
        if obj.get("type") in {"tool_call", "function_call"}:
            name = obj.get("name") or obj.get("tool_name")
            if isinstance(name, str) and name:
                names.append(name)
    return list(dict.fromkeys(names))


def collect_observable_text(records: list[Any]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        message = record.get("message") if isinstance(record.get("message"), dict) else record
        role = message.get("role") or message.get("type") or record.get("role")
        if role not in {"user", "assistant", "model", "gemini"}:
            continue
        content = message.get("content")
        parts: list[str] = []
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    if any(key in part for key in PRIVATE_CONTENT_KEYS):
                        continue
                    text = part.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        if parts:
            messages.append({"role": str(role), "text": redact_text("\n".join(parts))})
    return messages


def normalized_summary(value: str) -> str:
    value = redact_text(value).lower()
    value = re.sub(r"\b\d+\b", "#", value)
    value = re.sub(r"\s+", " ", value).strip(" .:-")
    return value[:240]


def validation_is_success(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"passed", "pass", "success", "successful", "validated", "complete"}
    if isinstance(value, dict):
        return any(validation_is_success(child) for child in value.values())
    return False


def session_summary(path: Path, include_content: bool, include_paths: bool) -> tuple[dict[str, Any], list[str]]:
    records, source_format, warnings = load_records(path)
    objects = list(iter_dicts(records))
    timestamps = collect_timestamps(objects)
    updated_at = max(timestamps) if timestamps else None
    scratchpads = collect_scratchpads(objects)
    tools = collect_tool_names(objects)

    summaries: list[str] = []
    scratchpad_tools: list[str] = []
    paths: list[str] = []
    validation_values: list[Any] = []
    for pad in scratchpads:
        summary = pad.get("workflowSummary") or pad.get("workflow_summary")
        if isinstance(summary, str) and summary.strip():
            summaries.append(redact_text(summary.strip()))
        sequence = pad.get("toolSequence") or pad.get("tool_sequence")
        if isinstance(sequence, list):
            scratchpad_tools.extend(str(item) for item in sequence if isinstance(item, (str, int)))
        touched = pad.get("touchedPaths") or pad.get("touched_paths")
        if isinstance(touched, list):
            paths.extend(str(item) for item in touched if isinstance(item, str))
        validation_values.append(pad.get("validationStatus") or pad.get("validation_status"))

    tool_sequence = list(dict.fromkeys(scratchpad_tools or tools))
    session_id = first_string(objects, ("sessionId", "session_id", "id")) or path.stem
    entry: dict[str, Any] = {
        "session_id": redact_text(session_id),
        "source_file": path.name,
        "source_format": source_format,
        "updated_at": updated_at,
        "message_records": sum(
            1
            for record in records
            if isinstance(record, dict)
            and (record.get("type") == "message" or "message" in record or "role" in record)
        ),
        "workflow_summaries": list(dict.fromkeys(summaries)),
        "tool_sequence": tool_sequence,
        "validation_passed": any(validation_is_success(value) for value in validation_values),
        "fingerprint": hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:12],
    }
    if include_paths:
        entry["touched_paths"] = list(dict.fromkeys(sanitize_path(value) for value in paths))
    if include_content:
        entry["observable_messages"] = collect_observable_text(records)
    return entry, warnings


def candidate_key(session: dict[str, Any]) -> tuple[str, str] | None:
    summaries = session["workflow_summaries"]
    if summaries:
        label = summaries[0]
        return normalized_summary(label), label
    tools = session["tool_sequence"]
    if tools:
        label = "Tool sequence: " + " → ".join(tools)
        return "tools:" + "|".join(str(tool).lower() for tool in tools), label
    return None


def build_candidates(sessions: list[dict[str, Any]], minimum: int) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for session in sessions:
        keyed = candidate_key(session)
        if not keyed:
            continue
        key, label = keyed
        group = groups.setdefault(
            key,
            {"label": label, "session_ids": [], "tool_sequences": [], "validated_sessions": 0},
        )
        group["session_ids"].append(session["session_id"])
        if session["tool_sequence"]:
            group["tool_sequences"].append(session["tool_sequence"])
        if session["validation_passed"]:
            group["validated_sessions"] += 1

    candidates: list[dict[str, Any]] = []
    for group in groups.values():
        occurrences = len(group["session_ids"])
        if occurrences < minimum:
            continue
        sequences = collections.Counter(tuple(seq) for seq in group.pop("tool_sequences"))
        common_sequence = list(sequences.most_common(1)[0][0]) if sequences else []
        group.update(
            {
                "occurrences": occurrences,
                "common_tool_sequence": common_sequence,
                "score": occurrences * 3 + group["validated_sessions"] * 2,
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
    args = parse_args(argv or sys.argv[1:])
    if not args.session_dir.is_dir():
        print(f"error: session directory does not exist: {args.session_dir}", file=sys.stderr)
        return 2
    if args.min_occurrences < 1:
        print("error: --min-occurrences must be at least 1", file=sys.stderr)
        return 2

    sessions: list[dict[str, Any]] = []
    warnings: list[str] = []
    for path in discover_files(args.session_dir):
        try:
            session, file_warnings = session_summary(path, args.include_content, args.include_paths)
        except OSError as error:
            warnings.append(f"{path.name}: {error}")
            continue
        if args.since:
            updated = parse_date(session.get("updated_at"))
            if updated and updated < args.since:
                continue
        sessions.append(session)
        warnings.extend(file_warnings)

    report = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": {
            "session_dir_name": args.session_dir.name,
            "files_scanned": len(discover_files(args.session_dir)),
        },
        "privacy": {
            "metadata_only": not args.include_content,
            "full_paths_included": False,
            "observable_content_included": args.include_content,
            "thought_or_reasoning_included": False,
            "note": "Review the report before sharing or committing it.",
        },
        "sessions": sessions,
        "workflow_candidates": build_candidates(sessions, args.min_occurrences),
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
