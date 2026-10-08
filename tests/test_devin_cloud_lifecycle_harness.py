from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "adapters/devin/cloud_lifecycle_conformance.py"
SPEC = importlib.util.spec_from_file_location("contextos_devin_cloud_lifecycle", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
cloud = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cloud
SPEC.loader.exec_module(cloud)

from contextos.kernel import sha256_text  # noqa: E402
from contextos.primitives import canonical_json  # noqa: E402

ORG = "org-test"
REPOSITORY = "conorbronsdon/contextos-devin-cloud-fixture"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "-c", "core.autocrlf=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout


def file_sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class Remote:
    """A local bare repository standing in for the public fixture."""

    def __init__(self, base: Path) -> None:
        self.bare = base / "remote.git"
        seed = base / "seed"
        seed.mkdir()
        git(base, "init", "--quiet", "--bare", "--initial-branch=main", str(self.bare))
        git(seed, "init", "--quiet", "--initial-branch=main")
        (seed / "README.md").write_text("# Template\n", encoding="utf-8")
        (seed / "state").mkdir()
        (seed / "state/current.md").write_text("# Current State\n", encoding="utf-8")
        (seed / ".gitignore").write_text(".context-os/\n", encoding="utf-8")
        git(seed, "add", "-A")
        git(seed, "commit", "--quiet", "-m", "template")
        git(seed, "remote", "add", "origin", str(self.bare))
        git(seed, "push", "--quiet", "origin", "main")
        self.seed = seed
        self.fixture_sha = git(seed, "rev-parse", "HEAD").strip()


class FakeClock:
    """Shared test clock: sleep advances it, so the approval hold is exercised."""

    def __init__(self) -> None:
        self.offset = 0.0

    def now(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(seconds=self.offset)

    def sleep(self, seconds: float) -> None:
        self.offset += max(seconds, 0)


CLOCK = FakeClock()


def proposal_document(phase: str, changes: list[dict], serial: int) -> dict:
    document = {"schema_version": 1, "workflow": phase, "proposal_id": f"{phase}-{serial}",
                "serial": serial, "created_at": CLOCK.now().isoformat(), "changes": changes}
    document["proposal_digest"] = sha256_text(canonical_json(document))
    return document


def kernel_simulator(faults: set[str], devin: "FakeDevin | None" = None):
    """A stand-in for the fixture kernel's apply: digest gate, stale gate, receipt."""

    def run(args, cwd):
        cwd = Path(cwd)
        assert args[0] == "apply" and args[2] == "--confirm" and args[4] == "--runtime"
        document = json.loads((cwd / args[1]).read_text(encoding="utf-8"))
        if args[3] != document["proposal_digest"]:
            if devin is not None and "push_before_approval" in faults:
                devin.push_extra()
            if "wrong_accepted" in faults:
                return subprocess.CompletedProcess(args, 0, "applied", "")
            return subprocess.CompletedProcess(args, 1, "", "apply: --confirm must exactly match the proposal_digest")
        for change in document["changes"]:
            if file_sha(cwd / change["path"]) != change["sha256_before"]:
                return subprocess.CompletedProcess(
                    args, 1, f"refusing stale proposal; file changed: {change['path']}", "")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
                              text=True, check=True).stdout.strip()
        changed = []
        for change in document["changes"]:
            target = cwd / change["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(change["after_text"].encode("utf-8"))
            changed.append({"path": change["path"], "sha256_before": change["sha256_before"],
                            "sha256_after": file_sha(target)})
        (cwd / ".context-os/receipts").mkdir(parents=True, exist_ok=True)
        (cwd / ".context-os/journal.log").write_text("kernel-internal\n", encoding="utf-8")
        receipt = {"schema_version": 1, "proposal_id": document["proposal_id"],
                   "proposal_digest": document["proposal_digest"], "runtime": args[5],
                   "files_changed": changed, "git_head_before": head, "git_head_after": head,
                   "invariants_checked": ["workflow-path-policy"],
                   "applied_at": CLOCK.now().isoformat()}
        (cwd / f".context-os/receipts/{document['proposal_id']}.json").write_text(
            json.dumps(receipt), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "applied", "")

    return run


class FakeDevin:
    """Simulates the v3 API and a Devin session that pushes to the fixture remote."""

    def __init__(self, remote: Remote, base: Path, faults: set[str]) -> None:
        self.remote, self.base, self.faults = remote, base, faults
        self.kernel = kernel_simulator(faults)
        self.sessions: dict[str, dict] = {}
        self.archived: list[str] = []
        self.terminated: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.build_calls = 0
        self.serial = 0

    # Session simulation -----------------------------------------------------------

    def reply(self, session: dict, text: str) -> None:
        session["events"] += 1
        session["messages"].append({"source": "devin", "message": text,
                                    "event_id": f"{session['id']}-{session['events']}"})

    def commit_push(self, session: dict, message: str, ref: str | None = None) -> None:
        work = session["work"]
        git(work, "commit", "--quiet", "-m", message)
        git(work, "push", "--quiet", "origin", f"HEAD:refs/heads/{ref or session['branch']}")

    def lifecycle(self) -> dict:
        return next(s for s in self.sessions.values() if s["kind"] == "lifecycle")

    def push_extra(self) -> None:
        session = self.lifecycle()
        work = session["work"]
        (work / ".context-os/inputs/extra.json").write_text("{}", encoding="utf-8")
        git(work, "add", "-f", ".context-os/inputs/extra.json")
        self.commit_push(session, "extra pending input")

    def propose(self, session: dict, phase: str, prompt: str) -> None:
        work = session["work"]

        def change(path: str, after_text: str, diff: str) -> dict:
            return {"path": path, "diff": diff, "after_text": after_text,
                    "sha256_before": file_sha(work / path)}

        if phase == "setup":
            changes = [
                change("identity/lifecycle-fixture.md",
                       "# Synthetic lifecycle identity\n\nThe fixture tests portable continuity.\n", "+identity"),
                change("state/current.md",
                       "# Current State\n\n**Last Updated:** 2026-10-08\n\n## Active priorities\n\n"
                       "1. Verify synthetic portable continuity.\n", "+priority"),
            ]
            if "setup_touches_agents" in self.faults:
                changes.append(change("AGENTS.md", "# Rewritten\n", "+agents"))
        elif phase == "update":
            changes = [change("sessions/2026-10-08.md",
                              "# Session\n\nThe synthetic fixture completed its Devin setup test.\n", "+fact")]
        else:
            fact = re.search(r"Record this exact next action: (.*?\.) Create exactly", prompt).group(1)
            current = (work / "sessions/2026-10-08.md").read_text(encoding="utf-8")
            changes = [change("sessions/2026-10-08.md",
                              current + "\nThe synthetic fixture completed its Devin lifecycle test.\n\n"
                              "## Next time\n\n" + fact + "\n", "+session")]
        self.serial += 1
        document = proposal_document(phase, changes, self.serial)
        if "early_apply_reverted" in self.faults and phase == "setup":
            originals = {c["path"]: (work / c["path"]).read_bytes() if (work / c["path"]).is_file() else None
                         for c in changes}
            for c in changes:
                (work / c["path"]).parent.mkdir(parents=True, exist_ok=True)
                (work / c["path"]).write_text(c["after_text"], encoding="utf-8")
            (work / ".context-os/receipts").mkdir(parents=True, exist_ok=True)
            (work / ".context-os/receipts/early.json").write_text("{}", encoding="utf-8")
            git(work, "add", "-A")
            git(work, "add", "-f", ".context-os/receipts/early.json")
            git(work, "commit", "--quiet", "-m", "early apply")
            for path, original in originals.items():
                if original is None:
                    (work / path).unlink()
                else:
                    (work / path).write_bytes(original)
            git(work, "rm", "--quiet", "--cached", ".context-os/receipts/early.json")
            (work / ".context-os/receipts/early.json").unlink()
            git(work, "add", "-A")
            git(work, "commit", "--quiet", "-m", "revert early apply")
        relative = f".context-os/proposals/{phase}-{self.serial}.json"
        (work / ".context-os/proposals").mkdir(parents=True, exist_ok=True)
        (work / ".context-os/inputs").mkdir(parents=True, exist_ok=True)
        (work / relative).write_text(json.dumps(document), encoding="utf-8")
        (work / f".context-os/inputs/{phase}-{self.serial}.json").write_text("{}", encoding="utf-8")
        git(work, "add", "-f", ".context-os/proposals", ".context-os/inputs")
        if "receipt_before_approval" in self.faults and phase == "setup":
            (work / ".context-os/receipts").mkdir(parents=True, exist_ok=True)
            (work / ".context-os/receipts/early.json").write_text(
                json.dumps({"proposal_digest": document["proposal_digest"], "runtime": "devin"}), encoding="utf-8")
            git(work, "add", "-f", ".context-os/receipts")
        self.commit_push(session, f"{phase} proposal")
        self.reply(session, f"Proposal ready.\nCONTEXTOS_PHASE_DONE {phase} {document['proposal_digest']}")

    def apply(self, session: dict, text: str) -> None:
        work = session["work"]
        match = re.search(r"proposal (\S+) with exact digest ([0-9a-f]{64})", text)
        path, digest = match.group(1), match.group(2)
        document = json.loads((work / path).read_text(encoding="utf-8"))
        assert document["proposal_digest"] == digest
        if "early_ack" in self.faults:
            self.reply(session, f"I'll reply with `CONTEXTOS_APPLIED {document['workflow']}` when done.")
            return
        receipt = work / f".context-os/receipts/{document['proposal_id']}.json"
        if "fabricated_receipt" in self.faults:
            for change in document["changes"]:
                target = work / change["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(change["after_text"].encode("utf-8"))
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(json.dumps({"proposal_digest": digest, "runtime": "devin"}), encoding="utf-8")
        else:
            result = self.kernel(["apply", path, "--confirm", digest, "--runtime", "devin"], work)
            assert result.returncode == 0, result
            (work / ".context-os/journal.log").unlink(missing_ok=True)
            if "tamper" in self.faults:
                first = work / document["changes"][0]["path"]
                first.write_bytes(first.read_bytes() + b"tampered\n")
            if "applied_before_approval" in self.faults:
                data = json.loads(receipt.read_text(encoding="utf-8"))
                # Applied right after the proposal was created, before approval.
                data["applied_at"] = (datetime.fromisoformat(document["created_at"])
                                      + timedelta(seconds=1)).isoformat()
                receipt.write_text(json.dumps(data), encoding="utf-8")
        git(work, "add", "-A")
        git(work, "add", "-f", receipt.relative_to(work).as_posix())
        self.commit_push(session, f"{document['workflow']} apply")
        self.reply(session, f"Applied.\nCONTEXTOS_APPLIED {document['workflow']}")

    def make_handoff_branch(self, session: dict, text: str) -> None:
        work = session["work"]
        handoff = re.search(r"orphan branch (handoff/[0-9A-Za-z-]+)", text).group(1)
        if "handoff_parent" in self.faults:
            git(work, "checkout", "--quiet", "-b", handoff)
        else:
            git(work, "checkout", "--quiet", "--orphan", handoff)
        if "handoff_pending" not in self.faults:
            git(work, "rm", "-r", "--cached", "--quiet", ".context-os/inputs", ".context-os/proposals")
            shutil.rmtree(work / ".context-os/inputs")
            shutil.rmtree(work / ".context-os/proposals")
        self.commit_push(session, "handoff", ref=handoff)
        self.reply(session, f"Handoff branch ready.\n{cloud.HANDOFF_READY}")

    def handle(self, session: dict, text: str) -> None:
        if session["kind"] == "handoff":
            work = session["work"]
            git(work, "fetch", "--quiet", "origin", session["branch"])
            git(work, "checkout", "--quiet", "--force", "FETCH_HEAD")
            saved = (work / "sessions/2026-10-08.md").read_text(encoding="utf-8")
            sentence = saved.rsplit("## Next time", 1)[1].strip()
            value = re.search(r"[0-9a-f]{32}", sentence).group(0)
            if "handoff_mutates" in self.faults:
                (work / "README.md").write_text("changed\n", encoding="utf-8")
                git(work, "add", "-A")
                self.commit_push(session, "handoff write")
            if "handoff_missing" in self.faults:
                answer = "Next action: verify continuity"
            elif "handoff_token_only" in self.faults:
                answer = f"The value is {value}"
            else:
                answer = f"Next action:\n{sentence}"
            self.reply(session, answer + "\nCONTEXTOS_PHASE_DONE handoff")
            return
        if text.startswith("Approved after review"):
            self.apply(session, text)
            return
        if text.startswith("Create an orphan branch"):
            self.make_handoff_branch(session, text)
            return
        for phase in ("setup", "update", "end"):
            if f"@skills:context-{phase}" in text:
                self.propose(session, phase, text)
                return
        if "@skills:context-start" in text:
            if "start_pushes" in self.faults:
                (session["work"] / "README.md").write_text("start wrote\n", encoding="utf-8")
                git(session["work"], "add", "-A")
                self.commit_push(session, "start write")
            if "push_main" in self.faults:
                seed = self.remote.seed
                (seed / "README.md").write_text("# Template changed\n", encoding="utf-8")
                git(seed, "commit", "--quiet", "-am", "main write")
                git(seed, "push", "--quiet", "origin", "main")
            self.reply(session, "Inventory summarized.\nCONTEXTOS_PHASE_DONE start")

    def create(self, prompt: str) -> dict:
        session_id = f"{len(self.sessions) + 1:032x}"
        branch = re.search(r"branch ((?:lifecycle|handoff)/[0-9A-Za-z-]+)", prompt).group(1)
        work = self.base / session_id
        git(self.base, "clone", "--quiet", str(self.remote.bare), str(work))
        session = {"id": session_id, "branch": branch, "work": work, "messages": [], "events": 0,
                   "kind": "handoff" if "existing branch" in prompt else "lifecycle"}
        if session["kind"] == "lifecycle":
            git(work, "checkout", "--quiet", "-b", branch, self.remote.fixture_sha)
        self.sessions[session_id] = session
        self.handle(session, prompt)
        return {"session_id": session_id, "org_id": ORG, "devin_mode": "agent"}

    # Transport --------------------------------------------------------------------

    def __call__(self, method, url, payload, headers, timeout):
        parsed = urllib.parse.urlsplit(url)
        path = parsed.path
        self.calls.append((method, path))
        beta = f"/v3beta1/organizations/{ORG}"
        if path in (beta + "/snapshot-setup/builds", beta + "/repositories"):
            path = path[len(beta):]
        else:
            prefix = f"/v3/organizations/{ORG}"
            assert path.startswith(prefix), path
            path = path[len(prefix):]
        if path == "/snapshot-setup/builds":
            self.build_calls += 1
            build = "build-2" if "build_changes" in self.faults and self.build_calls > 1 else "build-1"
            return {"items": [{"build_id": build, "status": "succeeded"}]}
        if path == "/repositories":
            return {"items": [{"repo_path": REPOSITORY}]}
        if path == "/sessions" and method == "POST":
            return self.create(payload["prompt"])
        match = re.fullmatch(r"/sessions/([0-9a-f]{32})(/messages|/archive)?", path)
        assert match, path
        session = self.sessions[match.group(1)]
        if match.group(2) == "/messages" and method == "GET":
            if "error_with_id" in self.faults and session["kind"] == "lifecycle" and session["events"] >= 1:
                raise cloud.HarnessError(f"session {session['id']} not found in {ORG}")
            return {"items": list(session["messages"])}
        if match.group(2) == "/messages" and method == "POST":
            self.handle(session, payload["message"])
            return {"ok": True}
        if match.group(2) == "/archive":
            if "archive_urlerror_first" in self.faults and session["id"] == f"{1:032x}":
                raise urllib.error.URLError("network unreachable")
            self.archived.append(session["id"])
            return {"session_id": session["id"], "is_archived": True}
        if method == "DELETE":
            self.terminated.append(session["id"])
            return {"session_id": session["id"], "status": "exit"}
        return {"session_id": session["id"], "status": "running"}


class DevinCloudLifecycleHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.remote = Remote(self.base)

    def run_harness(self, faults: set[str] = frozenset(), *, opt_ins: bool = True, evidence: Path | None = None,
                    poll_timeout: str = "5"):
        devin = FakeDevin(self.remote, self.base, set(faults))
        evidence = evidence or self.base / f"evidence-{len(list(self.base.glob('evidence-*')))}.json"
        argv = ["--repository", REPOSITORY, "--fixture-sha", self.remote.fixture_sha, "--org-id", ORG,
                "--expected-active-build", "build-1", "--evidence", str(evidence),
                "--poll-timeout", poll_timeout, "--poll-interval", "0"]
        if opt_ins:
            argv += ["--allow-live-devin-session", "--allow-fixture-branch-push"]
        with mock.patch.object(cloud, "repository_source_sha", return_value="a" * 40), \
                mock.patch.dict(os.environ, {"DEVIN_API_TOKEN": "cog_test"}):
            code = cloud.main(argv, transport=devin, kernel=kernel_simulator(set(faults), devin),
                              remote_url=str(self.remote.bare), sleep=CLOCK.sleep, clock=CLOCK.now)
        stored = json.loads(evidence.read_text(encoding="utf-8")) if evidence.exists() else None
        return code, stored, devin

    def assert_failed(self, faults: set[str], message: str, **kwargs) -> dict:
        code, evidence, devin = self.run_harness(faults, **kwargs)
        self.assertEqual(code, 1)
        self.assertEqual(evidence["controls"]["run"], "failed")
        self.assertIn(message, evidence["failure"])
        self.assertTrue(devin.archived, "every created session must be archived after a failure")
        self.assertEqual(sorted(devin.archived), sorted(devin.sessions))
        return evidence

    def test_happy_path_binds_each_phase_and_the_handoff(self) -> None:
        code, evidence, devin = self.run_harness()
        self.assertEqual(code, 0, evidence.get("failure"))
        controls = evidence["controls"]
        for key in ("repository_access", "exact_fixture_commit", "start_read_only", "handoff",
                    "handoff_branch_isolated", "refs_unchanged", "exact_active_build", "run",
                    "sessions_closed"):
            self.assertEqual(controls[key], "passed", key)
        for phase in ("setup", "update", "end"):
            for name in ("proposal_before_apply", "no_preapproval_commits", "path_scope",
                         "kernel_wrong_digest_rejected", "proposal_apply", "receipt_matches_replay",
                         "applied_after_approval"):
                self.assertEqual(controls[f"{phase}_{name}"], "passed", f"{phase}_{name}")
            record = evidence["phases"][phase]
            self.assertEqual(record["receipt_proposal_digest"], record["proposal_digest"])
            self.assertEqual(record["receipt_runtime"], "devin")
            self.assertTrue(record["receipt_matches_replay"])
        self.assertEqual(controls["update_kernel_stale_rejected"], "passed")
        self.assertEqual(controls["end_kernel_stale_rejected"], "passed")
        self.assertNotIn("setup_kernel_stale_rejected", controls)
        self.assertEqual(evidence["active_build_id"], "build-1")
        self.assertEqual(evidence["approval_hold_seconds"], cloud.APPROVAL_HOLD_SECONDS)
        for phase in ("setup", "update", "end"):
            record = evidence["phases"][phase]
            self.assertGreaterEqual(record["harness_push_to_approval_seconds"], cloud.APPROVAL_HOLD_SECONDS)
            self.assertGreaterEqual(record["devin_proposal_to_apply_seconds"],
                                    record["harness_push_to_approval_seconds"] - cloud.ORDERING_TOLERANCE_SECONDS)
        self.assertRegex(evidence["branch"], r"^lifecycle/\d{8}T\d{6}Z-[0-9a-f]{8}$")
        self.assertEqual(evidence["handoff_branch"], "handoff/" + evidence["branch"].split("/", 1)[1])
        self.assertEqual(len(devin.archived), 2)
        stored = json.dumps(evidence)
        self.assertNotIn("Next action", stored)
        for session_id in devin.sessions:
            self.assertNotIn(session_id, stored)

    def test_receipt_pushed_before_approval_fails(self) -> None:
        self.assert_failed({"receipt_before_approval"}, "beyond new pending inputs and proposals")

    def test_early_apply_reverted_in_intermediate_commits_fails(self) -> None:
        self.assert_failed({"early_apply_reverted"}, "pushed a commit beyond new pending inputs")

    def test_push_after_proposal_before_approval_fails(self) -> None:
        self.assert_failed({"push_before_approval"}, "moved after the proposal and before approval")

    def test_fabricated_receipt_fails_independent_replay(self) -> None:
        self.assert_failed({"fabricated_receipt"}, "does not match an independent kernel replay")

    def test_receipt_timestamp_before_approval_fails(self) -> None:
        self.assert_failed({"applied_before_approval"}, "before the approval was sent")

    def test_setup_outside_path_scope_fails(self) -> None:
        self.assert_failed({"setup_touches_agents"}, "outside its allowed scope")

    def test_wrong_digest_must_be_rejected(self) -> None:
        self.assert_failed({"wrong_accepted"}, "wrong digest was not rejected")

    def test_applied_content_mismatch_fails(self) -> None:
        self.assert_failed({"tamper"}, "unexpected files or produced incorrect content")

    def test_start_must_not_push(self) -> None:
        self.assert_failed({"start_pushes"}, "start pushed")

    def test_push_to_main_fails_refs_check(self) -> None:
        self.assert_failed({"push_main"}, "refs changed outside the run and handoff branches")

    def test_handoff_branch_must_be_parentless(self) -> None:
        self.assert_failed({"handoff_parent"}, "not a single parentless commit")

    def test_handoff_branch_must_drop_pending_artifacts(self) -> None:
        self.assert_failed({"handoff_pending"}, "without pending artifacts")

    def test_handoff_must_recover_value(self) -> None:
        self.assert_failed({"handoff_missing"}, "did not recover the saved next action")

    def test_handoff_token_alone_is_not_the_next_action(self) -> None:
        self.assert_failed({"handoff_token_only"}, "did not recover the saved next action")

    def test_handoff_must_not_change_branch(self) -> None:
        self.assert_failed({"handoff_mutates"}, "handoff changed the handoff branch")

    def test_active_build_change_fails(self) -> None:
        self.assert_failed({"build_changes"}, "active Devin build")

    def test_marker_in_an_early_acknowledgement_is_not_counted(self) -> None:
        self.assert_failed({"early_ack"}, "timed out waiting", poll_timeout="1")

    def test_failure_text_redacts_session_and_org_ids(self) -> None:
        evidence = self.assert_failed({"error_with_id"}, "not found")
        self.assertNotIn(f"{1:032x}", evidence["failure"])
        self.assertNotIn(ORG, evidence["failure"])
        self.assertIn("{devin_id}", evidence["failure"])

    def test_cleanup_network_error_still_closes_every_session(self) -> None:
        code, evidence, devin = self.run_harness({"archive_urlerror_first"})
        self.assertEqual(code, 1)
        self.assertEqual(evidence["controls"]["run"], "failed")
        self.assertEqual(evidence["controls"]["sessions_closed"], "failed")
        self.assertEqual(devin.terminated, [f"{1:032x}"])
        self.assertEqual(devin.archived, [f"{2:032x}"])
        self.assertTrue(evidence["cleanup_errors"])
        self.assertNotIn(f"{1:032x}", json.dumps(evidence))

    def test_redaction_keeps_shas_and_digests(self) -> None:
        harness = cloud.CloudLifecycleHarness.__new__(cloud.CloudLifecycleHarness)
        harness.sessions = ["abc"]
        harness.api = mock.Mock()
        harness.api.client.org_id = ORG
        sha, digest, session = "1" * 40, "2" * 64, "3" * 32
        text = harness.redact(f"{ORG} abc {sha} {digest} {session}")
        self.assertEqual(text, f"{{org_id}} {{devin_id}} {sha} {digest} {{id}}")

    def test_opt_ins_are_required_before_any_call(self) -> None:
        code, evidence, devin = self.run_harness(opt_ins=False)
        self.assertEqual(code, 1)
        self.assertIsNone(evidence)
        self.assertEqual(devin.calls, [])

    def test_evidence_inside_source_is_refused_before_any_call(self) -> None:
        code, evidence, devin = self.run_harness(evidence=ROOT / "cloud-evidence.json")
        self.assertEqual(code, 1)
        self.assertFalse((ROOT / "cloud-evidence.json").exists())
        self.assertEqual(devin.calls, [])

    def test_source_never_pushes_or_writes_github(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in ('"push"', "'push'", "api.github.com", "devinreview.com"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
