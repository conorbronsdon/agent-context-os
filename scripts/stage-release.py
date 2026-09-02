#!/usr/bin/env python3
"""Create or recover one exact GitHub draft release without retrying uploads."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence


HTTP_STATUS_RE = re.compile(r"(?m)^HTTP/\S+\s+(\d{3})(?:\s|$)")


class StageReleaseError(RuntimeError):
    """Raised when draft lookup or creation cannot be proven safe."""


class CommandRunner:
    def run(
        self, arguments: Sequence[str], *, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                list(arguments), check=check, capture_output=True,
                text=True, encoding="utf-8",
            )
        except OSError as exc:
            raise StageReleaseError(
                "command could not start: " + " ".join(arguments)
            ) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip()
            raise StageReleaseError(
                "command failed: " + " ".join(arguments)
                + (f": {detail}" if detail else "")
            ) from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StageReleaseError(message)


def _normalized_body(value: str) -> str:
    return value.replace("\r\n", "\n").rstrip("\n")


def _included_json(completed: subprocess.CompletedProcess[str]) -> tuple[int, Any]:
    output = completed.stdout.replace("\r\n", "\n")
    statuses = HTTP_STATUS_RE.findall(output)
    _require(bool(statuses), "release lookup did not expose an HTTP status")
    status = int(statuses[-1])
    if completed.returncode != 0:
        if status == 404:
            return status, None
        detail = completed.stderr.strip()
        raise StageReleaseError(
            f"release lookup failed with HTTP {status}"
            + (f": {detail}" if detail else "")
        )
    _require(200 <= status < 300, f"release lookup returned HTTP {status}")
    separator = output.rfind("\n\n")
    _require(separator >= 0, "release lookup response did not contain a body")
    try:
        return status, json.loads(output[separator + 2:])
    except json.JSONDecodeError as exc:
        raise StageReleaseError("release lookup did not return valid JSON") from exc


def _lookup_by_tag(
    runner: CommandRunner, repository: str, tag: str,
) -> dict[str, Any] | None:
    completed = runner.run([
        "gh", "api", "--include", "-H", "X-GitHub-Api-Version: 2026-03-10",
        f"repos/{repository}/releases/tags/{tag}",
    ], check=False)
    status, value = _included_json(completed)
    if status == 404:
        return None
    _require(isinstance(value, dict), "release lookup response must be an object")
    return value


def _exact_draft(
    value: Any, *, tag: str, title: str, body: str,
) -> int:
    _require(isinstance(value, dict), "draft release response must be an object")
    release_id = value.get("id")
    _require(type(release_id) is int and release_id > 0,
             "draft release numeric ID is invalid")
    _require(value.get("tag_name") == tag, "draft release tag does not match")
    _require(value.get("name") == title, "draft release title does not match")
    _require(_normalized_body(value.get("body") or "") == _normalized_body(body),
             "draft release body does not match")
    _require(value.get("draft") is True, "release is not an unpublished draft")
    _require(value.get("prerelease") is False, "release must not be a prerelease")
    return release_id


def stage_release(
    *, repository: str, tag: str, title: str, notes_file: Path,
    artifacts: Sequence[Path], visibility_attempts: int = 5,
    visibility_seconds: float = 2.0, runner: CommandRunner | None = None,
) -> dict[str, Any]:
    runner = runner or CommandRunner()
    _require(bool(repository), "repository is required")
    _require(bool(tag), "tag is required")
    _require(bool(title), "title is required")
    _require(visibility_attempts > 0 and visibility_seconds >= 0,
             "visibility wait settings are invalid")
    _require(notes_file.is_file(), "release notes file is absent")
    artifact_paths = [path.absolute().resolve() for path in artifacts]
    _require(len(artifact_paths) == 5, "exactly five release artifacts are required")
    _require(len({path.name for path in artifact_paths}) == 5,
             "release artifact names must be unique")
    _require(all(path.is_file() for path in artifact_paths),
             "one or more release artifacts are absent")
    body = notes_file.read_text(encoding="utf-8")

    existing = _lookup_by_tag(runner, repository, tag)
    if existing is not None:
        return {
            "schema_version": 1,
            "release_id": _exact_draft(existing, tag=tag, title=title, body=body),
            "created_by_this_run": False,
        }

    create = runner.run([
        "gh", "release", "create", tag,
        *(str(path) for path in artifact_paths),
        "--repo", repository, "--draft", "--verify-tag",
        "--title", title, "--notes-file", str(notes_file),
    ], check=False)

    for attempt in range(visibility_attempts):
        current = _lookup_by_tag(runner, repository, tag)
        if current is not None:
            return {
                "schema_version": 1,
                "release_id": _exact_draft(current, tag=tag, title=title, body=body),
                "created_by_this_run": create.returncode == 0,
            }
        if attempt + 1 < visibility_attempts:
            time.sleep(visibility_seconds)

    detail = create.stderr.strip()
    if create.returncode != 0:
        raise StageReleaseError(
            "release creation failed and no exact draft appeared"
            + (f": {detail}" if detail else "")
        )
    raise StageReleaseError("created draft release did not become readable")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--notes-file", required=True, type=Path)
    parser.add_argument("--artifact", action="append", required=True, type=Path)
    parser.add_argument("--visibility-attempts", type=int, default=5)
    parser.add_argument("--visibility-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    try:
        result = stage_release(
            repository=args.repository, tag=args.tag, title=args.title,
            notes_file=args.notes_file, artifacts=args.artifact,
            visibility_attempts=args.visibility_attempts,
            visibility_seconds=args.visibility_seconds,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (StageReleaseError, OSError, UnicodeError, ValueError) as exc:
        print(f"stage release: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
