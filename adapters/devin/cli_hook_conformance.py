"""Opt-in Devin CLI hook and skill-allowlist test on a clean source clone.

Runs ``devin -p`` against a disposable clone of the exact source commit in
Devin's default Normal mode. The clone carries the shipped
``.devin/config.json`` import guard and ``.devin/hooks.v1.json``. A local
probe hook in the ignored ``.devin/config.local.json`` logs only event names,
tool names, and write targets, so the controls can show that Devin loaded and
ran project hooks, rather than relying on the model to report it. Advisories
count only as system steps Devin injects, and a countercontrol with the shipped
hook file removed must inject neither. The probe also blocks one synthetic path
to show that a blocking pre-tool hook works.
Two synthetic user-only skills, one with ``allowed-tools`` and one without,
show that the allowlist auto-approves a shell command that Normal mode
otherwise rejects in print mode.

Shareable evidence records control results, booleans, versions, and hashes.
It never records credentials, raw model responses, or temporary paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import secrets
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from adapters.devin.cli_conformance import (  # noqa: E402
    REJECTED_BY_MODE, REPOSITORY_ROOT, DevinCliHarness, HarnessError, Trajectory,
    native_windows, platform_record, repository_source_sha, require_outside_source, write_text,
)

SHIPPED_HOOKS = REPOSITORY_ROOT / ".devin" / "hooks.v1.json"
WRITE_MATCHER = "^(edit|write|apply_patch|notebook_edit)$"
BLOCKED_TARGET = "hook-blocked.txt"
SESSION_NOTICE = "Context OS is not initialized"
WRITE_NOTICE = "Use the lifecycle proposal/apply kernel for current.md"
ALLOWED_SKILL = "contextos-devin-allowlist-control"
UNLISTED_SKILL = "contextos-devin-allowlist-negative"
MARKER_SCRIPT = "allowlist-marker.sh"
MARKER_FILE = ".context-os/allowlist-marker.txt"
PROBE_BLOCK_MESSAGE = "Context OS conformance probe blocked this write"

SESSION_PROMPT = "Do not read any file or run any command. Reply with only the word ready."
WRITE_PROMPT = ("Do not read any file or run any command. Call the write tool exactly once "
                "with file_path {path} and content: {value} Then reply with only the word done.")

PROBE_SOURCE = '''import json
import os
import sys
from pathlib import Path

log, blocked = Path(sys.argv[1]), sys.argv[2]
raw = sys.stdin.read()
try:
    payload = json.loads(raw) if raw.strip() else {}
except json.JSONDecodeError:
    payload = {}
if not isinstance(payload, dict):
    payload = {}
tool_input = payload.get("tool_input")
tool_input = tool_input if isinstance(tool_input, dict) else {}
target = str(tool_input.get("file_path") or tool_input.get("path") or "").replace("\\\\", "/")
entry = {
    "event": payload.get("hook_event_name"),
    "tool": payload.get("tool_name"),
    "target": target,
    "project_dir_set": bool(os.environ.get("DEVIN_PROJECT_DIR")),
    # Which shell ran the hook: Git Bash sets MSYSTEM, WSL sets WSL_DISTRO_NAME,
    # POSIX shells export SHELL; none of these hold user data.
    "shell": os.path.basename(os.environ.get("SHELL", "")),
    "msystem": os.environ.get("MSYSTEM", ""),
    "wsl": bool(os.environ.get("WSL_DISTRO_NAME")),
    # Whether the hook runs from the project root, so a relative command works.
    "cwd_is_project": bool(os.environ.get("DEVIN_PROJECT_DIR")) and os.path.normcase(
        os.path.realpath(os.getcwd())) == os.path.normcase(os.path.realpath(os.environ["DEVIN_PROJECT_DIR"])),
    "parent": "",
    # Whether the hook environment can find a Python for the kernel wrapper.
    "python_on_path": bool(__import__("shutil").which("python")),
    "python3_on_path": bool(__import__("shutil").which("python3")),
}
if os.name == "nt":
    import subprocess
    try:
        query = "(Get-CimInstance Win32_Process -Filter 'ProcessId=%d').Name" % os.getppid()
        entry["parent"] = subprocess.run(["powershell", "-NoProfile", "-Command", query], capture_output=True,
                                         text=True, timeout=8).stdout.strip()[:32]
    except Exception:
        entry["parent"] = "unknown"
with log.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(entry) + "\\n")
if entry["event"] == "PreToolUse" and target.endswith(blocked):
    print("Context OS conformance probe blocked this write", file=sys.stderr)
    sys.exit(2)
'''


def write_probe(base: Path) -> tuple[Path, str]:
    """Write the probe outside the workspace and return its log and command."""
    probe, log = base / "hook-probe.py", base / "hook-log.jsonl"
    write_text(probe, PROBE_SOURCE)
    parts = (sys.executable, str(probe), str(log), BLOCKED_TARGET)
    if native_windows():
        # Devin's Windows hook shell is undocumented, so use a form that bash,
        # PowerShell, and cmd all run: forward slashes and no quoting.
        parts = tuple(part.replace("\\", "/") for part in parts)
        if any(" " in part or "'" in part or '"' in part for part in parts):
            raise HarnessError("hook probe paths must not contain spaces or quotes on Windows")
        return log, " ".join(parts)
    command = " ".join(shlex.quote(part) for part in parts)
    return log, command


def hook_shells(entries: list[dict]) -> list[str]:
    """Summarize which shells ran the probe, without any payload content."""
    shells = set()
    for entry in entries:
        if entry.get("wsl"):
            shells.add("wsl")
        elif entry.get("msystem"):
            shells.add("git-bash:" + str(entry["msystem"])[:16])
        elif entry.get("shell"):
            shells.add("posix:" + str(entry["shell"])[:16])
        else:
            shells.add("no-posix-shell-markers")
        if entry.get("parent"):
            shells.add("parent:" + str(entry["parent"])[:32])
        if "python_on_path" in entry:
            shells.add("python:" + str(bool(entry["python_on_path"])).lower()
                       + ",python3:" + str(bool(entry["python3_on_path"])).lower())
        if "cwd_is_project" in entry:
            shells.add("cwd_is_project:" + str(bool(entry["cwd_is_project"])).lower())
    return sorted(shells)


def probe_hooks(command: str) -> dict[str, list[dict]]:
    entry = {"type": "command", "command": command, "timeout": 10}
    return {
        "SessionStart": [{"matcher": "", "hooks": [dict(entry)]}],
        "PreToolUse": [{"matcher": WRITE_MATCHER, "hooks": [dict(entry)]}],
        "PostToolUse": [{"matcher": WRITE_MATCHER, "hooks": [dict(entry)]}],
    }


def write_local_config(root: Path, permissions: Mapping[str, list[str]], hooks: Mapping[str, list]) -> None:
    """Probe hooks and per-control permissions live only in the ignored local config."""
    write_text(root / ".devin" / "config.local.json",
               json.dumps({"permissions": dict(permissions), "hooks": dict(hooks)}, indent=2) + "\n")


def read_hook_log(log: Path) -> list[dict]:
    if not log.exists():
        return []
    entries = []
    for line in log.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if not isinstance(entry, dict):
            raise HarnessError("hook probe log entry is not an object")
        entries.append(entry)
    return entries


def require_hook_event(entries: list[dict], event: str, *, tool: str | None = None,
                       target: str | None = None) -> None:
    for entry in entries:
        if entry.get("event") != event or not entry.get("project_dir_set"):
            continue
        if tool is not None and entry.get("tool") != tool:
            continue
        if target is not None and not str(entry.get("target", "")).endswith(target):
            continue
        return
    raise HarnessError(f"Devin did not run the project {event} hook for the controlled action")


def require_shipped_hooks(root: Path) -> None:
    for name in ("config.json", "hooks.v1.json"):
        if (root / ".devin" / name).read_bytes() != (REPOSITORY_ROOT / ".devin" / name).read_bytes():
            raise HarnessError(f"fixture does not carry the shipped .devin/{name}")


ALLOWLIST_BODY = (f"Run exactly this shell command once: bash {MARKER_SCRIPT}\n"
                  "Then reply with only the word done.\n")


def allowlist_skill(name: str, *, allowed: bool) -> str:
    allowed_tools = "allowed-tools:\n  - exec\n" if allowed else ""
    return (f"---\nname: {name}\n"
            "description: Synthetic Devin CLI skill allowlist control.\n"
            f"triggers: [\"user\"]\n{allowed_tools}---\n\n" + ALLOWLIST_BODY)


def write_lf(path: Path, text: str) -> None:
    """Write LF line endings on every platform so bash can run the fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def write_allowlist_fixture(root: Path, token: str) -> None:
    write_lf(root / MARKER_SCRIPT,
             "#!/usr/bin/env bash\nset -eu\n"
             f"mkdir -p \"$(dirname \"$0\")/.context-os\"\nprintf '%s\\n' {shlex.quote(token)} "
             f">> \"$(dirname \"$0\")/{MARKER_FILE}\"\n")
    for name, allowed in ((ALLOWED_SKILL, True), (UNLISTED_SKILL, False)):
        write_lf(root / ".agents" / "skills" / name / "SKILL.md", allowlist_skill(name, allowed=allowed))


def require_probe_blocked(trajectory: Trajectory) -> None:
    """Every write to the blocked target must carry the probe's exit-2 rejection."""
    calls = [call for call in trajectory.tool_calls()
             if call.name == "write" and BLOCKED_TARGET in json.dumps(call.arguments)]
    if not calls:
        raise HarnessError("blocking control did not attempt the controlled write")
    for call in calls:
        if len(call.observations) != 1 or PROBE_BLOCK_MESSAGE not in call.observations[0]:
            raise HarnessError("controlled write was not rejected by the probe hook")


def require_marker_exec(trajectory: Trajectory, subject: str) -> str:
    """The skill must expand and make exactly one shell call: its marker command."""
    if not any(ALLOWLIST_BODY.strip() in message for message in trajectory.user_messages()):
        raise HarnessError(f"{subject} did not expand")
    calls = [call for call in trajectory.tool_calls() if call.name == "exec"]
    if len(calls) != 1:
        raise HarnessError(f"{subject} must make exactly one shell call")
    call = calls[0]
    if call.arguments.get("command") != f"bash {MARKER_SCRIPT}" or len(call.observations) != 1:
        raise HarnessError(f"{subject} did not attempt exactly its marker command")
    return call.observations[0]


def require_allowlisted_exec(trajectory: Trajectory) -> None:
    """The allowed skill's marker command must run without a prompt and succeed."""
    if not require_marker_exec(trajectory, "allowed-tools skill").rstrip().endswith("Exit code: 0"):
        raise HarnessError("allowed-tools skill did not run exactly its marker command")


def require_unlisted_exec_rejected(trajectory: Trajectory) -> None:
    """The same command from the skill without allowed-tools must be rejected by Normal mode."""
    if REJECTED_BY_MODE not in require_marker_exec(trajectory, "unlisted skill"):
        raise HarnessError("unlisted skill's marker command was not rejected by Normal mode")


def injected_notice(trajectory: Trajectory, text: str, *, after_tool: str | None = None) -> bool:
    """True when Devin placed a system step containing text, after the tool's call if given."""
    start = 0
    if after_tool is not None:
        calls = [index for index, step in enumerate(trajectory.steps)
                 if any(isinstance(call, dict) and call.get("function_name") == after_tool
                        for call in step.get("tool_calls") or [])]
        if not calls:
            return False
        start = calls[0] + 1
    return any(step["source"] == "system" and text in step.get("message", "")
               for step in trajectory.steps[start:])


def execute(harness: DevinCliHarness) -> dict:
    source_sha = repository_source_sha()
    if source_sha != harness.evidence.source_sha:
        raise HarnessError("source revision mismatch")
    controls = harness.evidence.controls
    observations = harness.evidence.observations
    current = "preflight"
    try:
        with harness.isolated() as base:
            harness.preflight(base)
            root = base / "workspace"
            cloned = subprocess.run(["git", "clone", "-c", "core.autocrlf=false", "--local", "--no-hardlinks",
                                     "--quiet", str(REPOSITORY_ROOT), str(root)], capture_output=True, check=False)
            if cloned.returncode:
                raise HarnessError("cannot clone clean source fixture")
            subprocess.run(["git", "remote", "remove", "origin"], cwd=root, capture_output=True, check=True)
            require_shipped_hooks(root)
            log, command = write_probe(base)
            hooks = probe_hooks(command)
            controls[current] = "passed"

            current = "session_start_hooks_fire"
            write_local_config(root, {"deny": ["exec"]}, hooks)
            trajectory = harness.session(root, current, SESSION_PROMPT)
            entries = read_hook_log(log)
            harness.evidence.host_environment["hook_shells"] = ",".join(hook_shells(entries))
            # Recorded before gating so a Windows run shows whether hooks ran at all.
            observations["probe_session_start_hook_fired"] = any(
                entry.get("event") == "SessionStart" for entry in entries)
            observations["shipped_session_start_advisory_injected"] = injected_notice(trajectory, SESSION_NOTICE)
            require_hook_event(entries, "SessionStart")
            if not injected_notice(trajectory, SESSION_NOTICE):
                raise HarnessError("shipped SessionStart advisory did not reach the model")
            controls[current] = "passed"

            current = "write_hook_fires_on_lifecycle_state"
            log.unlink(missing_ok=True)
            write_local_config(root, {"allow": ["Write(state/**)"], "deny": ["exec"]}, hooks)
            trajectory = harness.session(root, current, WRITE_PROMPT.format(
                path="state/current.md", value=secrets.token_hex(8)))
            require_hook_event(read_hook_log(log), "PostToolUse", tool="write", target="state/current.md")
            if not injected_notice(trajectory, WRITE_NOTICE, after_tool="write"):
                raise HarnessError("shipped write advisory did not reach the model")
            controls[current] = "passed"

            current = "write_hook_silent_elsewhere"
            log.unlink(missing_ok=True)
            write_local_config(root, {"allow": ["Write(allowed/**)"], "deny": ["exec"]}, hooks)
            trajectory = harness.session(root, current, WRITE_PROMPT.format(
                path="allowed/probe.txt", value=secrets.token_hex(8)))
            require_hook_event(read_hook_log(log), "PostToolUse", tool="write", target="allowed/probe.txt")
            if injected_notice(trajectory, "proposal/apply kernel", after_tool="write"):
                raise HarnessError("write advisory fired for an unprotected path")
            controls[current] = "passed"

            current = "shipped_hooks_removed_injects_nothing"
            log.unlink(missing_ok=True)
            shipped, parked = root / ".devin" / "hooks.v1.json", base / "hooks.v1.json.parked"
            shipped.replace(parked)
            try:
                write_local_config(root, {"allow": ["Write(state/**)"], "deny": ["exec"]}, hooks)
                trajectory = harness.session(root, current, WRITE_PROMPT.format(
                    path="state/current.md", value=secrets.token_hex(8)))
            finally:
                parked.replace(shipped)
            require_shipped_hooks(root)
            require_hook_event(read_hook_log(log), "PostToolUse", tool="write", target="state/current.md")
            if (injected_notice(trajectory, SESSION_NOTICE)
                    or injected_notice(trajectory, "proposal/apply kernel")):
                raise HarnessError("advisory reached the model without the shipped hooks")
            controls[current] = "passed"

            current = "blocking_pre_tool_hook_blocks_write"
            log.unlink(missing_ok=True)
            write_local_config(root, {"allow": ["Write(**)"], "deny": ["exec"]}, hooks)
            trajectory = harness.session(root, current, WRITE_PROMPT.format(
                path=BLOCKED_TARGET, value=secrets.token_hex(8)))
            require_hook_event(read_hook_log(log), "PreToolUse", tool="write", target=BLOCKED_TARGET)
            require_probe_blocked(trajectory)
            if (root / BLOCKED_TARGET).exists():
                raise HarnessError("blocking pre-tool hook did not stop the write")
            controls[current] = "passed"

            token = secrets.token_hex(12)
            write_allowlist_fixture(root, token)
            marker = root / MARKER_FILE

            current = "skill_without_allowlist_rejects_exec"
            write_local_config(root, {}, hooks)
            trajectory = harness.session(root, current, f"/{UNLISTED_SKILL}")
            require_unlisted_exec_rejected(trajectory)
            if marker.exists():
                raise HarnessError("unlisted skill ran its shell command without approval")
            controls[current] = "passed"

            current = "skill_allowed_tools_auto_approves_exec"
            trajectory = harness.session(root, current, f"/{ALLOWED_SKILL}")
            require_allowlisted_exec(trajectory)
            if not marker.is_file() or marker.read_text(encoding="utf-8").splitlines() != [token]:
                raise HarnessError("allowed-tools skill did not run its shell command exactly once")
            controls[current] = "passed"

            observations["hook_events_seen"] = bool(read_hook_log(log))
            harness.evidence.host_environment["hook_shells"] = ",".join(hook_shells(read_hook_log(log)))
            harness.verify_binary()
            if repository_source_sha() != harness.evidence.source_sha:
                raise HarnessError("source changed during the live run")
            controls["run"] = "passed"
    except Exception as exc:
        controls[current] = "failed"
        controls["run"] = "failed"
        print(f"Devin CLI hook conformance failed at {current}: {exc}", flush=True)
        harness.evidence.sessions.setdefault("failure", {})["type"] = type(exc).__name__
    return controls


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("binary", "expected-version", "source-sha", "data-home", "evidence"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--model")
    parser.add_argument("--debug-dir", help="local directory for raw ATIF exports; never share")
    parser.add_argument("--allow-model-traffic", action="store_true")
    parser.add_argument("--windows-real-profile", action="store_true",
                        help="native Windows only: accept that user-level skills are visible")
    args = parser.parse_args()
    if not args.allow_model_traffic:
        parser.error("requires --allow-model-traffic for disposable synthetic model calls")
    evidence = require_outside_source(Path(args.evidence))
    if evidence.exists():
        parser.error("evidence path must not exist")
    harness = DevinCliHarness(Path(args.binary), args.expected_version, args.source_sha,
                              Path(args.data_home), model=args.model,
                              debug_dir=Path(args.debug_dir) if args.debug_dir else None,
                              windows_real_profile=args.windows_real_profile)
    started = datetime.now(timezone.utc).isoformat()
    controls = execute(harness)
    record = {
        "runtime": "devin", "surface": "cli", "harness": "hooks-and-skill-allowlists",
        "os": platform.platform(), "platform": platform_record(), "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "model_selection": args.model or "Devin CLI default",
        "permission_mode": "Normal (default)",
        "shipped_hooks_sha256": hashlib.sha256(SHIPPED_HOOKS.read_bytes()).hexdigest(),
        "host": vars(harness.evidence),
        "limits": [
            "Synthetic fixture only; scoped to the recorded client, model, and operating system.",
            "Shipped hooks are advisory; the blocking control uses a synthetic local probe.",
            "No MCP execution, cloud handoff, or native-memory claim.",
            "On native Windows the shipped hooks run `bash`; host_environment records which shell ran them.",
        ],
    }
    with evidence.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    return 0 if controls.get("run") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
