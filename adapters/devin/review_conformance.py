"""Devin Review instruction conformance on a dedicated public fixture.

The fixture repository's base commit holds only ``README.md`` and the synthetic
``REVIEW.md`` from ``adapters/devin/review-fixture/``. One pull request adds the
prohibited marker (``control.txt``): Devin Review must report a finding that
carries the canary. A second adds a benign file: the canary must not appear.

Every control is read from GitHub: fixture bytes, the exact files each pull
request changes, a Devin Review review bound to each exact head commit, and
Devin's own review comments. When an organization's Review settings keep
findings in the Devin UI, the operator publishes the finding with Devin
Review's "Post to GitHub" action; Devin marks such a comment ``user_posted`` and
the evidence records that provenance. This script never comments, approves,
merges, triggers Review, or changes Devin or GitHub settings.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from adapters.devin.ui_conformance import (  # noqa: E402
    REPO_RE, SHA_RE, GITHUB_ROOT, HarnessError, Transport, default_transport,
    repository_source_sha, require_outside_source, write_create_only,
)

FIXTURE = Path(__file__).resolve().parent / "review-fixture"
REVIEW_CANARY = "CONTEXTOS_DEVIN_REVIEW_CANARY_63F0A2D8"
MARKER = "CONTEXTOS_DEVIN_REVIEW_PROHIBITED_MARKER"
REVIEW_BOT = "devin-ai-integration[bot]"
BASE_FILES = {"README.md", "REVIEW.md"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ReviewFixture:
    def __init__(self, repository: str, base_sha: str, *, transport: Transport = default_transport) -> None:
        if not REPO_RE.fullmatch(repository):
            raise HarnessError("--repository must be an exact owner/name path")
        if not SHA_RE.fullmatch(base_sha):
            raise HarnessError("--base-sha must be an exact lowercase commit")
        self.repository, self.base_sha, self.transport = repository, base_sha, transport

    def get(self, path: str) -> object:
        return self.transport(f"{GITHUB_ROOT}/repos/{self.repository}{path}")

    def blob(self, path: str, ref: str) -> bytes:
        content = self.get(f"/contents/{path}?ref={ref}")
        if not isinstance(content, dict) or content.get("encoding") != "base64":
            raise HarnessError(f"GitHub did not return {path} at {ref}")
        return base64.b64decode(content["content"])

    def verify_base(self) -> dict[str, str]:
        tree = self.get(f"/git/trees/{self.base_sha}?recursive=1")
        if not isinstance(tree, dict) or tree.get("truncated") is not False:
            raise HarnessError("GitHub did not return the complete base tree")
        paths = {item["path"] for item in tree.get("tree", []) if item.get("type") == "blob"}
        if paths != BASE_FILES:
            raise HarnessError(f"base commit must hold exactly {sorted(BASE_FILES)}, found {sorted(paths)}")
        review = self.blob("REVIEW.md", self.base_sha)
        if review != (FIXTURE / "REVIEW.md.fixture").read_bytes():
            raise HarnessError("base REVIEW.md differs from the checked-in fixture source")
        return {"REVIEW.md": sha256(review)}

    def verify_pull(self, number: int, *, filename: str, expected: bytes) -> dict[str, object]:
        pull = self.get(f"/pulls/{number}")
        if not isinstance(pull, dict) or pull.get("merged") or pull.get("state") != "open":
            raise HarnessError(f"pull request #{number} must be open and unmerged")
        if (pull.get("base") or {}).get("sha") != self.base_sha:
            raise HarnessError(f"pull request #{number} is not based on the fixture base commit")
        head = (pull.get("head") or {}).get("sha")
        if not isinstance(head, str) or not SHA_RE.fullmatch(head):
            raise HarnessError(f"pull request #{number} has no exact head commit")
        files = self.get(f"/pulls/{number}/files?per_page=100")
        if not isinstance(files, list) or [(f.get("filename"), f.get("status")) for f in files] != [(filename, "added")]:
            raise HarnessError(f"pull request #{number} must add exactly {filename}")
        if self.blob(filename, head) != expected:
            raise HarnessError(f"pull request #{number} {filename} differs from the fixture source")
        return {"number": number, "head_sha": head, "file": filename, "file_sha256": sha256(expected)}

    def devin_review(self, number: int, head: str) -> dict[str, object]:
        reviews = self.get(f"/pulls/{number}/reviews?per_page=100")
        if not isinstance(reviews, list):
            raise HarnessError("GitHub returned an invalid review list")
        matches = [r for r in reviews if (r.get("user") or {}).get("login") == REVIEW_BOT
                   and r.get("commit_id") == head and "Devin Review" in str(r.get("body", ""))]
        if not matches:
            raise HarnessError(f"no Devin Review review is bound to pull request #{number} head {head}")
        latest = max(matches, key=lambda r: r.get("submitted_at") or "")
        body = str(latest.get("body", ""))
        return {"review_id": latest.get("id"), "commit_id": head, "state": latest.get("state"),
                "submitted_at": latest.get("submitted_at"), "body_sha256": sha256(body.encode("utf-8")),
                "body_has_canary": REVIEW_CANARY in body,
                "summary_line": body.splitlines()[0][:120] if body else ""}


def devin_comments(fixture: ReviewFixture, number: int, head: str) -> list[dict[str, object]]:
    comments = fixture.get(f"/pulls/{number}/comments?per_page=100")
    if not isinstance(comments, list):
        raise HarnessError("GitHub returned an invalid review-comment list")
    found = []
    for comment in comments:
        if (comment.get("user") or {}).get("login") != REVIEW_BOT:
            continue
        body = str(comment.get("body", ""))
        meta = {}
        if body.startswith("<!-- devin-review-comment "):
            try:
                meta = json.loads(body[len("<!-- devin-review-comment "):body.index(" -->")])
            except (ValueError, json.JSONDecodeError):
                meta = {}
        found.append({"id": comment.get("id"), "commit_id": comment.get("commit_id"),
                      "path": comment.get("path"), "line": comment.get("line"),
                      "has_canary": REVIEW_CANARY in body, "user_posted": meta.get("user_posted"),
                      "kind": meta.get("kind"), "body_sha256": sha256(body.encode("utf-8")),
                      "bound_to_head": comment.get("commit_id") == head})
    return found


def record(args: argparse.Namespace, *, transport: Transport = default_transport) -> dict:
    if not args.allow_public_fixture_access:
        raise HarnessError("record requires --allow-public-fixture-access")
    source_sha = repository_source_sha()
    fixture = ReviewFixture(args.repository, args.base_sha, transport=transport)
    base = fixture.verify_base()
    must_fire = fixture.verify_pull(args.must_fire_pr, filename="control.txt",
                                    expected=(FIXTURE / "control.txt").read_bytes())
    benign_head = fixture.get(f"/pulls/{args.must_not_fire_pr}")["head"]["sha"]
    benign_bytes = fixture.blob("benign.txt", benign_head)
    if MARKER.encode() in benign_bytes or REVIEW_CANARY.encode() in benign_bytes:
        raise HarnessError("the must-not-fire control file contains the marker or canary")
    must_not_fire = fixture.verify_pull(args.must_not_fire_pr, filename="benign.txt", expected=benign_bytes)
    fire_review = fixture.devin_review(must_fire["number"], must_fire["head_sha"])
    quiet_review = fixture.devin_review(must_not_fire["number"], must_not_fire["head_sha"])
    if quiet_review["body_has_canary"]:
        raise HarnessError("Devin Review posted the canary on the must-not-fire control")
    fire_comments = [c for c in devin_comments(fixture, must_fire["number"], must_fire["head_sha"])
                     if c["has_canary"] and c["bound_to_head"] and c["path"] == "control.txt"]
    if not fire_comments:
        raise HarnessError("no Devin Review finding on control.txt at the head carries the canary")
    quiet_comments = devin_comments(fixture, must_not_fire["number"], must_not_fire["head_sha"])
    if any(c["has_canary"] for c in quiet_comments):
        raise HarnessError("a Devin Review comment on the must-not-fire control carries the canary")
    if repository_source_sha() != source_sha:
        raise HarnessError("source commit changed during Review evidence recording")
    evidence = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "runtime": "devin",
        "surface": "review",
        "source_sha": source_sha,
        "repository": args.repository,
        "base_sha": args.base_sha,
        "base_file_sha256": base,
        "must_fire": {**must_fire, "review": fire_review, "findings": fire_comments},
        "must_not_fire": {**must_not_fire, "review": quiet_review, "findings": quiet_comments},
        "verified_controls": {
            "base_review_instructions_exact": True,
            "control_files_exact": True,
            "devin_review_bound_to_each_head": True,
            "must_fire_finding_carries_canary": True,
            "must_not_fire_has_no_canary": True,
            "source_commit_unchanged": True,
        },
        "finding_publication": ("user_posted" if all(c["user_posted"] for c in fire_comments)
                                else "automatic"),
        "limits": [
            "Devin generated the finding; when 'finding_publication' is 'user_posted', an operator "
            "published it with Devin Review's Post to GitHub action.",
            "Review reads repository instructions only; it is not a lifecycle host.",
        ],
    }
    write_create_only(Path(args.evidence), evidence)
    return evidence


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--must-fire-pr", type=int, required=True)
    parser.add_argument("--must-not-fire-pr", type=int, required=True)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--allow-public-fixture-access", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        require_outside_source(args.evidence, "evidence")
        record(args)
    except (HarnessError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Devin Review conformance failed safely: {exc}", file=sys.stderr)
        return 1
    print(f"Devin Review conformance passed; evidence: {args.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
