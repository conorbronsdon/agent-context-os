#!/usr/bin/env python3
"""Validate the small, intentionally strict schema used by agents/openai.yaml."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path


KEY = re.compile(r"^[a-z][a-z0-9_]*$")
EXPECTED = {
    "interface": {"display_name", "short_description", "default_prompt"},
    "policy": {"allow_implicit_invocation"},
}
COMMAND_KEY = re.compile(r"^[a-z][a-z0-9-]*$")
START_TOOLS = "Read, Glob"
REQUIRED_COMMAND_FIELDS = {
    "name",
    "description",
    "allowed-tools",
    "disable-model-invocation",
}
OPTIONAL_COMMAND_FIELDS = {"x-source", "x-source-version"}


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
        if any(unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for character in value):
            raise MetadataError(f"interface.{field} contains a control or format character")
    if not 25 <= len(interface["short_description"]) <= 64:
        raise MetadataError("interface.short_description must be 25-64 characters")
    if not interface["default_prompt"].startswith(f"Use ${skill_name} "):
        raise MetadataError(f"default_prompt must directly invoke the exact ${skill_name} token")
    if data["policy"]["allow_implicit_invocation"] is not False:
        raise MetadataError("policy.allow_implicit_invocation must be boolean false")


def command_frontmatter(path: Path) -> dict[str, object]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise MetadataError(f"cannot read UTF-8 command: {exc}") from exc
    if not lines or lines[0] != "---":
        raise MetadataError("command must begin with frontmatter")
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise MetadataError("command frontmatter is not closed") from exc

    result: dict[str, object] = {}
    for line_number, line in enumerate(lines[1:closing], 2):
        key, separator, raw_value = line.partition(": ")
        if not separator or not COMMAND_KEY.fullmatch(key) or not raw_value or line != line.rstrip():
            raise MetadataError(f"line {line_number}: malformed command frontmatter")
        if key in result:
            raise MetadataError(f"line {line_number}: duplicate command field {key}")
        if key == "name":
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", raw_value):
                raise MetadataError(f"line {line_number}: command name must be a plain name string")
            result[key] = raw_value
        else:
            result[key] = scalar(raw_value, line_number)
    return result


def validate_command(path: Path, command_name: str) -> None:
    data = command_frontmatter(path)
    fields = set(data)
    if not REQUIRED_COMMAND_FIELDS <= fields or not fields <= REQUIRED_COMMAND_FIELDS | OPTIONAL_COMMAND_FIELDS:
        raise MetadataError(
            "command fields must contain exactly the required fields and optional reviewed source metadata"
        )
    if data["name"] != command_name:
        raise MetadataError(f"command name must be {command_name}")
    if not isinstance(data["description"], str) or not data["description"].strip():
        raise MetadataError("description must be a non-empty quoted string")
    if not isinstance(data["allowed-tools"], str) or not data["allowed-tools"].strip():
        raise MetadataError("allowed-tools must be a non-empty quoted string")
    for field in ("description", "allowed-tools", *sorted(OPTIONAL_COMMAND_FIELDS & fields)):
        if not isinstance(data[field], str) or not data[field].strip():
            raise MetadataError(f"{field} must be a non-empty quoted string")
        if any(unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for character in data[field]):
            raise MetadataError(f"{field} contains a control or format character")
    if data["disable-model-invocation"] is not True:
        raise MetadataError("disable-model-invocation must be boolean true in frontmatter")
    if command_name == "start" and data["allowed-tools"] != START_TOOLS:
        raise MetadataError("start must pre-approve only repository read tools")


def main() -> int:
    command_mode = len(sys.argv) == 4 and sys.argv[1] == "--command"
    if len(sys.argv) != 3 and not command_mode:
        print("usage: validate-openai-metadata.py [--command] PATH NAME", file=sys.stderr)
        return 2
    try:
        if command_mode:
            validate_command(Path(sys.argv[2]), sys.argv[3])
        else:
            validate(Path(sys.argv[1]), sys.argv[2])
    except MetadataError as exc:
        path = sys.argv[2] if command_mode else sys.argv[1]
        print(f"{path}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
