#!/usr/bin/env python3
"""Opt-in exact-client conformance for the OpenCode adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath


LIFECYCLE = ("setup", "start", "update", "end")
CONFIG_OVERRIDE_ENV = (
    "OPENCODE_CONFIG",
    "OPENCODE_CONFIG_DIR",
    "OPENCODE_CONFIG_CONTENT",
    "OPENCODE_DISABLE_PROJECT_CONFIG",
    "OPENCODE_DISABLE_EXTERNAL_SKILLS",
    "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS",
    "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT",
)
ISOLATED_HOST_PATH_ENV = {
    "HOME": "home",
    "USERPROFILE": "home",
    "XDG_CONFIG_HOME": "config",
    "XDG_DATA_HOME": "data",
    "XDG_CACHE_HOME": "cache",
    "APPDATA": "appdata",
    "LOCALAPPDATA": "localappdata",
}
OPENCODE_GENERATED_PATHS = {".opencode/.gitignore"}
OPENCODE_GENERATED_PREFIXES = (".opencode/node_modules",)


def run(
    binary: Path, cwd: Path, *args: str, timeout: int = 120,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in CONFIG_OVERRIDE_ENV:
        environment.pop(name, None)
    environment.update(extra_env or {})
    environment["OPENCODE_PURE"] = "1"
    with tempfile.TemporaryDirectory(prefix="contextos-opencode-env-") as temporary:
        isolation_root = Path(temporary)
        for name, relative in ISOLATED_HOST_PATH_ENV.items():
            target = isolation_root / relative
            target.mkdir(exist_ok=True)
            environment[name] = str(target)
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
    paths = [root]
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if relative in OPENCODE_GENERATED_PATHS or any(
            relative == prefix or relative.startswith(prefix + "/")
            for prefix in OPENCODE_GENERATED_PREFIXES
        ):
            continue
        paths.append(path)
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISREG(metadata.st_mode):
            kind = "file"
        elif stat.S_ISDIR(metadata.st_mode):
            kind = "directory"
        elif stat.S_ISLNK(metadata.st_mode):
            kind = "symlink"
        else:
            kind = "other"
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(f"{kind}\0{mode:o}\0{metadata.st_nlink}\0".encode("ascii"))
        if kind == "file":
            digest.update(path.read_bytes())
        elif kind == "symlink":
            digest.update(os.fsencode(os.readlink(path)))
    return digest.hexdigest()


def verify_exact_clean_checkout(repo: Path, expected_commit: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_commit):
        raise RuntimeError("--expected-commit must be a full 40-character commit SHA")
    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"], cwd=repo,
        text=True, encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    if resolved.returncode != 0:
        raise RuntimeError("--repo must be a Git checkout with a readable HEAD commit")
    actual = resolved.stdout.strip().lower()
    if actual != expected_commit.lower():
        raise RuntimeError(f"expected commit {expected_commit.lower()}, got {actual}")
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=repo, capture_output=True, check=False,
    )
    if status.returncode != 0:
        raise RuntimeError("could not verify that --repo is clean")
    if status.stdout:
        raise RuntimeError("--repo must be clean so fixture bytes match --expected-commit")
    return actual


def copy_tracked_fixture(repo: Path, fixture: Path, commit: str) -> None:
    listed = subprocess.run(
        ["git", "ls-tree", "-rz", "--full-tree", commit],
        cwd=repo, capture_output=True, check=False,
    )
    if listed.returncode != 0:
        raise RuntimeError("could not enumerate the verified commit tree")
    fixture.mkdir(parents=True)
    for record in listed.stdout.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_name = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("git returned a malformed tree entry") from exc
        name = os.fsdecode(raw_name)
        relative = PurePosixPath(name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or re.match(r"^[A-Za-z]:", relative.parts[0])
        ):
            raise RuntimeError(f"unsafe tracked path: {name!r}")
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise RuntimeError(f"tracked fixture source must be a regular file: {name!r}")
        blob = subprocess.run(
            ["git", "cat-file", "blob", object_id], cwd=repo,
            capture_output=True, check=False,
        )
        if blob.returncode != 0:
            raise RuntimeError(f"could not read verified blob for {name!r}")
        target = fixture.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob.stdout)
        if os.name != "nt":
            target.chmod(0o755 if mode == "100755" else 0o644)


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
                candidate = Path(inputs["filePath"])
                if not candidate.is_absolute():
                    candidate = root / candidate
                if candidate.resolve() == wanted_path:
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


def bash_commands(output: str) -> list[str]:
    commands: list[str] = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = event.get("part", {})
        state = part.get("state", {}) if isinstance(part, dict) else {}
        inputs = state.get("input", {}) if isinstance(state, dict) else {}
        if (
            event.get("type") == "tool_use"
            and part.get("tool") == "bash"
            and isinstance(inputs, dict)
            and isinstance(inputs.get("command"), str)
        ):
            commands.append(inputs["command"])
    return commands


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-commit", required=True)
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
    verified_commit = verify_exact_clean_checkout(repo, args.expected_commit)
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
        copy_tracked_fixture(repo, fixture, verified_commit)
        skills = parse_json_document(run(binary, fixture, "debug", "skill"), "debug skill")
        by_name: dict[str, dict[str, object]] = {}
        for skill in skills:
            if not isinstance(skill, dict) or not isinstance(skill.get("name"), str):
                continue
            name = skill["name"]
            if name in by_name:
                raise RuntimeError(f"duplicate discovered skill name: {name}")
            by_name[name] = skill
        for name in (f"context-{item}" for item in LIFECYCLE):
            skill = by_name.get(name)
            if skill is None:
                raise RuntimeError(f"required skill not discovered: {name}")
            location = skill.get("location")
            if not isinstance(location, str):
                raise RuntimeError(f"discovered skill has no location: {name}")
            discovered = Path(location).resolve()
            expected = (fixture / ".agents" / "skills" / name / "SKILL.md").resolve()
            if discovered != expected:
                raise RuntimeError(f"{name} resolved to {discovered}, expected {expected}")

        config = parse_json_document(run(binary, fixture, "debug", "config"), "debug config")
        commands = config.get("command", {}) if isinstance(config, dict) else {}
        for item in LIFECYCLE:
            name = f"context-{item}"
            command = commands.get(name, {})
            if not isinstance(command, dict):
                raise RuntimeError(f"resolved command {name} has an invalid shape")
            template = command.get("template", "")
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
            # OpenCode may initialize project-local host dependencies on the first
            # model run. Establish that known client baseline with an exact,
            # non-mutating positive control before attesting lifecycle read-only.
            positive = run(
                binary, fixture, "run", "--pure", "--format", "json", "-m", args.model,
                "Conformance control: use the bash tool to run echo "
                "CONTEXTOS_POSITIVE_SENTINEL. Do not use another tool.",
                timeout=300,
            )
            if positive.returncode != 0:
                raise RuntimeError(
                    f"permission positive control failed: {positive.stderr.strip()}"
                )
            if (
                tool_names(positive.stdout) != ["bash"]
                or bash_commands(positive.stdout) != ["echo CONTEXTOS_POSITIVE_SENTINEL"]
            ):
                raise RuntimeError(
                    "permission positive control did not execute only the exact bash sentinel"
                )
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
        f"OpenCode conformance passed for exact version {args.expected_version} "
        f"at commit {verified_commit}"
        + (f" with model {args.model}" if args.model else " (native discovery only)")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
