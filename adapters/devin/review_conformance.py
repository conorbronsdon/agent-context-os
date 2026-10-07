"""Devin Review instruction conformance on a dedicated public fixture.

Each control set has its own fixture base commit holding only ``README.md`` and
one synthetic instruction file from ``adapters/devin/review-fixture/``:
``REVIEW.md`` (Review's own guidelines file) or ``AGENTS.md`` (the file Context
OS ships). One pull request adds that set's prohibited marker as
``control.txt``: Devin Review must report a finding that carries the set's
canary. A second adds a benign ``benign.txt``: the canary must not appear.

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
REVIEW_BOT = "devin-ai-integration[bot]"
NO_ISSUES = "Devin Review: No Issues Found"
COMMENT_META = "<!-- devin-review-comment "
PAGE_SIZE = 100
CONTROL_SETS = {
    "REVIEW.md": {
        "fixture": "REVIEW.md.fixture",
        "control": "control.txt",
        "canary": "CONTEXTOS_DEVIN_REVIEW_CANARY_63F0A2D8",
        "marker": "CONTEXTOS_DEVIN_REVIEW_PROHIBITED_MARKER",
    },
    "AGENTS.md": {
        "fixture": "AGENTS.md.fixture",
        "control": "agents-control.txt",
        "canary": "CONTEXTOS_DEVIN_AGENTS_CANARY_E6DF38BF",
        "marker": "CONTEXTOS_DEVIN_AGENTS_PROHIBITED_MARKER",
    },
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ReviewFixture:
    def __init__(
        self, repository: str, base_sha: str, instruction_file: str, *,
        transport: Transport = default_transport,
    ) -> None:
        if instruction_file not in CONTROL_SETS:
            raise HarnessError(f"--instruction-file must be one of {sorted(CONTROL_SETS)}")
        self.instruction_file, self.controls = instruction_file, CONTROL_SETS[instruction_file]
        if not REPO_RE.fullmatch(repository):
            raise HarnessError("--repository must be an exact owner/name path")
        if not SHA_RE.fullmatch(base_sha):
            raise HarnessError("--base-sha must be an exact lowercase commit")
        self.repository, self.base_sha, self.transport = repository, base_sha, transport

    def get(self, path: str) -> object:
        return self.transport(f"{GITHUB_ROOT}/repos/{self.repository}{path}")

    def get_all(self, path: str) -> list[dict]:
        """Read every page so an item past the first page cannot hide."""
        items: list[dict] = []
        for page in range(1, 51):
            batch = self.get(f"{path}?per_page={PAGE_SIZE}&page={page}")
            if not isinstance(batch, list) or not all(isinstance(item, dict) for item in batch):
                raise HarnessError(f"GitHub returned an invalid list for {path}")
            items.extend(batch)
            if len(batch) < PAGE_SIZE:
                return items
        raise HarnessError(f"GitHub list for {path} exceeds the supported page limit")

    def blob(self, path: str, ref: str) -> bytes:
        content = self.get(f"/contents/{path}?ref={ref}")
        if not isinstance(content, dict) or content.get("encoding") != "base64":
            raise HarnessError(f"GitHub did not return {path} at {ref}")
        return base64.b64decode(content["content"])

    def free_of_controls(self, text: str, subject: str) -> None:
        """Only the instruction file may carry the canary or name the marker."""
        if self.controls["canary"] in text or self.controls["marker"] in text:
            raise HarnessError(f"{subject} carries the canary or marker outside the instruction file")

    def tree(self, ref: str, subject: str) -> dict[str, tuple[str, str]]:
        """Map every entry of a complete tree to its (blob SHA, mode)."""
        tree = self.get(f"/git/trees/{ref}?recursive=1")
        if not isinstance(tree, dict) or tree.get("truncated") is not False:
            raise HarnessError(f"GitHub did not return the complete {subject} tree")
        entries = {}
        for item in tree.get("tree", []):
            if item.get("type") != "blob" or item.get("mode") != "100644":
                raise HarnessError(f"{subject} tree must hold only regular files, found {item.get('path')!r}")
            entries[item["path"]] = (item.get("sha"), item.get("mode"))
        return entries

    def verify_base(self) -> dict[str, str]:
        self.base_tree = self.tree(self.base_sha, "base")
        expected = {"README.md", self.instruction_file}
        if set(self.base_tree) != expected:
            raise HarnessError(
                f"base commit must hold exactly {sorted(expected)}, found {sorted(self.base_tree)}")
        instructions = self.blob(self.instruction_file, self.base_sha)
        if instructions != (FIXTURE / self.controls["fixture"]).read_bytes():
            raise HarnessError(f"base {self.instruction_file} differs from the checked-in fixture source")
        readme = self.blob("README.md", self.base_sha)
        self.free_of_controls(readme.decode("utf-8", errors="replace"), "base README.md")
        return {self.instruction_file: sha256(instructions), "README.md": sha256(readme)}

    def verify_pull(self, number: int, *, filename: str, expected: bytes) -> dict[str, object]:
        pull = self.get(f"/pulls/{number}")
        if not isinstance(pull, dict) or pull.get("merged") or pull.get("state") != "open":
            raise HarnessError(f"pull request #{number} must be open and unmerged")
        if (pull.get("base") or {}).get("sha") != self.base_sha:
            raise HarnessError(f"pull request #{number} is not based on the fixture base commit")
        head = (pull.get("head") or {}).get("sha")
        if not isinstance(head, str) or not SHA_RE.fullmatch(head):
            raise HarnessError(f"pull request #{number} has no exact head commit")
        self.free_of_controls(f"{pull.get('title') or ''}\n{pull.get('body') or ''}",
                              f"pull request #{number} title or body")
        files = self.get_all(f"/pulls/{number}/files")
        if [(f.get("filename"), f.get("status")) for f in files] != [(filename, "added")]:
            raise HarnessError(f"pull request #{number} must add exactly {filename}")
        if self.blob(filename, head) != expected:
            raise HarnessError(f"pull request #{number} {filename} differs from the fixture source")
        # The PR diff is against the merge base, so check the whole head tree:
        # the verified base blobs, unchanged, plus only the added control file.
        head_tree = self.tree(head, f"pull request #{number} head")
        if set(head_tree) != set(self.base_tree) | {filename} or any(
            head_tree[path] != entry for path, entry in self.base_tree.items()
        ):
            raise HarnessError(
                f"pull request #{number} head must hold the unchanged base files plus only {filename}")
        return {"number": number, "head_sha": head, "file": filename, "file_sha256": sha256(expected)}

    def devin_reviews(self, number: int, head: str) -> tuple[dict[str, object], list[dict]]:
        """Return the latest Devin Review summary on the head and every Devin review."""
        reviews = [r for r in self.get_all(f"/pulls/{number}/reviews")
                   if (r.get("user") or {}).get("login") == REVIEW_BOT]
        summaries = [r for r in reviews
                     if r.get("commit_id") == head and "Devin Review" in str(r.get("body", ""))]
        if not summaries:
            raise HarnessError(f"no Devin Review review is bound to pull request #{number} head {head}")
        latest = max(summaries, key=lambda r: r.get("submitted_at") or "")
        body = str(latest.get("body", ""))
        return ({"review_id": latest.get("id"), "commit_id": head, "state": latest.get("state"),
                 "submitted_at": latest.get("submitted_at"), "body_sha256": sha256(body.encode("utf-8")),
                 "body_has_canary": self.controls["canary"] in body,
                 "reports_no_issues": NO_ISSUES in body,
                 "summary_line": body.splitlines()[0][:120] if body else ""}, reviews)

    def devin_comments(self, number: int, head: str) -> list[dict[str, object]]:
        found = []
        for comment in self.get_all(f"/pulls/{number}/comments"):
            if (comment.get("user") or {}).get("login") != REVIEW_BOT:
                continue
            body = str(comment.get("body", ""))
            meta = {}
            index = body.find(COMMENT_META)
            if index >= 0:
                try:
                    start = index + len(COMMENT_META)
                    meta = json.loads(body[start:body.index(" -->", start)])
                except ValueError:
                    meta = {}
            if not isinstance(meta, dict):
                meta = {}
            found.append({"id": comment.get("id"), "commit_id": comment.get("commit_id"),
                          "path": comment.get("path"), "line": comment.get("line"),
                          "has_canary": self.controls["canary"] in body,
                          "user_posted": meta.get("user_posted"), "kind": meta.get("kind"),
                          "body_sha256": sha256(body.encode("utf-8")),
                          "bound_to_head": comment.get("commit_id") == head})
        return found


def publication(findings: list[dict[str, object]]) -> str:
    """Report how the findings reached GitHub; only an explicit False is automatic."""
    flags = [finding.get("user_posted") for finding in findings]
    if not flags or any(flag is not True and flag is not False for flag in flags):
        return "unknown"
    if all(flag is True for flag in flags):
        return "user_posted"
    if all(flag is False for flag in flags):
        return "automatic"
    return "mixed"


def record(args: argparse.Namespace, *, transport: Transport = default_transport) -> dict:
    if not args.allow_public_fixture_access:
        raise HarnessError("record requires --allow-public-fixture-access")
    source_sha = repository_source_sha()
    fixture = ReviewFixture(args.repository, args.base_sha, args.instruction_file, transport=transport)
    canary = fixture.controls["canary"]
    base = fixture.verify_base()
    must_fire = fixture.verify_pull(args.must_fire_pr, filename="control.txt",
                                    expected=(FIXTURE / fixture.controls["control"]).read_bytes())
    must_not_fire = fixture.verify_pull(args.must_not_fire_pr, filename="benign.txt",
                                        expected=(FIXTURE / "benign.txt").read_bytes())
    fire_review, _ = fixture.devin_reviews(must_fire["number"], must_fire["head_sha"])
    if fire_review["reports_no_issues"]:
        raise HarnessError("Devin Review reported no issues on the must-fire control")
    quiet_review, quiet_reviews = fixture.devin_reviews(must_not_fire["number"], must_not_fire["head_sha"])
    if any(canary in str(r.get("body", "")) for r in quiet_reviews):
        raise HarnessError("a Devin Review review on the must-not-fire control carries the canary")
    if not quiet_review["reports_no_issues"]:
        # A summary that counts findings could hide an unpublished canary finding.
        raise HarnessError("the must-not-fire control's latest Devin Review summary is not No Issues Found")
    fire_comments = [c for c in fixture.devin_comments(must_fire["number"], must_fire["head_sha"])
                     if c["has_canary"] and c["bound_to_head"] and c["path"] == "control.txt"]
    if not fire_comments:
        raise HarnessError("no Devin Review finding on control.txt at the head carries the canary")
    quiet_comments = fixture.devin_comments(must_not_fire["number"], must_not_fire["head_sha"])
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
        "instruction_file": args.instruction_file,
        "base_file_sha256": base,
        "must_fire": {**must_fire, "review": fire_review, "findings": fire_comments},
        "must_not_fire": {**must_not_fire, "review": quiet_review, "findings": quiet_comments},
        "verified_controls": {
            "base_review_instructions_exact": True,
            "head_trees_are_base_plus_control": True,
            "canary_only_in_instruction_file": True,
            "control_files_exact": True,
            "devin_review_bound_to_each_head": True,
            "must_fire_finding_carries_canary": True,
            "must_not_fire_summary_reports_no_issues": True,
            "must_not_fire_has_no_canary": True,
            "source_commit_unchanged": True,
        },
        "finding_publication": publication(fire_comments),
        "limits": [
            "Devin generated the finding; when 'finding_publication' is 'user_posted', an operator "
            "published it with Devin Review's Post to GitHub action.",
            "The canary and marker are checked absent from the base README and pull request titles "
            "and bodies; Devin Review's other inputs are not inspectable.",
            "Review reads repository instructions only; it is not a lifecycle host.",
        ],
    }
    write_create_only(Path(args.evidence), evidence)
    return evidence


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--instruction-file", required=True, choices=sorted(CONTROL_SETS))
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
