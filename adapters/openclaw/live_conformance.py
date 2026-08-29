"""Operator-driven OpenClaw conformance through the Context OS Gateway plugin.

The run is isolated, synthetic, and disposable. The operator must type every
exact proposal digest; neither the model nor this harness can auto-approve it.
"""

from __future__ import annotations

import argparse
import csv
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
import unicodedata
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
PROPOSAL_PHASES = frozenset(("setup", "update", "end"))
MAX_PROPOSAL_BYTES = 2 * 1024 * 1024
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


@dataclass(frozen=True)
class TrustedProposal:
    relative_path: str
    path: Path
    phase: str
    digest: str
    snapshot_sha256: str
    rendered_diffs: str


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
        pass
    # Windows may expose the same existing directory through an 8.3 short name
    # and a canonical long name. File identity closes that spelling gap without
    # weakening the linked-component rejection performed by callers.
    for candidate in (child, *child.parents):
        try:
            if os.path.samefile(parent, candidate):
                return True
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise HarnessError(f"could not verify path containment for {parent} and {child}") from exc
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


def load_snapshot_primitives() -> Any:
    """Load trusted no-follow and canonical-JSON primitives without executing a script."""
    module_path = REPOSITORY_ROOT / "contextos" / "primitives.py"
    try:
        spec = importlib.util.spec_from_file_location("contextos_openclaw_primitives", module_path)
        if spec is None or spec.loader is None:
            raise ImportError(str(module_path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except (ImportError, OSError, AttributeError) as exc:
        raise HarnessError("OpenClaw promotion requires trusted Context OS snapshot primitives") from exc


def strict_proposal_json(raw: str, *, source: str) -> Any:
    """Match the kernel's duplicate-key, BOM, and non-finite JSON rejection."""
    if raw.startswith("\ufeff"):
        raise HarnessError(f"{source}: UTF-8 BOM is not allowed")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise HarnessError(f"{source}: duplicate JSON object key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise HarnessError(f"{source}: JSON constant {value!r} is not allowed")

    try:
        return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except json.JSONDecodeError as exc:
        raise HarnessError(
            f"{source}: invalid JSON at line {exc.lineno} column {exc.colno}"
        ) from exc


def verify_port_is_free(port: int) -> None:
    if not 1024 <= port <= 65535:
        raise HarnessError("--port must be between 1024 and 65535")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def openclaw_config(
    workspace: Path, port: int, claude_binary: Path, repo: Path,
    gateway_token: str,
) -> dict[str, Any]:
    return {
        "agents": {"defaults": {
            "workspace": str(workspace), "skipBootstrap": True,
            "skills": list(LIFECYCLE_SKILLS), "model": {"primary": MODEL_ROUTE},
            "cliBackends": {"claude-cli": {
                "command": str(claude_binary),
                "args": ["--safe-mode", "--verbose"],
            }},
        }},
        "plugins": {"allow": ["context-os"], "entries": {
            "anthropic": {"enabled": True},
            "context-os": {"enabled": True, "config": {
                "projects": {PROJECT_ALIAS: {"root": str(repo)}},
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
    gateway_token: str,
) -> Path:
    harden_private_directory(state)
    harden_private_directory(workspace)
    target = state / "openclaw.json"
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(openclaw_config(
                workspace, port, claude_binary, repo, gateway_token,
            ), indent=2) + "\n")
    except FileExistsError as exc:
        raise HarnessError(f"refusing to overwrite existing OpenClaw config: {target}") from exc
    return target


def harden_private_directory(path: Path) -> None:
    """Create a private directory before any credential or canary is written."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
        return
    identity = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"], text=True,
        encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    try:
        rows = list(csv.reader(identity.stdout.splitlines()))
        sid = rows[0][1].strip() if identity.returncode == 0 and rows else ""
    except (csv.Error, IndexError):
        sid = ""
    if not re.fullmatch(r"S-\d+(?:-\d+)+", sid):
        raise HarnessError("could not resolve the current Windows user SID for private state")
    restricted = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
        text=True, encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    if restricted.returncode != 0:
        raise HarnessError("could not establish a user-only Windows DACL for private state")


def plugin_install_command(command_prefix: Sequence[str], plugin_package: Path) -> list[str]:
    return [*command_prefix, "plugins", "install", str(plugin_package)]


def gateway_call_command(
    command_prefix: Sequence[str], method: str, params: Mapping[str, Any], timeout_ms: int,
) -> list[str]:
    if not method.startswith("contextos."):
        raise HarnessError("live harness may call only contextos.* Gateway methods")
    return [
        *command_prefix, "gateway", "call", method,
        "--params", json.dumps(dict(params), separators=(",", ":"), sort_keys=True),
        "--timeout", str(timeout_ms), "--json",
    ]


def gateway_server_env(client_env: Mapping[str, str]) -> dict[str, str]:
    """Keep the client credential out of the Gateway and its model subprocesses."""
    server_env = dict(client_env)
    server_env.pop("OPENCLAW_GATEWAY_TOKEN", None)
    return server_env


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
    require_terminal_safe(proposal, "model-reported proposal path")
    return proposal, digest


def require_terminal_safe(value: str, subject: str, *, multiline: bool = False) -> None:
    """Reject terminal controls that could falsify the operator's trusted display."""
    for character in value:
        if multiline and character in {"\n", "\t"}:
            continue
        if character in {"\n", "\r", "\t"} or unicodedata.category(character) in {
            "Cc", "Cf", "Cs", "Zl", "Zp",
        }:
            raise HarnessError(f"{subject} contains a terminal-unsafe control character")


def load_trusted_proposal(repo: Path, proposal: str, reported_digest: str, phase: str) -> TrustedProposal:
    """Bind model-reported metadata to one independently verified proposal snapshot."""
    if phase not in PROPOSAL_PHASES:
        raise HarnessError(f"proposal review is unsupported for lifecycle phase {phase!r}")
    proposal_path = reject_linked_path(repo / proposal, f"{phase} proposal")
    if not _contains(repo, proposal_path):
        raise HarnessError(f"{phase} proposal is outside the repository")
    proposal_directory = reject_linked_path(repo / ".context-os" / "proposals", "proposal directory")
    if proposal_path.parent != proposal_directory or proposal_path.suffix != ".json":
        raise HarnessError(f"{phase} proposal is not a direct JSON child of .context-os/proposals")
    primitives = load_snapshot_primitives()
    try:
        raw, _ = primitives.read_regular_file_snapshot(proposal_path, subject=f"{phase} proposal")
    except OSError as exc:
        raise HarnessError(f"{phase} proposal is not one stable regular file: {exc}") from exc
    if len(raw) > MAX_PROPOSAL_BYTES:
        raise HarnessError(f"{phase} proposal exceeds the trusted review size limit")
    try:
        document = strict_proposal_json(raw.decode("utf-8"), source=str(proposal_path))
    except UnicodeDecodeError as exc:
        raise HarnessError(f"{phase} proposal is not strict UTF-8 JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise HarnessError(f"{phase} proposal must contain a JSON object")
    if document.get("workflow") != phase:
        raise HarnessError(
            f"{phase} proposal workflow mismatch: found {document.get('workflow')!r}"
        )
    stored_digest = document.get("proposal_digest")
    if stored_digest != reported_digest:
        raise HarnessError(f"{phase} proposal digest does not match the model-reported digest")
    unsigned = dict(document)
    unsigned.pop("proposal_digest", None)
    computed_digest = hashlib.sha256(primitives.canonical_json(unsigned).encode("utf-8")).hexdigest()
    if computed_digest != reported_digest:
        raise HarnessError(f"{phase} proposal digest does not match its canonical contents")
    changes = document.get("changes")
    if not isinstance(changes, list) or not changes:
        raise HarnessError(f"{phase} proposal has no reviewable changes")
    rendered: list[str] = []
    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            raise HarnessError(f"{phase} proposal changes[{index}] is not an object")
        relative = change.get("path")
        displayed_diff = change.get("diff")
        if not isinstance(relative, str) or not relative or not isinstance(displayed_diff, str) or not displayed_diff:
            raise HarnessError(f"{phase} proposal changes[{index}] has no stored path and diff")
        require_terminal_safe(relative, f"{phase} proposal changes[{index}] path")
        require_terminal_safe(displayed_diff, f"{phase} proposal changes[{index}] diff", multiline=True)
        framed_diff = "\n".join(f"| {line}" for line in displayed_diff.splitlines())
        rendered.append(
            f"--- trusted change {index + 1}: {json.dumps(relative, ensure_ascii=True)} ---\n"
            f"{framed_diff}"
        )
    return TrustedProposal(
        relative_path=proposal,
        path=proposal_path,
        phase=phase,
        digest=reported_digest,
        snapshot_sha256=hashlib.sha256(raw).hexdigest(),
        rendered_diffs="\n\n".join(rendered),
    )


def recheck_trusted_proposal(repo: Path, proposal: TrustedProposal) -> None:
    """Refuse approval-to-apply drift at the last harness-controlled boundary."""
    current = load_trusted_proposal(
        repo, proposal.relative_path, proposal.digest, proposal.phase
    )
    if current.path != proposal.path or current.snapshot_sha256 != proposal.snapshot_sha256:
        raise HarnessError(f"{proposal.phase} proposal changed after trusted review")


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
        if path.is_symlink() or (path.exists() and _is_link_or_reparse(path)):
            raise HarnessError(f"disposable repository contains linked content: {relative}")
        path_stat = path.stat()
        mode = stat.S_IMODE(path_stat.st_mode)
        metadata = (
            f"{mode:o}:{getattr(path_stat, 'st_uid', 0)}:{getattr(path_stat, 'st_gid', 0)}:"
            f"{getattr(path_stat, 'st_file_attributes', 0)}"
        )
        key = relative.as_posix()
        if stat.S_ISDIR(path_stat.st_mode):
            snapshot[f"{key}/"] = f"directory:{metadata}"
        elif stat.S_ISREG(path_stat.st_mode):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            snapshot[key] = f"file:{metadata}:{digest}"
        else:
            raise HarnessError(f"disposable repository contains unsupported filesystem entry: {relative}")
    return snapshot


def snapshot_changes(before: Mapping[str, str], after: Mapping[str, str]) -> list[str]:
    """Return stable relative paths added, removed, or changed between snapshots."""
    return sorted(
        relative for relative in set(before) | set(after)
        if before.get(relative) != after.get(relative)
    )


def require_proposal_only_mutation(before: Mapping[str, str], after: Mapping[str, str], phase: str) -> None:
    """Reject model writes outside local proposal/input staging during a proposal turn."""
    changed = snapshot_changes(before, after)
    allowed_trees = (".context-os/proposals/", ".context-os/inputs/")
    allowed_directories = {".context-os/", *allowed_trees}
    unexpected = sorted(
        relative for relative in changed
        if relative not in allowed_directories and not relative.startswith(allowed_trees)
    )
    if unexpected:
        raise HarnessError(
            f"{phase} lifecycle changed paths outside proposal staging: {', '.join(unexpected)}"
        )


def require_no_private_canary_in_changed_files(
    repo: Path, before: Mapping[str, str], after: Mapping[str, str], phase: str,
    canary_values: Sequence[str],
) -> None:
    """Reject private-memory canaries in every staging file changed by a model turn."""
    changed = snapshot_changes(before, after)
    canaries = tuple(value.encode("utf-8") for value in canary_values)
    for relative in sorted(changed):
        target = repo / relative
        if not target.is_file():
            continue
        raw = target.read_bytes()
        if any(canary in raw for canary in canaries):
            raise HarnessError(f"private OpenClaw memory canary surfaced in {phase} staging file")


def skill_inventory(stdout: str) -> dict[str, dict[str, Any]]:
    try:
        skills = json.loads(stdout)["skills"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise HarnessError("OpenClaw skill inventory was not valid JSON") from exc
    if not isinstance(skills, list):
        raise HarnessError("OpenClaw skill inventory has no skills list")
    return {str(skill["name"]): skill for skill in skills if isinstance(skill, dict) and "name" in skill}


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
            "OPENCLAW_GATEWAY_TOKEN": self.gateway_token,
            "PYTHONDONTWRITEBYTECODE": "1", "OPENCLAW_NO_RESPAWN": "1",
            "GIT_OPTIONAL_LOCKS": "0",
        })
        self.evidence = Evidence(expected_version=expected_version)
        self.gateway: subprocess.Popen[str] | None = None
        self.setup_continuity_challenge = ""
        self.private_memory_canaries = (
            f"CONTEXTOS_PRIVATE_USER_CANARY_{secrets.token_hex(16)}",
            f"CONTEXTOS_PRIVATE_MEMORY_CANARY_{secrets.token_hex(16)}",
        )

    def require_no_private_canary(self, value: str, subject: str) -> None:
        if any(canary in value for canary in self.private_memory_canaries):
            raise HarnessError(f"private OpenClaw memory canary surfaced in {subject}")

    def run_command(self, argv: Sequence[str], *, cwd: Path | None = None, timeout: float = 120) -> CommandResult:
        result = self.runner(argv, cwd or self.repo, self.env, timeout)
        shape = [Path(item).name if Path(item).is_absolute() else item for item in argv[:4]]
        self.evidence.commands.append({"command": shape, **output_summary(result)})
        return result

    def gateway_call(self, method: str, params: Mapping[str, Any], timeout_ms: int = 10_000) -> dict[str, Any]:
        command = gateway_call_command(
            self.command_prefix, method, params, timeout_ms,
        )
        return parse_gateway_result(self.run_command(command, cwd=self.workspace, timeout=timeout_ms / 1000 + 30), method)

    def lifecycle(self, action: str, *, show_output: bool = False) -> dict[str, str]:
        setup_before = repository_snapshot(self.repo) if action == "setup" else None
        setup_workspace_before = repository_snapshot(self.workspace) if action == "setup" else None
        started = self.gateway_call("contextos.run", {
            "alias": PROJECT_ALIAS, "action": action, "scenario": CONFORMANCE_SCENARIO,
        })
        if action == "setup":
            challenge = started.get("continuityChallenge")
            if not isinstance(challenge, str) or not re.fullmatch(
                r"contextos-continuity-[A-Za-z0-9-]+", challenge
            ):
                raise HarnessError("OpenClaw setup returned no bounded continuity challenge")
            self.setup_continuity_challenge = challenge
        text, session_key, ownership_token = self.completed_lifecycle_text(action, started)
        self.require_no_private_canary(text, f"{action} lifecycle output")
        if action == "setup":
            first = parse_lifecycle_result(text)
            if first.get("status") != "awaiting_input":
                raise HarnessError("OpenClaw setup did not pause for an owned continuation turn")
            first_turn_changes = snapshot_changes(setup_before or {}, repository_snapshot(self.repo))
            first_turn_workspace_changes = snapshot_changes(
                setup_workspace_before or {}, repository_snapshot(self.workspace)
            )
            if first_turn_changes or first_turn_workspace_changes:
                raise HarnessError(
                    "OpenClaw setup first turn persisted continuity outside its owned conversation"
                )
            self.evidence.controls["setup_first_turn_repository_read_only"] = True
            continued = self.gateway_call("contextos.continue", {
                "alias": PROJECT_ALIAS,
                "sessionKey": session_key,
                "scenario": CONFORMANCE_SCENARIO,
                "ownershipToken": ownership_token,
            })
            text, continued_session, continued_owner = self.completed_lifecycle_text(action, continued)
            self.require_no_private_canary(text, f"{action} continuation output")
            if continued_session != session_key or continued_owner != ownership_token:
                raise HarnessError("OpenClaw continuation changed the owned lifecycle authority")
            self.evidence.controls["owned_continuation_round_trip"] = True
        return parse_lifecycle_result(text)

    def completed_lifecycle_text(self, action: str, started: Mapping[str, Any]) -> tuple[str, str, str]:
        run_id = started.get("runId")
        session_key = started.get("sessionKey")
        ownership_token = started.get("ownershipToken")
        if (
            not isinstance(run_id, str)
            or not isinstance(session_key, str)
            or not isinstance(ownership_token, str)
            or not ownership_token.startswith("contextos-owner-")
        ):
            raise HarnessError(f"Context OS returned no owned identifiers for {action}")
        completed = self.gateway_call("contextos.wait", {
            "runId": run_id,
            "timeoutMs": 700_000,
            "ownershipToken": ownership_token,
        }, 710_000)
        if completed.get("status") != "ok":
            raise HarnessError(f"OpenClaw lifecycle {action} ended with status {completed.get('status')!r}")
        result = self.gateway_call("contextos.result", {
            "sessionKey": session_key,
            "ownershipToken": ownership_token,
        })
        text = result.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HarnessError(f"OpenClaw lifecycle {action} returned no assistant text")
        return text, session_key, ownership_token

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
            cwd=self.repo, env=gateway_server_env(self.env), text=True, encoding="utf-8", errors="replace",
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
        claude_backend = config["agents"]["defaults"]["cliBackends"]["claude-cli"]
        if claude_backend.get("args") != ["--safe-mode", "--verbose"]:
            raise HarnessError("Claude CLI live conformance must disable user hooks and customizations")
        self.evidence.controls["claude_safe_mode_configured"] = True
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
        self.evidence.controls["empty_skill_allowlist_hides_lifecycle"] = True
        config["agents"]["defaults"]["skills"] = list(LIFECYCLE_SKILLS)
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    def proposal_phase(self, phase: str) -> None:
        before_lifecycle = repository_snapshot(self.repo)
        proposal, digest = require_proposal(self.lifecycle(phase, show_output=True))
        after_lifecycle = repository_snapshot(self.repo)
        require_proposal_only_mutation(before_lifecycle, after_lifecycle, phase)
        require_no_private_canary_in_changed_files(
            self.repo, before_lifecycle, after_lifecycle, phase,
            self.private_memory_canaries,
        )
        trusted = load_trusted_proposal(self.repo, proposal, digest, phase)
        self.require_no_private_canary(trusted.rendered_diffs, f"{phase} trusted proposal")
        if phase == "setup":
            if (
                not self.setup_continuity_challenge
                or self.setup_continuity_challenge not in trusted.rendered_diffs
            ):
                raise HarnessError("setup proposal did not retain the first-turn continuity challenge")
            self.evidence.controls["owned_conversation_state_retained"] = True
        print(
            f"\n{phase} proposal: {proposal}\ndigest: {digest}\n"
            f"\n--- independently loaded proposal diffs ---\n{trusted.rendered_diffs}\n"
            "--- end independently loaded proposal diffs ---\n"
        )
        wrong = "0" * 64 if digest != "0" * 64 else "f" * 64
        before_control = repository_snapshot(self.repo)
        removed_apply = self.run_command(
            gateway_call_command(
                self.command_prefix, "contextos.apply",
                {"alias": PROJECT_ALIAS, "digest": digest}, 10_000,
            ),
            cwd=self.workspace,
        )
        removed_detail = f"{removed_apply.stdout}\n{removed_apply.stderr}".lower()
        if removed_apply.returncode == 0 or "unknown method" not in removed_detail:
            raise HarnessError("plugin unexpectedly exposes privileged contextos.apply execution")
        if repository_snapshot(self.repo) != before_control:
            raise HarnessError("removed plugin apply must-not-fire control changed the repository")
        self.evidence.controls["plugin_has_no_privileged_apply"] = True
        rejected = self.run_command([
            str(self.bash_path), "scripts/contextos.sh", "apply", proposal,
            "--confirm", wrong, "--runtime", "openclaw",
        ])
        if not is_wrong_digest_rejection(rejected) or repository_snapshot(self.repo) != before_control:
            raise HarnessError("wrong-digest must-not-fire control did not prove rejection")
        require_operator_digest(digest, phase, self.input_fn)
        recheck_trusted_proposal(self.repo, trusted)
        receipts = self.repo / ".context-os/receipts"
        before_receipts = set(receipts.glob("*.json")) if receipts.exists() else set()
        applied = self.run_command([
            str(self.bash_path), "scripts/contextos.sh", "apply", proposal,
            "--confirm", digest, "--runtime", "openclaw",
        ], timeout=710)
        if applied.returncode != 0:
            raise HarnessError(f"{phase} kernel apply failed after exact operator approval")
        after_receipts = set(receipts.glob("*.json")) if receipts.exists() else set()
        new_receipts = after_receipts - before_receipts
        if len(new_receipts) != 1:
            raise HarnessError(f"{phase} apply did not create exactly one kernel receipt")
        receipt = json.loads(next(iter(new_receipts)).read_text(encoding="utf-8"))
        if receipt.get("runtime") != "openclaw":
            raise HarnessError(f"{phase} receipt was not attributed to OpenClaw")
        self.evidence.lifecycle.append({
            "phase": phase, "digest": digest,
            "trusted_proposal_review": True, "kernel_wrong_digest_rejected": True,
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
        harden_private_directory(self.workspace)
        (self.workspace / "USER.md").write_text(
            f"Synthetic private user memory: {self.private_memory_canaries[0]}\n", encoding="utf-8"
        )
        (self.workspace / "MEMORY.md").write_text(
            f"Synthetic private durable memory: {self.private_memory_canaries[1]}\n", encoding="utf-8"
        )
        try:
            sync_report = load_sync_helper()(self.workspace)
        except (OSError, RuntimeError) as exc:
            raise HarnessError(f"lifecycle skill synchronization failed safely: {exc}") from exc
        if not isinstance(sync_report, dict) or sync_report.get("source_git_sha") != source_sha:
            raise HarnessError("skill synchronization provenance does not match the harness source commit")
        self.evidence.sync_report = redact(sync_report, (self.repo, self.workspace, self.state))
        config_path = write_openclaw_config(
            self.state, self.workspace, self.port, self.claude_binary, self.repo,
            self.gateway_token,
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
        start_changes = snapshot_changes(before_start, repository_snapshot(self.repo))
        if started.get("status") != "started" or start_changes:
            changed_detail = ", ".join(start_changes[:20]) or "none"
            raise HarnessError(
                f"start lifecycle did not complete read-only; changed paths: {changed_detail}"
            )
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
        plugin_report = self.evidence.diagnostics["plugins"].get("report", {})
        context_os = next(
            (
                plugin for plugin in plugin_report.get("plugins", [])
                if isinstance(plugin, dict) and plugin.get("id") == "context-os"
            ),
            None,
        )
        if not context_os or context_os.get("status") != "loaded" or context_os.get("hookCount") != 0:
            raise HarnessError("Context OS plugin was not loaded with the expected zero-hook boundary")
        memory_after = native_memory_snapshot(self.repo)
        self.evidence.controls.update({
            "repo_native_memory_absent": not any(memory_after.values()),
            "context_os_plugin_loaded": True,
            "context_os_hook_count_zero": True,
            "gateway_plugin_is_execution_surface": True,
            "private_memory_canaries_not_surfaced": True,
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
