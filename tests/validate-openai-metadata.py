#!/usr/bin/env python3
"""Validate the small, intentionally strict schema used by agents/openai.yaml."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


KEY = re.compile(r"^[a-z][a-z0-9_]*$")
EXPECTED = {
    "interface": {"display_name", "short_description", "default_prompt"},
    "policy": {"allow_implicit_invocation"},
}


class MetadataError(ValueError):
    pass


def scalar(value: str, line_number: int) -> object:
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise MetadataError(f"line {line_number}: invalid quoted string") from exc
        if not isinstance(parsed, str):
            raise MetadataError(f"line {line_number}: expected a string")
        return parsed
    raise MetadataError(f"line {line_number}: unsupported or malformed scalar")


def parse(path: Path) -> dict[str, dict[str, object]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise MetadataError(f"cannot read UTF-8 metadata: {exc}") from exc

    result: dict[str, dict[str, object]] = {}
    section: str | None = None
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line or line != line.rstrip() or "\t" in line:
            raise MetadataError(f"line {line_number}: blank, tabbed, or trailing-space line")

        if line.startswith("  ") and not line.startswith("   "):
            if section is None:
                raise MetadataError(f"line {line_number}: field has no parent section")
            field, separator, raw_value = line[2:].partition(": ")
            if not separator or not KEY.fullmatch(field):
                raise MetadataError(f"line {line_number}: malformed field")
            if field in result[section]:
                raise MetadataError(f"line {line_number}: duplicate field {field}")
            result[section][field] = scalar(raw_value, line_number)
            continue

        if line.startswith(" "):
            raise MetadataError(f"line {line_number}: indentation must be exactly two spaces")
        name, separator, suffix = line.partition(":")
        if separator != ":" or suffix or not KEY.fullmatch(name):
            raise MetadataError(f"line {line_number}: malformed section")
        if name in result:
            raise MetadataError(f"line {line_number}: duplicate section {name}")
        result[name] = {}
        section = name

    return result


def validate(path: Path, skill_name: str) -> None:
    data = parse(path)
    if set(data) != set(EXPECTED):
        raise MetadataError(f"sections must be exactly {sorted(EXPECTED)}")
    for section, fields in EXPECTED.items():
        if set(data[section]) != fields:
            raise MetadataError(f"{section} fields must be exactly {sorted(fields)}")

    interface = data["interface"]
    for field in EXPECTED["interface"]:
        value = interface[field]
        if not isinstance(value, str) or not value.strip():
            raise MetadataError(f"interface.{field} must be a non-empty string")
    if not 25 <= len(interface["short_description"]) <= 64:
        raise MetadataError("interface.short_description must be 25-64 characters")
    if f"${skill_name}" not in interface["default_prompt"]:
        raise MetadataError(f"default_prompt must explicitly invoke ${skill_name}")
    if data["policy"]["allow_implicit_invocation"] is not False:
        raise MetadataError("policy.allow_implicit_invocation must be boolean false")


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: validate-openai-metadata.py PATH SKILL_NAME", file=sys.stderr)
        return 2
    try:
        validate(Path(sys.argv[1]), sys.argv[2])
    except MetadataError as exc:
        print(f"{sys.argv[1]}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
