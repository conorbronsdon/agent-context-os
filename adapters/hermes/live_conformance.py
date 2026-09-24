#!/usr/bin/env python3
"""Operator-driven, disposable Hermes lifecycle conformance. No approval is automated."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import platform
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from contextos.primitives import canonical_json, is_link_like, read_regular_file_snapshot
from contextos.workspace_schema import strict_json_loads


SKILLS = ("setup", "context-setup", "start", "context-start", "update", "context-update", "end", "context-end")
PHASES = ("setup", "start", "update", "end")
MARKER = ".context-os-live-disposable"
SECRET = re.compile(r"(?i)((?:api[_-]?key|token|password|secret|credential)\s*[:=]\s*)[^\s,;]+")
ENV_ASSIGN = re.compile(r"(?m)(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*=)[^\s,;]+")
BEARER = re.compile(r"(?i)(?:Bearer\s+[^\s,;]+|\b(?:sk|or)-[A-Za-z0-9._-]+)")
LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_=-]{32,}(?![A-Za-z0-9+/=_-])")
PATH = re.compile(r"(?<![A-Za-z0-9.])(?:[A-Za-z]:[\\/]|/)[^\s\"']+")
SELF_READ = re.compile(
    r"(?i)(?:\bAGENTS\.md\b|\bAGENTS?[?*][\w.?*]*|\bAGENTS\.\?d\b|"
    r"\.agents[/\\]skills[/\\][^\s\"']*(?:SKILL\.md\b|\*)|\.context-os-live-manifest(?:\.json)?\b|"
    r"(?<![/\\\w])\*\.md\b|git\s+(?:diff|show|log\s+-p)\b)"
)
READ_TOOLS = {"read_file", "search_files", "terminal", "execute_code", "delegate_task"}
SLASH_COMMANDS = {f"/context-{phase}" for phase in PHASES}


class HarnessError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def route_id(value: str, field: str) -> str:
    """Record an operator-chosen model or provider verbatim; evidence must name it exactly."""
    segments = re.split(r"[/:]", value)
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", value)
            or SECRET.search(value) or BEARER.search(value) or ENV_ASSIGN.search(value)
            or any(LONG_TOKEN.fullmatch(segment) for segment in segments)):
        raise HarnessError(f"{field} must be a plain route identifier")
    return value


def clean(text: str, known: Sequence[str] = ()) -> str:
    redacted = ENV_ASSIGN.sub("[REDACTED ENV]", BEARER.sub("[REDACTED]", SECRET.sub(r"\1[REDACTED]", text)))
    redacted = LONG_TOKEN.sub(lambda match: match.group() if match.group() in known or
                              re.match(r"\.[A-Za-z0-9]{1,8}\b", redacted[match.end():]) or
                              match.group().startswith(("agents/", "docs/", "adapters/", "contextos/",
                                                        "state/", "sessions/", "identity/", "projects/",
                                                        "scripts/", "tests/", "runtimes/", "components/"))
                              else "[REDACTED]", redacted)
    return PATH.sub(lambda match: match.group() if match.group() in SLASH_COMMANDS else "[PATH]", redacted)[:20000]


def command(argv: Sequence[str], cwd: Path, env: dict[str, str] | None = None,
            timeout: int = 120, raw_output: bool = False) -> dict:
    started = time.monotonic()
    try:
        result = subprocess.run(list(argv), cwd=cwd, env=env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        code, stdout, stderr = 124, str(exc.stdout or b""), "timed out"
    result = {"argv": [clean(item) for item in argv], "exit_code": code,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout": clean(stdout), "stderr": clean(stderr), "at": now()}
    if raw_output:
        result["_raw_stdout"] = stdout
    return result


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    if result.returncode:
        raise HarnessError(f"git {' '.join(args)} failed: {clean(result.stderr)}")
    if args[:1] == ("status",) and result.stderr.strip():
        raise HarnessError("git status reported unreadable paths")
    return result.stdout.strip()


def outside_checkouts(path: Path, source: Path) -> None:
    raw = path.absolute()
    for component in (raw, *raw.parents):
        if is_link_like(component):
            raise HarnessError("fixture path contains a link")
    target = raw.resolve(strict=False)
    if target == source or source in target.parents or target in source.parents:
        raise HarnessError("fixture and source must be separate, non-nested directories")
    for parent in (target, *target.parents):
        if (parent / ".git").exists() or ((parent / "AGENTS.md").exists() and (parent / "contextos").exists()):
            raise HarnessError("fixture path is inside an existing checkout")


def prompt_for(phase: str) -> str:
    if phase == "setup":
        prompt = "/context-setup Create a kernel proposal for a synthetic fixture identity. Stop after creating the proposal."
    if phase == "start":
        prompt = "/context-start"
    if phase in ("update", "end"):
        prompt = f"/context-{phase} Hermes fixture {phase} checkpoint. Stop after creating the kernel proposal."
    return prompt + " Also report any line that begins 'Hermes fixture canary:' from the repository instructions and the skill instructions you loaded."


def stream_evidence(output: str, known: Sequence[str] | dict[str, str],
                    phase: str | None = None) -> tuple[list[dict], str, list[str], bool]:
    markers = tuple(known.values()) if isinstance(known, dict) else tuple(known)
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for child in value.values():
                yield from strings(child)
        elif isinstance(value, list):
            for child in value:
                yield from strings(child)

    def redact(value):
        if isinstance(value, str):
            return clean(value, markers)
        if isinstance(value, dict):
            return {key: redact(child) for key, child in value.items()}
        if isinstance(value, list):
            return [redact(child) for child in value]
        return value

    events, assistant, final, skills = [], [], [], []
    self_read = False
    requested_skill = None
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HarnessError("Hermes stream contains invalid JSON") from exc
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise HarnessError("Hermes stream contains an invalid event")
        kind = event["type"]
        if kind == "tool_use":
            name = event.get("name")
            detail = event.get("input", {})
            requested_skill = None
            if name == "skill_view" and isinstance(detail, dict) and isinstance(detail.get("name"), str):
                requested_skill = (detail["name"], event.get("id"))
                skills.append(clean(requested_skill[0], markers))
            if name != "write_file" and (name in READ_TOOLS or (isinstance(detail, dict) and
                                      any(key in detail for key in ("path", "command", "pattern", "code")))):
                detail_text = " ".join(strings(detail))
                if (SELF_READ.search(detail_text) or
                        (re.search(r"(?i)\b(?:grep|rg|findstr|Select-String)\b", detail_text)
                         and re.search(r"(?i)Hermes fixture canary:", detail_text))):
                    self_read = True
        if kind == "tool_result":
            found = {marker for value in strings(event) for marker in markers if marker in value}
            allowed = set()
            if (event.get("name") == "skill_view" and requested_skill
                    and requested_skill[0] in (phase, f"context-{phase}")
                    and event.get("id") == requested_skill[1] and isinstance(known, dict)):
                allowed = {known[requested_skill[0]]}
            if found - allowed:
                self_read = True
            requested_skill = None
        if kind in ("assistant", "assistant_message") or (kind == "message" and event.get("role") == "assistant"):
            content = event.get("content", event.get("text", ""))
            if isinstance(content, str):
                assistant.append(content + "\n")
        elif kind == "text" and isinstance(event.get("text"), str):
            # Streaming deltas can split a token mid-word, so join them without separators.
            assistant.append(event["text"])
        elif kind == "result" and isinstance(event.get("text"), str):
            final.append(event["text"])
        if kind == "text":
            # Deltas can split a secret, so record them only after joining (below).
            continue
        recorded = dict(event)
        if kind == "tool_result":
            for field in ("content", "output", "result", "text"):
                if field in recorded:
                    recorded[field] = "[REDACTED TOOL RESULT]"
        events.append(redact(recorded))
    deltas = "".join(assistant)
    if deltas:
        events.append({"type": "text", "text": clean(deltas, markers), "joined_deltas": True})
    if not events:
        raise HarnessError("Hermes stream contains no events")
    return events, ("".join(assistant) + "\n" + "\n".join(final)).strip(), skills, self_read


def operator_approval(phase: str, path: Path, proposal: dict, digest: str,
                      input_fn, approval_dir: Path | None, timeout: float = 900) -> None:
    review = f"Proposal: {path}\nDigest: {digest}\n" + "".join(
        f"\n{change['path']}\n{change['diff']}\n" for change in proposal["changes"])
    if approval_dir is None:
        print(review)
        if input_fn(f"Type the exact {phase} digest {digest} to approve: ").strip() != digest:
            raise HarnessError("operator did not type the exact proposal digest")
        return
    if not approval_dir.is_dir():
        raise HarnessError("approval directory must exist")
    review_path, approve_path = approval_dir / f"{phase}.review.txt", approval_dir / f"{phase}.approve"
    if approve_path.exists():
        raise HarnessError("approval file existed before review")
    with review_path.open("x", encoding="utf-8") as stream:
        stream.write(review)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if approve_path.exists():
            if approve_path.read_text(encoding="utf-8") != digest:
                raise HarnessError("approval file did not contain the exact proposal digest")
            return
        time.sleep(1)
    raise HarnessError("operator approval timed out")


def prepare(source: Path, fixture: Path, home: Path, expected_commit: str,
            manifest_path: Path | None = None) -> dict:
    source = source.resolve(strict=True)
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise HarnessError("expected commit must be a full lowercase SHA")
    if git(source, "rev-parse", "HEAD") != expected_commit or git(source, "status", "--porcelain", "--untracked-files=all"):
        raise HarnessError("source must be clean at the exact expected HEAD")
    if fixture.exists() or home.exists():
        raise HarnessError("fixture and HERMES_HOME must not exist")
    outside_checkouts(fixture, source)
    outside_checkouts(home, source)
    manifest_raw = (manifest_path or fixture.parent / (fixture.name + "-manifest.json")).absolute()
    if manifest_raw == fixture or fixture in manifest_raw.parents:
        raise HarnessError("manifest must be new and outside fixture and HERMES_HOME")
    manifest_path = manifest_raw.resolve(strict=False)
    if manifest_path.exists() or manifest_path == fixture or fixture in manifest_path.parents or home in manifest_path.parents:
        raise HarnessError("manifest must be new and outside fixture and HERMES_HOME")
    outside_checkouts(manifest_path, source)
    if fixture.resolve(strict=False) in home.resolve(strict=False).parents or home.resolve(strict=False) in fixture.resolve(strict=False).parents:
        raise HarnessError("fixture and HERMES_HOME must be separate")
    fixture.parent.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, mode=0o700 if os.name != "nt" else 0o777)
    memories = home / "memories"
    memories.mkdir()
    memory_canaries = {}
    for name in ("MEMORY.md", "USER.md"):
        memory_canaries[name] = secrets.token_hex(16)
        (memories / name).write_text(f"# Synthetic Hermes fixture memory\nFixture native memory canary: {memory_canaries[name]}\n", encoding="utf-8")
    cloned = command(["git", "clone", "--local", "--no-hardlinks", "--quiet", str(source), str(fixture)], source)
    if cloned["exit_code"] or git(fixture, "rev-parse", "HEAD") != expected_commit:
        raise HarnessError("could not clone the exact clean source commit")
    (fixture / MARKER).write_text("disposable\n", encoding="utf-8")
    (fixture / "unrelated-sentinel.txt").write_bytes(secrets.token_bytes(64))
    canaries = {"agents": secrets.token_hex(16)}
    agents = fixture / "AGENTS.md"
    agents.write_bytes(agents.read_bytes() + f"\nHermes fixture canary: {canaries['agents']}\n".encode())
    skill_digests = {}
    for name in SKILLS:
        path = fixture / ".agents" / "skills" / name / "SKILL.md"
        skill_digests[name] = sha(path)
        canaries[name] = secrets.token_hex(16)
        path.write_bytes(path.read_bytes() + f"\nHermes fixture canary: {canaries[name]}\n".encode())
    git(fixture, "-c", "core.autocrlf=false", "add", "--", "AGENTS.md", *(f".agents/skills/{name}/SKILL.md" for name in SKILLS))
    git(fixture, "-c", "user.name=Context OS Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-m", "Add synthetic Hermes discovery canaries")
    fixture_commit = git(fixture, "rev-parse", "HEAD")
    manifest = {"source_sha": expected_commit, "fixture_commit": fixture_commit,
                "prepared_at": now(), "skill_source_sha256": skill_digests, "canaries": canaries,
                "native_memory_canaries": memory_canaries,
                "sentinel_sha256": sha(fixture / "unrelated-sentinel.txt"),
                "prompts": {phase: prompt_for(phase) for phase in PHASES},
                "commands": ["hermes skills trust <fixture>", "hermes skills list --source local",
                             "python adapters/hermes/live_conformance.py record --fixture <fixture> --home <home> --manifest <manifest> --evidence <new-json> --binary <hermes> --model <model> --provider <provider> --expected-version 'Hermes Agent v0.21.4' --run-budget 120 --max-turns 20"],
                "steps": ["Set HERMES_HOME to the fresh home path printed by prepare.",
                          "Supply provider credentials through environment variables; do not copy credentials into the fixture.",
                          "Run hermes skills trust <fixture> yourself, then verify hermes skills list --source local.",
                          "Run record with --binary, --model, --provider, --run-budget, --max-turns and --evidence.",
                          "For each proposal, inspect the printed diff and type its exact digest."]}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"fixture": str(fixture), "hermes_home": str(home), "manifest_path": str(manifest_path), "manifest": manifest}


def tracked_state(fixture: Path, include_kernel: bool = True) -> tuple[str, dict[str, str]]:
    status = git(fixture, "status", "--porcelain=v1", "--untracked-files=all")
    files = {p.relative_to(fixture).as_posix(): sha(p) for p in fixture.rglob("*")
             if p.is_file() and ".git" not in p.relative_to(fixture).parts
             and (include_kernel or ".context-os" not in p.relative_to(fixture).parts)}
    return status, files


def check_memory(fixture: Path, home: Path, canaries: dict[str, str]) -> None:
    for name in ("MEMORY.md", "USER.md"):
        if any(p.name == name for p in fixture.rglob(name) if ".git" not in p.parts):
            raise HarnessError(f"fixture contains Hermes native {name}")
    state = {name: digest for name, digest in tracked_state(fixture)[1].items()
             if name not in {MARKER, "unrelated-sentinel.txt"}}
    for marker in canaries.values():
        if any(mirrors_memory((fixture / rel).read_text(encoding="utf-8", errors="replace"), (marker,))
               for rel in state):
            raise HarnessError("Hermes native memory canary appeared in fixture state")
    for name in ("MEMORY.md", "USER.md"):
        for memory in home.rglob(name):
            content = memory.read_bytes()
            if content and any(content in p.read_bytes() for rel in state for p in [fixture / rel]):
                raise HarnessError("host memory appeared in fixture state")


def native_memory_state(home: Path) -> dict[str, str]:
    memories = home / "memories"
    return {p.relative_to(memories).as_posix():
            "link" if is_link_like(p) else "directory" if p.is_dir() else sha(p)
            for p in memories.rglob("*")}


def native_memory_contents(home: Path) -> dict[str, str]:
    memories = home / "memories"
    return {p.relative_to(memories).as_posix(): p.read_bytes()[:10000].decode("utf-8", errors="replace")
            for p in memories.rglob("*") if p.is_file() and not is_link_like(p)}


def check_native_memory(home: Path, before: dict[str, str], contents: dict[str, str],
                        result: dict, canaries: Sequence[str]) -> None:
    after = native_memory_state(home)
    if after == before:
        return
    after_contents = native_memory_contents(home)
    result["native_memory_changes"] = []
    for name in sorted(set(before) | set(after)):
        if before.get(name) == after.get(name):
            continue
        diff = "".join(difflib.unified_diff(
            contents.get(name, "").splitlines(keepends=True),
            after_contents.get(name, "").splitlines(keepends=True),
            fromfile=f"before/{name}", tofile=f"after/{name}"))
        result["native_memory_changes"].append({"path": clean(name), "diff": clean(diff, canaries)[:2000]})
    raise HarnessError("Hermes native memory changed")


def mirrors_memory(text: str, canaries: Sequence[str]) -> bool:
    normalized = re.sub(r"[^0-9a-f]", "", text.lower())
    return any(marker.lower() in normalized for marker in canaries)


def hermes_environment(home: Path, provider: str, allow: Sequence[str] = ()) -> dict[str, str]:
    base = {"PATH", "SYSTEMROOT", "HOME", "USERPROFILE", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA",
            "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR",
            "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"}
    names = base | {name.upper() for name in allow}
    if provider.lower() == "openrouter":
        names.add("OPENROUTER_API_KEY")
    env = {name: value for name, value in os.environ.items()
           if (name.upper() in names or name.upper().startswith("HERMES_"))
           and (not name.upper().endswith("_API_KEY") or name.upper() in names)}
    env["HERMES_HOME"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("HERMES_ACCEPT_HOOKS", None)
    return env


def new_proposal(fixture: Path, before: set[Path], phase: str) -> tuple[Path, dict]:
    folder = fixture / ".context-os" / "proposals"
    if is_link_like(folder) or is_link_like(folder.parent):
        raise HarnessError("proposal store contains a link")
    added = set(folder.glob("*.json")) - before
    if len(added) != 1:
        raise HarnessError(f"{phase} did not create exactly one kernel proposal")
    path = added.pop()
    raw, _ = read_regular_file_snapshot(path, subject="Hermes proposal")
    if len(raw) > 2_000_000:
        raise HarnessError("proposal is too large")
    document = strict_json_loads(raw.decode("utf-8"), source=str(path))
    digest = document.get("proposal_digest")
    unsigned = dict(document)
    unsigned.pop("proposal_digest", None)
    if document.get("workflow") != phase or not re.fullmatch(r"[0-9a-f]{64}", str(digest)) or hashlib.sha256(canonical_json(unsigned).encode()).hexdigest() != digest:
        raise HarnessError("proposal workflow or canonical digest is invalid")
    if not document.get("changes") or any(not isinstance(c, dict) or not c.get("path") or not c.get("diff") for c in document["changes"]):
        raise HarnessError("proposal has no reviewable changes")
    for change in document["changes"]:
        if any(ord(char) < 32 and char not in "\n\t" for char in change["diff"] + change["path"]):
            raise HarnessError("proposal diff contains unsafe terminal controls")
    return path, document


def record(fixture: Path, home: Path, evidence: Path, binary: Sequence[str], model: str,
           provider: str, run_budget: int, max_turns: int, input_fn=input,
           expected_version: str = "", approval_dir: Path | None = None,
           approval_timeout: float = 900, manifest_path: Path | None = None,
           env_allow: Sequence[str] = ()) -> dict:
    fixture, home, evidence = fixture.resolve(), home.resolve(), evidence.resolve(strict=False)
    if not home.is_dir() or fixture in home.parents or home in fixture.parents:
        raise HarnessError("HERMES_HOME must be a separate existing directory")
    outside_checkouts(home, fixture)
    if evidence.exists() or fixture in evidence.parents or home in evidence.parents:
        raise HarnessError("evidence must be new and outside fixture and HERMES_HOME")
    outside_checkouts(evidence, fixture)
    if approval_dir is not None:
        approval_dir = approval_dir.resolve(strict=False)
        outside_checkouts(approval_dir, fixture)
        if approval_dir == home or home in approval_dir.parents or approval_dir in home.parents:
            raise HarnessError("approval directory must be separate from HERMES_HOME")

    manifest_raw = (manifest_path or fixture.parent / (fixture.name + "-manifest.json")).absolute()
    if manifest_raw == fixture or fixture in manifest_raw.parents:
        raise HarnessError("manifest must be outside fixture and HERMES_HOME")
    manifest_path = manifest_raw.resolve(strict=False)
    if manifest_path == fixture or fixture in manifest_path.parents or home in manifest_path.parents:
        raise HarnessError("manifest must be outside fixture and HERMES_HOME")
    outside_checkouts(manifest_path, fixture)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (set(manifest.get("skill_source_sha256", {})) != set(SKILLS)
            or set(manifest.get("canaries", {})) != {"agents", *SKILLS}
            or set(manifest.get("native_memory_canaries", {})) != {"MEMORY.md", "USER.md"}
            or manifest.get("prompts") != {phase: prompt_for(phase) for phase in PHASES}):
        raise HarnessError("manifest lifecycle skill set is incomplete")
    if (fixture / MARKER).read_text(encoding="utf-8").strip() != "disposable" or git(fixture, "rev-parse", "HEAD") != manifest["fixture_commit"]:
        raise HarnessError("fixture marker or fixture commit mismatch")
    for name, digest in manifest["skill_source_sha256"].items():
        content = (fixture / ".agents" / "skills" / name / "SKILL.md").read_bytes()
        if hashlib.sha256(content.split(b"\nHermes fixture canary:")[0]).hexdigest() != digest:
            raise HarnessError("fixture skill drift; prepare again from a clean source")
    for name, marker in manifest["native_memory_canaries"].items():
        if marker not in (home / "memories" / name).read_text(encoding="utf-8"):
            raise HarnessError("synthetic native memory canary is missing")
    result = {"started_at": now(), "source_sha": manifest["source_sha"], "fixture_commit": manifest["fixture_commit"],
              "os": platform.platform(), "fresh_hermes_home": True,
              "operator_mode": "approval-dir" if approval_dir is not None else "interactive",
              "model": route_id(model, "model"), "provider": route_id(provider, "provider"),
              "controls": {name: "unsupported" for name in (
                  "version", "agents_discovery", "setup_discovery", "setup_proposal_apply",
                  "start_discovery", "start_read_only", "update_discovery", "update_proposal_apply",
                  "end_discovery", "end_proposal_apply", "wrong_digest_rejected", "stale_target_rejected",
                  "memory_separation", "unrelated_sentinel", "hook_example")},
              "commands": [], "skill_source_sha256": manifest["skill_source_sha256"]}
    env = hermes_environment(home, provider, env_allow)
    result["environment_names"] = sorted(env)
    result["api_key_names"] = sorted(name for name in env if name.upper().endswith("_API_KEY"))
    memory_before = native_memory_state(home)
    memory_contents = native_memory_contents(home)
    sentinel = sha(fixture / "unrelated-sentinel.txt")
    current_control = "version"
    try:
        version = command([*binary, "--version"], fixture, env)
        result["commands"].append(version)
        current_control = "memory_separation"
        check_native_memory(home, memory_before, memory_contents, result,
                            tuple(manifest["native_memory_canaries"].values()))
        current_control = "version"
        result["version"] = version["stdout"].splitlines()[0] if version["stdout"] else ""
        if (version["exit_code"] or not re.search(r"Hermes Agent v\d+\.\d+\.\d+", result["version"])
                or (expected_version and not result["version"].startswith(expected_version))):
            raise HarnessError("Hermes version was not verified")
        result["controls"]["version"] = "passed"
        canaries = manifest["canaries"]
        stream_canaries = {**canaries, **{f"native-{name}": marker
                                         for name, marker in manifest["native_memory_canaries"].items()}}
        for phase in PHASES:
            current_control = f"{phase}_discovery"
            before = tracked_state(fixture, include_kernel=phase == "start")
            proposals = set((fixture / ".context-os" / "proposals").glob("*.json"))
            prompt = prompt_for(phase)
            argv = [*binary, "chat", "--format", "stream-json", "--source", "tool", "-m", model, "--provider", provider,
                    "--run-budget", str(run_budget), "--max-turns", str(max_turns), "-q", prompt]
            call = command(argv, fixture, env, timeout=run_budget + 30, raw_output=True)
            raw = call.pop("_raw_stdout")
            call["stdout"] = "[stream-json events recorded separately]"
            result["commands"].append(call)
            current_control = "memory_separation"
            check_native_memory(home, memory_before, memory_contents, result,
                                tuple(manifest["native_memory_canaries"].values()))
            current_control = f"{phase}_discovery"
            if call["exit_code"]:
                raise HarnessError(f"{phase} chat failed or timed out")
            events, assistant, skills, self_read = stream_evidence(raw, stream_canaries, phase)
            call["events"] = events
            call["skill_view_names"] = skills
            required = [canaries["agents"], canaries[f"context-{phase}"]]
            if self_read:
                raise HarnessError("self-read: discovery not shown")
            missing = [name for name, value in (("agents", canaries["agents"]), (f"context-{phase}", canaries[f"context-{phase}"]))
                       if value not in assistant]
            if missing:
                raise HarnessError(f"canary not reported: {', '.join(missing)}")
            result["controls"][f"{phase}_discovery"] = "passed"
            if phase == "setup":
                result["controls"]["agents_discovery"] = "passed"
            current_control = "memory_separation"
            check_memory(fixture, home, manifest["native_memory_canaries"])
            check_native_memory(home, memory_before, memory_contents, result,
                                tuple(manifest["native_memory_canaries"].values()))
            after = tracked_state(fixture, include_kernel=phase == "start")
            if phase == "start":
                current_control = "start_read_only"
                if before != after:
                    raise HarnessError("start changed Git status or fixture file digests")
                result["controls"]["start_read_only"] = "passed"
            if phase in ("setup", "update", "end"):
                current_control = f"{phase}_proposal_apply"
                path, proposal = new_proposal(fixture, proposals, phase)
                proposal_snapshot = sha(path)
                if before != after:
                    raise HarnessError("proposal turn changed fixture files before operator apply")
                current_control = "memory_separation"
                proposed = "".join(change["path"] + change["diff"] + change.get("after_text", "")
                                   for change in proposal["changes"])
                if mirrors_memory(proposed, tuple(manifest["native_memory_canaries"].values())):
                    raise HarnessError("proposal mirrors Hermes native memory into repository state")
                current_control = f"{phase}_proposal_apply"
                digest = proposal["proposal_digest"]
                operator_approval(phase, path.relative_to(fixture), proposal, digest,
                                  input_fn, approval_dir, approval_timeout)
                if sha(path) != proposal_snapshot:
                    raise HarnessError("proposal changed after review")
                wrong = "0" * 64 if digest != "0" * 64 else "1" * 64
                relative = path.relative_to(fixture).as_posix()
                current_control = "wrong_digest_rejected"
                reject = command(["bash", "scripts/contextos.sh", "apply", relative, "--confirm", wrong, "--runtime", "hermes"], fixture, env)
                result["commands"].append(reject)
                if reject["exit_code"] == 0 or "--confirm must exactly match" not in (reject["stdout"] + reject["stderr"]):
                    raise HarnessError("kernel did not reject wrong digest")
                result["controls"]["wrong_digest_rejected"] = "passed"
                current_control = f"{phase}_proposal_apply"
                receipts_before = set((fixture / ".context-os" / "receipts").glob("*.json"))
                applied = command(["bash", "scripts/contextos.sh", "apply", relative, "--confirm", digest, "--runtime", "hermes"], fixture, env)
                result["commands"].append(applied)
                added = set((fixture / ".context-os" / "receipts").glob("*.json")) - receipts_before
                if applied["exit_code"] or len(added) != 1:
                    raise HarnessError("apply failed or did not issue exactly one receipt")
                receipt = json.loads(added.pop().read_text(encoding="utf-8"))
                if receipt.get("proposal_digest") != digest or receipt.get("runtime") != "hermes":
                    raise HarnessError("receipt does not bind exact Hermes proposal")
                result["controls"][f"{phase}_proposal_apply"] = "passed"
                if phase != "setup":
                    current_control = "stale_target_rejected"
                    stale = command(["bash", "scripts/contextos.sh", "apply", relative, "--confirm", digest, "--runtime", "hermes"], fixture, env)
                    result["commands"].append(stale)
                    if stale["exit_code"] == 0 or "refusing stale proposal; file changed" not in (stale["stdout"] + stale["stderr"]):
                        raise HarnessError("kernel accepted already-applied proposal")
                    result["controls"]["stale_target_rejected"] = "passed"
            current_control = "unrelated_sentinel"
            if sha(fixture / "unrelated-sentinel.txt") != sentinel:
                raise HarnessError("unrelated fixture sentinel changed")
            current_control = "memory_separation"
            check_memory(fixture, home, manifest["native_memory_canaries"])
            check_native_memory(home, memory_before, memory_contents, result,
                                tuple(manifest["native_memory_canaries"].values()))
        result["controls"]["memory_separation"] = "passed"
        result["controls"]["unrelated_sentinel"] = "passed"
        result["controls"]["hook_example"] = "unsupported"
    except Exception as exc:
        result["controls"][current_control] = "failed"
        result["controls"]["run"] = "failed"
        result["failure"] = clean(f"{type(exc).__name__}: {exc}")
    else:
        result["controls"]["run"] = "passed"
    result["finished_at"] = now()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    with evidence.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    prep = commands.add_parser("prepare")
    for flag in ("source", "fixture", "home", "expected-commit"):
        prep.add_argument("--" + flag, required=True)
    prep.add_argument("--manifest")
    run = commands.add_parser("record")
    for flag in ("fixture", "home", "manifest", "evidence", "binary", "model", "provider", "expected-version"):
        run.add_argument("--" + flag, required=True)
    run.add_argument("--env-allow", action="append", default=[], metavar="NAME")
    run.add_argument("--run-budget", type=int, default=120)
    run.add_argument("--max-turns", type=int, default=20)
    run.add_argument("--approval-dir")
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            print(json.dumps(prepare(Path(args.source), Path(args.fixture), Path(args.home), args.expected_commit,
                                     Path(args.manifest) if args.manifest else None), indent=2))
        else:
            if args.run_budget < 1 or args.max_turns < 1:
                raise HarnessError("budgets must be positive")
            result = record(Path(args.fixture), Path(args.home), Path(args.evidence), [args.binary], args.model, args.provider, args.run_budget, args.max_turns,
                            expected_version=args.expected_version,
                            approval_dir=Path(args.approval_dir) if args.approval_dir else None,
                            manifest_path=Path(args.manifest), env_allow=args.env_allow)
            print(json.dumps({"controls": result["controls"], "evidence": args.evidence}, indent=2))
            return 0 if result["controls"]["run"] == "passed" else 1
    except HarnessError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
