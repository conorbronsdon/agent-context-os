#!/usr/bin/env python3
"""Publish one fully qualified draft with a local admin-authenticated GitHub CLI."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_JOBS = (
    "build-linux",
    "verify-candidate-linux",
    "verify-candidate-windows",
    "stage-draft",
    "verify-draft-linux",
    "verify-draft-windows",
    "ready-to-publish",
)


class PublishError(RuntimeError):
    """Raised before or after publication when a release invariant fails."""


class CommandRunner:
    """Small subprocess boundary so the irreversible sequence can be tested."""

    def run(
        self, arguments: Sequence[str], *, cwd: Path | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                list(arguments), cwd=cwd, check=check, capture_output=True,
                text=True, encoding="utf-8",
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            stderr = getattr(exc, "stderr", "") or ""
            detail = stderr.strip()
            raise PublishError(
                "command failed: " + " ".join(arguments) + (f": {detail}" if detail else "")
            ) from exc

    def json(self, arguments: Sequence[str], *, cwd: Path | None = None) -> Any:
        completed = self.run(arguments, cwd=cwd)
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise PublishError("command did not return valid JSON: " + " ".join(arguments)) from exc

    def download_artifact(
        self, repository: str, artifact: dict[str, Any], destination: Path,
        expected_names: set[str],
    ) -> None:
        """Download one exact Actions artifact ID and safely extract its zip."""
        artifact_id = artifact["id"]
        archive = destination.parent / f"artifact-{artifact_id}.zip"
        arguments = [
            "gh", "api", "-H", "X-GitHub-Api-Version: 2026-03-10",
            f"repos/{repository}/actions/artifacts/{artifact_id}/zip",
        ]
        try:
            with archive.open("wb") as output:
                completed = subprocess.run(
                    arguments, check=False, stdout=output, stderr=subprocess.PIPE,
                    cwd=ROOT, text=False,
                )
        except OSError as exc:
            raise PublishError("artifact download failed") from exc
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise PublishError(f"artifact download failed: {detail}")
        _require(archive.stat().st_size == artifact["size_in_bytes"],
                 "Actions artifact zip size changed during download")
        _require("sha256:" + _sha256_file(archive) == artifact["digest"],
                 "Actions artifact zip digest changed during download")
        try:
            with zipfile.ZipFile(archive) as bundle:
                seen: set[str] = set()
                for member in bundle.infolist():
                    parts = Path(member.filename).parts
                    _require(
                        not member.is_dir() and not Path(member.filename).is_absolute()
                        and ".." not in parts and len(parts) == 1,
                        "Actions artifact zip contains an unsafe path",
                    )
                    _require(member.filename not in seen, "Actions artifact zip has duplicate names")
                    seen.add(member.filename)
                    mode = member.external_attr >> 16
                    _require((mode & 0o170000) != 0o120000,
                             "Actions artifact zip contains a symbolic link")
                _require(seen == expected_names,
                         "Actions artifact zip names do not match the five-file contract")
                bundle.extractall(destination)
        except (OSError, zipfile.BadZipFile) as exc:
            raise PublishError("Actions artifact is not a valid zip") from exc


def _load_release_artifacts() -> Any:
    path = ROOT / "scripts/release-artifacts.py"
    spec = importlib.util.spec_from_file_location("release_artifacts", path)
    if spec is None or spec.loader is None:
        raise PublishError("cannot load scripts/release-artifacts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_body(value: str) -> str:
    return value.replace("\r\n", "\n").rstrip("\n")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublishError(message)


def _git_text(runner: CommandRunner, root: Path, *arguments: str) -> str:
    return runner.run(["git", *arguments], cwd=root).stdout.strip()


def _github_ref(runner: CommandRunner, repository: str, ref: str) -> str:
    value = runner.json([
        "gh", "api", "-H", "X-GitHub-Api-Version: 2026-03-10",
        f"repos/{repository}/git/ref/{ref}",
    ])
    _require(isinstance(value, dict) and isinstance(value.get("object"), dict),
             f"target repository ref is absent or malformed: {ref}")
    target = value["object"]
    _require(target.get("type") == "commit" and COMMIT_RE.fullmatch(target.get("sha") or ""),
             f"target repository ref is not a commit: {ref}")
    return target["sha"]


def _validate_run(value: Any, *, commit: str) -> int:
    _require(isinstance(value, dict), "workflow run response must be an object")
    expected = {
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": commit,
        "path": ".github/workflows/release.yml",
        "status": "completed",
        "conclusion": "success",
    }
    for key, wanted in expected.items():
        _require(value.get(key) == wanted, f"workflow run {key} does not match: {value.get(key)!r}")
    attempt = value.get("run_attempt")
    _require(type(attempt) is int and attempt > 0, "workflow run attempt must be a positive integer")
    return attempt


def _validate_jobs(value: Any, *, attempt: int) -> None:
    _require(isinstance(value, dict) and isinstance(value.get("jobs"), list), "jobs response is invalid")
    current = [job for job in value["jobs"] if job.get("run_attempt", attempt) == attempt]
    by_name = {job.get("name"): job for job in current}
    for name in REQUIRED_JOBS:
        job = by_name.get(name)
        _require(job is not None, f"required workflow job is absent: {name}")
        _require(job.get("status") == "completed" and job.get("conclusion") == "success",
                 f"required workflow job did not succeed: {name}")


def _candidate_artifact(value: Any, *, expected_name: str) -> dict[str, Any]:
    _require(isinstance(value, dict) and isinstance(value.get("artifacts"), list),
             "workflow artifacts response is invalid")
    matches = [
        artifact for artifact in value["artifacts"]
        if artifact.get("name") == expected_name and artifact.get("expired") is False
    ]
    _require(len(matches) == 1, "exactly one unexpired candidate Actions artifact is required")
    artifact_id = matches[0].get("id")
    _require(type(artifact_id) is int and artifact_id > 0, "candidate artifact ID is invalid")
    return matches[0]


def _validate_artifact_record(
    artifact: Any, *, expected_id: int | None, expected_name: str,
    run_id: int, commit: str,
) -> dict[str, Any]:
    _require(isinstance(artifact, dict), "candidate artifact response must be an object")
    if expected_id is not None:
        _require(artifact.get("id") == expected_id, "candidate artifact ID changed")
    _require(artifact.get("name") == expected_name, "candidate artifact name changed")
    _require(artifact.get("expired") is False, "candidate artifact expired")
    size = artifact.get("size_in_bytes")
    digest = artifact.get("digest")
    _require(type(size) is int and size > 0, "candidate artifact zip size is invalid")
    _require(isinstance(digest, str) and digest.startswith("sha256:")
             and SHA256_RE.fullmatch(digest.removeprefix("sha256:")) is not None,
             "candidate artifact zip digest is invalid")
    workflow_run = artifact.get("workflow_run")
    _require(isinstance(workflow_run, dict), "candidate artifact workflow identity is absent")
    _require(workflow_run.get("id") == run_id, "candidate artifact belongs to another run")
    _require(workflow_run.get("head_sha") == commit, "candidate artifact commit does not match")
    _require(workflow_run.get("head_branch") == "main", "candidate artifact branch does not match")
    return artifact


def _asset_snapshot(
    release: Any, *, expected_names: set[str], expected_tag: str,
    expected_title: str, expected_body: str, draft: bool,
) -> tuple[tuple[int, str, int, str], ...]:
    _require(isinstance(release, dict), "release response must be an object")
    _require(release.get("tag_name") == expected_tag, "release tag does not match")
    _require(release.get("name") == expected_title, "release title does not match")
    _require(_normalized_body(release.get("body") or "") == _normalized_body(expected_body),
             "release body does not match the checked-in notes")
    _require(release.get("draft") is draft, "release draft state does not match")
    _require(release.get("prerelease") is False, "release must not be a prerelease")
    assets = release.get("assets")
    _require(isinstance(assets, list), "release assets response is invalid")
    _require({asset.get("name") for asset in assets} == expected_names,
             "release asset names do not match the five-file contract")
    snapshot: list[tuple[int, str, int, str]] = []
    for asset in assets:
        asset_id = asset.get("id")
        name = asset.get("name")
        size = asset.get("size")
        digest = asset.get("digest")
        _require(type(asset_id) is int and asset_id > 0, f"release asset ID is invalid: {name}")
        _require(isinstance(name, str) and name in expected_names, "release asset name is invalid")
        _require(type(size) is int and size >= 0, f"release asset size is invalid: {name}")
        _require(
            isinstance(digest, str) and digest.startswith("sha256:")
            and SHA256_RE.fullmatch(digest.removeprefix("sha256:")) is not None,
            f"release asset digest is invalid: {name}",
        )
        snapshot.append((asset_id, name, size, digest))
    return tuple(sorted(snapshot, key=lambda item: item[1]))


def _require_server_bytes(snapshot: Sequence[tuple[int, str, int, str]], root: Path) -> None:
    local = {path.name: path for path in root.iterdir() if path.is_file()}
    _require({item[1] for item in snapshot} == set(local), "downloaded asset names do not match server state")
    for _, name, size, digest in snapshot:
        path = local[name]
        _require(path.stat().st_size == size, f"downloaded asset size does not match server: {name}")
        _require("sha256:" + _sha256_file(path) == digest,
                 f"downloaded asset digest does not match server: {name}")


def _require_same_files(left: Path, right: Path, expected_names: set[str]) -> None:
    left_files = {path.name: path for path in left.iterdir() if path.is_file()}
    right_files = {path.name: path for path in right.iterdir() if path.is_file()}
    _require(set(left_files) == expected_names and set(right_files) == expected_names,
             "candidate and release asset sets do not match the contract")
    for name in sorted(expected_names):
        _require(left_files[name].read_bytes() == right_files[name].read_bytes(),
                 f"draft or published asset differs from the exact-run candidate: {name}")


def _release_by_id(runner: CommandRunner, repository: str, release_id: int) -> Any:
    value = runner.json([
        "gh", "api", "-H", "X-GitHub-Api-Version: 2026-03-10",
        f"repos/{repository}/releases/{release_id}",
    ])
    _require(
        isinstance(value, dict) and type(value.get("id")) is int
        and value["id"] == release_id,
        "release response does not match the selected numeric ID",
    )
    return value


def _require_no_competing_runs(
    runner: CommandRunner, repository: str, *, selected_run_id: int,
) -> None:
    value = runner.json([
        "gh", "api",
        f"repos/{repository}/actions/workflows/release.yml/runs?per_page=100",
    ])
    _require(isinstance(value, dict) and isinstance(value.get("workflow_runs"), list),
             "release workflow runs response is invalid")
    for run in value["workflow_runs"]:
        run_id = run.get("id")
        status = run.get("status")
        if run_id != selected_run_id and status != "completed":
            raise PublishError(f"another release workflow run is nonterminal: {run_id} ({status})")


def _artifact_for_attempt(
    runner: CommandRunner, repository: str, run_id: int, *,
    version: str, commit: str, attempt: int,
) -> dict[str, Any]:
    expected_name = f"v{version}-candidate-{commit}-{run_id}-{attempt}"
    value = runner.json([
        "gh", "api", f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100",
    ])
    artifact = _candidate_artifact(value, expected_name=expected_name)
    return _validate_artifact_record(
        artifact, expected_id=None, expected_name=expected_name,
        run_id=run_id, commit=commit,
    )


def _recheck_artifact(
    runner: CommandRunner, repository: str, *, artifact: dict[str, Any],
    expected_name: str, run_id: int, commit: str,
) -> dict[str, Any]:
    current = runner.json([
        "gh", "api", "-H", "X-GitHub-Api-Version: 2026-03-10",
        f"repos/{repository}/actions/artifacts/{artifact['id']}",
    ])
    current = _validate_artifact_record(
        current, expected_id=artifact["id"], expected_name=expected_name,
        run_id=run_id, commit=commit,
    )
    _require(current["size_in_bytes"] == artifact["size_in_bytes"],
             "candidate artifact zip size changed")
    _require(current["digest"] == artifact["digest"], "candidate artifact zip digest changed")
    return current


def _recheck_run_attempt(
    runner: CommandRunner, repository: str, *, run_id: int, attempt: int, commit: str,
) -> None:
    current = runner.json(["gh", "api", f"repos/{repository}/actions/runs/{run_id}"])
    _require(_validate_run(current, commit=commit) == attempt,
             "workflow run advanced to another attempt")
    selected = runner.json([
        "gh", "api", f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}",
    ])
    _require(_validate_run(selected, commit=commit) == attempt,
             "selected workflow run attempt changed")


def publish_release(
    *, root: Path, repository: str, run_id: int, release_id: int, commit: str,
    version: str, tag: str, wait_attempts: int, wait_seconds: float,
    verify_published: bool = False,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    runner = runner or CommandRunner()
    root = root.absolute().resolve()
    _require(COMMIT_RE.fullmatch(commit) is not None, "commit must be exact lowercase 40-hex")
    _require(tag == f"v{version}", "tag must equal v<version>")
    _require(type(run_id) is int and run_id > 0, "run ID must be a positive integer")
    _require(type(release_id) is int and release_id > 0,
             "release ID must be a positive integer")
    _require(wait_attempts > 0 and wait_seconds >= 0, "attestation wait settings are invalid")

    _require(_git_text(runner, root, "rev-parse", "HEAD") == commit, "local HEAD is not the release commit")
    _require(_git_text(runner, root, "status", "--porcelain=v1", "--untracked-files=all") == "",
             "local release worktree is not clean")
    _require(_github_ref(runner, repository, "heads/main") == commit,
             "target repository main moved")
    _require(_github_ref(runner, repository, f"tags/{tag}") == commit,
             "target repository release tag is absent or moved")

    run = runner.json(["gh", "api", f"repos/{repository}/actions/runs/{run_id}"])
    attempt = _validate_run(run, commit=commit)
    jobs = runner.json([
        "gh", "api", f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100",
    ])
    _validate_jobs(jobs, attempt=attempt)

    release_artifacts = _load_release_artifacts()
    names = release_artifacts.artifact_names(version)
    expected_names = set(names.values())
    candidate_name = f"v{version}-candidate-{commit}-{run_id}-{attempt}"
    candidate_record = _artifact_for_attempt(
        runner, repository, run_id, version=version, commit=commit, attempt=attempt,
    )

    expected_title = f"Context OS v{version}"
    expected_body = (root / f"docs/releases/v{version}.md").read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix=f"contextos-publish-v{version}-") as temporary:
        workspace = Path(temporary)
        candidate = workspace / "candidate"
        release_assets = workspace / "release"
        published = workspace / "published"
        candidate.mkdir()
        release_assets.mkdir()
        published.mkdir()
        expected_draft = not verify_published
        first_state = _release_by_id(runner, repository, release_id)
        first_snapshot = _asset_snapshot(
            first_state, expected_names=expected_names, expected_tag=tag,
            expected_title=expected_title, expected_body=expected_body,
            draft=expected_draft,
        )
        runner.download_artifact(repository, candidate_record, candidate, expected_names)
        _recheck_artifact(
            runner, repository, artifact=candidate_record, expected_name=candidate_name,
            run_id=run_id, commit=commit,
        )
        runner.run([
            "gh", "release", "download", tag, "--repo", repository,
            "--dir", str(release_assets),
        ])
        release_artifacts.verify_artifacts(
            candidate, workspace / "candidate-extracted", version=version, tag=tag, commit=commit,
        )
        release_artifacts.verify_artifacts(
            release_assets, workspace / "release-extracted",
            version=version, tag=tag, commit=commit,
        )
        _require_same_files(candidate, release_assets, expected_names)

        _require_server_bytes(first_snapshot, release_assets)
        second_state = _release_by_id(runner, repository, release_id)
        second_snapshot = _asset_snapshot(
            second_state, expected_names=expected_names, expected_tag=tag,
            expected_title=expected_title, expected_body=expected_body, draft=expected_draft,
        )
        _require(second_snapshot == first_snapshot, "release assets changed during local verification")

        operator = runner.run(["gh", "api", "user", "--jq", ".login"]).stdout.strip()
        _require(bool(operator), "authenticated GitHub operator identity is empty")
        runner.run(["gh", "release", "verify", "--help"])
        runner.run(["gh", "release", "verify-asset", "--help"])

        if verify_published:
            _require(first_state.get("immutable") is True and second_state.get("immutable") is True,
                     "published release is not immutable")
            _require(_github_ref(runner, repository, "heads/main") == commit,
                     "target repository main moved during published verification")
            _require(_github_ref(runner, repository, f"tags/{tag}") == commit,
                     "target repository release tag moved during published verification")
            _recheck_run_attempt(
                runner, repository, run_id=run_id, attempt=attempt, commit=commit,
            )
            _recheck_artifact(
                runner, repository, artifact=candidate_record, expected_name=candidate_name,
                run_id=run_id, commit=commit,
            )
            runner.run(["gh", "release", "verify", tag, "--repo", repository])
            for name in sorted(expected_names):
                runner.run([
                    "gh", "release", "verify-asset", tag, str(release_assets / name),
                    "--repo", repository,
                ])
            return {
                "schema_version": 1,
                "mode": "verify-published",
                "repository": repository,
                "operator": operator,
                "verified_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "workflow_run_id": run_id,
                "workflow_run_attempt": attempt,
                "candidate_artifact_id": candidate_record["id"],
                "release_id": release_id,
                "tag": tag,
                "commit": commit,
                "immutable": True,
                "release_attestation_verified": True,
                "asset_attestations_verified": sorted(expected_names),
                "assets": [
                    {"id": asset_id, "name": name, "size": size, "digest": digest}
                    for asset_id, name, size, digest in second_snapshot
                ],
            }

        _require_no_competing_runs(runner, repository, selected_run_id=run_id)
        _require(_github_ref(runner, repository, "heads/main") == commit,
                 "target repository main moved before publish")
        _require(_github_ref(runner, repository, f"tags/{tag}") == commit,
                 "target repository release tag moved before publish")
        final_state = _release_by_id(runner, repository, release_id)
        final_snapshot = _asset_snapshot(
            final_state, expected_names=expected_names, expected_tag=tag,
            expected_title=expected_title, expected_body=expected_body, draft=True,
        )
        _require(final_snapshot == first_snapshot, "draft state changed before publish")
        _recheck_run_attempt(
            runner, repository, run_id=run_id, attempt=attempt, commit=commit,
        )
        _recheck_artifact(
            runner, repository, artifact=candidate_record, expected_name=candidate_name,
            run_id=run_id, commit=commit,
        )
        policy = runner.json([
            "gh", "api", "-H", "X-GitHub-Api-Version: 2026-03-10",
            f"repos/{repository}/immutable-releases",
        ])
        _require(isinstance(policy, dict) and policy.get("enabled") is True,
                 "immutable releases are not enabled immediately before publish")

        runner.json([
            "gh", "api", "--method", "PATCH", "-H", "X-GitHub-Api-Version: 2026-03-10",
            f"repos/{repository}/releases/{release_id}",
            "-F", "draft=false", "-f", "make_latest=true",
        ])

        published_state: Any = None
        attestation_ok = False
        for _ in range(wait_attempts):
            published_state = _release_by_id(runner, repository, release_id)
            if published_state.get("draft") is False and published_state.get("immutable") is True:
                verified = runner.run(
                    ["gh", "release", "verify", tag, "--repo", repository], check=False
                )
                if verified.returncode == 0:
                    attestation_ok = True
                    break
            time.sleep(wait_seconds)
        _require(attestation_ok, "published release did not expose a valid immutable attestation")
        published_snapshot = _asset_snapshot(
            published_state, expected_names=expected_names, expected_tag=tag,
            expected_title=expected_title, expected_body=expected_body, draft=False,
        )
        _require(published_state.get("immutable") is True, "published release is not immutable")
        _require(published_snapshot == first_snapshot, "published asset metadata changed")
        _require(_github_ref(runner, repository, f"tags/{tag}") == commit,
                 "release tag changed after publication")

        runner.run([
            "gh", "release", "download", tag, "--repo", repository, "--dir", str(published),
        ])
        release_artifacts.verify_artifacts(
            published, workspace / "published-extracted", version=version, tag=tag, commit=commit,
        )
        _require_same_files(candidate, published, expected_names)
        _require_server_bytes(published_snapshot, published)
        for name in sorted(expected_names):
            runner.run([
                "gh", "release", "verify-asset", tag, str(published / name),
                "--repo", repository,
            ])

        return {
            "schema_version": 1,
            "mode": "publish",
            "repository": repository,
            "operator": operator,
            "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "workflow_run_id": run_id,
            "workflow_run_attempt": attempt,
            "candidate_artifact_id": candidate_record["id"],
            "release_id": release_id,
            "tag": tag,
            "commit": commit,
            "immutable_policy_enabled": True,
            "immutable": True,
            "release_attestation_verified": True,
            "asset_attestations_verified": sorted(expected_names),
            "assets": [
                {"id": asset_id, "name": name, "size": size, "digest": digest}
                for asset_id, name, size, digest in published_snapshot
            ],
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--release-id", type=int, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--wait-attempts", type=int, default=18)
    parser.add_argument("--wait-seconds", type=float, default=5.0)
    parser.add_argument(
        "--verify-published", action="store_true",
        help="read-only recovery: verify an already-published immutable release",
    )
    args = parser.parse_args(argv)
    try:
        result = publish_release(
            root=ROOT, repository=args.repository, run_id=args.run_id,
            release_id=args.release_id,
            commit=args.commit, version=args.version, tag=args.tag,
            wait_attempts=args.wait_attempts, wait_seconds=args.wait_seconds,
            verify_published=args.verify_published,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (PublishError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"publish release: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
