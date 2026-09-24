"""Operator-assisted Devin web-session conformance for a public fixture.

This path exists for accounts without Devin API credentials. It verifies the
public fixture and pull-request inventory through GitHub, then records only
synthetic canary outcomes and hashes the Devin session URL. It never opens
Devin, creates a session, enables Review, or sends repository data itself.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCAL_FIXTURE = REPOSITORY_ROOT / "adapters" / "devin" / "live-fixture"
ROOT_CANARY = "CONTEXTOS_DEVIN_ROOT_7D6A41C9"
SKILL_CANARY = "CONTEXTOS_DEVIN_SKILL_49B28E73"
SKILL_NAME = "contextos-devin-live-control"
FIXTURE_PATHS = (
    ".agents/skills/contextos-devin-live-control/SKILL.md",
    "AGENTS.md",
)
LOCAL_FIXTURE_FILES = {
    FIXTURE_PATHS[0]: "SKILL.md.fixture",
    FIXTURE_PATHS[1]: "AGENTS.md.fixture",
}
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
SHA_RE = re.compile(r"[0-9a-f]{40}")
SESSION_RE = re.compile(r"https://app\.devin\.ai/sessions/[A-Za-z0-9_-]+/?")
GITHUB_ROOT = "https://api.github.com"


class HarnessError(RuntimeError):
    """An operator-assisted Devin control failed safely."""


Transport = Callable[[str], object]


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def default_transport(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "agent-context-os-devin-conformance",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise HarnessError(f"GitHub fixture request failed with HTTP {exc.code}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HarnessError("GitHub fixture request returned invalid JSON") from exc


def repository_source_sha() -> str:
    status = subprocess.run(
        ["git", "status", "--short"], cwd=REPOSITORY_ROOT, text=True,
        encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    if status.returncode or status.stdout.strip():
        raise HarnessError("UI conformance must bind to one clean source commit")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, text=True,
        encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    value = head.stdout.strip()
    if head.returncode or not SHA_RE.fullmatch(value):
        raise HarnessError("could not bind UI conformance to the source commit")
    return value


def require_outside_source(path: Path, subject: str) -> Path:
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(REPOSITORY_ROOT.resolve())
    except ValueError:
        return resolved
    raise HarnessError(f"{subject} must be outside the source repository")


def write_create_only(path: Path, payload: Mapping[str, object]) -> None:
    target = require_outside_source(path, "evidence or manifest")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise HarnessError(f"refusing to overwrite: {target}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


class GitHubFixture:
    def __init__(
        self, repository: str, fixture_sha: str, *, transport: Transport = default_transport
    ) -> None:
        if not REPO_RE.fullmatch(repository):
            raise HarnessError("--repository must be an exact owner/name path")
        if not SHA_RE.fullmatch(fixture_sha):
            raise HarnessError("--fixture-sha must be an exact lowercase commit")
        self.repository = repository
        self.fixture_sha = fixture_sha
        self.transport = transport

    def request(self, path: str) -> object:
        return self.transport(f"{GITHUB_ROOT}/repos/{self.repository}{path}")

    def verify(self) -> str:
        repository = self.request("")
        default_branch = repository.get("default_branch") if isinstance(repository, dict) else None
        if not isinstance(default_branch, str) or not default_branch:
            raise HarnessError("GitHub fixture response omitted its default branch")
        branch = urllib.parse.quote(default_branch, safe="")
        reference = self.request(f"/git/ref/heads/{branch}")
        target = reference.get("object") if isinstance(reference, dict) else None
        if not isinstance(target, dict) or target.get("type") != "commit" or target.get("sha") != self.fixture_sha:
            raise HarnessError("public fixture default branch drifted from the exact fixture commit")
        commit = self.request(f"/commits/{self.fixture_sha}")
        if not isinstance(commit, dict) or commit.get("sha") != self.fixture_sha:
            raise HarnessError("GitHub did not return the exact fixture commit")
        tree = self.request(f"/git/trees/{self.fixture_sha}?recursive=1")
        if not isinstance(tree, dict) or tree.get("truncated") is True:
            raise HarnessError("GitHub did not return a complete fixture tree")
        entries = tree.get("tree")
        if not isinstance(entries, list):
            raise HarnessError("GitHub fixture tree omitted entries")
        blob_paths = sorted(
            str(item.get("path")) for item in entries
            if isinstance(item, dict) and item.get("type") == "blob"
        )
        if blob_paths != list(FIXTURE_PATHS):
            raise HarnessError(f"public fixture contains unexpected files: {blob_paths}")
        remote_hashes: dict[str, str] = {}
        for path in FIXTURE_PATHS:
            encoded_path = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))
            content = self.request(f"/contents/{encoded_path}?ref={self.fixture_sha}")
            if not isinstance(content, dict) or content.get("encoding") != "base64":
                raise HarnessError(f"GitHub omitted base64 content for {path}")
            try:
                remote = base64.b64decode(str(content["content"]), validate=False)
            except (ValueError, KeyError) as exc:
                raise HarnessError(f"GitHub returned invalid content for {path}") from exc
            local = (LOCAL_FIXTURE / LOCAL_FIXTURE_FILES[path]).read_bytes()
            if remote != local:
                raise HarnessError(f"public fixture content drifted from source: {path}")
            remote_hashes[path] = hashlib.sha256(remote).hexdigest()
        return canonical_hash({
            "default_branch_head": self.fixture_sha,
            "fixture_file_hashes": remote_hashes,
        })

    def pull_snapshot(self) -> tuple[str, int]:
        pulls = self.request("/pulls?state=all&per_page=100")
        if not isinstance(pulls, list) or len(pulls) >= 100:
            raise HarnessError("pull-request inventory is invalid or requires pagination")
        normalized = []
        for pull in pulls:
            if not isinstance(pull, dict):
                raise HarnessError("pull-request inventory contains a non-object")
            head = pull.get("head")
            base = pull.get("base")
            if not isinstance(head, dict) or not isinstance(base, dict):
                raise HarnessError("pull-request inventory omitted head or base")
            normalized.append({
                "number": pull.get("number"),
                "state": pull.get("state"),
                "head_sha": head.get("sha"),
                "base_sha": base.get("sha"),
            })
        return canonical_hash(sorted(normalized, key=lambda item: int(item["number"]))), len(normalized)


def prepare(args: argparse.Namespace, *, transport: Transport = default_transport) -> None:
    if not args.allow_public_fixture_access or not args.acknowledge_operator_session:
        raise HarnessError("prepare requires both explicit opt-in flags")
    source_sha = repository_source_sha()
    if args.source_sha != source_sha:
        raise HarnessError(f"--source-sha must equal the clean harness commit {source_sha}")
    fixture = GitHubFixture(args.repository, args.fixture_sha, transport=transport)
    fixture_content_sha = fixture.verify()
    pull_sha, pull_count = fixture.pull_snapshot()
    write_create_only(args.manifest, {
        "schema_version": 1,
        "runtime": "devin",
        "surface": "session-ui",
        "source_sha": source_sha,
        "repository": args.repository,
        "fixture_sha": args.fixture_sha,
        "fixture_content_sha256": fixture_content_sha,
        "baseline_pull_snapshot_sha256": pull_sha,
        "baseline_pull_count": pull_count,
        "prompts": {
            "root": (
                "Read-only conformance. Do not edit, branch, commit, push, or open a PR. "
                "Use the available Context OS control without an explicit @skills reference. "
                "Return only the root instruction canary from your repository instructions, "
                "followed by one space and the observed commit SHA from git rev-parse HEAD "
                "in the fixture checkout."
            ),
            "explicit": f"@skills:{SKILL_NAME} Return only the canary required by this skill.",
        },
        "controls": {
            "public_fixture_exact": True,
            "review_must_not_be_invoked": True,
            "repository_must_remain_read_only": True,
        },
    })


def require_text(observations: Mapping[str, object], name: str) -> str:
    value = observations.get(name)
    if not isinstance(value, str) or not value.strip():
        raise HarnessError(f"observation {name!r} must be a non-empty string")
    return value.strip()


def normalize_fixture_reply(value: str, canary: str) -> str:
    """Accept only the public fixture's documented inline-code wrapper."""
    return value.strip().replace(f"`{canary}`", canary)


def record(args: argparse.Namespace, *, transport: Transport = default_transport) -> None:
    if not args.allow_public_fixture_access or not args.acknowledge_operator_attestation:
        raise HarnessError("record requires both explicit opt-in flags")
    manifest_path = require_outside_source(args.manifest, "manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    observations = json.loads(args.observations.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("surface") != "session-ui":
        raise HarnessError("unsupported Devin UI manifest")
    source_sha = repository_source_sha()
    if manifest.get("source_sha") != source_sha:
        raise HarnessError("Devin UI manifest is not bound to the clean source commit")
    fixture = GitHubFixture(
        str(manifest["repository"]), str(manifest["fixture_sha"]), transport=transport
    )
    if fixture.verify() != manifest.get("fixture_content_sha256"):
        raise HarnessError("public fixture content changed during conformance")
    pull_sha, pull_count = fixture.pull_snapshot()
    if pull_sha != manifest.get("baseline_pull_snapshot_sha256") or pull_count != manifest.get("baseline_pull_count"):
        raise HarnessError("public fixture pull-request inventory changed during conformance")

    expected_root = f"{ROOT_CANARY} {manifest['fixture_sha']}"
    root_response = require_text(observations, "root_response")
    if normalize_fixture_reply(root_response, ROOT_CANARY) != expected_root or SKILL_CANARY in root_response:
        raise HarnessError("root or implicit-skill control did not return the exact expected output")
    if normalize_fixture_reply(require_text(observations, "explicit_response"), SKILL_CANARY) != SKILL_CANARY:
        raise HarnessError("explicit skill did not return its exact canary")
    for name in (
        "repository_remained_read_only", "no_pull_request_observed",
        "review_not_invoked", "session_archived",
    ):
        if observations.get(name) is not True:
            raise HarnessError(f"operator control {name!r} was not affirmed")
    session_url = require_text(observations, "session_url")
    if not SESSION_RE.fullmatch(session_url):
        raise HarnessError("session_url is not an app.devin.ai session URL")
    product_build = require_text(observations, "product_build")
    environment_identity = require_text(observations, "environment_identity")
    devin_mode = require_text(observations, "devin_mode")
    account_identity_inspectable = environment_identity != "unavailable"
    build_identity_inspectable = product_build != "unavailable"

    if repository_source_sha() != source_sha:
        raise HarnessError("source commit changed during Devin UI evidence recording")
    write_create_only(args.evidence, {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "runtime": "devin",
        "surface": "session-ui",
        "evidence_kind": "operator-attested-with-local-verification",
        "source_sha": source_sha,
        "repository": manifest["repository"],
        "fixture_sha": manifest["fixture_sha"],
        "fixture_content_sha256": manifest["fixture_content_sha256"],
        "session_url_sha256": hashlib.sha256(session_url.encode()).hexdigest(),
        "product_build": product_build,
        "environment_identity_sha256": (
            hashlib.sha256(environment_identity.encode()).hexdigest()
            if account_identity_inspectable else None
        ),
        "devin_mode": devin_mode,
        "account_identity_inspectable": account_identity_inspectable,
        "build_identity_inspectable": build_identity_inspectable,
        "verified_controls": {
            "exact_fixture_commit": True,
            "public_fixture_content_unchanged": True,
            "pull_request_inventory_unchanged": True,
            "recorded_response_values_exact": True,
            "source_commit_unchanged": True,
        },
        "attested_controls": {
            "repository_access": True,
            "root_instruction_discovery": True,
            "implicit_skill_must_not_fire": True,
            "explicit_skill_must_fire": True,
            "repository_remained_read_only": True,
            "no_pull_request_created": True,
            "review_not_invoked": True,
            "session_archived": True,
        },
    })


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--repository", required=True)
    prepare_parser.add_argument("--fixture-sha", required=True)
    prepare_parser.add_argument("--source-sha", required=True)
    prepare_parser.add_argument("--manifest", required=True, type=Path)
    prepare_parser.add_argument("--allow-public-fixture-access", action="store_true")
    prepare_parser.add_argument("--acknowledge-operator-session", action="store_true")

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--manifest", required=True, type=Path)
    record_parser.add_argument("--observations", required=True, type=Path)
    record_parser.add_argument("--evidence", required=True, type=Path)
    record_parser.add_argument("--allow-public-fixture-access", action="store_true")
    record_parser.add_argument("--acknowledge-operator-attestation", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args)
            print(f"Devin UI conformance manifest prepared: {args.manifest}")
        else:
            record(args)
            print(f"Devin UI conformance passed; evidence: {args.evidence}")
    except (HarnessError, OSError, subprocess.SubprocessError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Devin UI conformance failed safely: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
