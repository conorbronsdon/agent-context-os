#!/usr/bin/env python3
"""Opt-in exact-client conformance for the OpenCode adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


LIFECYCLE = ("setup", "start", "update", "end")


def run(
    binary: Path, cwd: Path, *args: str, timeout: int = 120,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["OPENCODE_PURE"] = "1"
    environment.update(extra_env or {})
    return subprocess.run(
        [str(binary), *args], cwd=cwd, env=environment, text=True,
        encoding="utf-8", errors="replace", capture_output=True,
        check=False, timeout=timeout,
    )


def parse_json_document(result: subprocess.CompletedProcess[str], label: str) -> object:
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed: {result.stderr.strip()}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} did not return JSON") from exc


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def copy_tracked_fixture(repo: Path, fixture: Path) -> None:
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=repo, capture_output=True, check=False
    )
    if listed.returncode != 0:
        raise RuntimeError("--repo must be a Git checkout with a readable tracked-file index")
    fixture.mkdir(parents=True)
    for raw_name in listed.stdout.split(b"\0"):
        if not raw_name:
            continue
        name = os.fsdecode(raw_name)
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe tracked path: {name!r}")
        source = repo / relative
        if source.is_symlink() or not source.is_file():
            raise RuntimeError(f"tracked fixture source must be a regular file: {name!r}")
        target = fixture / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def tool_loaded_exact_skill(output: str, root: Path, skill_name: str) -> bool:
    wanted_path = (root / ".agents" / "skills" / skill_name / "SKILL.md").resolve()
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "tool_use":
            continue
        part = event.get("part", {})
        state = part.get("state", {})
        tool = part.get("tool")
        inputs = state.get("input", {})
        if tool == "skill" and inputs.get("name") == skill_name:
            return True
        if tool == "read" and inputs.get("filePath"):
            try:
                if Path(inputs["filePath"]).resolve() == wanted_path:
                    return True
            except OSError:
                pass
    return False


def tool_names(output: str) -> list[str]:
    names: list[str] = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "tool_use" and isinstance(event.get("part"), dict):
            names.append(str(event["part"].get("tool", "")))
    return names


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--model")
    parser.add_argument("--acknowledge-external-model-egress", action="store_true")
    parser.add_argument("--acknowledge-disposable-repo", action="store_true")
    parser.add_argument("--acknowledge-public-or-synthetic-material", action="store_true")
    args = parser.parse_args()

    binary = Path(args.binary).resolve(strict=True)
    repo = Path(args.repo).resolve(strict=True)
    if not binary.is_file():
        parser.error("--binary must resolve to an exact file")
    if args.model and not all((
        args.acknowledge_external_model_egress,
        args.acknowledge_disposable_repo,
        args.acknowledge_public_or_synthetic_material,
    )):
        parser.error(
            "model-backed checks require --acknowledge-external-model-egress "
            "--acknowledge-disposable-repo, and "
            "--acknowledge-public-or-synthetic-material"
        )

    version = run(binary, repo, "--version")
    if version.returncode != 0 or version.stdout.strip() != args.expected_version:
        raise RuntimeError(
            f"expected OpenCode {args.expected_version!r}, got {version.stdout.strip()!r}"
        )
    help_result = run(binary, repo, "--help")
    if help_result.returncode != 0 or "--auto" not in help_result.stdout + help_result.stderr:
        raise RuntimeError("installed client does not expose the documented --auto boundary")

    with tempfile.TemporaryDirectory(prefix="contextos-opencode-") as temporary:
        fixture = Path(temporary) / "public-fixture"
        copy_tracked_fixture(repo, fixture)
        skills = parse_json_document(run(binary, fixture, "debug", "skill"), "debug skill")
        by_name = {item["name"]: item for item in skills if isinstance(item, dict)}
        for name in (f"context-{item}" for item in LIFECYCLE):
            discovered = Path(by_name[name]["location"]).resolve()
            expected = (fixture / ".agents" / "skills" / name / "SKILL.md").resolve()
            if discovered != expected:
                raise RuntimeError(f"{name} resolved to {discovered}, expected {expected}")

        config = parse_json_document(run(binary, fixture, "debug", "config"), "debug config")
        commands = config.get("command", {}) if isinstance(config, dict) else {}
        for item in LIFECYCLE:
            name = f"context-{item}"
            template = commands.get(name, {}).get("template", "")
            if f"`{name}`" not in template or "Use the `skill` tool" not in template:
                raise RuntimeError(f"resolved command {name} does not route to its exact skill")

        denied_config = parse_json_document(
            run(
                binary, fixture, "debug", "config",
                extra_env={
                    "OPENCODE_CONFIG_CONTENT": json.dumps(
                        {
                            "permission": {
                                "bash": "deny", "edit": "deny", "skill": {"*": "deny"}
                            }
                        }
                    )
                },
            ),
            "permission debug config",
        )
        denied_permissions = denied_config.get("permission", {})
        if (
            denied_permissions.get("bash") != "deny"
            or denied_permissions.get("edit") != "deny"
            or denied_permissions.get("skill") != {"*": "deny"}
        ):
            raise RuntimeError("installed client did not resolve the permission-denial control")

        if args.model:
            before = tree_digest(fixture)
            for item in LIFECYCLE:
                name = f"context-{item}"
                result = run(
                    binary, fixture, "run", "--pure", "--format", "json", "-m", args.model,
                    f"/{name} Conformance control: load the exact skill, then stop before "
                    "running shell commands or editing files.", timeout=300,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"live {name} failed: {result.stderr.strip()}")
                if not tool_loaded_exact_skill(result.stdout, fixture, name):
                    raise RuntimeError(f"live {name} produced no exact-skill tool event")
            denial = run(
                binary, fixture, "run", "--pure", "--format", "json", "-m", args.model,
                "Conformance control: use the bash tool to run echo "
                "CONTEXTOS_DENIAL_SENTINEL. Do not use another tool.",
                timeout=300,
                extra_env={
                    "OPENCODE_CONFIG_CONTENT": json.dumps(
                        {"permission": {"bash": "deny", "edit": "deny"}}
                    )
                },
            )
            if denial.returncode != 0:
                raise RuntimeError(f"permission denial control failed: {denial.stderr.strip()}")
            exposed = {"bash", "edit"} & set(tool_names(denial.stdout))
            if exposed:
                raise RuntimeError(f"denied tools were exposed to model intent: {sorted(exposed)}")
            after = tree_digest(fixture)
            if after != before:
                raise RuntimeError("read-only live command routing changed the disposable fixture")

    print(
        f"OpenCode conformance passed for exact version {args.expected_version}"
        + (f" with model {args.model}" if args.model else " (native discovery only)")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
