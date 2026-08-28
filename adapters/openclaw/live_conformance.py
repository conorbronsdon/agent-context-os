"""Operator-driven live conformance harness for the OpenClaw adapter.

This is intentionally not part of the ordinary test suite.  It sends a small,
synthetic lifecycle scenario to an external model and pauses before every
proposal apply.  The operator, not the model or this program, authenticates the
exact proposal digest.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import queue
import re
import socket
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


LIFECYCLE_SKILLS = (
    "setup", "context-setup", "start", "context-start",
    "update", "context-update", "end", "context-end",
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
NATIVE_MEMORY_NAMES = ("SOUL.md", "USER.md", "MEMORY.md", "memory")
DISPOSABLE_MARKER = ".context-os-live-disposable"
RESULT_PREFIX = "CONTEXTOS_LIVE_RESULT="
MODEL_ROUTE = "claude-cli/claude-sonnet-5"
EXECUTION_ROOT_BOUNDARY = (
    "Treat the repository working directory supplied in ACP session metadata as "
    "the exact lifecycle execution root. Before any repository read, write, or "
    "kernel command, explicitly set the tool working directory to that root and "
    "verify it contains AGENTS.md and scripts/contextos.sh. Never substitute the "
    "process/tool cwd, OpenClaw private workspace, skill install location, or an "
    "ancestor found by searching upward. Stop without creating a payload or "
    "running the kernel if the exact root cannot be established."
)
SENSITIVE_KEY = re.compile(r"(?i)(auth|credential|password|secret|token|api.?key|prompt|message)")
ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|/)[^\s\"']+")


class HarnessError(RuntimeError):
    """A live gate failed safely."""


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class Evidence:
    expected_version: str
    binary_version: str = ""
    sync_report: Any = None
    commands: list[dict[str, Any]] = field(default_factory=list)
    lifecycle: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    controls: dict[str, Any] = field(default_factory=dict)


Runner = Callable[[Sequence[str], Path, Mapping[str, str], float], CommandResult]


def default_runner(
    argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout: float,
) -> CommandResult:
    completed = subprocess.run(
        list(argv), cwd=cwd, env=dict(env), text=True, encoding="utf-8",
        errors="replace", capture_output=True, check=False, timeout=timeout,
    )
    return CommandResult(list(argv), completed.returncode, completed.stdout, completed.stderr)


def _existing_components(path: Path) -> list[Path]:
    absolute = path.absolute()
    components: list[Path] = []
    cursor = absolute
    while True:
        if cursor.exists() or cursor.is_symlink():
            components.append(cursor)
        if cursor == cursor.parent:
            break
        cursor = cursor.parent
    return components


def _is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & reparse)


def reject_linked_path(path: Path, label: str) -> Path:
    for component in _existing_components(path):
        if _is_link_or_reparse(component):
            raise HarnessError(f"{label} contains a symbolic-link or reparse-point component: {component}")
    return path.resolve(strict=False)


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_paths(repo: Path, state: Path, workspace: Path, evidence: Path) -> tuple[Path, Path, Path, Path]:
    resolved = tuple(
        reject_linked_path(path, label)
        for path, label in (
            (repo, "repository"), (state, "state directory"),
            (workspace, "private workspace"), (evidence, "evidence path"),
        )
    )
    repo_r, state_r, workspace_r, evidence_r = resolved
    if not repo_r.is_dir():
        raise HarnessError(f"repository does not exist: {repo_r}")
    marker = repo_r / DISPOSABLE_MARKER
    if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != "disposable":
        raise HarnessError(f"sanitized disposable repository must contain {DISPOSABLE_MARKER} with value 'disposable'")
    for left, right in ((repo_r, state_r), (repo_r, workspace_r), (state_r, workspace_r)):
        if _contains(left, right) or _contains(right, left):
            raise HarnessError(f"live paths must be separate, non-nested directories: {left} and {right}")
    if _contains(repo_r, evidence_r) or _contains(state_r, evidence_r) or _contains(workspace_r, evidence_r):
        raise HarnessError("evidence must be outside the repository, state, and private workspace")
    return repo_r, state_r, workspace_r, evidence_r


def load_sync_helper() -> Callable[[Path], Any]:
    module_path = Path(__file__).with_name("sync_skills.py")
    try:
        spec = importlib.util.spec_from_file_location("contextos_openclaw_sync", module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"could not load {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        helper = getattr(module, "sync")
    except (ImportError, AttributeError, OSError) as exc:
        raise HarnessError(
            "OpenClaw promotion requires adapters.openclaw.sync_skills."
            "sync(workspace) before this harness can run"
        ) from exc
    return helper


def verify_port_is_free(port: int) -> None:
    if not 1024 <= port <= 65535:
        raise HarnessError("--port must be between 1024 and 65535")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def openclaw_config(workspace: Path, port: int, claude_binary: Path) -> dict[str, Any]:
    return {
        "agents": {"defaults": {
            "workspace": str(workspace),
            "skipBootstrap": True,
            "skills": list(LIFECYCLE_SKILLS),
            "model": {"primary": MODEL_ROUTE},
            "cliBackends": {"claude-cli": {"command": str(claude_binary)}},
        }},
        "plugins": {"entries": {"anthropic": {"enabled": True}}},
        "gateway": {
            "mode": "local", "bind": "loopback", "port": port,
            "auth": {"mode": "none"},
        },
        "hooks": {"internal": {"enabled": False}},
    }


def write_openclaw_config(
    state: Path, workspace: Path, port: int, claude_binary: Path,
) -> Path:
    state.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    config = openclaw_config(workspace, port, claude_binary)
    target = state / "openclaw.json"
    try:
        with target.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(config, indent=2) + "\n")
    except FileExistsError as exc:
        raise HarnessError(f"refusing to overwrite existing OpenClaw config: {target}") from exc
    return target


def acp_server_command(command_prefix: Sequence[str]) -> list[str]:
    return [*command_prefix, "acp"]


AcpRunner = Callable[[Sequence[str], Path, Mapping[str, str], str, float], CommandResult]


def default_acp_runner(
    argv: Sequence[str], cwd: Path, env: Mapping[str, str], prompt: str, timeout: float,
) -> CommandResult:
    """Drive one ACP turn over the server's newline-delimited JSON-RPC stdio."""
    spawn_env = dict(env)
    spawn_env["OPENCLAW_NO_RESPAWN"] = "1"
    process = subprocess.Popen(
        list(argv), cwd=cwd, env=spawn_env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", bufsize=1,
    )
    if process.stdin is None or process.stdout is None or process.stderr is None:
        process.kill()
        raise HarnessError("could not open ACP server stdio")
    stdout_lines: queue.Queue[str | None] = queue.Queue()
    stderr_parts: list[str] = []

    def pump_stdout() -> None:
        for line in process.stdout:
            stdout_lines.put(line)
        stdout_lines.put(None)

    def pump_stderr() -> None:
        for chunk in iter(lambda: process.stderr.read(1024), ""):
            stderr_parts.append(chunk)

    pumps = [
        threading.Thread(target=pump_stdout, daemon=True),
        threading.Thread(target=pump_stderr, daemon=True),
    ]
    for thread in pumps:
        thread.start()
    rendered: list[str] = []
    deadline = time.monotonic() + timeout

    def send(message: Mapping[str, Any]) -> None:
        process.stdin.write(json.dumps(dict(message), separators=(",", ":")) + "\n")
        process.stdin.flush()

    def request(identifier: int, method: str, params: Mapping[str, Any]) -> None:
        send({"jsonrpc": "2.0", "id": identifier, "method": method, "params": dict(params)})

    def next_message() -> dict[str, Any]:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HarnessError("ACP JSON-RPC turn timed out")
            try:
                line = stdout_lines.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                if process.poll() is not None:
                    raise HarnessError("ACP server exited before completing the turn")
                continue
            if line is None:
                raise HarnessError("ACP server closed stdout before completing the turn")
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                raise HarnessError("ACP server emitted non-JSON stdout") from exc
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise HarnessError("ACP server emitted an invalid JSON-RPC message")
            return message

    def handle_incoming(message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "session/update":
            update = params.get("update") if isinstance(params.get("update"), dict) else {}
            kind = update.get("sessionUpdate")
            if kind == "agent_message_chunk":
                content = update.get("content") if isinstance(update.get("content"), dict) else {}
                if content.get("type") == "text" and isinstance(content.get("text"), str):
                    rendered.append(content["text"])
            elif kind == "tool_call":
                rendered.append(
                    f"\n[tool] {update.get('title', 'tool')} "
                    f"({update.get('status', 'unknown')})\n"
                )
            elif kind == "tool_call_update":
                rendered.append(
                    f"\n[tool update] {update.get('toolCallId', 'unknown')}: "
                    f"{update.get('status', 'unknown')}\n"
                )
            return
        if "id" not in message:
            return
        if method == "session/request_permission":
            send({
                "jsonrpc": "2.0", "id": message["id"],
                "result": {"outcome": {"outcome": "cancelled"}},
            })
            return
        send({
            "jsonrpc": "2.0", "id": message["id"],
            "error": {"code": -32601, "message": "Method not supported by conformance client"},
        })

    def await_response(identifier: int) -> dict[str, Any]:
        while True:
            message = next_message()
            if message.get("id") == identifier and "method" not in message:
                if "error" in message:
                    raise HarnessError(f"ACP request {identifier} failed")
                result = message.get("result")
                if not isinstance(result, dict):
                    raise HarnessError("ACP response result was not an object")
                return result
            handle_incoming(message)

    try:
        request(1, "initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {
                "fs": {"readTextFile": False, "writeTextFile": False},
                "terminal": False,
            },
            "clientInfo": {"name": "contextos-live-harness", "version": "1"},
        })
        initialized = await_response(1)
        if initialized.get("protocolVersion") != 1:
            raise HarnessError("ACP protocol version mismatch")
        request(2, "session/new", {"cwd": str(cwd), "mcpServers": []})
        session = await_response(2)
        session_id = session.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            raise HarnessError("ACP session/new returned no session id")
        request(3, "session/prompt", {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": prompt}],
        })
        response = await_response(3)
        stop_reason = response.get("stopReason")
        if not isinstance(stop_reason, str) or not stop_reason:
            raise HarnessError("ACP prompt returned no stop reason")
        rendered.append(f"\n[{stop_reason}]\n")
        return CommandResult(list(argv), 0, "".join(rendered), "".join(stderr_parts))
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for thread in pumps:
            thread.join(timeout=1)
        process.stdout.close()
        process.stderr.close()


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _string_values(child)]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    return []


def parse_lifecycle_result(stdout: str) -> dict[str, str]:
    try:
        payload = json.loads(stdout)
        candidates = _string_values(payload)
    except json.JSONDecodeError:
        candidates = [stdout]
    markers: list[dict[str, Any]] = []
    for candidate in candidates:
        for line in candidate.splitlines():
            if RESULT_PREFIX not in line:
                continue
            raw = line.split(RESULT_PREFIX, 1)[1].strip()
            try:
                marker = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(marker, dict):
                markers.append(marker)
    if len(markers) != 1:
        raise HarnessError(f"expected exactly one {RESULT_PREFIX} marker, found {len(markers)}")
    marker = markers[0]
    result = {str(key): str(value) for key, value in marker.items()}
    return result


def require_proposal(result: dict[str, str]) -> tuple[str, str]:
    proposal, digest = result.get("proposal", ""), result.get("digest", "")
    if not proposal or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise HarnessError("agent result did not contain a repository proposal path and lowercase SHA-256 digest")
    proposal_path = Path(proposal)
    if proposal_path.is_absolute() or ".." in proposal_path.parts:
        raise HarnessError("agent returned an unsafe proposal path")
    return proposal, digest


def require_operator_digest(digest: str, phase: str, input_fn: Callable[[str], str] = input) -> None:
    entered = input_fn(
        f"Review the complete {phase} proposal diff above. To approve exactly {digest}, type that digest: "
    ).strip()
    if entered != digest:
        raise HarnessError(f"{phase} proposal was not approved with its exact digest")


def redact(value: Any, private_paths: Sequence[Path] = ()) -> Any:
    if isinstance(value, dict):
        return {
            str(key): ("[REDACTED]" if SENSITIVE_KEY.search(str(key)) else redact(child, private_paths))
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact(child, private_paths) for child in value]
    if isinstance(value, str):
        sanitized = value
        for path in private_paths:
            sanitized = sanitized.replace(str(path), f"[{path.name.upper()}]")
        return ABSOLUTE_PATH.sub("[PATH]", sanitized)
    return value


def output_summary(result: CommandResult) -> dict[str, Any]:
    return {
        "returncode": result.returncode,
        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
    }


def is_wrong_digest_rejection(result: CommandResult) -> bool:
    diagnostic = f"{result.stdout}\n{result.stderr}"
    return (
        result.returncode != 0
        and "--confirm must exactly match the proposal_digest" in diagnostic
    )


def parse_diagnostic(result: CommandResult, private_paths: Sequence[Path]) -> dict[str, Any]:
    summary = output_summary(result)
    try:
        summary["report"] = redact(json.loads(result.stdout), private_paths)
    except json.JSONDecodeError:
        summary["report"] = {"format": "non-json", "bytes": len(result.stdout.encode())}
    return summary


def native_memory_snapshot(repo: Path) -> dict[str, bool]:
    return {name: (repo / name).exists() for name in NATIVE_MEMORY_NAMES}


def repository_snapshot(repo: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(repo.rglob("*")):
        relative = path.relative_to(repo)
        if relative.parts and relative.parts[0] == ".git":
            continue
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink() or (path.exists() and _is_link_or_reparse(path)):
            raise HarnessError(f"disposable repository contains linked content: {relative}")
        if path.is_file():
            snapshot[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def skill_inventory(stdout: str) -> dict[str, dict[str, Any]]:
    try:
        report = json.loads(stdout)
        skills = report["skills"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise HarnessError("OpenClaw skill inventory was not valid JSON") from exc
    if not isinstance(skills, list):
        raise HarnessError("OpenClaw skill inventory has no skills list")
    return {
        str(skill["name"]): skill for skill in skills
        if isinstance(skill, dict) and "name" in skill
    }


def set_execution_policy(
    config_path: Path, security: str, ask: str | None = None,
    host: str = "gateway",
) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    policy: dict[str, str] = {"host": host, "security": security}
    if ask is not None:
        policy["ask"] = ask
    config.setdefault("tools", {})["exec"] = policy
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def exec_policy_preset_command(
    command_prefix: Sequence[str], preset: str,
) -> list[str]:
    if preset not in {"deny-all", "yolo"}:
        raise HarnessError(f"unsupported execution-policy preset: {preset}")
    return [*command_prefix, "exec-policy", "preset", preset, "--json"]


class LiveHarness:
    def __init__(
        self, *, binary: str, expected_version: str, repo: Path, state: Path,
        workspace: Path, evidence_path: Path, port: int, runner: Runner = default_runner,
        claude_binary: Path, binary_args: Sequence[str] = (),
        acp_runner: AcpRunner = default_acp_runner,
        input_fn: Callable[[str], str] = input,
    ) -> None:
        self.command_prefix = (binary, *binary_args)
        self.expected_version = expected_version
        self.repo, self.state, self.workspace, self.evidence_path = validate_paths(
            repo, state, workspace, evidence_path,
        )
        for path, label in (
            (self.state, "state directory"),
            (self.workspace, "private workspace"),
        ):
            if path.exists():
                raise HarnessError(f"{label} must not exist before the live run: {path}")
        self.claude_binary = reject_linked_path(claude_binary, "Claude binary")
        if not self.claude_binary.is_file():
            raise HarnessError(f"Claude binary does not exist: {self.claude_binary}")
        self.runner = runner
        self.acp_runner = acp_runner
        self.port = port
        self.input_fn = input_fn
        self.env = os.environ.copy()
        self.env["OPENCLAW_STATE_DIR"] = str(self.state)
        self.env["OPENCLAW_CONFIG_PATH"] = str(self.state / "openclaw.json")
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        # The Windows launcher otherwise respawns the piped ACP client to add a
        # Node stack-size flag. The wrapper can consume the queued prompt before
        # the final child's readline loop starts, leaving the turn idle.
        self.env["OPENCLAW_NO_RESPAWN"] = "1"
        self.evidence = Evidence(expected_version=expected_version)
        self.gateway: subprocess.Popen[str] | None = None

    def run_command(self, argv: Sequence[str], *, cwd: Path | None = None, timeout: float = 120) -> CommandResult:
        result = self.runner(argv, cwd or self.repo, self.env, timeout)
        command_shape = [
            Path(item).name if Path(item).is_absolute() else item
            for item in argv[:3]
        ]
        self.evidence.commands.append({"command": command_shape, **output_summary(result)})
        return result

    def rpc(
        self, prompt: str, phase: str, *, show_output: bool = False,
        enforce_execution_root: bool = True,
    ) -> dict[str, str]:
        command = acp_server_command(self.command_prefix)
        bounded_prompt = (
            f"{EXECUTION_ROOT_BOUNDARY}\n\n{prompt}"
            if enforce_execution_root else prompt
        )
        result = self.acp_runner(
            command, self.repo, self.env, bounded_prompt, 700,
        )
        self.evidence.commands.append({
            "command": [Path(item).name if Path(item).is_absolute() else item for item in command[:4]],
            **output_summary(result),
        })
        if result.returncode:
            detail = redact(
                (result.stderr or result.stdout).strip()[:1000],
                (self.repo, self.workspace, self.state),
            )
            raise HarnessError(
                f"OpenClaw ACP turn failed during {phase}: {detail or 'no diagnostic output'}"
            )
        if show_output:
            print(f"\n--- OpenClaw {phase} output (not retained in evidence) ---\n{result.stdout}\n--- end output ---")
        return parse_lifecycle_result(result.stdout)

    def wait_for_gateway(self, timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.gateway is not None and self.gateway.poll() is not None:
                raise HarnessError(f"OpenClaw Gateway exited early with code {self.gateway.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.1)
        raise HarnessError("OpenClaw Gateway did not become ready on loopback")

    def start_gateway(self) -> None:
        self.gateway = subprocess.Popen(
            [*self.command_prefix, "gateway", "run", "--port", str(self.port),
             "--bind", "loopback", "--auth", "none"],
            cwd=self.repo, env=self.env, text=True, encoding="utf-8",
            errors="replace", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.wait_for_gateway()

    def stop_gateway(self) -> None:
        if self.gateway is None or self.gateway.poll() is not None:
            return
        self.gateway.terminate()
        try:
            self.gateway.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.gateway.kill()
            self.gateway.wait(timeout=5)

    def validate_config(self) -> None:
        result = self.run_command([*self.command_prefix, "config", "validate"], cwd=self.workspace, timeout=60)
        if result.returncode:
            raise HarnessError("OpenClaw rejected the generated live-conformance config")

    def verify_preflight_controls(self, config_path: Path) -> None:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        visible_result = self.run_command(
            [*self.command_prefix, "skills", "list", "--json"], cwd=self.workspace, timeout=120,
        )
        if visible_result.returncode:
            raise HarnessError("could not inspect the effective OpenClaw skill allowlist")
        visible = skill_inventory(visible_result.stdout)
        if not all(name in visible and visible[name].get("modelVisible") for name in LIFECYCLE_SKILLS):
            raise HarnessError("the eight-skill allowlist is not effective")

        config["agents"]["defaults"]["skills"] = []
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        self.validate_config()
        blocked_result = self.run_command(
            [*self.command_prefix, "skills", "list", "--json"], cwd=self.workspace, timeout=120,
        )
        blocked = skill_inventory(blocked_result.stdout) if blocked_result.returncode == 0 else {}
        if not all(
            name in blocked and not blocked[name].get("modelVisible", True)
            for name in LIFECYCLE_SKILLS
        ):
            raise HarnessError("empty skill allowlist must-not-fire control failed")
        self.evidence.controls["empty_skill_allowlist_blocks_lifecycle"] = True

        config["agents"]["defaults"]["skills"] = list(LIFECYCLE_SKILLS)
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        set_execution_policy(config_path, "deny", "off")
        self.validate_config()
        deny_policy = self.run_command(
            exec_policy_preset_command(self.command_prefix, "deny-all"),
            cwd=self.workspace, timeout=60,
        )
        if deny_policy.returncode:
            raise HarnessError("could not install isolated deny-all execution policy")
        self.evidence.controls["exec_policy_deny_all_configured"] = True
        sentinel = self.repo / ".context-os-exec-denial-sentinel"
        try:
            self.start_gateway()
            denied = self.rpc(
                f"Attempt exactly one Bash tool execution that creates {sentinel.name} in the current repository. "
                f"Do not use another tool or retry. After execution authorization refuses it, return only "
                f"{RESULT_PREFIX}{{\"status\":\"rejected\"}}.",
                "execution-deny-control",
                enforce_execution_root=False,
            )
        finally:
            self.stop_gateway()
        if sentinel.exists() or denied.get("status") != "rejected":
            raise HarnessError("execution-authorization must-not-fire control failed")
        self.evidence.controls["execution_security_deny_blocks_shell"] = True

        set_execution_policy(config_path, "full", "off")
        self.validate_config()
        yolo_policy = self.run_command(
            exec_policy_preset_command(self.command_prefix, "yolo"),
            cwd=self.workspace, timeout=60,
        )
        if yolo_policy.returncode:
            raise HarnessError("could not install disposable-repository must-fire execution policy")
        self.evidence.controls["exec_policy_yolo_configured"] = True
        self.evidence.controls["execution_full_must_fire_configured"] = True

    def proposal_phase(self, phase: str, prompt: str) -> None:
        proposed = self.rpc(prompt, f"{phase}-propose", show_output=True)
        proposal, digest = require_proposal(proposed)
        proposal_file = reject_linked_path(self.repo / proposal, f"{phase} proposal")
        if not _contains(self.repo, proposal_file) or not proposal_file.is_file():
            raise HarnessError(f"{phase} proposal is not a plain file inside the repository")
        print(f"\n{phase} proposal: {proposal}\ndigest: {digest}\n")

        wrong = "0" * 64 if digest != "0" * 64 else "f" * 64
        before_control = repository_snapshot(self.repo)
        rejected = self.run_command(
            ["bash", "scripts/contextos.sh", "apply", proposal, "--confirm", wrong,
             "--runtime", "openclaw"],
            timeout=120,
        )
        if (
            not is_wrong_digest_rejection(rejected)
            or repository_snapshot(self.repo) != before_control
        ):
            raise HarnessError("wrong-digest must-not-fire control did not prove rejection")
        require_operator_digest(digest, phase, self.input_fn)
        receipts = self.repo / ".context-os/receipts"
        before_receipts = set(receipts.glob("*.json")) if receipts.exists() else set()
        applied = self.rpc(
            f"The operator approved exact digest {digest}. Run exactly: bash scripts/contextos.sh apply "
            f"{proposal} --confirm {digest} --runtime openclaw. Do not commit or push. Return only "
            f"{RESULT_PREFIX}{{\"status\":\"applied\",\"digest\":\"{digest}\"}} after success.",
            f"{phase}-apply",
        )
        if applied.get("status") != "applied" or applied.get("digest") != digest:
            raise HarnessError(f"{phase} apply did not return the approved digest")
        after_receipts = set(receipts.glob("*.json")) if receipts.exists() else set()
        new_receipts = after_receipts - before_receipts
        if len(new_receipts) != 1:
            raise HarnessError(f"{phase} apply did not create exactly one kernel receipt")
        receipt = json.loads(next(iter(new_receipts)).read_text(encoding="utf-8"))
        if receipt.get("runtime") != "openclaw":
            raise HarnessError(f"{phase} receipt was not attributed to OpenClaw")
        self.evidence.lifecycle.append({"phase": phase, "digest": digest, "wrong_digest_rejected": True})

    def execute(self) -> Evidence:
        try:
            return self._execute_unprotected()
        finally:
            self.stop_gateway()

    def _execute_unprotected(self) -> Evidence:
        verify_port_is_free(self.port)
        version = self.run_command([*self.command_prefix, "--version"], timeout=30)
        if version.returncode:
            raise HarnessError("could not execute the requested OpenClaw binary")
        self.evidence.binary_version = version.stdout.strip()
        if self.evidence.binary_version != self.expected_version:
            raise HarnessError(
                f"exact version gate failed: expected {self.expected_version!r}, got {self.evidence.binary_version!r}"
            )

        source_sha_result = self.run_command(
            ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, timeout=30,
        )
        source_sha = source_sha_result.stdout.strip()
        if source_sha_result.returncode or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
            raise HarnessError("could not bind copied skills to the harness source commit")
        repo_sha_result = self.run_command(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, timeout=30,
        )
        repo_sha = repo_sha_result.stdout.strip()
        if repo_sha_result.returncode or repo_sha != source_sha:
            raise HarnessError(
                "disposable repository HEAD must exactly match the harness source commit"
            )
        self.workspace.mkdir(parents=True)
        try:
            sync_report = load_sync_helper()(self.workspace)
        except (OSError, RuntimeError) as exc:
            raise HarnessError(f"lifecycle skill synchronization failed safely: {exc}") from exc
        json.dumps(sync_report)
        if not isinstance(sync_report, dict) or sync_report.get("source_git_sha") != source_sha:
            raise HarnessError("skill synchronization provenance does not match the harness source commit")
        self.evidence.sync_report = redact(sync_report, (self.repo, self.workspace, self.state))
        config_path = write_openclaw_config(
            self.state, self.workspace, self.port, self.claude_binary,
        )
        self.validate_config()
        self.verify_preflight_controls(config_path)
        memory_before = native_memory_snapshot(self.repo)
        if any(memory_before.values()):
            raise HarnessError("disposable repository already contains OpenClaw native-memory paths")

        self.start_gateway()
        self.proposal_phase(
                "setup",
                f"Invoke /skill setup using only this pre-reviewed synthetic public-safe fixture: project name "
                f"'Lifecycle Fixture', purpose 'verify Context OS', current focus 'complete live conformance', "
                f"no personal facts, no links, no credentials. The repository audience is explicitly confirmed "
                f"as sanitized and disposable. Create a setup proposal, print its complete diff, do not apply it, "
                f"then return only {RESULT_PREFIX}{{\"proposal\":\"<repo-relative path>\",\"digest\":\"<sha256>\"}}.",
        )
        before_start = repository_snapshot(self.repo)
        started = self.rpc(
                f"Invoke /skill start. It must remain read-only. Return only "
                f"{RESULT_PREFIX}{{\"status\":\"started\"}} after reporting the continuity inventory.",
                "start",
        )
        if started.get("status") != "started" or repository_snapshot(self.repo) != before_start:
            raise HarnessError("start lifecycle did not complete read-only")
        self.evidence.lifecycle.append({"phase": "start", "read_only": True})
        self.proposal_phase(
                "update",
                f"Invoke /skill update with the synthetic fact 'Live OpenClaw checkpoint completed.' Create and "
                f"show the complete proposal diff, do not apply it, then return only {RESULT_PREFIX}"
                f"{{\"proposal\":\"<repo-relative path>\",\"digest\":\"<sha256>\"}}.",
        )
        draft = self.rpc(
                f"Invoke /skill end only through its draft-review step using synthetic outcome 'OpenClaw live "
                f"lifecycle exercised' and next action 'Review promotion evidence'; no personal facts and no "
                f"durable decision. Do not create a proposal yet. Show the complete draft, then return only "
                f"{RESULT_PREFIX}{{\"status\":\"draft-ready\"}}.",
                "end-draft",
                show_output=True,
        )
        if draft.get("status") != "draft-ready":
            raise HarnessError("end lifecycle did not present a draft for review")
        end_confirmation = self.input_fn(
            "Review the end draft above. To authorize proposal creation, type 'approve end draft': "
        ).strip()
        if end_confirmation != "approve end draft":
            raise HarnessError("end draft was not explicitly confirmed")
        self.proposal_phase(
                "end",
                f"Continue /skill end using the operator-confirmed synthetic draft: outcome 'OpenClaw live "
                f"lifecycle exercised' and next action 'Review promotion evidence'; no durable decision. Create and show "
                f"the complete proposal diff, do not apply it, then return only {RESULT_PREFIX}"
                f"{{\"proposal\":\"<repo-relative path>\",\"digest\":\"<sha256>\"}}.",
        )

        paths = (self.repo, self.workspace, self.state)
        for name, args, codes in (
            ("doctor", [*self.command_prefix, "doctor", "--lint", "--json"], (0, 1)),
            ("hooks", [*self.command_prefix, "hooks", "list", "--json"], (0,)),
            ("plugins", [*self.command_prefix, "plugins", "list", "--json"], (0,)),
        ):
            result = self.run_command(args, cwd=self.workspace, timeout=120)
            self.evidence.diagnostics[name] = parse_diagnostic(result, paths)
            if result.returncode not in codes:
                raise HarnessError(f"OpenClaw {name} diagnostic failed")

        memory_after = native_memory_snapshot(self.repo)
        self.evidence.controls["repo_native_memory_absent"] = not any(memory_after.values())
        self.evidence.controls["hooks_configured_disabled"] = True
        if memory_after != memory_before:
            raise HarnessError("OpenClaw created native-memory files inside the repository")
        self.stop_gateway()
        return self.evidence


def write_evidence(path: Path, evidence: Evidence) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 1,
        "expected_version": evidence.expected_version,
        "binary_version": evidence.binary_version,
        "sync_report": evidence.sync_report,
        "commands": evidence.commands,
        "lifecycle": evidence.lifecycle,
        "diagnostics": evidence.diagnostics,
        "controls": evidence.controls,
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default="openclaw")
    parser.add_argument(
        "--binary-arg", action="append", default=[],
        help="Argument inserted after --binary and before every OpenClaw command; repeat as needed",
    )
    parser.add_argument("--claude-binary", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--private-workspace", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--acknowledge-external-model-egress", action="store_true", required=True)
    parser.add_argument("--acknowledge-disposable-repo", action="store_true", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    harness: LiveHarness | None = None
    try:
        harness = LiveHarness(
            binary=args.binary, binary_args=args.binary_arg,
            expected_version=args.expected_version, repo=args.repo,
            state=args.state_dir, workspace=args.private_workspace,
            evidence_path=args.evidence, port=args.port, claude_binary=args.claude_binary,
        )
        evidence = harness.execute()
        write_evidence(harness.evidence_path, evidence)
    except (HarnessError, OSError, subprocess.SubprocessError, TypeError, ValueError) as exc:
        if harness is not None:
            harness.evidence.controls["failure"] = redact(
                str(exc), (harness.repo, harness.workspace, harness.state),
            )
            try:
                write_evidence(harness.evidence_path, harness.evidence)
            except OSError:
                pass
        print(f"openclaw live conformance failed safely: {exc}", file=sys.stderr)
        return 1
    finally:
        if harness is not None:
            harness.stop_gateway()
    print(f"OpenClaw live conformance passed; redacted evidence: {harness.evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
