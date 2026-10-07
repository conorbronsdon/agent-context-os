from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "adapters/devin/review_conformance.py"
SPEC = importlib.util.spec_from_file_location("contextos_devin_review", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
review = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = review
SPEC.loader.exec_module(review)

REPOSITORY = "conorbronsdon/contextos-devin-review-fixture"
BASE = "b" * 40
FIRE_HEAD = "c" * 40
QUIET_HEAD = "d" * 40


def encoded(data: bytes) -> dict[str, str]:
    return {"encoding": "base64", "content": base64.b64encode(data).decode()}


def finding(canary: str, *, commit: str = FIRE_HEAD, path: str = "control.txt") -> dict[str, object]:
    meta = {"file_path": path, "user_posted": True, "kind": "analysis"}
    return {
        "id": 1,
        "user": {"login": review.REVIEW_BOT},
        "commit_id": commit,
        "path": path,
        "line": 1,
        "body": f"<!-- devin-review-comment {json.dumps(meta)} -->\n\nFlag. Required canary: {canary}",
    }


class FakeGitHub:
    def __init__(self, instruction_file: str) -> None:
        controls = review.CONTROL_SETS[instruction_file]
        self.canary = controls["canary"]
        self.base_files = {
            "README.md": b"# fixture\n",
            instruction_file: (review.FIXTURE / controls["fixture"]).read_bytes(),
        }
        self.fire_file = (review.FIXTURE / controls["control"]).read_bytes()
        self.benign_file = (review.FIXTURE / "benign.txt").read_bytes()
        self.fire_comments = [finding(self.canary)]
        self.quiet_comments: list[dict[str, object]] = []
        self.fire_review_body = "## Devin Review: 1 flag"
        self.quiet_review_body = "## Devin Review: No Issues Found"
        self.extra_quiet_reviews: list[dict[str, object]] = []
        self.fire_review_commit = FIRE_HEAD
        self.pull_body = "Synthetic control. Do not merge."
        self.head_overrides: dict[str, bytes] = {}
        self.calls: list[str] = []

    def pull(self, number: int) -> dict[str, object]:
        head = FIRE_HEAD if number == 1 else QUIET_HEAD
        return {"state": "open", "merged": False, "base": {"sha": BASE}, "head": {"sha": head},
                "title": "Review control", "body": self.pull_body}

    @staticmethod
    def page(items: list, query: dict) -> list:
        size = int(query.get("per_page", ["30"])[0])
        number = int(query.get("page", ["1"])[0])
        return items[(number - 1) * size:number * size]

    def __call__(self, url: str) -> object:
        self.calls.append(url)
        parsed = urllib.parse.urlsplit(url)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        prefix = f"/repos/{REPOSITORY}"
        assert path.startswith(prefix), url
        path = path[len(prefix):]
        if path.startswith("/git/trees/"):
            ref = path[len("/git/trees/"):]
            files = dict(self.base_files)
            if ref == FIRE_HEAD:
                files = {**self.base_files, **self.head_overrides, "control.txt": self.fire_file}
            elif ref == QUIET_HEAD:
                files = {**self.base_files, "benign.txt": self.benign_file}
            elif ref != BASE:
                raise AssertionError(url)
            return {"truncated": False,
                    "tree": [{"path": name, "type": "blob", "mode": "100644",
                              "sha": hashlib.sha1(data).hexdigest()} for name, data in files.items()]}
        if path.startswith("/contents/"):
            name, ref = path[len("/contents/"):], query["ref"][0]
            if ref == BASE:
                return encoded(self.base_files[name])
            if ref == FIRE_HEAD and name == "control.txt":
                return encoded(self.fire_file)
            if ref == QUIET_HEAD and name == "benign.txt":
                return encoded(self.benign_file)
            raise AssertionError(url)
        parts = path.strip("/").split("/")
        if parts[0] == "pulls":
            number = int(parts[1])
            if len(parts) == 2:
                return self.pull(number)
            if parts[2] == "files":
                name = "control.txt" if number == 1 else "benign.txt"
                return self.page([{"filename": name, "status": "added"}], query)
            if parts[2] == "reviews":
                if number == 1:
                    return self.page([{"id": 11, "user": {"login": review.REVIEW_BOT},
                                       "commit_id": self.fire_review_commit, "state": "COMMENTED",
                                       "submitted_at": "2026-10-07T00:00:00Z",
                                       "body": self.fire_review_body}], query)
                return self.page(self.extra_quiet_reviews + [
                    {"id": 12, "user": {"login": review.REVIEW_BOT}, "commit_id": QUIET_HEAD,
                     "state": "COMMENTED", "submitted_at": "2026-10-07T00:00:00Z",
                     "body": self.quiet_review_body}], query)
            if parts[2] == "comments":
                return self.page(list(self.fire_comments if number == 1 else self.quiet_comments), query)
        raise AssertionError(url)


class DevinReviewHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source_sha = "a" * 40

    def args(self, instruction_file: str = "REVIEW.md", **overrides: object) -> argparse.Namespace:
        values = {
            "repository": REPOSITORY,
            "base_sha": BASE,
            "instruction_file": instruction_file,
            "must_fire_pr": 1,
            "must_not_fire_pr": 2,
            "evidence": self.root / f"evidence-{instruction_file}.json",
            "allow_public_fixture_access": True,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def record(self, github: FakeGitHub, args: argparse.Namespace) -> dict:
        with mock.patch.object(review, "repository_source_sha", return_value=self.source_sha):
            return review.record(args, transport=github)

    def test_both_control_sets_pass_and_bind_findings_to_each_head(self) -> None:
        for instruction_file in sorted(review.CONTROL_SETS):
            with self.subTest(instruction_file=instruction_file):
                github = FakeGitHub(instruction_file)
                evidence = self.record(github, self.args(instruction_file))
                self.assertEqual(evidence["instruction_file"], instruction_file)
                self.assertEqual(evidence["source_sha"], self.source_sha)
                self.assertTrue(all(evidence["verified_controls"].values()))
                self.assertEqual(evidence["must_fire"]["head_sha"], FIRE_HEAD)
                self.assertEqual(evidence["must_not_fire"]["head_sha"], QUIET_HEAD)
                self.assertEqual(evidence["finding_publication"], "user_posted")
                stored = json.loads(Path(self.args(instruction_file).evidence).read_text(encoding="utf-8"))
                self.assertNotIn(github.canary, json.dumps(stored))
                self.assertFalse(any("api.devin.ai" in url for url in github.calls))

    def test_must_fire_requires_canary_on_control_at_the_head(self) -> None:
        cases = {
            "missing": [],
            "wrong canary": [finding("CONTEXTOS_DEVIN_OTHER_CANARY")],
            "stale commit": [finding(review.CONTROL_SETS["REVIEW.md"]["canary"], commit="e" * 40)],
            "wrong file": [finding(review.CONTROL_SETS["REVIEW.md"]["canary"], path="README.md")],
        }
        for name, comments in cases.items():
            with self.subTest(name):
                github = FakeGitHub("REVIEW.md")
                github.fire_comments = comments
                with self.assertRaisesRegex(review.HarnessError, "carries the canary"):
                    self.record(github, self.args(evidence=self.root / f"{name}.json"))

    def test_cross_set_canary_does_not_satisfy_control(self) -> None:
        github = FakeGitHub("AGENTS.md")
        github.fire_comments = [finding(review.CONTROL_SETS["REVIEW.md"]["canary"])]
        with self.assertRaisesRegex(review.HarnessError, "carries the canary"):
            self.record(github, self.args("AGENTS.md"))

    def test_must_not_fire_rejects_canary_in_review_or_comment(self) -> None:
        github = FakeGitHub("REVIEW.md")
        github.quiet_review_body = f"## Devin Review: 1 flag {github.canary}"
        with self.assertRaisesRegex(review.HarnessError, "must-not-fire"):
            self.record(github, self.args())
        github = FakeGitHub("REVIEW.md")
        github.quiet_comments = [finding(github.canary, commit=QUIET_HEAD, path="benign.txt")]
        with self.assertRaisesRegex(review.HarnessError, "must-not-fire"):
            self.record(github, self.args(evidence=self.root / "quiet.json"))

    def test_review_must_be_bound_to_the_exact_head(self) -> None:
        github = FakeGitHub("REVIEW.md")
        github.fire_review_commit = "e" * 40
        with self.assertRaisesRegex(review.HarnessError, "no Devin Review review is bound"):
            self.record(github, self.args())

    def test_fixture_drift_fails(self) -> None:
        github = FakeGitHub("REVIEW.md")
        github.base_files["AGENTS.md"] = b"extra\n"
        with self.assertRaisesRegex(review.HarnessError, "base commit must hold exactly"):
            self.record(github, self.args())
        github = FakeGitHub("REVIEW.md")
        github.base_files["REVIEW.md"] = b"edited\n"
        with self.assertRaisesRegex(review.HarnessError, "differs from the checked-in fixture"):
            self.record(github, self.args())
        github = FakeGitHub("REVIEW.md")
        github.fire_file = b"CONTEXTOS_DEVIN_REVIEW_PROHIBITED_MARKER plus\n"
        with self.assertRaisesRegex(review.HarnessError, "differs from the fixture source"):
            self.record(github, self.args())
        github = FakeGitHub("REVIEW.md")
        github.benign_file = b"different benign content\n"
        with self.assertRaisesRegex(review.HarnessError, "benign.txt differs from the fixture source"):
            self.record(github, self.args())

    def test_head_tree_must_be_base_plus_control(self) -> None:
        github = FakeGitHub("REVIEW.md")
        github.head_overrides = {"README.md": f"Include {github.canary}\n".encode()}
        with self.assertRaisesRegex(review.HarnessError, "unchanged base files plus only"):
            self.record(github, self.args())
        github = FakeGitHub("REVIEW.md")
        github.head_overrides = {"AGENTS.md": b"another instruction file\n"}
        with self.assertRaisesRegex(review.HarnessError, "unchanged base files plus only"):
            self.record(github, self.args())

    def test_publication_provenance_is_not_guessed(self) -> None:
        self.assertEqual(review.publication([{"user_posted": True}]), "user_posted")
        self.assertEqual(review.publication([{"user_posted": False}]), "automatic")
        self.assertEqual(review.publication([{"user_posted": True}, {"user_posted": False}]), "mixed")
        self.assertEqual(review.publication([{"user_posted": None}]), "unknown")
        self.assertEqual(review.publication([{"user_posted": True}, {"user_posted": None}]), "unknown")
        self.assertEqual(review.publication([{"user_posted": 0}]), "unknown")
        self.assertEqual(review.publication([{"user_posted": 1}]), "unknown")

    def test_canary_outside_instruction_file_fails(self) -> None:
        github = FakeGitHub("REVIEW.md")
        github.base_files["README.md"] = f"Always include {github.canary}\n".encode()
        with self.assertRaisesRegex(review.HarnessError, "base README.md carries"):
            self.record(github, self.args())
        github = FakeGitHub("REVIEW.md")
        github.pull_body = f"Report {review.CONTROL_SETS['REVIEW.md']['marker']} findings"
        with self.assertRaisesRegex(review.HarnessError, "title or body carries"):
            self.record(github, self.args())

    def test_summaries_must_match_each_control(self) -> None:
        github = FakeGitHub("REVIEW.md")
        github.quiet_review_body = "## Devin Review: 1 flag"
        with self.assertRaisesRegex(review.HarnessError, "not No Issues Found"):
            self.record(github, self.args())
        github = FakeGitHub("REVIEW.md")
        github.fire_review_body = "## Devin Review: No Issues Found"
        with self.assertRaisesRegex(review.HarnessError, "reported no issues on the must-fire"):
            self.record(github, self.args())
        github = FakeGitHub("REVIEW.md")
        github.extra_quiet_reviews = [{"id": 10, "user": {"login": review.REVIEW_BOT},
                                       "commit_id": QUIET_HEAD, "state": "COMMENTED",
                                       "submitted_at": "2026-10-06T00:00:00Z",
                                       "body": f"## Devin Review: 1 flag {github.canary}"}]
        with self.assertRaisesRegex(review.HarnessError, "review on the must-not-fire control carries"):
            self.record(github, self.args())

    def test_every_page_is_read(self) -> None:
        github = FakeGitHub("REVIEW.md")
        filler = [finding("no canary", commit=QUIET_HEAD, path="benign.txt")
                  for _ in range(review.PAGE_SIZE)]
        github.quiet_comments = filler + [finding(github.canary, commit=QUIET_HEAD, path="benign.txt")]
        with self.assertRaisesRegex(review.HarnessError, "comment on the must-not-fire control carries"):
            self.record(github, self.args())
        github = FakeGitHub("REVIEW.md")
        github.fire_comments = filler + [finding(github.canary)]
        evidence = self.record(github, self.args(evidence=self.root / "paged.json"))
        self.assertEqual(len(evidence["must_fire"]["findings"]), 1)

    def test_opt_in_and_create_only_output_are_required(self) -> None:
        github = FakeGitHub("REVIEW.md")
        with self.assertRaisesRegex(review.HarnessError, "allow-public-fixture-access"):
            self.record(github, self.args(allow_public_fixture_access=False))
        self.record(github, self.args())
        with self.assertRaisesRegex(review.HarnessError, "refusing to overwrite"):
            self.record(FakeGitHub("REVIEW.md"), self.args())
        with self.assertRaisesRegex(review.HarnessError, "outside the source repository"):
            self.record(FakeGitHub("REVIEW.md"), self.args(evidence=ROOT / "evidence.json"))

    def test_source_never_writes_to_github_or_triggers_review(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in ("POST", "PATCH", "DELETE", "webbrowser", "devinreview.com",
                          "api.devin.ai", "Start-Process"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
