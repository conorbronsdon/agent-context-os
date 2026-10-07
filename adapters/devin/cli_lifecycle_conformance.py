"""Opt-in Devin CLI lifecycle test; exact proposals require operator approval.

Runs the shipped setup/start/update/end skills through ``devin -p`` against a
disposable clone of the exact source commit, in Devin's default Normal mode.
The fixture's local Devin config allows only the read-only kernel inventory,
proposal creation, and payload writes. Devin never receives an allow for
``apply``: an operator outside the Devin process reviews each proposal and
supplies its exact digest, then the harness runs the kernel apply itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import secrets
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from adapters.devin.cli_conformance import (  # noqa: E402
    DevinCliHarness, HarnessError, REPOSITORY_ROOT, Trajectory, output_summary,
    repository_source_sha, require_outside_source, require_success, write_local_permissions,
)
from contextos.kernel import validate_proposal  # noqa: E402
from contextos.primitives import is_link_like, read_regular_file_snapshot  # noqa: E402
from contextos.workspace_schema import strict_json_loads  # noqa: E402

PHASES = ("setup", "start", "update", "end")
LIFECYCLE_PERMISSIONS = {
    "allow": [
        "Exec(bash scripts/contextos.sh start)",
        "Exec(bash scripts/contextos.sh propose)",
        "Exec(bash scripts/contextos.sh doctor)",
        "Exec(git status)",
        "Exec(git diff)",
        "Exec(git log)",
        "Write(.context-os/inputs/**)",
    ],
    "deny": ["webfetch", "web_search"],
}


def require_fact(document: dict, fact: str) -> None:
    if not any(fact in change["after_text"] for change in document["changes"]):
        raise HarnessError("proposal omitted the requested synthetic fact")


def git_state(root: Path) -> dict[str, str]:
    """Track control metadata without treating Devin's info/exclude update as a write."""
    result = {}
    for name in ("HEAD", "config", "packed-refs", "refs", "hooks"):
        path = root / ".git" / name
        if is_link_like(path):
            raise HarnessError("fixture Git metadata contains a link")
        paths = path.rglob("*") if path.is_dir() else [path]
        for item in paths:
            if is_link_like(item):
                raise HarnessError("fixture Git metadata contains a link")
            if item.is_file():
                result[item.relative_to(root).as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
    staged = subprocess.run(["git", "diff", "--cached", "--exit-code"], cwd=root,
                            capture_output=True, check=False)
    if staged.returncode:
        raise HarnessError("fixture index changed")
    return result


def state(root: Path, *, include_pending: bool = True) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts[0] == ".git":
            continue
        if is_link_like(path):
            raise HarnessError("fixture contains a link")
        rel = relative.as_posix()
        if not include_pending and rel.startswith((".context-os/inputs/", ".context-os/proposals/")):
            continue
        if path.is_file():
            result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def proposal(root: Path, previous: set[Path], phase: str) -> tuple[Path, dict]:
    added = set((root / ".context-os/proposals").glob("*.json")) - previous
    if len(added) != 1:
        raise HarnessError("phase must create exactly one proposal")
    path = added.pop()
    raw, _ = read_regular_file_snapshot(path, subject="Devin lifecycle proposal")
    if len(raw) > 2_000_000:
        raise HarnessError("proposal too large")
    document = strict_json_loads(raw.decode("utf-8"), source=str(path))
    validate_proposal(document)
    if document.get("workflow") != phase or not document.get("changes"):
        raise HarnessError("proposal has wrong workflow or no changes")
    for change in document["changes"]:
        if not isinstance(change, dict) or not all(isinstance(change.get(k), str) for k in ("path", "diff", "after_text")):
            raise HarnessError("proposal lacks reviewable text")
        if any(unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"} and c not in "\n\t"
               for c in change["path"] + change["diff"]):
            raise HarnessError("unsafe proposal display")
    return path, document


def approve(directory: Path, phase: str, document: dict, timeout: float = 1800) -> None:
    review, approval = directory / f"{phase}.review.txt", directory / f"{phase}.approve"
    if approval.exists():
        raise HarnessError("approval existed before review")
    with review.open("x", encoding="utf-8") as stream:
        stream.write("Digest: " + document["proposal_digest"] + "\n")
        for change in document["changes"]:
            stream.write(change["path"] + "\n" + change["diff"] + "\n")
    print(f"Review {review}; write the exact digest to {approval}", flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if approval.exists():
            if approval.read_text(encoding="utf-8").strip() != document["proposal_digest"]:
                raise HarnessError("operator did not approve the exact digest")
            return
        time.sleep(1)
    raise HarnessError("operator approval timed out")


def check_applied(root: Path, document: dict, before: dict[str, str]) -> None:
    after = state(root, include_pending=False)
    expected = dict(before)
    for change in document["changes"]:
        expected[change["path"]] = hashlib.sha256(change["after_text"].encode("utf-8")).hexdigest()
    without_receipts = lambda value: {k: v for k, v in value.items() if not k.startswith(".context-os/receipts/")}
    if without_receipts(after) != without_receipts(expected):
        raise HarnessError("apply changed unexpected files or produced incorrect content")


def require_guarded_context(trajectory: Trajectory) -> None:
    """The shipped import guard must keep Claude rules out of every phase."""
    rules = trajectory.system_block("<rules")
    if '<rule name="AGENTS"' not in rules or '<rule name="CLAUDE"' in rules:
        raise HarnessError("lifecycle context did not load exactly the Context OS instruction sources")


def prompt_for(phase: str, handoff_fact: str) -> str:
    detail = {
        "setup": "Audience confirmed: synthetic public fixture only. Use identity/lifecycle-fixture.md containing '# Synthetic lifecycle identity\\n\\nThe fixture tests portable continuity.\\n'.",
        "start": "Read the continuity inventory and summarize it. Make no changes.",
        "update": "Record this fact: The synthetic fixture completed its Devin setup test.",
        "end": "Record this outcome: The synthetic fixture completed its Devin lifecycle test. Record this exact next action: " + handoff_fact,
    }[phase]
    return (f"/context-{phase} This is an explicitly authorized synthetic lifecycle fixture. "
            f"Use the colocated repository. {detail} "
            "For mutations, create exactly one kernel proposal, display its diff and digest, "
            "then stop. Do not apply, commit, push, or modify other files. "
            "Use .context-os/inputs for payloads. Do not use host-native memory as input.")


def execute(harness: DevinCliHarness, approvals: Path, evidence: Path) -> dict:
    source_sha = repository_source_sha()
    if source_sha != harness.evidence.source_sha:
        raise HarnessError("source revision mismatch")
    controls: dict[str, str] = {}
    handoff_value = secrets.token_hex(16)
    handoff_fact = "The synthetic fixture must verify continuity using " + handoff_value + "."
    facts = {
        "setup": "The fixture tests portable continuity.",
        "update": "The synthetic fixture completed its Devin setup test.",
        "end": handoff_fact,
    }
    result = {"runtime": "devin", "surface": "cli", "harness": "lifecycle", "source_sha": source_sha,
              "controls": controls, "operator": "external-exact-digest",
              "os": platform.platform(), "model_selection": harness.model or "Devin CLI default",
              "permission_mode": "Normal (default)",
              "started_at": datetime.now(timezone.utc).isoformat(),
              "prompts": {}, "phases": {}, "kernel_commands": [],
              "limits": ["No hook, MCP execution, cloud handoff, or native-memory claim.",
                         "Scoped to the recorded client, model selection, and operating system.",
                         "Apply authorization is the operator digest, not a Devin permission rule."]}
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
            if (root / ".devin" / "config.json").read_bytes() != (REPOSITORY_ROOT / ".devin" / "config.json").read_bytes():
                raise HarnessError("fixture does not carry the shipped Devin project config")
            write_local_permissions(root, LIFECYCLE_PERMISSIONS)
            metadata = git_state(root)
            (root / "unrelated-sentinel.txt").write_text(secrets.token_hex(24), encoding="utf-8")
            controls[current] = "passed"
            for phase in PHASES:
                current = phase
                print(f"Devin lifecycle: {phase}", flush=True)
                before = state(root, include_pending=phase == "start")
                pending = set((root / ".context-os/proposals").glob("*.json"))
                prompt = prompt_for(phase, handoff_fact)
                result["prompts"][phase] = prompt
                trajectory = harness.session(root, f"lifecycle-{phase}", prompt)
                require_guarded_context(trajectory)
                if state(root, include_pending=phase == "start") != before:
                    raise HarnessError("lifecycle changed files before operator apply")
                head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                                      text=True, check=True).stdout.strip()
                if head != source_sha:
                    raise HarnessError("model changed fixture HEAD")
                if git_state(root) != metadata:
                    raise HarnessError("model changed fixture Git metadata")
                if phase == "start":
                    controls["start_read_only"] = "passed"
                    continue
                path, document = proposal(root, pending, phase)
                require_fact(document, facts[phase])
                raw = path.read_bytes()
                approve(approvals, phase, document)
                if path.read_bytes() != raw:
                    raise HarnessError("proposal changed after operator review")
                digest = document["proposal_digest"]

                def kernel(confirm: str):
                    output = harness.runner([sys.executable, "-m", "contextos", "apply",
                                             path.relative_to(root).as_posix(), "--confirm", confirm,
                                             "--runtime", "devin"], root, harness.env, harness.timeout)
                    result["kernel_commands"].append(output_summary(output))
                    return output

                rejected_before = state(root)
                wrong = kernel("0" * 64 if digest != "0" * 64 else "1" * 64)
                if not wrong.returncode or "--confirm must exactly match" not in wrong.stderr + wrong.stdout:
                    raise HarnessError("wrong digest was not rejected")
                if state(root) != rejected_before:
                    raise HarnessError("wrong-digest rejection mutated fixture")
                controls[f"{phase}_wrong_digest_rejected"] = "passed"
                receipts_before = set((root / ".context-os/receipts").glob("*.json"))
                require_success(kernel(digest), "approved apply")
                added = set((root / ".context-os/receipts").glob("*.json")) - receipts_before
                if len(added) != 1:
                    raise HarnessError("apply must emit exactly one receipt")
                receipt_path = added.pop()
                receipt_raw = receipt_path.read_bytes()
                receipt = json.loads(receipt_raw.decode("utf-8"))
                if receipt.get("proposal_digest") != digest or receipt.get("runtime") != "devin":
                    raise HarnessError("receipt does not bind the Devin proposal")
                check_applied(root, document, before)
                result["phases"][phase] = {
                    "proposal_digest": digest,
                    "proposal_sha256": hashlib.sha256(raw).hexdigest(),
                    "receipt": receipt_path.relative_to(root).as_posix(),
                    "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
                    "receipt_proposal_digest": receipt["proposal_digest"],
                    "receipt_runtime": receipt["runtime"],
                    "applied_files": {change["path"]: hashlib.sha256(
                        (root / change["path"]).read_bytes()).hexdigest() for change in document["changes"]},
                }
                controls[f"{phase}_proposal_apply"] = "passed"
                if phase != "setup":
                    stale_before = state(root)
                    stale = kernel(digest)
                    if not stale.returncode or "refusing stale proposal; file changed" not in stale.stdout + stale.stderr:
                        raise HarnessError("stale proposal was not rejected")
                    if state(root) != stale_before:
                        raise HarnessError("stale rejection mutated fixture")
                    controls[f"{phase}_stale_rejected"] = "passed"
            current = "handoff"
            before = state(root)
            result["prompts"]["handoff"] = ("/context-start Read the saved session and report the exact next "
                                            "action for the synthetic fixture, including its verification value.")
            trajectory = harness.session(root, "lifecycle-handoff", result["prompts"]["handoff"])
            require_guarded_context(trajectory)
            answer = trajectory.final_message()
            result["handoff_value_recovered"] = handoff_value in answer
            result["handoff_read_only"] = state(root) == before
            if git_state(root) != metadata:
                raise HarnessError("handoff changed fixture Git metadata")
            result["handoff_answer_sha256"] = hashlib.sha256(answer.encode()).hexdigest()
            if not result["handoff_value_recovered"] or not result["handoff_read_only"]:
                raise HarnessError(f"handoff failed: value recovered={result['handoff_value_recovered']}, "
                                   f"read-only={result['handoff_read_only']}")
            controls[current] = "passed"
            harness.verify_binary()
            if repository_source_sha() != source_sha:
                raise HarnessError("source changed during live run")
            controls["run"] = "passed"
    except Exception as exc:
        controls[current] = "failed"
        controls["run"] = "failed"
        # Local diagnostics only; shareable evidence excludes raw model output and paths.
        print(f"Devin lifecycle failed: {exc}", file=sys.stderr)
        result["failure_type"] = type(exc).__name__
    result["host"] = vars(harness.evidence)
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    evidence = require_outside_source(evidence)
    with evidence.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("binary", "expected-version", "source-sha", "data-home", "evidence", "approval-dir"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--model")
    parser.add_argument("--debug-dir", help="local directory for raw ATIF exports; never share")
    parser.add_argument("--allow-model-traffic", action="store_true")
    args = parser.parse_args()
    if not args.allow_model_traffic:
        parser.error("requires --allow-model-traffic for disposable synthetic model calls")
    approvals = require_outside_source(Path(args.approval_dir))
    evidence = require_outside_source(Path(args.evidence))
    if not approvals.is_dir() or any(approvals.iterdir()) or evidence.exists():
        parser.error("use an empty external approval directory and a new evidence path")
    harness = DevinCliHarness(Path(args.binary), args.expected_version, args.source_sha,
                              Path(args.data_home), model=args.model, timeout=900,
                              debug_dir=Path(args.debug_dir) if args.debug_dir else None)
    return 0 if execute(harness, approvals, evidence)["controls"]["run"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
