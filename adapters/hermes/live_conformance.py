#!/usr/bin/env python3
"""Operator-driven, disposable Hermes lifecycle conformance. No approval is automated."""

from __future__ import annotations

import argparse
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
BEARER = re.compile(r"(?i)(Bearer\s+|\b(?:sk|or)-)[A-Za-z0-9._-]{12,}")
PATH = re.compile(r"(?:[A-Za-z]:[\\/]|/)[^\s\"']+")


class HarnessError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean(text: str) -> str:
    return PATH.sub("[PATH]", BEARER.sub("[REDACTED]", SECRET.sub(r"\1[REDACTED]", text)))[:20000]


def command(argv: Sequence[str], cwd: Path, env: dict[str, str] | None = None, timeout: int = 120) -> dict:
    started = time.monotonic()
    try:
        result = subprocess.run(list(argv), cwd=cwd, env=env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        code, stdout, stderr = 124, str(exc.stdout or b""), "timed out"
    return {"argv": [clean(item) for item in argv], "exit_code": code,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout": clean(stdout), "stderr": clean(stderr), "at": now()}


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
        return "Read AGENTS.md and invoke /setup. Report the exact AGENTS, setup, and context-setup canaries. Create a kernel setup proposal for a new identity/hermes-fixture.md containing only a synthetic fixture identity. Stop before apply."
    if phase == "start":
        return "Invoke /start and the shared read-only kernel inventory. Report exact start and context-start skill canaries. Do not write anything."
    return f"Invoke /{phase} with synthetic progress 'Hermes fixture {phase} checkpoint'. Read both {phase} and context-{phase} skills and report their exact canaries. Create a kernel proposal, show its path and digest, and stop before apply."


def prepare(source: Path, fixture: Path, home: Path, expected_commit: str) -> dict:
    source = source.resolve(strict=True)
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise HarnessError("expected commit must be a full lowercase SHA")
    if git(source, "rev-parse", "HEAD") != expected_commit or git(source, "status", "--porcelain", "--untracked-files=all"):
        raise HarnessError("source must be clean at the exact expected HEAD")
    if fixture.exists() or home.exists():
        raise HarnessError("fixture and HERMES_HOME must not exist")
    outside_checkouts(fixture, source)
    outside_checkouts(home, source)
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
    manifest = {"source_sha": expected_commit, "fixture_commit": git(fixture, "rev-parse", "HEAD"),
                "prepared_at": now(), "skill_source_sha256": skill_digests, "canaries": canaries,
                "native_memory_canaries": memory_canaries,
                "sentinel_sha256": sha(fixture / "unrelated-sentinel.txt"),
                "prompts": {phase: prompt_for(phase) for phase in PHASES},
                "commands": ["hermes skills trust <fixture>", "hermes skills list --source local",
                             "python adapters/hermes/live_conformance.py record --fixture <fixture> --home <home> --evidence <new-json> --binary <hermes> --model <model> --provider <provider> --expected-version 'Hermes Agent v0.21.4' --run-budget 120 --max-turns 20"],
                "steps": ["Set HERMES_HOME to the fresh home path printed by prepare.",
                          "Supply provider credentials through environment variables; do not copy credentials into the fixture.",
                          "Run hermes skills trust <fixture> yourself, then verify hermes skills list --source local.",
                          "Run record with --binary, --model, --provider, --run-budget, --max-turns and --evidence.",
                          "For each proposal, inspect the printed diff and type its exact digest."]}
    (fixture / ".context-os-live-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"fixture": str(fixture), "hermes_home": str(home), "manifest": manifest}


def tracked_state(fixture: Path) -> tuple[str, dict[str, str]]:
    status = git(fixture, "status", "--porcelain=v1", "--untracked-files=all")
    files = {p.relative_to(fixture).as_posix(): sha(p) for p in fixture.rglob("*")
             if p.is_file() and ".git" not in p.relative_to(fixture).parts and ".context-os" not in p.relative_to(fixture).parts}
    return status, files


def check_memory(fixture: Path, home: Path, canaries: dict[str, str]) -> None:
    for name in ("MEMORY.md", "USER.md"):
        if any(p.name == name for p in fixture.rglob(name) if ".git" not in p.parts):
            raise HarnessError(f"fixture contains Hermes native {name}")
    state = {name: digest for name, digest in tracked_state(fixture)[1].items()
             if name not in {MARKER, ".context-os-live-manifest.json", "unrelated-sentinel.txt"}}
    for marker in canaries.values():
        if any(marker.encode() in (fixture / rel).read_bytes() for rel in state):
            raise HarnessError("Hermes native memory canary appeared in fixture state")
    for name in ("MEMORY.md", "USER.md"):
        for memory in home.rglob(name):
            content = memory.read_bytes()
            if content and any(content in p.read_bytes() for rel in state for p in [fixture / rel]):
                raise HarnessError("host memory appeared in fixture state")


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


def require_canaries(output: str, *values: str) -> None:
    if any(value not in output for value in values):
        raise HarnessError("response omitted an exact discovery canary")


def record(fixture: Path, home: Path, evidence: Path, binary: Sequence[str], model: str,
           provider: str, run_budget: int, max_turns: int, input_fn=input,
           expected_version: str = "") -> dict:
    fixture, home, evidence = fixture.resolve(), home.resolve(), evidence.resolve(strict=False)
    if not home.is_dir() or fixture in home.parents or home in fixture.parents:
        raise HarnessError("HERMES_HOME must be a separate existing directory")
    outside_checkouts(home, fixture)
    if evidence.exists() or fixture in evidence.parents or home in evidence.parents:
        raise HarnessError("evidence must be new and outside fixture and HERMES_HOME")
    outside_checkouts(evidence, fixture)
    manifest = json.loads((fixture / ".context-os-live-manifest.json").read_text(encoding="utf-8"))
    if (set(manifest.get("skill_source_sha256", {})) != set(SKILLS)
            or set(manifest.get("canaries", {})) != {"agents", *SKILLS}
            or set(manifest.get("native_memory_canaries", {})) != {"MEMORY.md", "USER.md"}
            or manifest.get("prompts") != {phase: prompt_for(phase) for phase in PHASES}):
        raise HarnessError("manifest lifecycle skill set is incomplete")
    if (fixture / MARKER).read_text(encoding="utf-8").strip() != "disposable" or git(fixture, "rev-parse", "HEAD") != manifest["source_sha"]:
        raise HarnessError("fixture marker or source commit mismatch")
    for name, digest in manifest["skill_source_sha256"].items():
        content = (fixture / ".agents" / "skills" / name / "SKILL.md").read_bytes()
        if hashlib.sha256(content.split(b"\nHermes fixture canary:")[0]).hexdigest() != digest:
            raise HarnessError("fixture skill drift; prepare again from a clean source")
    for name, marker in manifest["native_memory_canaries"].items():
        if marker not in (home / "memories" / name).read_text(encoding="utf-8"):
            raise HarnessError("synthetic native memory canary is missing")
    result = {"started_at": now(), "source_sha": manifest["source_sha"], "fixture_commit": manifest["fixture_commit"],
              "os": platform.platform(), "model": model, "provider": provider,
              "controls": {name: "unsupported" for name in (
                  "version", "agents_discovery", "setup_discovery", "setup_proposal_apply",
                  "start_discovery", "start_read_only", "update_discovery", "update_proposal_apply",
                  "end_discovery", "end_proposal_apply", "stale_digest_rejected",
                  "memory_separation", "unrelated_sentinel", "hook_example")},
              "commands": [], "skill_source_sha256": manifest["skill_source_sha256"]}
    env = os.environ.copy()
    env["HERMES_HOME"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("HERMES_ACCEPT_HOOKS", None)
    sentinel = sha(fixture / "unrelated-sentinel.txt")
    current_control = "version"
    try:
        version = command([*binary, "--version"], fixture, env)
        result["commands"].append(version)
        result["version"] = version["stdout"].splitlines()[0] if version["stdout"] else ""
        if (version["exit_code"] or not re.search(r"Hermes Agent v\d+\.\d+\.\d+", result["version"])
                or (expected_version and not result["version"].startswith(expected_version))):
            raise HarnessError("Hermes version was not verified")
        result["controls"]["version"] = "passed"
        canaries = manifest["canaries"]
        for phase in PHASES:
            current_control = f"{phase}_discovery"
            before = tracked_state(fixture)
            proposals = set((fixture / ".context-os" / "proposals").glob("*.json"))
            prompt = prompt_for(phase)
            argv = [*binary, "chat", "-Q", "--source", "tool", "-m", model, "--provider", provider,
                    "--run-budget", str(run_budget), "--max-turns", str(max_turns), "-q", prompt]
            call = command(argv, fixture, env, timeout=run_budget + 30)
            result["commands"].append(call)
            if call["exit_code"]:
                raise HarnessError(f"{phase} chat failed or timed out")
            required = [canaries[phase], canaries[f"context-{phase}"]]
            if phase == "setup":
                required.append(canaries["agents"])
            require_canaries(call["stdout"], *required)
            result["controls"][f"{phase}_discovery"] = "passed"
            if phase == "setup":
                result["controls"]["agents_discovery"] = "passed"
            current_control = "memory_separation"
            check_memory(fixture, home, manifest["native_memory_canaries"])
            after = tracked_state(fixture)
            if phase == "start":
                current_control = "start_read_only"
                if before != after:
                    raise HarnessError("start changed Git status or fixture file digests")
                result["controls"]["start_read_only"] = "passed"
            if phase in ("setup", "update", "end"):
                current_control = f"{phase}_proposal_apply"
                path, proposal = new_proposal(fixture, proposals, phase)
                proposal_snapshot = sha(path)
                if any(k not in (".context-os",) and k not in before[1] for k in after[1]):
                    raise HarnessError("proposal turn created an unrelated fixture file")
                digest = proposal["proposal_digest"]
                print(f"\n{phase} proposal: {path.relative_to(fixture)}\nDigest: {digest}")
                for change in proposal["changes"]:
                    print(f"{change['path']}\n{change['diff']}")
                if input_fn(f"Type the exact {phase} digest {digest} to approve: ").strip() != digest:
                    raise HarnessError("operator did not type the exact proposal digest")
                if sha(path) != proposal_snapshot:
                    raise HarnessError("proposal changed after review")
                wrong = "0" * 64 if digest != "0" * 64 else "1" * 64
                relative = path.relative_to(fixture).as_posix()
                reject = command(["bash", "scripts/contextos.sh", "apply", relative, "--confirm", wrong, "--runtime", "hermes"], fixture, env)
                result["commands"].append(reject)
                current_control = "stale_digest_rejected"
                if reject["exit_code"] == 0 or "--confirm must exactly match" not in (reject["stdout"] + reject["stderr"]):
                    raise HarnessError("kernel did not reject stale digest")
                result["controls"]["stale_digest_rejected"] = "passed"
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
            current_control = "unrelated_sentinel"
            if sha(fixture / "unrelated-sentinel.txt") != sentinel:
                raise HarnessError("unrelated fixture sentinel changed")
            current_control = "memory_separation"
            check_memory(fixture, home, manifest["native_memory_canaries"])
        result["controls"]["memory_separation"] = "passed"
        result["controls"]["unrelated_sentinel"] = "passed"
        result["controls"]["hook_example"] = "unsupported"
    except (HarnessError, OSError, ValueError, json.JSONDecodeError) as exc:
        result["controls"][current_control] = "failed"
        result["controls"]["run"] = "failed"
        result["failure"] = clean(str(exc))
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
    run = commands.add_parser("record")
    for flag in ("fixture", "home", "evidence", "binary", "model", "provider", "expected-version"):
        run.add_argument("--" + flag, required=True)
    run.add_argument("--run-budget", type=int, default=120)
    run.add_argument("--max-turns", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            print(json.dumps(prepare(Path(args.source), Path(args.fixture), Path(args.home), args.expected_commit), indent=2))
        else:
            if args.run_budget < 1 or args.max_turns < 1:
                raise HarnessError("budgets must be positive")
            result = record(Path(args.fixture), Path(args.home), Path(args.evidence), [args.binary], args.model, args.provider, args.run_budget, args.max_turns,
                            expected_version=args.expected_version)
            print(json.dumps({"controls": result["controls"], "evidence": args.evidence}, indent=2))
            return 0 if result["controls"]["run"] == "passed" else 1
    except HarnessError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
