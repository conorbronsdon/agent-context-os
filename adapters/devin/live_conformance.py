"""Opt-in Devin cloud-session conformance against a public synthetic fixture."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCAL_FIXTURE = REPOSITORY_ROOT / "adapters" / "devin" / "live-fixture"
API_ROOT = "https://api.devin.ai"
GITHUB_API_ROOT = "https://api.github.com"
ROOT_CANARY = "CONTEXTOS_DEVIN_ROOT_7D6A41C9"
SKILL_CANARY = "CONTEXTOS_DEVIN_SKILL_49B28E73"
SKILL_NAME = "contextos-devin-live-control"
SHA_RE = re.compile(r"[0-9a-f]{40}")
ORG_RE = re.compile(r"org-[A-Za-z0-9_-]+")
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
TOKEN_RE = re.compile(r"cog_[A-Za-z0-9_-]+")
FIXTURE_PATHS = (
    ".agents/skills/contextos-devin-live-control/SKILL.md",
    "AGENTS.md",
)
LOCAL_FIXTURE_FILES = {
    FIXTURE_PATHS[0]: "SKILL.md.fixture",
    FIXTURE_PATHS[1]: "AGENTS.md.fixture",
}


class HarnessError(RuntimeError):
    """A live conformance control failed safely."""


Transport = Callable[[str, str, Mapping[str, object] | None, Mapping[str, str], float], Mapping[str, object]]
GitHubTransport = Callable[[str, float], Mapping[str, object]]


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def safe_error_detail(value: object) -> str:
    """Return a bounded diagnostic that cannot echo a current Devin token."""
    return TOKEN_RE.sub("[REDACTED]", str(value))[:1000]


def normalize_fixture_reply(value: str, canary: str) -> str:
    """Accept only the fixture's documented inline-code wrapper."""
    return value.strip().replace(f"`{canary}`", canary)


def default_transport(
    method: str,
    url: str,
    payload: Mapping[str, object] | None,
    headers: Mapping[str, str],
    timeout: float,
) -> Mapping[str, object]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            detail = json.loads(raw.decode("utf-8")).get("detail")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            detail = None
        safe_detail = safe_error_detail(detail) if detail else "no safe detail"
        raise HarnessError(
            f"Devin API {method} failed with HTTP {exc.code}: {safe_detail}"
        ) from exc
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HarnessError(f"Devin API {method} returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise HarnessError(f"Devin API {method} returned a non-object response")
    return decoded


def default_github_transport(url: str, timeout: float) -> Mapping[str, object]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "agent-context-os-devin-conformance",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise HarnessError(f"GitHub fixture request failed with HTTP {exc.code}") from exc
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HarnessError("GitHub fixture request returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise HarnessError("GitHub fixture request returned a non-object response")
    return decoded


def verify_public_fixture_head(
    repository: str,
    fixture_sha: str,
    *,
    transport: GitHubTransport = default_github_transport,
    audit: list[dict[str, str]] | None = None,
) -> None:
    """Ensure the fixture's public default branch still names the exact commit."""
    repository_info = transport(f"{GITHUB_API_ROOT}/repos/{repository}", 30)
    if audit is not None:
        audit.append({"endpoint": "repository", "response_sha256": canonical_hash(repository_info)})
    default_branch = repository_info.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        raise HarnessError("GitHub fixture response omitted its default branch")
    encoded_branch = urllib.parse.quote(default_branch, safe="")
    reference = transport(
        f"{GITHUB_API_ROOT}/repos/{repository}/git/ref/heads/{encoded_branch}", 30
    )
    if audit is not None:
        audit.append({"endpoint": "default_branch_ref", "response_sha256": canonical_hash(reference)})
    target = reference.get("object")
    if not isinstance(target, dict) or target.get("type") != "commit":
        raise HarnessError("GitHub fixture default branch did not resolve to a commit")
    if target.get("sha") != fixture_sha:
        raise HarnessError("public fixture default branch drifted from the exact fixture commit")


def verify_public_fixture_content(
    repository: str,
    fixture_sha: str,
    *,
    transport: GitHubTransport = default_github_transport,
    audit: list[dict[str, str]] | None = None,
) -> str:
    """Bind the remote fixture's exact two blobs to the checked-in fixture."""
    commit = transport(f"{GITHUB_API_ROOT}/repos/{repository}/commits/{fixture_sha}", 30)
    if audit is not None:
        audit.append({"endpoint": "fixture_commit", "response_sha256": canonical_hash(commit)})
    if commit.get("sha") != fixture_sha:
        raise HarnessError("GitHub did not return the exact fixture commit")
    tree = transport(
        f"{GITHUB_API_ROOT}/repos/{repository}/git/trees/{fixture_sha}?recursive=1", 30
    )
    if audit is not None:
        audit.append({"endpoint": "fixture_tree", "response_sha256": canonical_hash(tree)})
    entries = tree.get("tree")
    if tree.get("truncated") is True or not isinstance(entries, list):
        raise HarnessError("GitHub did not return a complete fixture tree")
    blob_paths = sorted(
        str(item.get("path")) for item in entries
        if isinstance(item, dict) and item.get("type") == "blob"
    )
    if blob_paths != list(FIXTURE_PATHS):
        raise HarnessError(f"public fixture contains unexpected files: {blob_paths}")
    remote_hashes: dict[str, str] = {}
    for path in FIXTURE_PATHS:
        encoded_path = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))
        content = transport(
            f"{GITHUB_API_ROOT}/repos/{repository}/contents/{encoded_path}?ref={fixture_sha}", 30
        )
        if audit is not None:
            audit.append({
                "endpoint": f"fixture_content:{path}",
                "response_sha256": canonical_hash(content),
            })
        if content.get("encoding") != "base64" or not isinstance(content.get("content"), str):
            raise HarnessError(f"GitHub omitted base64 content for {path}")
        try:
            remote = base64.b64decode("".join(content["content"].split()), validate=True)
        except ValueError as exc:
            raise HarnessError(f"GitHub returned invalid content for {path}") from exc
        if remote != (LOCAL_FIXTURE / LOCAL_FIXTURE_FILES[path]).read_bytes():
            raise HarnessError(f"public fixture content drifted from source: {path}")
        remote_hashes[path] = hashlib.sha256(remote).hexdigest()
    return canonical_hash(remote_hashes)


def verify_public_fixture(
    repository: str,
    fixture_sha: str,
    *,
    transport: GitHubTransport = default_github_transport,
    audit: list[dict[str, str]] | None = None,
) -> str:
    verify_public_fixture_head(repository, fixture_sha, transport=transport, audit=audit)
    return verify_public_fixture_content(repository, fixture_sha, transport=transport, audit=audit)


@dataclass
class DevinClient:
    token: str = field(repr=False)
    org_id: str
    timeout: float = 30
    transport: Transport = default_transport
    requests: list[dict[str, object]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.token.startswith("cog_"):
            raise HarnessError("DEVIN_API_TOKEN must be a current cog_-prefixed credential")
        if not ORG_RE.fullmatch(self.org_id):
            raise HarnessError("--org-id must be an org- identifier")

    def request(
        self, method: str, path: str, payload: Mapping[str, object] | None = None
    ) -> Mapping[str, object]:
        url = f"{API_ROOT}{path}"
        response = self.transport(
            method,
            url,
            payload,
            {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            self.timeout,
        )
        safe_path = path.replace(self.org_id, "{org_id}")
        safe_path = re.sub(r"devin-[A-Za-z0-9_-]+", "{devin_id}", safe_path)
        self.requests.append({
            "method": method,
            "path": safe_path,
            "request_sha256": canonical_hash(payload) if payload is not None else None,
            "response_sha256": canonical_hash(response),
        })
        return response


def repository_source_sha() -> str:
    status = subprocess.run(
        ["git", "status", "--short"], cwd=REPOSITORY_ROOT, text=True,
        encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    if status.returncode or status.stdout.strip():
        raise HarnessError("live conformance must run from one clean source commit")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, text=True,
        encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    value = head.stdout.strip()
    if head.returncode or not SHA_RE.fullmatch(value):
        raise HarnessError("could not bind live conformance to the source commit")
    return value


def require_outside_source(path: Path) -> Path:
    target = path.resolve(strict=False)
    try:
        target.relative_to(REPOSITORY_ROOT.resolve())
    except ValueError:
        return target
    raise HarnessError("evidence must be outside the source repository")


def require_items(response: Mapping[str, object], subject: str) -> list[Mapping[str, object]]:
    items = response.get("items")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise HarnessError(f"{subject} response omitted an object items list")
    return items


@dataclass
class Evidence:
    source_sha: str
    fixture_sha: str
    repository: str
    active_build_id: str = ""
    session_id_sha256: str = ""
    devin_mode: str | None = None
    requests: list[dict[str, object]] = field(default_factory=list)
    github_requests: list[dict[str, str]] = field(default_factory=list)
    controls: dict[str, bool] = field(default_factory=dict)


class DevinHarness:
    def __init__(
        self,
        client: DevinClient,
        *,
        repository: str,
        fixture_sha: str,
        source_sha: str,
        expected_active_build: str,
        poll_timeout: float = 900,
        poll_interval: float = 10,
        github_transport: GitHubTransport = default_github_transport,
    ) -> None:
        if not REPO_RE.fullmatch(repository):
            raise HarnessError("--repository must be an exact owner/name path")
        if not SHA_RE.fullmatch(fixture_sha) or not SHA_RE.fullmatch(source_sha):
            raise HarnessError("source and fixture SHAs must be exact lowercase 40-character commits")
        if not expected_active_build:
            raise HarnessError("--expected-active-build is required")
        self.client = client
        self.repository = repository
        self.fixture_sha = fixture_sha
        self.expected_active_build = expected_active_build
        self.poll_timeout = poll_timeout
        self.poll_interval = poll_interval
        self.github_transport = github_transport
        self.evidence = Evidence(source_sha, fixture_sha, repository)

    @property
    def org_path(self) -> str:
        return f"/v3/organizations/{self.client.org_id}"

    def active_build(self) -> Mapping[str, object]:
        response = self.client.request(
            "GET",
            f"/v3/organizations/{self.client.org_id}/snapshot-setup/builds?active=true&first=2",
        )
        items = require_items(response, "active build")
        if len(items) != 1:
            raise HarnessError("Devin did not report exactly one active build")
        build = items[0]
        if build.get("build_id") != self.expected_active_build or build.get("status") != "succeeded":
            raise HarnessError("active Devin build does not match the expected successful build")
        return build

    def verify_repository_access(self) -> None:
        query = urllib.parse.urlencode({
            "filter_name": self.repository.rsplit("/", 1)[1],
            "load_indexing_status": "false",
            "first": 100,
        })
        response = self.client.request(
            "GET", f"/v3/organizations/{self.client.org_id}/repositories?{query}"
        )
        matches = [item for item in require_items(response, "repository access") if item.get("repo_path") == self.repository]
        if len(matches) != 1:
            raise HarnessError("the exact public fixture repository is not available to this Devin organization")

    def messages(self, session_id: str) -> list[Mapping[str, object]]:
        response = self.client.request(
            "GET", f"{self.org_path}/sessions/{session_id}/messages?first=200"
        )
        return require_items(response, "session messages")

    def session(self, session_id: str) -> Mapping[str, object]:
        return self.client.request("GET", f"{self.org_path}/sessions/{session_id}")

    def wait_for_devin(
        self, session_id: str, *, after_events: set[str], canary: str
    ) -> tuple[list[str], set[str]]:
        deadline = time.monotonic() + self.poll_timeout
        while time.monotonic() < deadline:
            messages = self.messages(session_id)
            new = [
                item for item in messages
                if item.get("source") == "devin" and item.get("event_id") not in after_events
            ]
            text = [str(item.get("message", "")) for item in new]
            if canary in "\n".join(text):
                return text, {str(item.get("event_id")) for item in messages}
            state = self.session(session_id)
            if state.get("status") in {"error", "exit", "suspended"}:
                raise HarnessError(
                    f"Devin session ended before the required canary: {state.get('status_detail') or state.get('status')}"
                )
            time.sleep(self.poll_interval)
        raise HarnessError("timed out waiting for Devin conformance output")

    def settle_implicit_output(self, session_id: str, observed_events: set[str]) -> set[str]:
        """Check delayed implicit output before the explicit skill turn begins."""
        observed = set(observed_events)
        for _ in range(2):
            messages = self.messages(session_id)
            new = [
                item for item in messages
                if item.get("source") == "devin" and str(item.get("event_id")) not in observed
            ]
            text = "\n".join(str(item.get("message", "")) for item in new)
            if SKILL_CANARY in text:
                raise HarnessError("user-only Devin skill fired without explicit invocation")
            observed.update(str(item.get("event_id")) for item in messages)
            time.sleep(self.poll_interval)
        return observed

    def wait_for_devin_after_user_message(
        self, session_id: str, user_message: str, *, canary: str
    ) -> tuple[list[str], set[str]]:
        """Use the API's chronological message order to bind the explicit turn."""
        deadline = time.monotonic() + self.poll_timeout
        while time.monotonic() < deadline:
            messages = self.messages(session_id)
            user_positions = [
                index for index, item in enumerate(messages)
                if item.get("source") != "devin" and item.get("message") == user_message
            ]
            if len(user_positions) > 1:
                raise HarnessError("Devin returned multiple matching explicit user messages")
            if user_positions:
                following = [
                    item for item in messages[user_positions[0] + 1:]
                    if item.get("source") == "devin"
                ]
                text = [str(item.get("message", "")) for item in following]
                if canary in "\n".join(text):
                    return text, {str(item.get("event_id")) for item in messages}
            state = self.session(session_id)
            if state.get("status") in {"error", "exit", "suspended"}:
                raise HarnessError(
                    f"Devin session ended before the required canary: {state.get('status_detail') or state.get('status')}"
                )
            time.sleep(self.poll_interval)
        raise HarnessError("timed out waiting for Devin explicit conformance output")

    def execute(self) -> Evidence:
        fixture_content_sha = verify_public_fixture(
            self.repository,
            self.fixture_sha,
            transport=self.github_transport,
            audit=self.evidence.github_requests,
        )
        self.verify_repository_access()
        before_build = self.active_build()
        self.evidence.active_build_id = str(before_build["build_id"])
        session_id = ""
        try:
            prompt = (
                "Read-only Context OS conformance in the supplied public synthetic repository. "
                "Do not edit files, run setup, create a branch, commit, push, or open a PR. "
                "Use the available Context OS control without an explicit @skills reference. "
                "Reply only with the root instruction canary from your repository instructions, "
                "followed by one space and the observed commit SHA from git rev-parse HEAD "
                "in the fixture checkout."
            )
            created = self.client.request(
                "POST",
                f"{self.org_path}/sessions",
                {
                    "prompt": prompt,
                    "repos": [self.repository],
                    "structured_output_required": False,
                    "title": "Context OS disposable Devin conformance",
                },
            )
            session_id = str(created.get("session_id", ""))
            if not re.fullmatch(r"devin-[A-Za-z0-9_-]+", session_id):
                raise HarnessError("session creation omitted a valid Devin session ID")
            if created.get("org_id") != self.client.org_id:
                raise HarnessError("session creation returned a different organization")
            self.evidence.session_id_sha256 = hashlib.sha256(session_id.encode()).hexdigest()
            self.evidence.devin_mode = created.get("devin_mode") if isinstance(created.get("devin_mode"), str) else None

            implicit_messages, events = self.wait_for_devin(session_id, after_events=set(), canary=ROOT_CANARY)
            implicit = "\n".join(implicit_messages)
            expected_root = f"{ROOT_CANARY} {self.fixture_sha}"
            if SKILL_CANARY in implicit:
                raise HarnessError("user-only Devin skill fired without explicit invocation")
            if not implicit_messages or normalize_fixture_reply(
                implicit_messages[-1], ROOT_CANARY
            ) != expected_root:
                raise HarnessError("implicit control did not return the exact root and fixture output")
            events = self.settle_implicit_output(session_id, events)

            explicit_prompt = f"@skills:{SKILL_NAME} Return only the canary required by this skill."
            self.client.request(
                "POST",
                f"{self.org_path}/sessions/{session_id}/messages",
                {"message": explicit_prompt},
            )
            explicit_messages, _ = self.wait_for_devin_after_user_message(
                session_id, explicit_prompt, canary=SKILL_CANARY
            )
            if not explicit_messages or normalize_fixture_reply(
                explicit_messages[-1], SKILL_CANARY
            ) != SKILL_CANARY:
                raise HarnessError("explicit skill control did not return its exact canary")

            final = self.session(session_id)
            if final.get("pull_requests") not in ([], None):
                raise HarnessError("disposable Devin session created a pull request")
            after_build = self.active_build()
            if after_build.get("build_id") != before_build.get("build_id"):
                raise HarnessError("the active Devin build changed during conformance")
            if verify_public_fixture(
                self.repository,
                self.fixture_sha,
                transport=self.github_transport,
                audit=self.evidence.github_requests,
            ) != fixture_content_sha:
                raise HarnessError("public fixture content changed during conformance")

            self.evidence.controls.update({
                "repository_access": True,
                "exact_fixture_commit": True,
                "public_fixture_content_exact": True,
                "public_fixture_default_head_unchanged": True,
                "exact_active_build": True,
                "root_instruction_discovery": True,
                "implicit_skill_must_not_fire": True,
                "explicit_skill_must_fire": True,
                "no_pull_request_created": True,
                "review_not_invoked": True,
            })
        finally:
            control_error = sys.exc_info()[1]
            control_detail = (
                f"control: {safe_error_detail(control_error)}; " if control_error else ""
            )
            if session_id:
                try:
                    archived = self.client.request(
                        "POST", f"{self.org_path}/sessions/{session_id}/archive"
                    )
                    if archived.get("session_id") != session_id:
                        raise HarnessError("session archive returned a different session ID")
                    archive_deadline = time.monotonic() + min(
                        30.0, max(1.0, self.poll_interval * 3)
                    )
                    while archived.get("is_archived") is not True:
                        if time.monotonic() >= archive_deadline:
                            break
                        time.sleep(min(5.0, max(0.1, self.poll_interval)))
                        archived = self.session(session_id)
                    if archived.get("is_archived") is not True:
                        raise HarnessError("Devin did not confirm that the session was archived")
                    self.evidence.controls["session_archived"] = True
                except HarnessError as archive_error:
                    try:
                        terminated = self.client.request(
                            "DELETE", f"{self.org_path}/sessions/{session_id}"
                        )
                        if terminated.get("session_id") != session_id:
                            raise HarnessError("session termination returned a different session ID")
                        if terminated.get("status") not in {"exit", "error", "suspended"}:
                            raise HarnessError("Devin did not confirm fallback session termination")
                        self.evidence.controls["session_terminated_after_archive_failure"] = True
                    except HarnessError as terminate_error:
                        raise HarnessError(
                            f"Devin cleanup failed: {control_detail}archive: "
                            f"{safe_error_detail(archive_error)}; fallback termination: "
                            f"{safe_error_detail(terminate_error)}"
                        ) from terminate_error
                    raise HarnessError(
                        "Devin session was terminated, but required archival failed: "
                        f"{control_detail}"
                        f"{safe_error_detail(archive_error)}"
                    ) from archive_error
        self.evidence.requests = list(self.client.requests)
        return self.evidence


def write_evidence(path: Path, evidence: Evidence) -> None:
    payload = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "runtime": "devin",
        "surface": "session",
        "source_sha": evidence.source_sha,
        "fixture_sha": evidence.fixture_sha,
        "repository": evidence.repository,
        "active_build_id": evidence.active_build_id,
        "session_id_sha256": evidence.session_id_sha256,
        "devin_mode": evidence.devin_mode,
        "requests": evidence.requests,
        "github_requests": evidence.github_requests,
        "controls": evidence.controls,
    }
    target = require_outside_source(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise HarnessError(f"refusing to overwrite evidence: {target}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--fixture-sha", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--expected-active-build", required=True)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--poll-timeout", type=float, default=900)
    parser.add_argument("--allow-account-access", action="store_true")
    parser.add_argument("--allow-session-create", action="store_true")
    parser.add_argument("--acknowledge-public-fixture", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not args.allow_account_access or not args.allow_session_create or not args.acknowledge_public_fixture:
            raise HarnessError("live Devin conformance requires all three explicit opt-in flags")
        source_sha = repository_source_sha()
        if args.source_sha != source_sha:
            raise HarnessError(f"--source-sha must equal the clean harness commit {source_sha}")
        token = os.environ.get("DEVIN_API_TOKEN", "")
        client = DevinClient(token, args.org_id)
        evidence = DevinHarness(
            client,
            repository=args.repository,
            fixture_sha=args.fixture_sha,
            source_sha=source_sha,
            expected_active_build=args.expected_active_build,
            poll_timeout=args.poll_timeout,
        ).execute()
        if repository_source_sha() != source_sha:
            raise HarnessError("source commit changed during Devin live conformance")
        write_evidence(args.evidence, evidence)
    except (HarnessError, OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"Devin live conformance failed safely: {exc}", file=sys.stderr)
        return 1
    print(f"Devin session conformance passed; evidence: {args.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
