from __future__ import annotations

import hashlib
import io
import importlib.util
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "publish_release", ROOT / "scripts/publish-release.py"
)
assert SPEC is not None and SPEC.loader is not None
publish_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publish_release)


REPOSITORY = "conorbronsdon/agent-context-os"
VERSION = "0.12.0"
TAG = "v0.12.0"
COMMIT = "a" * 40
RUN_ID = 12345
ATTEMPT = 3
ARTIFACT_ID = 67890
RELEASE_ID = 24680


class FakeArtifacts:
    names = {
        "archive": "agent-context-os-template-v0.12.0.tar",
        "lock": "agent-context-os-template-v0.12.0.bundle.lock.json",
        "provenance": "agent-context-os-template-v0.12.0.provenance.json",
        "instructions": "agent-context-os-template-v0.12.0.OFFLINE-VERIFY.md",
        "checksums": "SHA256SUMS",
    }

    @classmethod
    def artifact_names(cls, version: str) -> dict[str, str]:
        if version != VERSION:
            raise AssertionError(version)
        return cls.names

    @staticmethod
    def verify_artifacts(root: Path, extracted: Path, **_: object) -> None:
        if {path.name for path in root.iterdir()} != set(FakeArtifacts.names.values()):
            raise AssertionError("unexpected test artifact set")
        extracted.mkdir()


class FakeGitHubRunner:
    def __init__(self, root: Path, *, published: bool = False) -> None:
        self.root = root
        self.published = published
        self.immutable = published
        self.patch_count = 0
        self.calls: list[tuple[str, ...]] = []
        self.other_runs: list[dict[str, object]] = []
        self.main_sha = COMMIT
        self.tag_sha = COMMIT
        self.artifact_replaced = False
        self.verify_ok = True
        self.payloads = {
            name: (name + "\n").encode("utf-8") for name in FakeArtifacts.names.values()
        }
        self.body = (root / "docs/releases/v0.12.0.md").read_text(encoding="utf-8")

    def _completed(self, arguments: tuple[str, ...], stdout: str = "", returncode: int = 0):
        self.calls.append(arguments)
        return subprocess.CompletedProcess(arguments, returncode, stdout, "")

    def _run_value(self) -> dict[str, object]:
        return {
            "event": "workflow_dispatch", "head_branch": "main", "head_sha": COMMIT,
            "path": ".github/workflows/release.yml", "status": "completed",
            "conclusion": "success", "run_attempt": ATTEMPT,
        }

    def _artifact(self) -> dict[str, object]:
        return {
            "id": ARTIFACT_ID + int(self.artifact_replaced),
            "name": f"v{VERSION}-candidate-{COMMIT}-{RUN_ID}-{ATTEMPT}",
            "expired": False, "size_in_bytes": 111,
            "digest": "sha256:" + "b" * 64,
            "workflow_run": {"id": RUN_ID, "head_sha": COMMIT, "head_branch": "main"},
        }

    def _release(self) -> dict[str, object]:
        assets = []
        for index, (name, payload) in enumerate(sorted(self.payloads.items()), start=1):
            assets.append({
                "id": index, "name": name, "size": len(payload),
                "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
            })
        return {
            "id": RELEASE_ID, "tag_name": TAG, "name": f"Context OS v{VERSION}",
            "body": self.body, "draft": not self.published, "prerelease": False,
            "immutable": self.immutable, "assets": assets,
        }

    def run(self, arguments, *, cwd=None, check=True):
        args = tuple(str(value) for value in arguments)
        if args[:2] == ("git", "rev-parse"):
            return self._completed(args, COMMIT + "\n")
        if args[:2] == ("git", "status"):
            return self._completed(args, "")
        if args[:3] == ("gh", "release", "download"):
            destination = Path(args[args.index("--dir") + 1])
            for name, payload in self.payloads.items():
                (destination / name).write_bytes(payload)
            return self._completed(args)
        if args[:3] in (("gh", "release", "verify"), ("gh", "release", "verify-asset")):
            if "--help" in args:
                return self._completed(args)
            code = 0 if self.verify_ok else 1
            result = self._completed(args, returncode=code)
            if check and code:
                raise publish_release.PublishError("fake attestation failure")
            return result
        if args == ("gh", "api", "user", "--jq", ".login"):
            return self._completed(args, "release-operator\n")
        raise AssertionError(f"unexpected run command: {args}")

    def json(self, arguments, *, cwd=None):
        args = tuple(str(value) for value in arguments)
        self.calls.append(args)
        endpoint = next((value for value in args if value.startswith("repos/")), "")
        if endpoint.endswith("/git/ref/heads/main"):
            return {"object": {"type": "commit", "sha": self.main_sha}}
        if endpoint.endswith(f"/git/ref/tags/{TAG}"):
            return {"object": {"type": "commit", "sha": self.tag_sha}}
        if endpoint.endswith(f"/actions/runs/{RUN_ID}") or endpoint.endswith(
            f"/actions/runs/{RUN_ID}/attempts/{ATTEMPT}"
        ):
            return self._run_value()
        if endpoint.endswith(f"/attempts/{ATTEMPT}/jobs?per_page=100"):
            return {"jobs": [
                {"name": name, "run_attempt": ATTEMPT, "status": "completed", "conclusion": "success"}
                for name in publish_release.REQUIRED_JOBS
            ]}
        if endpoint.endswith(f"/actions/runs/{RUN_ID}/artifacts?per_page=100"):
            return {"artifacts": [self._artifact()]}
        if endpoint.endswith(f"/actions/artifacts/{ARTIFACT_ID}"):
            return self._artifact()
        if "/releases/" in endpoint and "/actions/" not in endpoint:
            if "PATCH" in args:
                if not endpoint.endswith(f"/releases/{RELEASE_ID}"):
                    raise AssertionError("PATCH targeted an unselected release")
                self.patch_count += 1
                self.published = True
                self.immutable = True
            return self._release()
        if endpoint.endswith("/actions/workflows/release.yml/runs?per_page=100"):
            return {"workflow_runs": [{"id": RUN_ID, "status": "completed"}, *self.other_runs]}
        if endpoint.endswith("/immutable-releases"):
            return {"enabled": True}
        raise AssertionError(f"unexpected json command: {args}")

    def download_artifact(self, repository, artifact, destination, expected_names):
        self.calls.append(("download-artifact-id", str(artifact["id"])))
        if repository != REPOSITORY or artifact["id"] != ARTIFACT_ID:
            raise AssertionError("artifact was not downloaded by the selected numeric ID")
        for name, payload in self.payloads.items():
            (destination / name).write_bytes(payload)
        if set(self.payloads) != expected_names:
            raise AssertionError("unexpected names")


class PublishReleaseTest(unittest.TestCase):
    def _publish(
        self, fake: FakeGitHubRunner, *, release_id: int = RELEASE_ID,
        verify_published: bool = False,
    ):
        with mock.patch.object(publish_release, "_load_release_artifacts", return_value=FakeArtifacts):
            return publish_release.publish_release(
                root=ROOT, repository=REPOSITORY, run_id=RUN_ID,
                release_id=release_id, commit=COMMIT,
                version=VERSION, tag=TAG, wait_attempts=1, wait_seconds=0,
                verify_published=verify_published, runner=fake,
            )

    def test_state_machine_publishes_exact_numeric_release_once(self) -> None:
        fake = FakeGitHubRunner(ROOT)
        result = self._publish(fake)
        self.assertEqual(fake.patch_count, 1)
        self.assertEqual(result["mode"], "publish")
        self.assertEqual(result["candidate_artifact_id"], ARTIFACT_ID)
        self.assertIn(("download-artifact-id", str(ARTIFACT_ID)), fake.calls)
        patches = [call for call in fake.calls if "PATCH" in call]
        self.assertEqual(len(patches), 1)
        self.assertIn(f"repos/{REPOSITORY}/releases/{RELEASE_ID}", patches[0])
        self.assertFalse(any(call[:3] == ("gh", "release", "view") for call in fake.calls))
        self.assertFalse(any(call[:3] == ("git", "ls-remote", "origin") for call in fake.calls))

    def test_wrong_numeric_release_id_prevents_patch(self) -> None:
        fake = FakeGitHubRunner(ROOT)
        with self.assertRaisesRegex(
            publish_release.PublishError, "selected numeric ID"
        ):
            self._publish(fake, release_id=RELEASE_ID + 1)
        self.assertEqual(fake.patch_count, 0)
        self.assertFalse(any("PATCH" in call for call in fake.calls))
        self.assertFalse(
            any(call[:3] == ("gh", "release", "download") for call in fake.calls)
        )

    def test_invalid_release_id_fails_before_runner_calls_in_both_modes(self) -> None:
        for release_id in (0, -1, True):
            for verify_published in (False, True):
                with self.subTest(
                    release_id=release_id, verify_published=verify_published
                ):
                    fake = FakeGitHubRunner(ROOT, published=verify_published)
                    with self.assertRaisesRegex(
                        publish_release.PublishError, "release ID must be"
                    ):
                        self._publish(
                            fake, release_id=release_id,
                            verify_published=verify_published,
                        )
                    self.assertEqual(fake.calls, [])
                    self.assertEqual(fake.patch_count, 0)

    def test_cli_requires_release_id(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            publish_release.main([
                "--repository", REPOSITORY, "--run-id", str(RUN_ID),
                "--commit", COMMIT, "--version", VERSION, "--tag", TAG,
            ])
        self.assertEqual(raised.exception.code, 2)

    def test_binary_artifact_download_binds_zip_digest_and_exact_files(self) -> None:
        payloads = {name: (name + "\n").encode() for name in FakeArtifacts.names.values()}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, payload in payloads.items():
                archive.writestr(name, payload)
        zip_bytes = buffer.getvalue()
        artifact = {
            "id": ARTIFACT_ID, "size_in_bytes": len(zip_bytes),
            "digest": "sha256:" + hashlib.sha256(zip_bytes).hexdigest(),
        }

        def stream_zip(arguments, **kwargs):
            kwargs["stdout"].write(zip_bytes)
            return subprocess.CompletedProcess(arguments, 0, b"", b"")

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "assets"
            destination.mkdir()
            with mock.patch.object(publish_release.subprocess, "run", side_effect=stream_zip):
                publish_release.CommandRunner().download_artifact(
                    REPOSITORY, artifact, destination, set(payloads),
                )
            self.assertEqual(
                {path.name: path.read_bytes() for path in destination.iterdir()}, payloads
            )

            artifact["digest"] = "sha256:" + "0" * 64
            with mock.patch.object(publish_release.subprocess, "run", side_effect=stream_zip):
                with self.assertRaisesRegex(publish_release.PublishError, "digest changed"):
                    publish_release.CommandRunner().download_artifact(
                        REPOSITORY, artifact, destination, set(payloads),
                    )

    def test_target_repository_ref_movement_prevents_patch(self) -> None:
        for attribute in ("main_sha", "tag_sha"):
            with self.subTest(attribute=attribute):
                fake = FakeGitHubRunner(ROOT)
                setattr(fake, attribute, "c" * 40)
                with self.assertRaisesRegex(publish_release.PublishError, "target repository"):
                    self._publish(fake)
                self.assertEqual(fake.patch_count, 0)

    def test_artifact_replacement_after_exact_id_download_prevents_patch(self) -> None:
        fake = FakeGitHubRunner(ROOT)

        def replace_after_download(repository, artifact, destination, expected_names):
            FakeGitHubRunner.download_artifact(
                fake, repository, artifact, destination, expected_names,
            )
            fake.artifact_replaced = True

        fake.download_artifact = replace_after_download
        with self.assertRaisesRegex(publish_release.PublishError, "artifact ID changed"):
            self._publish(fake)
        self.assertEqual(fake.patch_count, 0)

    def test_every_nonterminal_competing_run_prevents_patch(self) -> None:
        for status in ("queued", "in_progress", "requested", "waiting", "pending"):
            with self.subTest(status=status):
                fake = FakeGitHubRunner(ROOT)
                fake.other_runs = [{"id": 999, "status": status}]
                with self.assertRaisesRegex(publish_release.PublishError, "nonterminal"):
                    self._publish(fake)
                self.assertEqual(fake.patch_count, 0)

    def test_timeout_recovers_with_read_only_published_verification(self) -> None:
        fake = FakeGitHubRunner(ROOT)
        fake.verify_ok = False
        with self.assertRaisesRegex(publish_release.PublishError, "immutable attestation"):
            self._publish(fake)
        self.assertEqual(fake.patch_count, 1)
        fake.verify_ok = True
        result = self._publish(fake, verify_published=True)
        self.assertEqual(result["mode"], "verify-published")
        self.assertEqual(fake.patch_count, 1)
        self.assertTrue(result["immutable"])
        self.assertEqual(
            result["asset_attestations_verified"], sorted(FakeArtifacts.names.values())
        )

    def test_read_only_published_verification_is_patch_free(self) -> None:
        fake = FakeGitHubRunner(ROOT, published=True)
        result = self._publish(fake, verify_published=True)
        self.assertEqual(result["mode"], "verify-published")
        self.assertEqual(fake.patch_count, 0)
        self.assertFalse(any("PATCH" in call for call in fake.calls))

    def test_read_only_mode_rejects_draft_without_patch(self) -> None:
        fake = FakeGitHubRunner(ROOT)
        with self.assertRaisesRegex(publish_release.PublishError, "draft state"):
            self._publish(fake, verify_published=True)
        self.assertEqual(fake.patch_count, 0)

    def test_exact_run_and_required_jobs_are_fail_closed(self) -> None:
        commit = "a" * 40
        run = {
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": commit,
            "path": ".github/workflows/release.yml",
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 2,
        }
        self.assertEqual(publish_release._validate_run(run, commit=commit), 2)
        jobs = {
            "jobs": [
                {"name": name, "run_attempt": 2, "status": "completed", "conclusion": "success"}
                for name in publish_release.REQUIRED_JOBS
            ]
        }
        publish_release._validate_jobs(jobs, attempt=2)

        stale = dict(run, head_sha="b" * 40)
        with self.assertRaisesRegex(publish_release.PublishError, "head_sha"):
            publish_release._validate_run(stale, commit=commit)
        jobs["jobs"][-1]["conclusion"] = "failure"
        with self.assertRaisesRegex(publish_release.PublishError, "ready-to-publish"):
            publish_release._validate_jobs(jobs, attempt=2)

    def test_candidate_artifact_must_be_unique_and_unexpired(self) -> None:
        value = {"artifacts": [{"id": 41, "name": "candidate", "expired": False}]}
        self.assertEqual(
            publish_release._candidate_artifact(value, expected_name="candidate")["id"], 41
        )
        value["artifacts"].append({"id": 42, "name": "candidate", "expired": False})
        with self.assertRaisesRegex(publish_release.PublishError, "exactly one"):
            publish_release._candidate_artifact(value, expected_name="candidate")

    def test_release_snapshot_binds_metadata_and_downloaded_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_names = {"a.tar", "b.json", "c.json", "d.md", "SHA256SUMS"}
            assets = []
            for index, name in enumerate(sorted(expected_names), start=1):
                path = root / name
                path.write_bytes((name + "\n").encode("utf-8"))
                assets.append({
                    "id": index,
                    "name": name,
                    "size": path.stat().st_size,
                    "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                })
            release = {
                "tag_name": "v0.12.0",
                "name": "Context OS v0.12.0",
                "body": "notes\r\n",
                "draft": True,
                "prerelease": False,
                "assets": assets,
            }
            snapshot = publish_release._asset_snapshot(
                release,
                expected_names=expected_names,
                expected_tag="v0.12.0",
                expected_title="Context OS v0.12.0",
                expected_body="notes\n",
                draft=True,
            )
            publish_release._require_server_bytes(snapshot, root)
            (root / "a.tar").write_bytes(b"substituted\n")
            with self.assertRaisesRegex(publish_release.PublishError, "size|digest"):
                publish_release._require_server_bytes(snapshot, root)

    def test_candidate_and_release_directories_must_be_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()
            names = {"one", "two"}
            for name in names:
                (left / name).write_text(name, encoding="utf-8")
                (right / name).write_text(name, encoding="utf-8")
            publish_release._require_same_files(left, right, names)
            (right / "two").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(publish_release.PublishError, "differs"):
                publish_release._require_same_files(left, right, names)

    def test_admin_policy_check_is_immediately_before_numeric_id_patch(self) -> None:
        source = (ROOT / "scripts/publish-release.py").read_text(encoding="utf-8")
        policy = source.index('f"repos/{repository}/immutable-releases"')
        patch = source.index('"gh", "api", "--method", "PATCH"')
        self.assertLess(source.rindex("_require_no_competing_runs", 0, policy), policy)
        self.assertLess(source.rindex("final_snapshot = _asset_snapshot", 0, policy), policy)
        self.assertLess(policy, patch)
        between = source[policy:patch]
        self.assertNotIn("runner.", between.rsplit("runner.json([", 1)[0])

    def test_workflow_artifact_name_binds_run_and_attempt_without_overwrite(self) -> None:
        source = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        qualified = (
            "v0.12.0-candidate-${{ inputs.commit }}-"
            "${{ github.run_id }}-${{ github.run_attempt }}"
        )
        self.assertGreaterEqual(source.count(qualified), 5)
        self.assertNotIn("overwrite: true", source)


if __name__ == "__main__":
    unittest.main()
