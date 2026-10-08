from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
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
        self.fixture_sha = git(seed, "rev-parse", "HEAD").strip()


def proposal_document(phase: str, changes: list[dict], serial: int) -> dict:
    document = {"schema_version": 1, "workflow": phase, "serial": serial, "changes": changes}
    document["proposal_digest"] = sha256_text(canonical_json(document))
    return document


class FakeDevin:
    """Simulates the v3 API and a Devin session that pushes to the fixture remote."""

    def __init__(self, remote: Remote, base: Path, faults: set[str]) -> None:
        self.remote, self.base, self.faults = remote, base, faults
        self.sessions: dict[str, dict] = {}
        self.archived: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.build_calls = 0
        self.serial = 0

    # Session simulation -----------------------------------------------------------

    def reply(self, session: dict, text: str) -> None:
        session["events"] += 1
        session["messages"].append({"source": "devin", "message": text,
                                    "event_id": f"{session['id']}-{session['events']}"})

    def commit_push(self, session: dict, message: str) -> None:
        work = session["work"]
        git(work, "commit", "--quiet", "-m", message)
        git(work, "push", "--quiet", "origin", f"HEAD:refs/heads/{session['branch']}")

    def propose(self, session: dict, phase: str, prompt: str) -> None:
        work = session["work"]
        if phase == "setup":
            changes = [
                {"path": "identity/lifecycle-fixture.md", "diff": "+identity",
                 "after_text": "# Synthetic lifecycle identity\n\nThe fixture tests portable continuity.\n"},
                {"path": "state/current.md", "diff": "+priority",
                 "after_text": "# Current State\n\n**Last Updated:** 2026-10-08\n\n## Active priorities\n\n"
                               "1. Verify synthetic portable continuity.\n"},
            ]
        elif phase == "update":
            current = (work / "state/current.md").read_text(encoding="utf-8")
            changes = [{"path": "state/current.md", "diff": "+fact",
                        "after_text": current + "\nThe synthetic fixture completed its Devin setup test.\n"}]
        else:
            fact = re.search(r"Record this exact next action: (.*?\.) Create exactly", prompt).group(1)
            changes = [{"path": "sessions/2026-10-08.md", "diff": "+session",
                        "after_text": "# Session\n\nThe synthetic fixture completed its Devin lifecycle test.\n\n"
                                      "## Next time\n\n" + fact + "\n"}]
        self.serial += 1
        document = proposal_document(phase, changes, self.serial)
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
        for index, change in enumerate(document["changes"]):
            target = work / change["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            content = change["after_text"] + ("tampered\n" if "tamper" in self.faults and index == 0 else "")
            target.write_bytes(content.encode("utf-8"))
        (work / ".context-os/receipts").mkdir(parents=True, exist_ok=True)
        receipt = work / f".context-os/receipts/{document['workflow']}-{document['serial']}.json"
        receipt.write_text(json.dumps({"proposal_digest": digest, "runtime": "devin"}), encoding="utf-8")
        git(work, "add", "-A")
        git(work, "add", "-f", receipt.relative_to(work).as_posix())
        self.commit_push(session, f"{document['workflow']} apply")
        self.reply(session, f"Applied.\nCONTEXTOS_APPLIED {document['workflow']}")

    def handle(self, session: dict, text: str) -> None:
        if session["kind"] == "handoff":
            work = session["work"]
            git(work, "fetch", "--quiet", "origin", session["branch"])
            git(work, "checkout", "--quiet", "--force", "FETCH_HEAD")
            saved = (work / "sessions/2026-10-08.md").read_text(encoding="utf-8")
            value = re.search(r"[0-9a-f]{32}", saved.rsplit("## Next time", 1)[1]).group(0)
            if "handoff_mutates" in self.faults:
                (work / "README.md").write_text("changed\n", encoding="utf-8")
                git(work, "add", "-A")
                self.commit_push(session, "handoff write")
            answer = "Next action: verify continuity" + ("" if "handoff_missing" in self.faults else f" using {value}")
            self.reply(session, answer + "\nCONTEXTOS_PHASE_DONE handoff")
            return
        if text.startswith("Approved after review"):
            self.apply(session, text)
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
            self.reply(session, "Inventory summarized.\nCONTEXTOS_PHASE_DONE start")

    def create(self, prompt: str) -> dict:
        session_id = f"devin-{len(self.sessions) + 1}"
        branch = re.search(r"branch (lifecycle/[0-9A-Za-z-]+)", prompt).group(1)
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
        match = re.fullmatch(r"/sessions/(devin-\d+)(/messages|/archive)?", path)
        assert match, path
        session = self.sessions[match.group(1)]
        if match.group(2) == "/messages" and method == "GET":
            return {"items": list(session["messages"])}
        if match.group(2) == "/messages" and method == "POST":
            self.handle(session, payload["message"])
            return {"ok": True}
        if match.group(2) == "/archive":
            self.archived.append(session["id"])
            return {"session_id": session["id"], "is_archived": True}
        return {"session_id": session["id"], "status": "running"}


def fake_kernel(faults: set[str]):
    def run(args, cwd):
        assert args[0] == "apply" and args[2] == "--confirm"
        document = json.loads((Path(cwd) / args[1]).read_text(encoding="utf-8"))
        if args[3] != document["proposal_digest"]:
            if "wrong_accepted" in faults:
                return subprocess.CompletedProcess(args, 0, "applied", "")
            return subprocess.CompletedProcess(args, 1, "", "apply: --confirm must exactly match the digest")
        applied = all((Path(cwd) / change["path"]).is_file()
                      and (Path(cwd) / change["path"]).read_text(encoding="utf-8") == change["after_text"]
                      for change in document["changes"])
        if applied:
            return subprocess.CompletedProcess(args, 1, "refusing stale proposal; file changed: x", "")
        return subprocess.CompletedProcess(args, 0, "applied", "")
    return run


class DevinCloudLifecycleHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.remote = Remote(self.base)

    def run_harness(self, faults: set[str] = frozenset(), *, opt_ins: bool = True, evidence: Path | None = None):
        devin = FakeDevin(self.remote, self.base, set(faults))
        evidence = evidence or self.base / f"evidence-{len(list(self.base.glob('evidence-*')))}.json"
        argv = ["--repository", REPOSITORY, "--fixture-sha", self.remote.fixture_sha, "--org-id", ORG,
                "--expected-active-build", "build-1", "--evidence", str(evidence),
                "--poll-timeout", "5", "--poll-interval", "0"]
        if opt_ins:
            argv += ["--allow-live-devin-session", "--allow-fixture-branch-push"]
        with mock.patch.object(cloud, "repository_source_sha", return_value="a" * 40), \
                mock.patch.dict(os.environ, {"DEVIN_API_TOKEN": "cog_test"}):
            code = cloud.main(argv, transport=devin, kernel=fake_kernel(set(faults)),
                              remote_url=str(self.remote.bare), sleep=lambda seconds: None)
        stored = json.loads(evidence.read_text(encoding="utf-8")) if evidence.exists() else None
        return code, stored, devin

    def assert_failed(self, faults: set[str], message: str) -> None:
        code, evidence, devin = self.run_harness(faults)
        self.assertEqual(code, 1)
        self.assertEqual(evidence["controls"]["run"], "failed")
        self.assertIn(message, evidence["failure"])
        self.assertTrue(devin.archived, "every created session must be archived after a failure")
        self.assertEqual(sorted(devin.archived), sorted(devin.sessions))

    def test_happy_path_binds_each_phase_and_the_handoff(self) -> None:
        code, evidence, devin = self.run_harness()
        self.assertEqual(code, 0)
        controls = evidence["controls"]
        for key in ("repository_access", "exact_fixture_commit", "start_read_only", "handoff",
                    "exact_active_build", "run", "sessions_closed"):
            self.assertEqual(controls[key], "passed", key)
        for phase in ("setup", "update", "end"):
            self.assertEqual(controls[f"{phase}_proposal_before_apply"], "passed")
            self.assertEqual(controls[f"{phase}_wrong_digest_rejected"], "passed")
            self.assertEqual(controls[f"{phase}_proposal_apply"], "passed")
            record = evidence["phases"][phase]
            self.assertEqual(record["receipt_proposal_digest"], record["proposal_digest"])
            self.assertEqual(record["receipt_runtime"], "devin")
        self.assertEqual(controls["update_stale_rejected"], "passed")
        self.assertEqual(controls["end_stale_rejected"], "passed")
        self.assertEqual(evidence["active_build_id"], "build-1")
        self.assertRegex(evidence["branch"], r"^lifecycle/\d{8}T\d{6}Z-[0-9a-f]{8}$")
        self.assertEqual(len(devin.archived), 2)
        stored = json.dumps(evidence)
        self.assertNotIn("Next action", stored)
        self.assertNotIn("devin-1", stored)

    def test_receipt_pushed_before_approval_fails(self) -> None:
        self.assert_failed({"receipt_before_approval"}, "beyond new pending inputs and proposals")

    def test_wrong_digest_must_be_rejected(self) -> None:
        self.assert_failed({"wrong_accepted"}, "wrong digest was not rejected")

    def test_applied_content_mismatch_fails(self) -> None:
        self.assert_failed({"tamper"}, "unexpected files or produced incorrect content")

    def test_start_must_not_push(self) -> None:
        self.assert_failed({"start_pushes"}, "start pushed")

    def test_handoff_must_recover_value(self) -> None:
        self.assert_failed({"handoff_missing"}, "did not recover the saved next action")

    def test_handoff_must_not_change_branch(self) -> None:
        self.assert_failed({"handoff_mutates"}, "handoff changed the run branch")

    def test_active_build_change_fails(self) -> None:
        self.assert_failed({"build_changes"}, "active Devin build")

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
