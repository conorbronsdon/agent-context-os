"""Exact-version Cursor CLI conformance in a synthetic disposable workspace.

The harness never installs Cursor, alters PATH, invokes the dangerous built-in
``/update`` command, or runs against a real Context OS workspace. Model traffic
and temporary writes require an explicit command-line opt in.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_FLAGS = ("--print", "--force", "--workspace", "--trust", "--mode", "--output-format")
DISPOSABLE_MARKER = ".context-os-cursor-live-disposable"


class HarnessError(RuntimeError):
    """A live conformance control failed safely."""


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class Evidence:
    expected_version: str
    source_sha: str
    binary_version: str = ""
    user_cli_config_sha256: str | None = None
    commands: list[dict[str, object]] = field(default_factory=list)
    controls: dict[str, bool] = field(default_factory=dict)


Runner = Callable[[Sequence[str], Path, Mapping[str, str], float], CommandResult]


def executable_command(binary: Path, *arguments: str) -> list[str]:
    """Return a shell-free command, including the Windows batch-file bridge."""
    binary = binary.resolve(strict=True)
    requested = [str(binary), *arguments]
    if os.name == "nt" and binary.suffix.lower() in {".cmd", ".bat"}:
        command = subprocess.list2cmdline(requested)
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command]
    return requested


def default_runner(
    argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout: float
) -> CommandResult:
    completed = subprocess.run(
        list(argv), cwd=cwd, env=dict(env), text=True, encoding="utf-8",
        errors="replace", capture_output=True, check=False, timeout=timeout,
    )
    return CommandResult(list(argv), completed.returncode, completed.stdout, completed.stderr)


def output_summary(result: CommandResult) -> dict[str, object]:
    return {
        "command": Path(result.argv[0]).name if result.argv else "",
        "argv_sha256": hashlib.sha256(
            json.dumps(result.argv, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "returncode": result.returncode,
        "stdout_sha256": hashlib.sha256(result.stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr.encode("utf-8")).hexdigest(),
    }


def repository_source_sha(runner: Runner = default_runner) -> str:
    status = runner(["git", "status", "--short"], REPOSITORY_ROOT, os.environ, 30)
    if status.returncode or status.stdout.strip():
        raise HarnessError("live conformance must run from one clean source commit")
    head = runner(["git", "rev-parse", "HEAD"], REPOSITORY_ROOT, os.environ, 30)
    value = head.stdout.strip()
    if head.returncode or len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise HarnessError("could not bind live conformance to the source commit")
    return value


def require_outside_source(path: Path) -> Path:
    target = path.resolve(strict=False)
    try:
        target.relative_to(REPOSITORY_ROOT.resolve())
    except ValueError:
        return target
    raise HarnessError("evidence must be outside the source repository")


def require_success(result: CommandResult, subject: str) -> str:
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[:1000]
        raise HarnessError(f"{subject} failed: {detail or 'no diagnostic output'}")
    return f"{result.stdout}\n{result.stderr}"


def require_json_result(result: CommandResult, subject: str) -> str:
    """Return the sole final-response field from Cursor's documented JSON mode."""
    require_success(result, subject)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HarnessError(f"{subject} did not return one JSON result") from exc
    if not isinstance(payload, dict):
        raise HarnessError(f"{subject} returned a non-object JSON result")
    if payload.get("type") != "result" or payload.get("subtype") != "success":
        raise HarnessError(f"{subject} did not return a successful JSON result")
    if payload.get("is_error") is not False or not isinstance(payload.get("result"), str):
        raise HarnessError(f"{subject} omitted a successful text result")
    return payload["result"]


def require_canary(result: CommandResult, canary: str, subject: str) -> None:
    if require_json_result(result, subject) != canary:
        raise HarnessError(f"{subject} did not return only its instruction canary")


def require_denied_write_attempt(
    result: CommandResult, workspace: Path, filename: str, subject: str
) -> None:
    """Require a documented stream-json write attempt that project policy denied."""
    require_success(result, subject)
    events: list[Mapping[str, object]] = []
    try:
        for line in result.stdout.splitlines():
            if line.strip():
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("non-object event")
                events.append(event)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HarnessError(f"{subject} did not return valid stream-json") from exc
    terminal = [
        event for event in events
        if event.get("type") == "result" and event.get("subtype") == "success"
        and event.get("is_error") is False
    ]
    if len(terminal) != 1 or not isinstance(terminal[0].get("result"), str):
        raise HarnessError(f"{subject} did not complete with one successful stream result")
    attempts: dict[str, Mapping[str, object]] = {}
    for event in events:
        tool_call = event.get("tool_call")
        if not isinstance(tool_call, dict):
            continue
        write = tool_call.get("writeToolCall")
        args = write.get("args") if isinstance(write, dict) else None
        path = args.get("path") if isinstance(args, dict) else None
        call_id = event.get("call_id")
        if not isinstance(path, str) or not isinstance(call_id, str) or Path(path).name != filename:
            continue
        target = (workspace / path).resolve(strict=False) if not Path(path).is_absolute() else Path(path).resolve(strict=False)
        try:
            target.relative_to(workspace.resolve())
        except ValueError as exc:
            raise HarnessError(f"{subject} attempted a write outside the disposable workspace") from exc
        if event.get("subtype") == "started":
            attempts[call_id] = write
        elif event.get("subtype") == "completed" and call_id in attempts:
            outcome = write.get("result") if isinstance(write, dict) else None
            if isinstance(outcome, dict) and "error" in outcome:
                raise HarnessError(f"{subject} write failed for a reason other than policy denial")
            if isinstance(outcome, dict) and "success" not in outcome and any(
                key in outcome for key in ("denied", "rejected")
            ):
                return
    raise HarnessError(f"{subject} did not record a rejected denied write through Cursor")


def snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise HarnessError(f"synthetic workspace contains a link: {relative}")
        if path.is_dir():
            result[f"{relative}/"] = "directory"
        elif path.is_file():
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            raise HarnessError(f"synthetic workspace contains an unsupported entry: {relative}")
    return result


def changed_paths(before: Mapping[str, str], after: Mapping[str, str]) -> set[str]:
    return {name for name in set(before) | set(after) if before.get(name) != after.get(name)}


def write_fixture(root: Path, canaries: Mapping[str, str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / DISPOSABLE_MARKER).write_text("disposable\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "# Synthetic Cursor conformance\n\n"
        f"ROOT_INSTRUCTION_CANARY={canaries['root']}\n"
        "When asked for ROOT_INSTRUCTION_CANARY, return only its value.\n",
        encoding="utf-8",
    )
    nested = root / "nested"
    nested.mkdir()
    (nested / "AGENTS.md").write_text(
        "# Nested synthetic control\n\n"
        f"ROOT_INSTRUCTION_CANARY={canaries['nested']}\n"
        "For files in this directory, return only this nested value when asked.\n",
        encoding="utf-8",
    )
    (nested / "control.txt").write_text("nested fixture\n", encoding="utf-8")
    skill = root / ".agents" / "skills" / "contextos-live-explicit"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: contextos-live-explicit\n"
        "description: Synthetic explicit-invocation control used only by the disposable Cursor conformance harness.\n"
        "disable-model-invocation: true\n"
        "---\n\n"
        f"Return only {canaries['skill']}.\n",
        encoding="utf-8",
    )


def write_permissions(
    root: Path, *, allow: Sequence[str], deny: Sequence[str]
) -> None:
    cursor = root / ".cursor"
    cursor.mkdir(exist_ok=True)
    (cursor / "cli.json").write_text(
        json.dumps({
            "permissions": {
                "allow": list(allow),
                "deny": list(deny),
            }
        }, indent=2) + "\n",
        encoding="utf-8",
    )


class CursorHarness:
    def __init__(
        self, binary: Path, expected_version: str, source_sha: str,
        *, runner: Runner = default_runner, timeout: float = 300,
        user_cli_config: Path | None = None,
    ) -> None:
        self.binary = binary.resolve(strict=True)
        if not self.binary.is_file():
            raise HarnessError("--binary must identify one exact regular file")
        self.runner = runner
        self.timeout = timeout
        self.env = dict(os.environ)
        self.user_cli_config = user_cli_config or (Path.home() / ".cursor" / "cli-config.json")
        self.evidence = Evidence(expected_version=expected_version, source_sha=source_sha)

    def run(self, cwd: Path, *arguments: str) -> CommandResult:
        result = self.runner(
            executable_command(self.binary, *arguments), cwd, self.env, self.timeout
        )
        self.evidence.commands.append(output_summary(result))
        return result

    def agent(
        self, workspace: Path, prompt: str, *arguments: str, cwd: Path | None = None,
        output_format: str = "json",
    ) -> CommandResult:
        return self.run(
            cwd or workspace, "--print", "--output-format", output_format, "--trust",
            "--workspace", str(workspace), *arguments, prompt,
        )

    def preflight(self, workspace: Path) -> None:
        """Check the binary only from a disposable directory."""
        if self.user_cli_config.exists():
            config_bytes = self.user_cli_config.read_bytes()
            try:
                config = json.loads(config_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise HarnessError("Cursor user CLI configuration is not valid JSON") from exc
            permissions = config.get("permissions") if isinstance(config, dict) else None
            if permissions is not None and not isinstance(permissions, dict):
                raise HarnessError(
                    "Cursor user CLI permissions would confound project permission conformance"
                )
            denied = permissions.get("deny", []) if permissions else []
            if not isinstance(denied, list) or any(
                not isinstance(rule, str) or rule.startswith(("Write(", "Shell(", "Read(.agents"))
                for rule in denied
            ):
                raise HarnessError(
                    "Cursor user CLI permissions would confound project permission conformance"
                )
            self.evidence.user_cli_config_sha256 = hashlib.sha256(config_bytes).hexdigest()
        version = self.run(workspace, "--version")
        output = require_success(version, "Cursor version").strip()
        if output != self.evidence.expected_version:
            raise HarnessError(
                f"Cursor version mismatch: expected {self.evidence.expected_version!r}, got {output!r}"
            )
        self.evidence.binary_version = output
        help_result = self.run(workspace, "--help")
        help_text = require_success(help_result, "Cursor help")
        missing = [flag for flag in REQUIRED_FLAGS if flag not in help_text]
        if missing:
            raise HarnessError(f"Cursor help omitted required controls: {missing}")
        status = self.run(workspace, "status")
        status_text = require_success(status, "Cursor authentication status")
        normalized_status = status_text.casefold()
        if "not logged in" in normalized_status or "logged in" not in normalized_status:
            raise HarnessError(
                "Cursor CLI is not authenticated or did not positively confirm authentication"
            )
        self.evidence.controls["exact_version"] = True
        self.evidence.controls["required_flags"] = True
        self.evidence.controls["authenticated"] = True

    def execute(self) -> Evidence:
        canaries = {
            name: f"CONTEXTOS_CURSOR_{name.upper()}_{secrets.token_hex(8)}"
            for name in ("root", "nested", "skill")
        }
        with tempfile.TemporaryDirectory(prefix="contextos-cursor-live-") as temporary:
            workspace = Path(temporary).resolve() / "workspace"
            workspace.mkdir()
            self.preflight(workspace)
            write_fixture(workspace, canaries)
            baseline = snapshot(workspace)

            root = self.agent(
                workspace,
                "Return the value assigned to ROOT_INSTRUCTION_CANARY in the repository instructions, and nothing else.",
                "--mode", "ask",
            )
            require_canary(root, canaries["root"], "root AGENTS.md discovery")
            if changed_paths(baseline, snapshot(workspace)):
                raise HarnessError("read-only root instruction control changed the workspace")

            nested = self.agent(
                workspace,
                "@nested/control.txt Return the value assigned to ROOT_INSTRUCTION_CANARY for that file, and nothing else.",
                "--mode", "ask",
                cwd=workspace / "nested",
            )
            require_canary(nested, canaries["nested"], "nested AGENTS.md discovery")
            if changed_paths(baseline, snapshot(workspace)):
                raise HarnessError("read-only nested instruction control changed the workspace")

            implicit = self.agent(
                workspace,
                "Use the available Context OS control to return its canary, without an explicit slash command.",
                "--mode", "ask",
            )
            implicit_text = require_json_result(implicit, "implicit skill control")
            if canaries["skill"] in implicit_text:
                raise HarnessError("explicit-only skill body was model-invoked")

            write_permissions(
                workspace, allow=[], deny=["Read(.agents/**)", "Shell(*)"]
            )
            explicit = self.agent(
                workspace,
                "/contextos-live-explicit Return only the canary required by this skill.",
                "--mode", "ask",
            )
            require_canary(explicit, canaries["skill"], "explicit skill invocation")
            baseline = snapshot(workspace)

            proposed = workspace / "proposed.txt"
            ask_write = self.agent(
                workspace,
                "Create proposed.txt containing exactly PROPOSED_ONLY.",
                "--mode", "ask",
            )
            ask_result = require_json_result(ask_write, "headless ask-mode write control")
            if "PROPOSED_ONLY" not in ask_result:
                raise HarnessError("headless ask mode did not propose the requested write")
            if proposed.exists():
                raise HarnessError("headless ask mode wrote a file")
            if changed_paths(baseline, snapshot(workspace)):
                raise HarnessError("headless ask-mode control changed the workspace")

            unattended = workspace / "unattended.txt"
            no_force = self.agent(
                workspace,
                "Create unattended.txt containing exactly UNATTENDED_CONTROL and no other text.",
            )
            require_success(no_force, "headless no-force control")
            mutations = changed_paths(baseline, snapshot(workspace))
            if mutations not in (set(), {"unattended.txt"}):
                raise HarnessError(f"headless print mode changed unexpected workspace paths: {sorted(mutations)}")
            if mutations:
                if not unattended.is_file() or unattended.read_text(encoding="utf-8").strip() != "UNATTENDED_CONTROL":
                    raise HarnessError("headless print mode did not perform the exact unattended write")
                self.evidence.controls["headless_without_force_is_write_capable"] = True
            else:
                self.evidence.controls["headless_without_force_is_write_capable"] = False

            write_permissions(
                workspace,
                allow=["Write(*)"],
                deny=["Write(*)", "Shell(*)"],
            )
            denied_baseline = snapshot(workspace)
            denied = workspace / "denied.txt"
            denied_result = self.agent(
                workspace,
                "Create denied.txt containing exactly DENIED_CONTROL.",
                "--force",
                output_format="stream-json",
            )
            require_denied_write_attempt(
                denied_result, workspace, "denied.txt", "deny-precedence control"
            )
            if denied.exists():
                raise HarnessError("project deny did not override --force")
            if changed_paths(denied_baseline, snapshot(workspace)):
                raise HarnessError("deny-precedence control changed the workspace")
            self.evidence.controls["project_deny_rejected_a_write_attempt"] = True

            write_permissions(
                workspace,
                allow=["Write(*)"],
                deny=["Shell(*)"],
            )
            permission_baseline = snapshot(workspace)
            allowed = workspace / "allowed.txt"
            allowed_result = self.agent(
                workspace,
                "Create allowed.txt containing exactly ALLOWED_CONTROL and no other text.",
                "--force",
            )
            require_success(allowed_result, "forced disposable write control")
            if not allowed.is_file() or allowed.read_text(encoding="utf-8").strip() != "ALLOWED_CONTROL":
                raise HarnessError("--force did not produce the exact allowed disposable write")
            mutations = changed_paths(permission_baseline, snapshot(workspace))
            if mutations != {"allowed.txt"}:
                raise HarnessError(f"Cursor changed unexpected workspace paths: {sorted(mutations)}")

        self.evidence.controls.update({
            "root_instruction_discovery": True,
            "nested_instruction_discovery": True,
            "implicit_skill_must_not_fire": True,
            "explicit_skill_must_fire": True,
            "headless_ask_mode_preserves_files": True,
            "deny_precedes_force": True,
            "forced_write_is_scoped": True,
            "short_update_alias_not_invoked": True,
            "real_workspace_not_used": True,
        })
        return self.evidence


def write_evidence(path: Path, evidence: Evidence) -> None:
    payload = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "runtime": "cursor",
        "surface": "cli",
        "source_sha": evidence.source_sha,
        "expected_version": evidence.expected_version,
        "binary_version": evidence.binary_version,
        "user_cli_config_sha256": evidence.user_cli_config_sha256,
        "commands": evidence.commands,
        "controls": evidence.controls,
    }
    path = require_outside_source(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise HarnessError(f"refusing to overwrite evidence: {path}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--allow-model-traffic", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not args.allow_model_traffic:
            raise HarnessError("live conformance requires --allow-model-traffic")
        actual_sha = repository_source_sha()
        if args.source_sha != actual_sha:
            raise HarnessError(
                f"--source-sha must equal the clean harness commit {actual_sha}"
            )
        harness = CursorHarness(args.binary, args.expected_version, actual_sha)
        evidence = harness.execute()
        if repository_source_sha() != actual_sha:
            raise HarnessError("source commit changed during Cursor live conformance")
        write_evidence(args.evidence, evidence)
    except (HarnessError, OSError, subprocess.SubprocessError) as exc:
        print(f"cursor live conformance failed: {exc}", file=os.sys.stderr)
        return 1
    print(f"Cursor CLI conformance passed; evidence: {args.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
