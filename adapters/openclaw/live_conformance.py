"""Operator-driven OpenClaw conformance through the Context OS Gateway plugin.

The run is isolated, synthetic, and disposable. The operator must type every
exact proposal digest; neither the model nor this harness can auto-approve it.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import socket
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

LIFECYCLE_SKILLS = (
    "setup", "context-setup", "start", "context-start",
    "update", "context-update", "end", "context-end",
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_PACKAGE = Path(__file__).resolve().with_name("plugin")
NATIVE_MEMORY_NAMES = ("SOUL.md", "USER.md", "MEMORY.md", "memory")
DISPOSABLE_MARKER = ".context-os-live-disposable"
RESULT_PREFIX = "CONTEXTOS_LIVE_RESULT="
MODEL_ROUTE = "claude-cli/claude-sonnet-5"
PROJECT_ALIAS = "fixture"
CONFORMANCE_SCENARIO = "synthetic-conformance-v1"
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


def default_runner(argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout: float) -> CommandResult:
    completed = subprocess.run(
        list(argv), cwd=cwd, env=dict(env), text=True, encoding="utf-8",
        errors="replace", capture_output=True, check=False, timeout=timeout,
    )
    return CommandResult(list(argv), completed.returncode, completed.stdout, completed.stderr)


def _existing_components(path: Path) -> list[Path]:
    result: list[Path] = []
    cursor = path.absolute()
    while True:
        if cursor.exists() or cursor.is_symlink():
            result.append(cursor)
        if cursor == cursor.parent:
            return result
        cursor = cursor.parent


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
    repo_r, state_r, workspace_r, evidence_r = (
        reject_linked_path(path, label) for path, label in (
            (repo, "repository"), (state, "state directory"),
            (workspace, "private workspace"), (evidence, "evidence path"),
        )
    )
    if not repo_r.is_dir():
        raise HarnessError(f"repository does not exist: {repo_r}")
    marker = repo_r / DISPOSABLE_MARKER
    if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != "disposable":
        raise HarnessError(f"sanitized disposable repository must contain {DISPOSABLE_MARKER} with value 'disposable'")
    for left, right in ((repo_r, state_r), (repo_r, workspace_r), (state_r, workspace_r)):
        if _contains(left, right) or _contains(right, left):
            raise HarnessError(f"live paths must be separate, non-nested directories: {left} and {right}")
    if any(_contains(root, evidence_r) for root in (repo_r, state_r, workspace_r)):
        raise HarnessError("evidence must be outside the repository, state, and private workspace")
    return repo_r, state_r, workspace_r, evidence_r


def load_sync_helper() -> Callable[[Path], Any]:
    module_path = Path(__file__).with_name("sync_skills.py")
    try:
        spec = importlib.util.spec_from_file_location("contextos_openclaw_sync", module_path)
        if spec is None or spec.loader is None:
            raise ImportError(str(module_path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, "sync")
    except (ImportError, AttributeError, OSError) as exc:
        raise HarnessError("OpenClaw promotion requires adapters.openclaw.sync_skills.sync(workspace)") from exc


def verify_port_is_free(port: int) -> None:
    if not 1024 <= port <= 65535:
        raise HarnessError("--port must be between 1024 and 65535")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def openclaw_config(
    workspace: Path, port: int, claude_binary: Path, repo: Path,
    bash_path: Path, gateway_token: str,
) -> dict[str, Any]:
    return {
        "agents": {"defaults": {
            "workspace": str(workspace), "skipBootstrap": True,
            "skills": list(LIFECYCLE_SKILLS), "model": {"primary": MODEL_ROUTE},
            "cliBackends": {"claude-cli": {"command": str(claude_binary)}},
        }},
        "plugins": {"allow": ["context-os"], "entries": {
            "anthropic": {"enabled": True},
            "context-os": {"enabled": True, "config": {
                "projects": {PROJECT_ALIAS: {"root": str(repo), "bashPath": str(bash_path)}},
                "runTimeoutSeconds": 700,
            }},
        }},
        "gateway": {
            "mode": "local", "bind": "loopback", "port": port,
            "auth": {"mode": "token", "token": gateway_token},
        },
        "hooks": {"internal": {"enabled": False}},
    }


def write_openclaw_config(
    state: Path, workspace: Path, port: int, claude_binary: Path, repo: Path,
    bash_path: Path, gateway_token: str,
) -> Path:
    state.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    target = state / "openclaw.json"
    try:
        with target.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(openclaw_config(
                workspace, port, claude_binary, repo, bash_path, gateway_token,
            ), indent=2) + "\n")
    except FileExistsError as exc:
        raise HarnessError(f"refusing to overwrite existing OpenClaw config: {target}") from exc
    return target


def plugin_install_command(command_prefix: Sequence[str], plugin_package: Path) -> list[str]:
    return [*command_prefix, "plugins", "install", str(plugin_package)]


def gateway_call_command(
    command_prefix: Sequence[str], port: int, method: str, params: Mapping[str, Any],
    timeout_ms: int, gateway_token: str,
) -> list[str]:
    if not method.startswith("contextos."):
        raise HarnessError("live harness may call only contextos.* Gateway methods")
    return [
        *command_prefix, "gateway", "call", method,
        "--params", json.dumps(dict(params), separators=(",", ":"), sort_keys=True),
        "--url", f"ws://127.0.0.1:{port}", "--token", gateway_token,
        "--timeout", str(timeout_ms), "--json",
    ]


def parse_gateway_result(result: CommandResult, method: str) -> dict[str, Any]:
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[:1000]
        raise HarnessError(f"OpenClaw Gateway {method} failed: {detail or 'no diagnostic output'}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HarnessError(f"OpenClaw Gateway {method} did not return JSON") from exc
    if not isinstance(payload, dict):
        raise HarnessError(f"OpenClaw Gateway {method} result was not an object")
    return payload


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _string_values(child)]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    return []


def parse_lifecycle_result(value: Any) -> dict[str, str]:
    markers: list[dict[str, Any]] = []
    for candidate in _string_values(value):
        for line in candidate.splitlines():
            if RESULT_PREFIX not in line:
                continue
            try:
                marker = json.loads(line.split(RESULT_PREFIX, 1)[1].strip())
            except json.JSONDecodeError:
                continue
            if isinstance(marker, dict):
                markers.append(marker)
    if len(markers) != 1:
        raise HarnessError(f"expected exactly one {RESULT_PREFIX} marker, found {len(markers)}")
    return {str(key): str(value) for key, value in markers[0].items()}


def require_proposal(result: dict[str, str]) -> tuple[str, str]:
    proposal, digest = result.get("proposal", ""), result.get("digest", "")
    if not proposal or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise HarnessError("agent result did not contain a repository proposal path and lowercase SHA-256 digest")
    proposal_path = Path(proposal)
    if proposal_path.is_absolute() or ".." in proposal_path.parts:
        raise HarnessError("agent returned an unsafe proposal path")
    return proposal, digest


def require_operator_digest(digest: str, phase: str, input_fn: Callable[[str], str] = input) -> None:
    entered = input_fn(f"Review the complete {phase} proposal diff above. To approve exactly {digest}, type that digest: ").strip()
    if entered != digest:
        raise HarnessError(f"{phase} proposal was not approved with its exact digest")


def redact(value: Any, private_paths: Sequence[Path] = ()) -> Any:
    if isinstance(value, dict):
        return {str(key): ("[REDACTED]" if SENSITIVE_KEY.search(str(key)) else redact(child, private_paths)) for key, child in value.items()}
    if isinstance(value, list):
        return [redact(child, private_paths) for child in value]
    if isinstance(value, str):
        for private_path in private_paths:
            value = value.replace(str(private_path), f"[{private_path.name.upper()}]")
        return ABSOLUTE_PATH.sub("[PATH]", value)
    return value


def output_summary(result: CommandResult) -> dict[str, Any]:
    return {
        "returncode": result.returncode,
        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
    }


def is_wrong_digest_rejection(result: CommandResult) -> bool:
    return result.returncode != 0 and "--confirm must exactly match the proposal_digest" in f"{result.stdout}\n{result.stderr}"


def require_clean_source(result: CommandResult) -> None:
    if result.returncode != 0:
        raise HarnessError("could not verify that the harness source worktree is clean")
    if result.stdout.strip():
        raise HarnessError("harness source worktree must be clean so the live gate binds to one exact commit")


def is_explicit_lifecycle_denial(detail: str) -> bool:
    if not re.search(r"(?i)denied|not allowed|permission|disabled|blocked", detail):
        return False
    if RESULT_PREFIX not in detail:
        return True
    try:
        marker = parse_lifecycle_result(detail)
    except HarnessError:
        return False
    return marker.get("status") != "started"


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
        skills = json.loads(stdout)["skills"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise HarnessError("OpenClaw skill inventory was not valid JSON") from exc
    if not isinstance(skills, list):
        raise HarnessError("OpenClaw skill inventory has no skills list")
    return {str(skill["name"]): skill for skill in skills if isinstance(skill, dict) and "name" in skill}


def set_execution_policy(config_path: Path, security: str, ask: str | None = None, host: str = "gateway") -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    policy: dict[str, str] = {"host": host, "security": security}
    if ask is not None:
        policy["ask"] = ask
    config.setdefault("tools", {})["exec"] = policy
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def exec_policy_preset_command(command_prefix: Sequence[str], preset: str) -> list[str]:
    if preset not in {"deny-all", "yolo"}:
        raise HarnessError(f"unsupported execution-policy preset: {preset}")
    return [*command_prefix, "exec-policy", "preset", preset, "--json"]


class LiveHarness:
    def __init__(
        self, *, binary: str, expected_version: str, repo: Path, state: Path,
        workspace: Path, evidence_path: Path, port: int, claude_binary: Path,
        bash_path: Path = Path("bash"), runner: Runner = default_runner,
        binary_args: Sequence[str] = (), input_fn: Callable[[str], str] = input,
    ) -> None:
        self.command_prefix = (binary, *binary_args)
        self.expected_version = expected_version
        self.repo, self.state, self.workspace, self.evidence_path = validate_paths(repo, state, workspace, evidence_path)
        for path, label in ((self.state, "state directory"), (self.workspace, "private workspace")):
            if path.exists():
                raise HarnessError(f"{label} must not exist before the live run: {path}")
        self.claude_binary = reject_linked_path(claude_binary, "Claude binary")
        self.bash_path = reject_linked_path(bash_path, "Bash binary")
        if not self.claude_binary.is_file():
            raise HarnessError(f"Claude binary does not exist: {self.claude_binary}")
        if not self.bash_path.is_file():
            raise HarnessError(f"Bash binary does not exist: {self.bash_path}")
        self.runner, self.port, self.input_fn = runner, port, input_fn
        self.gateway_token = secrets.token_urlsafe(32)
        self.env = os.environ.copy()
        self.env.update({
            "OPENCLAW_STATE_DIR": str(self.state),
            "OPENCLAW_CONFIG_PATH": str(self.state / "openclaw.json"),
            "PYTHONDONTWRITEBYTECODE": "1", "OPENCLAW_NO_RESPAWN": "1",
        })
        self.evidence = Evidence(expected_version=expected_version)
        self.gateway: subprocess.Popen[str] | None = None

    def run_command(self, argv: Sequence[str], *, cwd: Path | None = None, timeout: float = 120) -> CommandResult:
        result = self.runner(argv, cwd or self.repo, self.env, timeout)
        shape = [Path(item).name if Path(item).is_absolute() else item for item in argv[:4]]
        self.evidence.commands.append({"command": shape, **output_summary(result)})
        return result

    def gateway_call(self, method: str, params: Mapping[str, Any], timeout_ms: int = 10_000) -> dict[str, Any]:
        command = gateway_call_command(
            self.command_prefix, self.port, method, params, timeout_ms, self.gateway_token,
        )
        return parse_gateway_result(self.run_command(command, cwd=self.workspace, timeout=timeout_ms / 1000 + 30), method)

    def lifecycle(self, action: str, *, show_output: bool = False) -> dict[str, str]:
        started = self.gateway_call("contextos.run", {
            "alias": PROJECT_ALIAS, "action": action, "scenario": CONFORMANCE_SCENARIO,
        })
        run_id, session_key = started.get("runId"), started.get("sessionKey")
        if not isinstance(run_id, str) or not isinstance(session_key, str):
            raise HarnessError(f"contextos.run returned no owned identifiers for {action}")
        completed = self.gateway_call("contextos.wait", {"runId": run_id, "timeoutMs": 700_000}, 710_000)
        if completed.get("status") != "ok":
            raise HarnessError(f"OpenClaw lifecycle {action} ended with status {completed.get('status')!r}")
        result = self.gateway_call("contextos.result", {"sessionKey": session_key})
        text = result.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HarnessError(f"OpenClaw lifecycle {action} returned no assistant text")
        if show_output:
            print(f"\n--- OpenClaw {action} output (not retained in evidence) ---\n{text}\n--- end output ---")
        return parse_lifecycle_result(text)

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
            [*self.command_prefix, "gateway", "run", "--port", str(self.port), "--bind", "loopback", "--auth", "token"],
            cwd=self.repo, env=self.env, text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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
        if self.run_command([*self.command_prefix, "config", "validate"], cwd=self.workspace, timeout=60).returncode:
            raise HarnessError("OpenClaw rejected the generated live-conformance config")

    def install_plugin(self) -> None:
        package = reject_linked_path(PLUGIN_PACKAGE, "OpenClaw plugin package")
        if any(not (package / name).is_file() for name in ("package.json", "openclaw.plugin.json", "index.js", "lib.js")):
            raise HarnessError("OpenClaw plugin package is incomplete")
        if self.run_command(plugin_install_command(self.command_prefix, package), cwd=self.workspace, timeout=120).returncode:
            raise HarnessError("could not install the local Context OS OpenClaw plugin")
        self.evidence.controls["local_plugin_installed"] = True

    def verify_preflight_controls(self, config_path: Path) -> None:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        visible_result = self.run_command([*self.command_prefix, "skills", "list", "--json"], cwd=self.workspace)
        visible = skill_inventory(visible_result.stdout) if visible_result.returncode == 0 else {}
        if not all(name in visible and visible[name].get("modelVisible") for name in LIFECYCLE_SKILLS):
            raise HarnessError("the eight-skill allowlist is not effective")
        config["agents"]["defaults"]["skills"] = []
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        self.validate_config()
        blocked_result = self.run_command([*self.command_prefix, "skills", "list", "--json"], cwd=self.workspace)
        blocked = skill_inventory(blocked_result.stdout) if blocked_result.returncode == 0 else {}
        if not all(name in blocked and not blocked[name].get("modelVisible", True) for name in LIFECYCLE_SKILLS):
            raise HarnessError("empty skill allowlist must-not-fire control failed")
        self.evidence.controls["empty_skill_allowlist_blocks_lifecycle"] = True
        config["agents"]["defaults"]["skills"] = list(LIFECYCLE_SKILLS)
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        set_execution_policy(config_path, "deny")
        self.validate_config()
        if self.run_command(exec_policy_preset_command(self.command_prefix, "deny-all"), cwd=self.workspace, timeout=60).returncode:
            raise HarnessError("could not install the deny-all execution-policy control")
        before_denied = repository_snapshot(self.repo)
        self.start_gateway()
        denial_detail = ""
        try:
            started = self.gateway_call("contextos.run", {
                "alias": PROJECT_ALIAS, "action": "start", "scenario": CONFORMANCE_SCENARIO,
            })
            run_id, session_key = started.get("runId"), started.get("sessionKey")
            if not isinstance(run_id, str) or not isinstance(session_key, str):
                raise HarnessError("deny control did not return owned lifecycle identifiers")
            completed = self.gateway_call("contextos.wait", {"runId": run_id, "timeoutMs": 700_000}, 710_000)
            denial_detail = str(completed.get("error", ""))
            try:
                denied_result = self.gateway_call("contextos.result", {"sessionKey": session_key})
                denial_detail += "\n" + str(denied_result.get("text", ""))
            except HarnessError as exc:
                denial_detail += "\n" + str(exc)
        finally:
            self.stop_gateway()
        if repository_snapshot(self.repo) != before_denied:
            raise HarnessError("deny-all execution control allowed a repository change")
        if not is_explicit_lifecycle_denial(denial_detail):
            raise HarnessError("deny-all execution control did not produce an explicit blocked-tool result")
        self.evidence.controls["deny_all_blocks_lifecycle_tools"] = True
        set_execution_policy(config_path, "full", "off")
        self.validate_config()
        if self.run_command(exec_policy_preset_command(self.command_prefix, "yolo"), cwd=self.workspace, timeout=60).returncode:
            raise HarnessError("could not install disposable-repository execution policy")
        self.evidence.controls["exec_policy_yolo_configured"] = True

    def proposal_phase(self, phase: str) -> None:
        proposal, digest = require_proposal(self.lifecycle(phase, show_output=True))
        proposal_file = reject_linked_path(self.repo / proposal, f"{phase} proposal")
        if not _contains(self.repo, proposal_file) or not proposal_file.is_file():
            raise HarnessError(f"{phase} proposal is not a plain file inside the repository")
        print(f"\n{phase} proposal: {proposal}\ndigest: {digest}\n")
        wrong = "0" * 64 if digest != "0" * 64 else "f" * 64
        before_control = repository_snapshot(self.repo)
        plugin_wrong = self.run_command(
            gateway_call_command(
                self.command_prefix, self.port, "contextos.apply",
                {"alias": PROJECT_ALIAS, "digest": wrong}, 10_000, self.gateway_token,
            ),
            cwd=self.workspace,
        )
        if plugin_wrong.returncode == 0 or "no proposal matches digest" not in f"{plugin_wrong.stdout}\n{plugin_wrong.stderr}":
            raise HarnessError("plugin wrong-digest control did not reject an unmatched digest")
        rejected = self.run_command([
            str(self.bash_path), "scripts/contextos.sh", "apply", proposal,
            "--confirm", wrong, "--runtime", "openclaw",
        ])
        if not is_wrong_digest_rejection(rejected) or repository_snapshot(self.repo) != before_control:
            raise HarnessError("wrong-digest must-not-fire control did not prove rejection")
        require_operator_digest(digest, phase, self.input_fn)
        receipts = self.repo / ".context-os/receipts"
        before_receipts = set(receipts.glob("*.json")) if receipts.exists() else set()
        applied = self.gateway_call("contextos.apply", {"alias": PROJECT_ALIAS, "digest": digest}, 710_000)
        if applied.get("digest") != digest:
            raise HarnessError(f"{phase} apply did not return the approved digest")
        after_receipts = set(receipts.glob("*.json")) if receipts.exists() else set()
        new_receipts = after_receipts - before_receipts
        if len(new_receipts) != 1:
            raise HarnessError(f"{phase} apply did not create exactly one kernel receipt")
        receipt = json.loads(next(iter(new_receipts)).read_text(encoding="utf-8"))
        if receipt.get("runtime") != "openclaw":
            raise HarnessError(f"{phase} receipt was not attributed to OpenClaw")
        self.evidence.lifecycle.append({
            "phase": phase, "digest": digest,
            "plugin_wrong_digest_rejected": True, "kernel_wrong_digest_rejected": True,
        })

    def execute(self) -> Evidence:
        try:
            return self._execute_unprotected()
        finally:
            self.stop_gateway()

    def _execute_unprotected(self) -> Evidence:
        verify_port_is_free(self.port)
        version = self.run_command([*self.command_prefix, "--version"], timeout=30)
        self.evidence.binary_version = version.stdout.strip()
        if version.returncode or self.evidence.binary_version != self.expected_version:
            raise HarnessError(f"exact version gate failed: expected {self.expected_version!r}, got {self.evidence.binary_version!r}")
        source_result = self.run_command(["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, timeout=30)
        source_sha = source_result.stdout.strip()
        require_clean_source(self.run_command(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=REPOSITORY_ROOT, timeout=30,
        ))
        repo_result = self.run_command(["git", "rev-parse", "HEAD"], cwd=self.repo, timeout=30)
        if source_result.returncode or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
            raise HarnessError("could not bind copied skills to the harness source commit")
        if repo_result.returncode or repo_result.stdout.strip() != source_sha:
            raise HarnessError("disposable repository HEAD must exactly match the harness source commit")
        self.workspace.mkdir(parents=True)
        try:
            sync_report = load_sync_helper()(self.workspace)
        except (OSError, RuntimeError) as exc:
            raise HarnessError(f"lifecycle skill synchronization failed safely: {exc}") from exc
        if not isinstance(sync_report, dict) or sync_report.get("source_git_sha") != source_sha:
            raise HarnessError("skill synchronization provenance does not match the harness source commit")
        self.evidence.sync_report = redact(sync_report, (self.repo, self.workspace, self.state))
        config_path = write_openclaw_config(
            self.state, self.workspace, self.port, self.claude_binary, self.repo,
            self.bash_path, self.gateway_token,
        )
        self.install_plugin()
        self.validate_config()
        self.verify_preflight_controls(config_path)
        memory_before = native_memory_snapshot(self.repo)
        if any(memory_before.values()):
            raise HarnessError("disposable repository already contains OpenClaw native-memory paths")
        self.start_gateway()
        self.proposal_phase("setup")
        before_start = repository_snapshot(self.repo)
        started = self.lifecycle("start")
        if started.get("status") != "started" or repository_snapshot(self.repo) != before_start:
            raise HarnessError("start lifecycle did not complete read-only")
        self.evidence.lifecycle.append({"phase": "start", "read_only": True})
        self.proposal_phase("update")
        self.proposal_phase("end")
        paths = (self.repo, self.workspace, self.state)
        for name, args, codes in (
            ("doctor", [*self.command_prefix, "doctor", "--lint", "--json"], (0, 1)),
            ("hooks", [*self.command_prefix, "hooks", "list", "--json"], (0,)),
            ("plugins", [*self.command_prefix, "plugins", "list", "--json"], (0,)),
        ):
            result = self.run_command(args, cwd=self.workspace)
            self.evidence.diagnostics[name] = parse_diagnostic(result, paths)
            if result.returncode not in codes:
                raise HarnessError(f"OpenClaw {name} diagnostic failed")
        memory_after = native_memory_snapshot(self.repo)
        self.evidence.controls.update({
            "repo_native_memory_absent": not any(memory_after.values()),
            "hooks_configured_disabled": True,
            "gateway_plugin_is_execution_surface": True,
        })
        if memory_after != memory_before:
            raise HarnessError("OpenClaw created native-memory files inside the repository")
        return self.evidence


def write_evidence(path: Path, evidence: Evidence) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": 1, "expected_version": evidence.expected_version,
        "binary_version": evidence.binary_version, "sync_report": evidence.sync_report,
        "commands": evidence.commands, "lifecycle": evidence.lifecycle,
        "diagnostics": evidence.diagnostics, "controls": evidence.controls,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default="openclaw")
    parser.add_argument("--binary-arg", action="append", default=[])
    parser.add_argument("--claude-binary", type=Path, required=True)
    parser.add_argument("--bash-path", type=Path, required=True)
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
            binary=args.binary, binary_args=args.binary_arg, expected_version=args.expected_version,
            repo=args.repo, state=args.state_dir, workspace=args.private_workspace,
            evidence_path=args.evidence, port=args.port, claude_binary=args.claude_binary,
            bash_path=args.bash_path,
        )
        write_evidence(harness.evidence_path, harness.execute())
    except (HarnessError, OSError, subprocess.SubprocessError, TypeError, ValueError) as exc:
        if harness is not None:
            harness.evidence.controls["failure"] = redact(str(exc), (harness.repo, harness.workspace, harness.state))
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
