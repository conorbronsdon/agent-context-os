"""Opt-in Devin CLI hook and skill-allowlist test on a clean source clone.

Runs ``devin -p`` against a disposable clone of the exact source commit in
Devin's default Normal mode. The clone carries the shipped
``.devin/config.json`` import guard and ``.devin/hooks.v1.json``. A local
probe hook in the ignored ``.devin/config.local.json`` logs only event names,
tool names, and write targets, so the controls can show that Devin loaded and
ran project hooks, rather than relying on the model to report it. The probe
also blocks one synthetic path to show that a blocking pre-tool hook works.
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
    repository_source_sha, require_outside_source, require_rejected_attempt, write_text,
)

SHIPPED_HOOKS = REPOSITORY_ROOT / ".devin" / "hooks.v1.json"
WRITE_MATCHER = "^(edit|write|apply_patch|notebook_edit)$"
BLOCKED_TARGET = "hook-blocked.txt"
SESSION_NOTICE = "Context OS is not initialized"
PRE_WRITE_NOTICE = "proposal/apply kernel"
ALLOWED_SKILL = "contextos-devin-allowlist-control"
UNLISTED_SKILL = "contextos-devin-allowlist-negative"
MARKER_SCRIPT = "allowlist-marker.sh"
MARKER_FILE = ".context-os/allowlist-marker.txt"

QUOTE_NOTICE = ("Then, if your context contains any notice that mentions Context OS, reply "
                "with its text exactly; otherwise reply NONE.")
SESSION_PROMPT = "Do not read any file or run any command. " + QUOTE_NOTICE
WRITE_PROMPT = ("Do not read any file or run any command. Call the write tool exactly once "
                "with file_path {path} and content: {value} " + QUOTE_NOTICE)

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
}
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
    command = " ".join(shlex.quote(part) for part in (sys.executable, str(probe), str(log), BLOCKED_TARGET))
    return log, command


def probe_hooks(command: str) -> dict[str, list[dict]]:
    entry = {"type": "command", "command": command, "timeout": 10}
    return {
        "SessionStart": [{"matcher": "", "hooks": [dict(entry)]}],
        "PreToolUse": [{"matcher": WRITE_MATCHER, "hooks": [dict(entry)]}],
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


def allowlist_skill(name: str, *, allowed: bool) -> str:
    allowed_tools = "allowed-tools:\n  - exec\n" if allowed else ""
    return (f"---\nname: {name}\n"
            "description: Synthetic Devin CLI skill allowlist control.\n"
            f"triggers: [\"user\"]\n{allowed_tools}---\n\n"
            f"Run exactly this shell command once: bash {MARKER_SCRIPT}\n"
            "Then reply with only the word done.\n")


def write_allowlist_fixture(root: Path, token: str) -> None:
    write_text(root / MARKER_SCRIPT,
               "#!/usr/bin/env bash\nset -eu\n"
               f"mkdir -p \"$(dirname \"$0\")/.context-os\"\nprintf '%s\\n' {shlex.quote(token)} "
               f">> \"$(dirname \"$0\")/{MARKER_FILE}\"\n")
    for name, allowed in ((ALLOWED_SKILL, True), (UNLISTED_SKILL, False)):
        write_text(root / ".agents" / "skills" / name / "SKILL.md", allowlist_skill(name, allowed=allowed))


def mentions(trajectory: Trajectory, text: str) -> bool:
    return text in trajectory.final_message()


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
            cloned = subprocess.run(["git", "clone", "--local", "--no-hardlinks", "--quiet",
                                     str(REPOSITORY_ROOT), str(root)], capture_output=True, check=False)
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
            require_hook_event(read_hook_log(log), "SessionStart")
            if not mentions(trajectory, SESSION_NOTICE):
                raise HarnessError("shipped SessionStart advisory did not reach the model")
            controls[current] = "passed"

            current = "pre_write_hook_fires_on_lifecycle_state"
            log.unlink(missing_ok=True)
            write_local_config(root, {"allow": ["Write(state/**)"], "deny": ["exec"]}, hooks)
            trajectory = harness.session(root, current, WRITE_PROMPT.format(
                path="state/current.md", value=secrets.token_hex(8)))
            require_hook_event(read_hook_log(log), "PreToolUse", tool="write", target="state/current.md")
            if not mentions(trajectory, PRE_WRITE_NOTICE):
                raise HarnessError("shipped pre-write advisory did not reach the model")
            controls[current] = "passed"

            current = "pre_write_hook_silent_elsewhere"
            log.unlink(missing_ok=True)
            write_local_config(root, {"allow": ["Write(allowed/**)"], "deny": ["exec"]}, hooks)
            trajectory = harness.session(root, current, WRITE_PROMPT.format(
                path="allowed/probe.txt", value=secrets.token_hex(8)))
            require_hook_event(read_hook_log(log), "PreToolUse", tool="write", target="allowed/probe.txt")
            if mentions(trajectory, PRE_WRITE_NOTICE):
                raise HarnessError("pre-write advisory fired for an unprotected path")
            controls[current] = "passed"

            current = "blocking_pre_tool_hook_blocks_write"
            log.unlink(missing_ok=True)
            write_local_config(root, {"allow": ["Write(**)"], "deny": ["exec"]}, hooks)
            trajectory = harness.session(root, current, WRITE_PROMPT.format(
                path=BLOCKED_TARGET, value=secrets.token_hex(8)))
            require_hook_event(read_hook_log(log), "PreToolUse", tool="write", target=BLOCKED_TARGET)
            if not any(call.name == "write" and BLOCKED_TARGET in json.dumps(call.arguments)
                       for call in trajectory.tool_calls()):
                raise HarnessError("blocking control did not attempt the controlled write")
            if (root / BLOCKED_TARGET).exists():
                raise HarnessError("blocking pre-tool hook did not stop the write")
            controls[current] = "passed"

            token = secrets.token_hex(12)
            write_allowlist_fixture(root, token)
            marker = root / MARKER_FILE

            current = "skill_without_allowlist_rejects_exec"
            write_local_config(root, {}, hooks)
            trajectory = harness.session(root, current, f"/{UNLISTED_SKILL}")
            require_rejected_attempt(trajectory, "exec", REJECTED_BY_MODE, current, argument=MARKER_SCRIPT)
            if marker.exists():
                raise HarnessError("unlisted skill ran its shell command without approval")
            controls[current] = "passed"

            current = "skill_allowed_tools_auto_approves_exec"
            harness.session(root, current, f"/{ALLOWED_SKILL}")
            if not marker.is_file() or marker.read_text(encoding="utf-8").splitlines() != [token]:
                raise HarnessError("allowed-tools skill did not run its shell command exactly once")
            controls[current] = "passed"

            observations["hook_events_seen"] = bool(read_hook_log(log))
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
    args = parser.parse_args()
    if not args.allow_model_traffic:
        parser.error("requires --allow-model-traffic for disposable synthetic model calls")
    evidence = require_outside_source(Path(args.evidence))
    if evidence.exists():
        parser.error("evidence path must not exist")
    harness = DevinCliHarness(Path(args.binary), args.expected_version, args.source_sha,
                              Path(args.data_home), model=args.model,
                              debug_dir=Path(args.debug_dir) if args.debug_dir else None)
    started = datetime.now(timezone.utc).isoformat()
    controls = execute(harness)
    record = {
        "runtime": "devin", "surface": "cli", "harness": "hooks-and-skill-allowlists",
        "os": platform.platform(), "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "model_selection": args.model or "Devin CLI default",
        "permission_mode": "Normal (default)",
        "shipped_hooks_sha256": hashlib.sha256(SHIPPED_HOOKS.read_bytes()).hexdigest(),
        "host": vars(harness.evidence),
        "limits": [
            "Synthetic fixture only; scoped to the recorded client, model, and operating system.",
            "Shipped hooks are advisory; the blocking control uses a synthetic local probe.",
            "No MCP execution, cloud handoff, native-memory, or native Windows claim.",
        ],
    }
    with evidence.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    return 0 if controls.get("run") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
