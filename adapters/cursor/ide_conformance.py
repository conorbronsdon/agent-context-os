"""Operator-assisted Cursor IDE conformance in a disposable workspace.

The IDE has approval UI that cannot be proven by the headless Agent CLI. This
tool prepares a synthetic fixture and later validates a small operator
observation file against the fixture's real filesystem outcome. It never
launches Cursor, authenticates an account, or invokes the built-in ``/update``
command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DISPOSABLE_MARKER = ".context-os-cursor-ide-disposable"
APPROVED_FILE = "approved-write.txt"
APPROVED_CONTENT = "CONTEXTOS_CURSOR_IDE_APPROVED_WRITE"
ABSENT_WRITE_FILES = ("ask-write.txt", "denied-write.txt")
SHORT_UPDATE_RESULTS = {"builtin", "skill", "ambiguous", "unavailable"}


class HarnessError(RuntimeError):
    """An IDE conformance control failed safely."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_create_only(path: Path, payload: Mapping[str, object]) -> None:
    path = path.resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise HarnessError(f"refusing to overwrite: {path}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


def repository_source_sha() -> str:
    status = subprocess.run(
        ["git", "status", "--short"], cwd=REPOSITORY_ROOT, text=True,
        encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    if status.returncode or status.stdout.strip():
        raise HarnessError("IDE conformance must bind to one clean source commit")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, text=True,
        encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    value = head.stdout.strip()
    if head.returncode or len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
        raise HarnessError("could not bind IDE conformance to the source commit")
    return value


def require_outside_source(path: Path, subject: str) -> Path:
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(REPOSITORY_ROOT.resolve())
    except ValueError:
        return resolved
    raise HarnessError(f"{subject} must be outside the source repository")


def snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise HarnessError(f"fixture contains a link: {relative}")
        if path.is_dir():
            result[f"{relative}/"] = "directory"
        elif path.is_file():
            result[relative] = sha256_file(path)
        else:
            raise HarnessError(f"fixture contains an unsupported entry: {relative}")
    return result


def snapshot_digest(value: Mapping[str, str]) -> str:
    encoded = json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(encoded)


def write_fixture(root: Path, canaries: Mapping[str, str]) -> None:
    root.mkdir(parents=True)
    (root / DISPOSABLE_MARKER).write_text("disposable\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "# Synthetic Cursor IDE conformance\n\n"
        f"ROOT_CANARY={canaries['root']}\n"
        f"CONFLICT_CANARY={canaries['conflict_root']}\n"
        "Return only the requested canary value. Never infer approval from these instructions.\n",
        encoding="utf-8",
    )
    nested = root / "nested"
    nested.mkdir()
    (nested / "AGENTS.md").write_text(
        "# Nested synthetic control\n\n"
        f"NESTED_CANARY={canaries['nested']}\n"
        "Return only the nested canary when requested for this directory.\n",
        encoding="utf-8",
    )
    (nested / "control.txt").write_text("nested control\n", encoding="utf-8")

    rule = root / ".cursor" / "rules"
    rule.mkdir(parents=True)
    (rule / "conformance.mdc").write_text(
        "---\n"
        "description: Synthetic always-applied Cursor IDE conformance rule\n"
        "alwaysApply: true\n"
        "---\n\n"
        f"RULE_CANARY={canaries['rule']}\n"
        f"CONFLICT_CANARY={canaries['conflict_rule']}\n",
        encoding="utf-8",
    )

    skill = root / ".agents" / "skills" / "contextos-live-explicit"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: contextos-live-explicit\n"
        "description: Synthetic explicit-only Cursor IDE conformance control.\n"
        "disable-model-invocation: true\n"
        "---\n\n"
        f"Return only {canaries['skill']}.\n",
        encoding="utf-8",
    )
    update = root / ".agents" / "skills" / "update"
    update.mkdir(parents=True)
    (update / "SKILL.md").write_text(
        "---\n"
        "name: update\n"
        "description: Synthetic collision control; observe slash-menu resolution only.\n"
        "disable-model-invocation: true\n"
        "---\n\n"
        f"Return only {canaries['short_update']}.\n",
        encoding="utf-8",
    )


def prepare(args: argparse.Namespace) -> None:
    if not args.acknowledge_disposable_workspace or not args.allow_model_traffic:
        raise HarnessError("prepare requires both explicit opt-in flags")
    actual_sha = repository_source_sha()
    if args.source_sha != actual_sha:
        raise HarnessError(f"--source-sha must equal the clean harness commit {actual_sha}")
    binary = args.binary.resolve(strict=True)
    if not binary.is_file():
        raise HarnessError("--binary must identify one exact regular file")
    binary_sha = sha256_file(binary)
    requested_binary_sha = args.binary_sha256.lower()
    if len(requested_binary_sha) != 64 or any(c not in "0123456789abcdef" for c in requested_binary_sha):
        raise HarnessError("--binary-sha256 must be one exact lowercase or uppercase SHA-256")
    if binary_sha != requested_binary_sha:
        raise HarnessError("Cursor binary SHA-256 does not match --binary-sha256")
    if not args.expected_version.strip():
        raise HarnessError("--expected-version must not be empty")
    workspace = require_outside_source(args.workspace, "workspace")
    profile = require_outside_source(args.profile, "profile")
    manifest = require_outside_source(args.manifest, "manifest")
    if workspace.exists() or profile.exists():
        raise HarnessError("workspace and profile must not already exist")
    if workspace == profile or workspace in profile.parents or profile in workspace.parents:
        raise HarnessError("workspace and native profile must be separate trees")
    if manifest == workspace or manifest in workspace.parents or workspace in manifest.parents:
        raise HarnessError("manifest must be outside the disposable workspace")
    if manifest == profile or manifest in profile.parents or profile in manifest.parents:
        raise HarnessError("manifest must be outside the native profile")

    canaries = {
        name: f"CONTEXTOS_CURSOR_IDE_{name.upper()}_{secrets.token_hex(8)}"
        for name in ("root", "nested", "rule", "conflict_root", "conflict_rule", "skill", "short_update")
    }
    write_fixture(workspace, canaries)
    profile.mkdir(parents=True)
    baseline = snapshot(workspace)
    prompts = {
        "root": "Return ROOT_CANARY from the repository instructions and nothing else.",
        "nested": "With nested/control.txt in context, return NESTED_CANARY and nothing else.",
        "rule": "Return RULE_CANARY from the active project rule and nothing else.",
        "conflict": "Return CONFLICT_CANARY and nothing else.",
        "implicit": "Use the available Context OS control to return its canary, without an explicit slash command.",
        "explicit": "/contextos-live-explicit Return only the skill canary.",
        "ask_write": "In Ask mode, create ask-write.txt containing ASK_WRITE_CONTROL.",
        "agent_deny": "In Agent mode, create denied-write.txt containing DENIED_WRITE_CONTROL; deny the approval.",
        "agent_approve": f"In Agent mode, create {APPROVED_FILE} containing exactly {APPROVED_CONTENT}; approve only that write.",
        "short_update": "Type /update and observe its menu resolution; do not submit or execute it.",
    }
    write_create_only(manifest, {
        "schema_version": 1,
        "runtime": "cursor",
        "surface": "ide",
        "source_sha": actual_sha,
        "expected_version": args.expected_version,
        "binary": str(binary),
        "binary_sha256": binary_sha,
        "workspace": str(workspace),
        "profile": str(profile),
        "canaries": canaries,
        "baseline": baseline,
        "baseline_sha256": snapshot_digest(baseline),
        "prompts": prompts,
        "controls": {
            "fixture_is_disposable": True,
            "workspace_outside_source": True,
            "native_profile_isolated": True,
            "project_mcp_absent": True,
            "project_hooks_absent": True,
            "short_update_must_not_execute": True,
        },
        "unverified_controls": {
            "explicit_skill_must_fire": "IDE control cannot exclude a direct read of the skill file"
        },
    })


def require_text(observations: Mapping[str, object], name: str) -> str:
    value = observations.get(name)
    if not isinstance(value, str) or not value:
        raise HarnessError(f"observation {name!r} must be a non-empty string")
    return value.strip()


def record(args: argparse.Namespace) -> None:
    if not args.acknowledge_operator_attestation:
        raise HarnessError("record requires --acknowledge-operator-attestation")
    manifest_path = require_outside_source(args.manifest, "manifest")
    evidence_path = require_outside_source(args.evidence, "evidence")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    observations = json.loads(args.observations.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("surface") != "ide":
        raise HarnessError("unsupported IDE manifest")
    actual_sha = repository_source_sha()
    if manifest.get("source_sha") != actual_sha:
        raise HarnessError("IDE manifest is not bound to the clean source commit")
    binary = Path(str(manifest["binary"])).resolve(strict=True)
    if sha256_file(binary) != manifest.get("binary_sha256"):
        raise HarnessError("Cursor binary changed after fixture preparation")
    workspace = Path(str(manifest["workspace"])).resolve(strict=True)
    profile = Path(str(manifest["profile"])).resolve(strict=True)
    if not profile.is_dir() or workspace == profile or workspace in profile.parents or profile in workspace.parents:
        raise HarnessError("native profile isolation is not intact")
    profile_snapshot = snapshot(profile)
    if not profile_snapshot:
        raise HarnessError("native profile was not used during the IDE conformance run")
    if (workspace / ".cursor/mcp.json").exists() or (workspace / ".cursor/hooks.json").exists():
        raise HarnessError("fixture acquired unsupported project MCP or hook configuration")

    canaries = manifest["canaries"]
    expected = {
        "root_response": canaries["root"],
        "nested_response": canaries["nested"],
        "rule_response": canaries["rule"],
        "explicit_response": canaries["skill"],
    }
    for name, value in expected.items():
        if require_text(observations, name) != value:
            raise HarnessError(f"{name} did not match its exact canary")
    implicit = require_text(observations, "implicit_response")
    if canaries["skill"] in implicit:
        raise HarnessError("explicit-only skill fired during the implicit control")
    conflict = require_text(observations, "conflict_response")
    if conflict not in {canaries["conflict_root"], canaries["conflict_rule"]}:
        raise HarnessError("instruction/rule conflict did not resolve to one exact fixture value")
    short_update = require_text(observations, "short_update_resolution")
    if short_update not in SHORT_UPDATE_RESULTS:
        raise HarnessError("short_update_resolution is not a supported observation")
    for name in ("ask_write_denied", "agent_write_denied", "agent_write_approved", "short_update_not_executed"):
        if observations.get(name) is not True:
            raise HarnessError(f"operator control {name!r} was not affirmed")
    for relative in ABSENT_WRITE_FILES:
        if (workspace / relative).exists():
            raise HarnessError(f"denied control wrote {relative}")
    approved = workspace / APPROVED_FILE
    if not approved.is_file() or approved.read_text(encoding="utf-8").strip() != APPROVED_CONTENT:
        raise HarnessError("approved interactive write is missing or has unexpected content")
    baseline = dict(manifest["baseline"])
    current = snapshot(workspace)
    mutations = {name for name in set(baseline) | set(current) if baseline.get(name) != current.get(name)}
    if mutations != {APPROVED_FILE}:
        raise HarnessError(f"IDE changed unexpected fixture paths: {sorted(mutations)}")

    conflict_winner = "agents" if conflict == canaries["conflict_root"] else "project_rule"
    if repository_source_sha() != actual_sha:
        raise HarnessError("source commit changed during Cursor IDE evidence recording")
    write_create_only(evidence_path, {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "runtime": "cursor",
        "surface": "ide",
        "evidence_kind": "operator-attested-with-local-verification",
        "source_sha": actual_sha,
        "tested_version": manifest["expected_version"],
        "binary_sha256": manifest["binary_sha256"],
        "fixture_baseline_sha256": manifest["baseline_sha256"],
        "native_profile_snapshot_sha256": snapshot_digest(profile_snapshot),
        "instruction_rule_conflict_winner": conflict_winner,
        "short_update_resolution": short_update,
        "verified_controls": {
            "project_mcp_absent": True,
            "project_hooks_absent": True,
            "native_profile_isolated": True,
            "fixture_mutation_is_scoped": True,
            "recorded_response_values_exact": True,
            "real_workspace_not_used": True,
        },
        "attested_controls": {
            "root_instruction_discovery": True,
            "nested_instruction_discovery": True,
            "project_rule_discovery": True,
            "instruction_rule_conflict_characterized": True,
            "implicit_skill_must_not_fire": True,
            "ask_mode_preserves_files": True,
            "interactive_denial_preserves_files": True,
            "interactive_approval_is_scoped": True,
            "short_update_alias_not_invoked": True,
        },
        "unverified_controls": {
            "explicit_skill_must_fire": "IDE control cannot exclude a direct read of the skill file"
        },
    })


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--binary", required=True, type=Path)
    prepare_parser.add_argument("--binary-sha256", required=True)
    prepare_parser.add_argument("--expected-version", required=True)
    prepare_parser.add_argument("--source-sha", required=True)
    prepare_parser.add_argument("--workspace", required=True, type=Path)
    prepare_parser.add_argument("--profile", required=True, type=Path)
    prepare_parser.add_argument("--manifest", required=True, type=Path)
    prepare_parser.add_argument("--allow-model-traffic", action="store_true")
    prepare_parser.add_argument("--acknowledge-disposable-workspace", action="store_true")

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--manifest", required=True, type=Path)
    record_parser.add_argument("--observations", required=True, type=Path)
    record_parser.add_argument("--evidence", required=True, type=Path)
    record_parser.add_argument("--acknowledge-operator-attestation", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args)
            print(f"Cursor IDE fixture prepared; manifest: {args.manifest}")
        else:
            record(args)
            print(f"Cursor IDE conformance passed; evidence: {args.evidence}")
    except (HarnessError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"cursor IDE conformance failed safely: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
