"""Opt-in Devin cloud-session lifecycle test with exact-digest operator approval.

One API-created cloud session runs the shipped setup/start/update/end skills
against a disposable run branch of a public fixture that holds the unmodified
Context OS release template. For each mutating phase Devin creates exactly one
kernel proposal, pushes only its inputs and proposal, and stops. The harness
fetches the branch anonymously, validates the proposal, confirms that nothing
was applied, proves a wrong digest is rejected, and only then sends a message
approving the exact digest. Devin applies in the cloud and pushes the result,
which the harness checks file by file. A fresh session must then recover the
saved next action without changing the branch.

Account, repository, and active-build identity come from the Devin v3 API.
Branch content comes from Git over HTTPS, not the GitHub REST API. Evidence
keeps hashes, digests, and controls; raw model output is never stored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from adapters.devin.live_conformance import (  # noqa: E402
    REPO_RE, SHA_RE, DevinClient, DevinHarness, HarnessError, Transport,
    default_transport, repository_source_sha, require_outside_source, safe_error_detail,
)
from contextos.kernel import ContextOSError, validate_proposal  # noqa: E402
from contextos.workspace_schema import strict_json_loads  # noqa: E402

PHASES = ("setup", "start", "update", "end")
MUTATING = ("setup", "update", "end")
PENDING_PREFIXES = (".context-os/inputs/", ".context-os/proposals/")
RECEIPT_PREFIX = ".context-os/receipts/"
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
SESSION_ID_RE = re.compile(r"devin-[A-Za-z0-9_-]+|[0-9a-f]{32}")
SAFE_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
SETUP_PRIORITY = "Verify synthetic portable continuity."
WRONG_DIGEST_TEXT = "--confirm must exactly match"
STALE_TEXT = "refusing stale proposal; file changed"

GitRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess]
KernelRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess]


def default_git(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-c", "core.hooksPath=" + os.devnull, *args],
        cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False, timeout=600,
    )


def default_kernel(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run the fixture's own kernel from its root, as the operator would."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", "contextos", *args], cwd=cwd, env=env, text=True,
        encoding="utf-8", errors="replace", capture_output=True, check=False, timeout=600,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FixtureClone:
    """An anonymous local clone used to read pushed branch state and run controls."""

    def __init__(
        self, repository: str, fixture_sha: str, workdir: Path, *,
        git: GitRunner = default_git, remote_url: str | None = None,
    ) -> None:
        if not REPO_RE.fullmatch(repository):
            raise HarnessError("--repository must be an exact owner/name path")
        if not SHA_RE.fullmatch(fixture_sha):
            raise HarnessError("--fixture-sha must be an exact lowercase commit")
        self.repository, self.fixture_sha, self.git = repository, fixture_sha, git
        self.remote_url = remote_url or f"https://github.com/{repository}.git"
        self.root = workdir / "fixture"

    def run(self, *args: str, cwd: Path | None = None) -> str:
        result = self.git(list(args), cwd or self.root)
        if result.returncode:
            raise HarnessError(f"git {args[0]} failed: {safe_error_detail(result.stderr.strip())}")
        return result.stdout

    def prepare(self) -> str:
        """Clone, require the default branch at the fixture commit, and return its tree."""
        self.root.parent.mkdir(parents=True, exist_ok=True)
        self.run("clone", "--quiet", "--no-checkout", self.remote_url, str(self.root), cwd=self.root.parent)
        self.run("config", "core.autocrlf", "false")
        head = self.run("ls-remote", "origin", "HEAD").split()
        if not head or head[0] != self.fixture_sha:
            raise HarnessError("fixture default branch does not point at --fixture-sha")
        if self.run("cat-file", "-t", self.fixture_sha).strip() != "commit":
            raise HarnessError("fixture commit is missing from the clone")
        self.checkout(self.fixture_sha)
        return self.run("rev-parse", f"{self.fixture_sha}^{{tree}}").strip()

    def remote_head(self, branch: str) -> str | None:
        lines = self.run("ls-remote", "origin", f"refs/heads/{branch}").split()
        return lines[0] if lines else None

    def fetch(self, branch: str) -> str:
        self.run("fetch", "--quiet", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
        return self.run("rev-parse", f"refs/remotes/origin/{branch}").strip()

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return self.git(["merge-base", "--is-ancestor", ancestor, descendant], self.root).returncode == 0

    def changed(self, before: str, after: str) -> list[tuple[str, str]]:
        output = self.run("diff", "--name-status", "--no-renames", before, after)
        return [tuple(line.split("\t", 1)) for line in output.splitlines() if line]  # type: ignore[misc]

    def checkout(self, sha: str) -> None:
        self.run("checkout", "--quiet", "--force", "--detach", sha)
        self.run("clean", "-fdxq")

    def snapshot(self) -> dict[str, str]:
        result = {}
        for path in sorted(self.root.rglob("*")):
            relative = path.relative_to(self.root)
            if relative.parts[0] == ".git" or not path.is_file() or path.is_symlink():
                continue
            result[relative.as_posix()] = sha256_bytes(path.read_bytes())
        return result

    def holders(self, value: str) -> list[str]:
        needle = value.encode("utf-8")
        return sorted(
            path.relative_to(self.root).as_posix() for path in self.root.rglob("*")
            if ".git" not in path.relative_to(self.root).parts and path.is_file()
            and needle in path.read_bytes()
        )


def require_fact(document: dict, fact: str, *, prefix: str = "") -> None:
    if not any(fact in change["after_text"] and change["path"].startswith(prefix)
               for change in document["changes"]):
        raise HarnessError("proposal omitted the requested synthetic fact")


def require_next_action(document: dict, fact: str) -> None:
    """The handoff fact must be saved under the session's ``## Next time`` heading."""
    for change in document["changes"]:
        if not change["path"].startswith("sessions/"):
            continue
        section = change["after_text"].rsplit("## Next time", 1)
        if len(section) == 2 and fact in section[1].split("\n## ", 1)[0]:
            return
    raise HarnessError("end did not save the handoff fact as the next action")


def load_proposal(root: Path, relative: str, phase: str) -> dict:
    raw = (root / relative).read_bytes()
    if len(raw) > 2_000_000:
        raise HarnessError("proposal too large")
    try:
        document = strict_json_loads(raw.decode("utf-8"), source=relative)
        validate_proposal(document)
    except (ContextOSError, UnicodeDecodeError, ValueError) as exc:
        raise HarnessError(f"pushed proposal is invalid: {safe_error_detail(exc)}") from exc
    if document.get("workflow") != phase or not document.get("changes"):
        raise HarnessError("proposal has wrong workflow or no changes")
    for change in document["changes"]:
        if not isinstance(change, dict) or not all(
            isinstance(change.get(key), str) for key in ("path", "diff", "after_text")
        ):
            raise HarnessError("proposal lacks reviewable text")
        if change["path"].startswith((".context-os/", ".git/")) or ".." in change["path"].split("/"):
            raise HarnessError("proposal targets a kernel or unsafe path")
    return document


def session_rules(repository: str, fixture_sha: str, branch: str) -> str:
    return (
        "This is an explicitly authorized synthetic Context OS lifecycle fixture in the public "
        f"repository {repository}. Work only on the branch {branch}: create it from commit "
        f"{fixture_sha} and push it to origin. Never push to main or any other branch, never open "
        "a pull request, never force-push, and never invoke Devin Review. Run kernel commands only "
        "as `bash scripts/contextos.sh ...` from the repository root. Never run `apply` unless a "
        "later message from me gives the exact proposal digest. Do not use host-native memory or "
        "Knowledge as input. "
    )


def phase_prompt(phase: str, handoff_fact: str) -> str:
    detail = {
        "setup": ("Audience confirmed: synthetic public fixture only. Use identity/lifecycle-fixture.md "
                  "containing '# Synthetic lifecycle identity\\n\\nThe fixture tests portable continuity.\\n' "
                  "and state/current.md containing '# Current State\\n\\n**Last Updated:** {{TODAY}}\\n\\n"
                  "## Active priorities\\n\\n1. " + SETUP_PRIORITY + "\\n'."),
        "update": "Record this fact: The synthetic fixture completed its Devin setup test.",
        "end": ("Record this outcome: The synthetic fixture completed its Devin lifecycle test. "
                "Record this exact next action: " + handoff_fact),
    }
    if phase == "start":
        return ("@skills:context-start Read the continuity inventory and summarize it. Make no "
                "changes, commits, or pushes. When finished, reply with `CONTEXTOS_PHASE_DONE start`.")
    return (
        f"@skills:context-{phase} {detail[phase]} Create exactly one kernel proposal with "
        "`bash scripts/contextos.sh propose`, writing its payload under .context-os/inputs. Then "
        "force-add only the new files under .context-os/inputs/ and .context-os/proposals/ "
        "(`git add -f`), commit them, and push the branch. Do not apply it or change any other "
        "file. Show the proposal diff and digest, reply with "
        f"`CONTEXTOS_PHASE_DONE {phase} <proposal_digest>`, and stop."
    )


def approval_prompt(phase: str, proposal: str, digest: str) -> str:
    return (
        f"Approved after review: proposal {proposal} with exact digest {digest}. Run "
        f"`bash scripts/contextos.sh apply {proposal} --confirm {digest} --runtime devin`. Then "
        "stage every file the apply changed (`git add -A`), force-add the one new receipt under "
        ".context-os/receipts/ (`git add -f`), commit, and push the branch. Change nothing else. "
        f"Reply with `CONTEXTOS_APPLIED {phase}` and stop."
    )


def handoff_prompt(repository: str, branch: str) -> str:
    return (
        "This is an explicitly authorized synthetic Context OS fixture in the public repository "
        f"{repository}. Fetch and check out the existing branch {branch}, and stay on it. Make no "
        "changes, commits, or pushes. @skills:context-start Read the saved session and report the "
        "exact next action for the synthetic fixture, including its verification value. Then "
        "reply with `CONTEXTOS_PHASE_DONE handoff`."
    )


class CloudLifecycleHarness:
    def __init__(
        self, api: DevinHarness, clone: FixtureClone, *, source_sha: str, branch: str,
        kernel: KernelRunner = default_kernel, poll_timeout: float = 1800,
        poll_interval: float = 15, settle_polls: int = 8,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api, self.clone, self.kernel = api, clone, kernel
        self.source_sha, self.branch = source_sha, branch
        self.poll_timeout, self.poll_interval, self.settle_polls = poll_timeout, poll_interval, settle_polls
        self.sleep = sleep
        self.controls: dict[str, object] = {}

    # Devin API helpers -------------------------------------------------------------

    def create_session(self, prompt: str, title: str, sessions: list[str]) -> tuple[str, str | None]:
        created = self.api.client.request("POST", f"{self.api.org_path}/sessions", {
            "prompt": prompt, "repos": [self.clone.repository],
            "structured_output_required": False, "title": title,
        })
        session_id = str(created.get("session_id", ""))
        # Track any plausible ID before validating it, so a session the API
        # created is still archived if its ID format is unexpected.
        if SAFE_ID_RE.fullmatch(session_id):
            sessions.append(session_id)
        if not SESSION_ID_RE.fullmatch(session_id):
            raise HarnessError("session creation omitted a valid Devin session ID")
        if created.get("org_id") != self.api.client.org_id:
            raise HarnessError("session creation returned a different organization")
        mode = created.get("devin_mode")
        return session_id, mode if isinstance(mode, str) else None

    def event_ids(self, session_id: str) -> set[str]:
        return {str(item.get("event_id")) for item in self.api.messages(session_id)}

    def send(self, session_id: str, message: str) -> set[str]:
        observed = self.event_ids(session_id)
        self.api.client.request("POST", f"{self.api.org_path}/sessions/{session_id}/messages",
                                {"message": message})
        return observed

    def wait_for(self, session_id: str, pattern: str, after: set[str]) -> str:
        """Return Devin's new text once a reply carries the requested completion marker."""
        marker = re.compile(pattern)
        deadline = time.monotonic() + self.poll_timeout
        while time.monotonic() < deadline:
            new = [item for item in self.api.messages(session_id)
                   if item.get("source") == "devin" and str(item.get("event_id")) not in after]
            text = "\n".join(str(item.get("message", "")) for item in new)
            if marker.search(text):
                return text
            state = self.api.session(session_id)
            if state.get("status") in {"error", "exit", "suspended"}:
                raise HarnessError("Devin session ended before the phase completed")
            self.sleep(self.poll_interval)
        raise HarnessError("timed out waiting for Devin to complete the phase")

    # Git helpers -------------------------------------------------------------------

    def wait_for_push(self, previous: str | None) -> str:
        for _ in range(max(1, self.settle_polls)):
            head = self.clone.remote_head(self.branch)
            if head and head != previous:
                return head
            self.sleep(self.poll_interval)
        raise HarnessError("Devin reported completion without pushing the run branch")

    def advance(self, previous: str) -> str:
        head = self.wait_for_push(previous)
        fetched = self.clone.fetch(self.branch)
        if fetched != head or not self.clone.is_ancestor(previous, head):
            raise HarnessError("run branch was rewritten instead of advanced")
        return head

    # Phases ------------------------------------------------------------------------

    def proposal_phase(self, session_id: str, phase: str, previous: str, after: set[str],
                       facts: Mapping[str, str]) -> tuple[str, dict]:
        reply = self.wait_for(session_id, rf"CONTEXTOS_PHASE_DONE {phase} [0-9a-f]{{64}}", after)
        head = self.advance(previous)
        changes = self.clone.changed(previous, head)
        if not changes or any(status != "A" or not path.startswith(PENDING_PREFIXES)
                              for status, path in changes):
            raise HarnessError(f"{phase} pushed changes beyond new pending inputs and proposals")
        proposals = [path for _, path in changes
                     if path.startswith(".context-os/proposals/") and path.endswith(".json")]
        if len(proposals) != 1:
            raise HarnessError(f"{phase} must push exactly one new proposal")
        self.clone.checkout(head)
        if any(path.startswith(RECEIPT_PREFIX) for path in self.clone.snapshot()
               if path not in self.receipts_seen):
            raise HarnessError(f"{phase} produced a receipt before operator approval")
        document = load_proposal(self.clone.root, proposals[0], phase)
        digest = document["proposal_digest"]
        if digest not in reply:
            raise HarnessError(f"{phase} reported a digest that differs from the pushed proposal")
        if phase == "setup":
            require_fact(document, facts["setup"])
            require_fact(document, SETUP_PRIORITY, prefix="state/current.md")
        elif phase == "update":
            require_fact(document, facts["update"])
        else:
            require_next_action(document, facts["end"])
        return head, {"path": proposals[0], "document": document}

    def wrong_digest_rejected(self, head: str, proposal: str, digest: str) -> None:
        self.clone.checkout(head)
        before = self.clone.snapshot()
        wrong = "0" * 64 if digest != "0" * 64 else "1" * 64
        result = self.kernel(["apply", proposal, "--confirm", wrong, "--runtime", "devin"], self.clone.root)
        if not result.returncode or WRONG_DIGEST_TEXT not in (result.stdout or "") + (result.stderr or ""):
            raise HarnessError("wrong digest was not rejected")
        if self.clone.snapshot() != before:
            raise HarnessError("wrong-digest rejection mutated the fixture")
        self.clone.checkout(head)

    def applied_phase(self, session_id: str, phase: str, pending_head: str, proposal: str,
                      document: dict, before: dict[str, str], after: set[str]) -> tuple[str, dict]:
        self.wait_for(session_id, rf"CONTEXTOS_APPLIED {phase}\b", after)
        head = self.advance(pending_head)
        changes = self.clone.changed(pending_head, head)
        proposed = {change["path"] for change in document["changes"]}
        receipts = [path for status, path in changes
                    if status == "A" and path.startswith(RECEIPT_PREFIX) and path.endswith(".json")]
        other = [(status, path) for status, path in changes
                 if path not in proposed and path not in receipts]
        if len(receipts) != 1 or other or any(status not in {"A", "M"} for status, _ in changes):
            raise HarnessError(f"{phase} apply pushed changes beyond the proposal and one receipt")
        self.clone.checkout(head)
        receipt_raw = (self.clone.root / receipts[0]).read_bytes()
        receipt = json.loads(receipt_raw.decode("utf-8"))
        digest = document["proposal_digest"]
        if receipt.get("proposal_digest") != digest or receipt.get("runtime") != "devin":
            raise HarnessError("receipt does not bind the approved Devin proposal")
        expected = dict(before)
        for change in document["changes"]:
            expected[change["path"]] = sha256_bytes(change["after_text"].encode("utf-8"))
        actual = {path: value for path, value in self.clone.snapshot().items()
                  if not path.startswith(RECEIPT_PREFIX)}
        expected = {path: value for path, value in expected.items() if not path.startswith(RECEIPT_PREFIX)}
        if actual != expected:
            raise HarnessError("apply changed unexpected files or produced incorrect content")
        self.receipts_seen.add(receipts[0])
        return head, {
            "receipt": receipts[0], "receipt_sha256": sha256_bytes(receipt_raw),
            "receipt_proposal_digest": receipt["proposal_digest"], "receipt_runtime": receipt["runtime"],
            "applied_files": {change["path"]: expected[change["path"]] for change in document["changes"]},
        }

    def stale_rejected(self, head: str, proposal: str, digest: str) -> None:
        self.clone.checkout(head)
        before = self.clone.snapshot()
        result = self.kernel(["apply", proposal, "--confirm", digest, "--runtime", "devin"], self.clone.root)
        if not result.returncode or STALE_TEXT not in (result.stdout or "") + (result.stderr or ""):
            raise HarnessError("stale proposal was not rejected")
        if self.clone.snapshot() != before:
            raise HarnessError("stale rejection mutated the fixture")
        self.clone.checkout(head)

    def execute(self) -> dict:
        controls = self.controls
        handoff_value = secrets.token_hex(16)
        handoff_fact = "The synthetic fixture must verify continuity using " + handoff_value + "."
        facts = {"setup": "The fixture tests portable continuity.",
                 "update": "The synthetic fixture completed its Devin setup test.",
                 "end": handoff_fact}
        result: dict[str, object] = {
            "schema_version": 1, "runtime": "devin", "surface": "session", "harness": "cloud-lifecycle",
            "source_sha": self.source_sha, "repository": self.clone.repository,
            "fixture_sha": self.clone.fixture_sha, "branch": self.branch,
            "operator": "harness-exact-digest", "started_at": datetime.now(timezone.utc).isoformat(),
            "phases": {}, "controls": controls,
            "limits": [
                "Skill expansion is evidenced by each proposal's workflow field and kernel output, "
                "not by a session trajectory.",
                "Pending inputs and proposals stay committed under .context-os/ on the run branch "
                "during the handoff.",
                "Cloud sessions have no execution-authorization control; Devin's adherence to the "
                "approval step is observed, not enforced.",
            ],
        }
        self.receipts_seen: set[str] = set()
        sessions: list[str] = []
        try:
            self.api.verify_repository_access()
            controls["repository_access"] = "passed"
            build = self.api.active_build()
            result["active_build_id"] = str(build["build_id"])
            result["fixture_tree"] = self.clone.prepare()
            controls["exact_fixture_commit"] = "passed"
            if self.clone.remote_head(self.branch) is not None:
                raise HarnessError("run branch already exists")
            self.receipts_seen = {path for path in self.clone.snapshot() if path.startswith(RECEIPT_PREFIX)}

            rules = session_rules(self.clone.repository, self.clone.fixture_sha, self.branch)
            session_id, mode = self.create_session(rules + phase_prompt("setup", handoff_fact),
                                                   "Context OS disposable Devin cloud lifecycle", sessions)
            result["devin_mode"] = mode
            result["session_id_sha256"] = sha256_bytes(session_id.encode())
            head, after = self.clone.fixture_sha, set()
            for phase in PHASES:
                if phase != "setup":
                    after = self.send(session_id, phase_prompt(phase, handoff_fact))
                if phase == "start":
                    self.wait_for(session_id, r"CONTEXTOS_PHASE_DONE start\b", after)
                    for _ in range(max(1, self.settle_polls // 2)):
                        if self.clone.remote_head(self.branch) != head:
                            raise HarnessError("start pushed to the run branch")
                        self.sleep(self.poll_interval)
                    controls["start_read_only"] = "passed"
                    continue
                pending_head, proposal = self.proposal_phase(session_id, phase, head, after, facts)
                document, path = proposal["document"], proposal["path"]
                digest = document["proposal_digest"]
                controls[f"{phase}_proposal_before_apply"] = "passed"
                self.clone.checkout(pending_head)
                before = self.clone.snapshot()
                self.wrong_digest_rejected(pending_head, path, digest)
                controls[f"{phase}_wrong_digest_rejected"] = "passed"
                after = self.send(session_id, approval_prompt(phase, path, digest))
                head, applied = self.applied_phase(session_id, phase, pending_head, path, document, before, after)
                controls[f"{phase}_proposal_apply"] = "passed"
                if phase != "setup":
                    self.stale_rejected(head, path, digest)
                    controls[f"{phase}_stale_rejected"] = "passed"
                result["phases"][phase] = {  # type: ignore[index]
                    "proposal": path, "proposal_digest": digest,
                    "proposal_sha256": sha256_bytes((self.clone.root / path).read_bytes()),
                    "pending_head": pending_head, "applied_head": head, **applied,
                }

            handoff_id, _ = self.create_session(handoff_prompt(self.clone.repository, self.branch),
                                                "Context OS disposable Devin cloud handoff", sessions)
            result["handoff_session_id_sha256"] = sha256_bytes(handoff_id.encode())
            answer = self.wait_for(handoff_id, r"CONTEXTOS_PHASE_DONE handoff\b", set())
            result["handoff_answer_sha256"] = sha256_bytes(answer.encode())
            if handoff_value not in answer:
                raise HarnessError("fresh session did not recover the saved next action")
            if self.clone.remote_head(self.branch) != head:
                raise HarnessError("handoff changed the run branch")
            self.clone.checkout(head)
            holders = self.clone.holders(handoff_value)
            if not any(path.startswith("sessions/") for path in holders) or any(
                not path.startswith(("sessions/", ".context-os/")) for path in holders
            ):
                raise HarnessError("handoff value is not held by saved session files")
            controls["handoff"] = "passed"
            result["final_head"] = head

            if self.api.active_build().get("build_id") != result["active_build_id"]:
                raise HarnessError("the active Devin build changed during conformance")
            controls["exact_active_build"] = "passed"
            if repository_source_sha() != self.source_sha:
                raise HarnessError("source commit changed during cloud lifecycle conformance")
            controls["run"] = "passed"
        except Exception as exc:
            controls["run"] = "failed"
            result["failure"] = safe_error_detail(exc)
            raise
        finally:
            cleanup: dict[str, bool] = {}
            errors = []
            for session_id in sessions:
                try:
                    self.api.close_session(session_id, cleanup, sys.exc_info()[1])
                except HarnessError as exc:
                    errors.append(safe_error_detail(exc))
            controls["sessions_closed"] = "passed" if not errors and sessions else ("failed" if errors else "none")
            result["requests"] = list(self.api.client.requests)
            result["finished_at"] = datetime.now(timezone.utc).isoformat()
            self.result = result
            if errors:
                raise HarnessError("; ".join(errors))
        return result


def write_evidence(path: Path, payload: Mapping[str, object]) -> None:
    target = require_outside_source(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise HarnessError(f"refusing to overwrite evidence: {target}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


def run_branch_name() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"lifecycle/{stamp}-{secrets.token_hex(4)}"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository", required=True)
    parser.add_argument("--fixture-sha", required=True)
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--expected-active-build", required=True)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--poll-timeout", type=float, default=1800)
    parser.add_argument("--poll-interval", type=float, default=15)
    parser.add_argument("--allow-live-devin-session", action="store_true")
    parser.add_argument("--allow-fixture-branch-push", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None, *, transport: Transport = default_transport,
    git: GitRunner = default_git, kernel: KernelRunner = default_kernel,
    remote_url: str | None = None, sleep: Callable[[float], None] = time.sleep,
) -> int:
    args = parse_args(argv)
    try:
        if not args.allow_live_devin_session or not args.allow_fixture_branch_push:
            raise HarnessError("cloud lifecycle conformance requires both explicit opt-in flags")
        require_outside_source(args.evidence)
        source_sha = repository_source_sha()
        client = DevinClient(os.environ.get("DEVIN_API_TOKEN", ""), args.org_id, transport=transport)
        api = DevinHarness(
            client, repository=args.repository, fixture_sha=args.fixture_sha, source_sha=source_sha,
            expected_active_build=args.expected_active_build, poll_timeout=args.poll_timeout,
            poll_interval=args.poll_interval,
        )
        workdir = Path(tempfile.mkdtemp(prefix="contextos-devin-cloud-"))
        require_outside_source(workdir)
        try:
            clone = FixtureClone(args.repository, args.fixture_sha, workdir, git=git, remote_url=remote_url)
            harness = CloudLifecycleHarness(
                api, clone, source_sha=source_sha, branch=run_branch_name(), kernel=kernel,
                poll_timeout=args.poll_timeout, poll_interval=args.poll_interval, sleep=sleep,
            )
            try:
                result = harness.execute()
            finally:
                if getattr(harness, "result", None) is not None:
                    write_evidence(args.evidence, harness.result)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    except (HarnessError, OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        print(f"Devin cloud lifecycle conformance failed safely: {safe_error_detail(exc)}", file=sys.stderr)
        return 1
    print(f"Devin cloud lifecycle conformance passed; evidence: {args.evidence}")
    return 0 if result.get("controls", {}).get("run") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
