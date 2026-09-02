from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path, PurePosixPath

from contextos.primitives import git_environment


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_artifacts", ROOT / "scripts/release-artifacts.py"
)
assert SPEC is not None and SPEC.loader is not None
release_artifacts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_artifacts)


class ReleaseFixture:
    version = "0.13.0"

    def __init__(self, root: Path) -> None:
        self.root = root
        for directory in ("components", "contextos", "workspace", "runtimes", "dev"):
            (root / directory).mkdir(parents=True)
        contextos_paths = []
        for source in sorted((ROOT / "contextos").glob("*.py")):
            shutil.copyfile(source, root / "contextos" / source.name)
            contextos_paths.append((f"contextos/{source.name}", "managed"))
        workspace = {
            "schema_version": 2,
            "agents": ["codex"],
            "composition": {"profile": "full-template", "extras": []},
            "paths": {
                "state_dir": "state",
                "sessions_dir": "sessions",
                "task_file": "TODO.md",
            },
            "template": {
                "version": self.version,
                "source": "agent-context-os-template",
                "bundle_sha256": "0" * 64,
            },
        }
        (root / "workspace/example.json").write_text(
            json.dumps(workspace, indent=2) + "\n", encoding="utf-8"
        )
        runtime = json.loads((ROOT / "runtimes/codex.json").read_text(encoding="utf-8"))
        runtime["components"] = ["core"]
        (root / "runtimes/codex.json").write_text(
            json.dumps(runtime, indent=2) + "\n", encoding="utf-8"
        )
        (root / "managed.txt").write_bytes(b"managed\x00bytes\n")
        (root / "seed.txt").write_text("seed\n", encoding="utf-8")
        (root / "dev/test.txt").write_text("never release\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [Unreleased]\n\n## [0.13.0] — 2026-09-02\n",
            encoding="utf-8",
        )
        paths = [
            ("components/manifest.json", "managed"),
            *contextos_paths,
            ("workspace/example.json", "managed"),
            ("runtimes/codex.json", "managed"),
            ("managed.txt", "managed"),
            ("seed.txt", "seed"),
            ("dev/test.txt", "development"),
            ("CHANGELOG.md", "development"),
        ]
        manifest = {
            "schema_version": 1,
            "extensible_paths": ["contextos.workspace.json"],
            "extensible_roots": ["state"],
            "components": [{
                "id": "core",
                "description": "Release artifact fixture.",
                "depends_on": [],
                "paths": [{"path": path, "policy": policy} for path, policy in paths],
            }],
        }
        (root / "components/manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        self.git("init", "--quiet")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Release Fixture")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.excludesFile", str(root / ".git/info/exclude"))
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "release fixture")
        self.commit = self.git("rev-parse", "HEAD").stdout.decode("ascii").strip()

    def git(self, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *arguments], cwd=self.root, check=True, capture_output=True,
            env=git_environment(),
        )

    def build(self, output: Path) -> dict:
        return release_artifacts.build_artifacts(
            self.root,
            output,
            version=self.version,
            tag="v0.13.0",
            commit=self.commit,
        )


class ReleaseArtifactTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.fixture = ReleaseFixture(self.source)

    def test_build_is_reproducible_full_closure_and_directory_verifiable(self) -> None:
        first = self.root / "first"
        second = self.root / "second"
        provenance = self.fixture.build(first)
        self.fixture.build(second)
        self.assertEqual(
            {path.name: path.read_bytes() for path in first.iterdir()},
            {path.name: path.read_bytes() for path in second.iterdir()},
        )
        report = release_artifacts.verify_artifacts(
            first,
            self.root / "extracted",
            version="0.13.0",
            tag="v0.13.0",
            commit=self.fixture.commit,
        )
        self.assertEqual(report["bundle_sha256"], provenance["bundle_lock"]["bundle_sha256"])
        self.assertEqual(report["source_mode"], "directory")
        self.assertTrue(report["unlocked_files_ignored"])
        self.assertFalse(report["writes"])
        extracted = self.root / "extracted/agent-context-os-template-v0.13.0"
        self.assertTrue((extracted / "managed.txt").is_file())
        self.assertTrue((extracted / "seed.txt").is_file())
        self.assertFalse((extracted / "dev/test.txt").exists())
        self.assertFalse((extracted / "CHANGELOG.md").exists())

    def test_generated_offline_command_works_in_documented_colocated_layout(self) -> None:
        output = self.root / "offline-verification"
        provenance = self.fixture.build(output)
        names = release_artifacts.artifact_names("0.13.0")
        instructions = (output / names["instructions"]).read_text(encoding="utf-8")
        self.assertIn("obtain all five release assets in\n   that directory", instructions)
        self.assertIn("do not select a separate extraction destination", instructions)
        self.assertIn("beside the five assets", instructions)

        with tarfile.open(output / names["archive"], mode="r:") as archive:
            for member in archive.getmembers():
                self.assertTrue(member.isfile())
                destination = output.joinpath(*PurePosixPath(member.name).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                payload = archive.extractfile(member)
                self.assertIsNotNone(payload)
                assert payload is not None
                destination.write_bytes(payload.read())
                if os.name != "nt":
                    destination.chmod(member.mode)

        extracted = output / "agent-context-os-template-v0.13.0"
        environment = git_environment()
        environment.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "contextos",
                "bundle",
                "check",
                "--lock",
                f"../{names['lock']}",
                "--source",
                ".",
                "--source-mode",
                "directory",
                "--expect-sha256",
                provenance["bundle_lock"]["bundle_sha256"],
            ],
            cwd=extracted,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["bundle_sha256"], provenance["bundle_lock"]["bundle_sha256"])
        self.assertEqual(report["files"], provenance["archive"]["file_count"])
        self.assertEqual(report["source_mode"], "directory")
        self.assertTrue(report["unlocked_files_ignored"])
        self.assertFalse(report["writes"])
        self.assertEqual(report["executable_modes_verified"], os.name != "nt")

    def test_tampered_archive_and_unexpected_asset_fail(self) -> None:
        output = self.root / "release"
        self.fixture.build(output)
        archive = output / "agent-context-os-template-v0.13.0.tar"
        archive.write_bytes(archive.read_bytes() + b"tamper")
        with self.assertRaisesRegex(release_artifacts.ReleaseArtifactError, "SHA-256 mismatch"):
            release_artifacts.verify_artifacts(
                output, self.root / "extract-one", version="0.13.0",
                tag="v0.13.0", commit=self.fixture.commit,
            )
        shutil.rmtree(output)
        self.fixture.build(output)
        (output / "unexpected.txt").write_text("extra\n", encoding="utf-8")
        with self.assertRaisesRegex(release_artifacts.ReleaseArtifactError, "artifact set"):
            release_artifacts.verify_artifacts(
                output, self.root / "extract-two", version="0.13.0",
                tag="v0.13.0", commit=self.fixture.commit,
            )

    def test_provenance_mismatch_fails_even_with_updated_checksum(self) -> None:
        output = self.root / "release"
        self.fixture.build(output)
        name = "agent-context-os-template-v0.13.0.provenance.json"
        path = output / name
        provenance = json.loads(path.read_text(encoding="utf-8"))
        provenance["release"]["commit"] = "0" * 40
        path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
        checksums = output / "SHA256SUMS"
        lines = checksums.read_text(encoding="ascii").splitlines()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksums.write_text(
            "\n".join(digest + "  " + name if line.endswith("  " + name) else line for line in lines) + "\n",
            encoding="ascii",
        )
        with self.assertRaisesRegex(release_artifacts.ReleaseArtifactError, "release identity"):
            release_artifacts.verify_artifacts(
                output, self.root / "extract", version="0.13.0",
                tag="v0.13.0", commit=self.fixture.commit,
            )

    def test_dirty_source_and_wrong_identity_fail_before_artifacts_exist(self) -> None:
        (self.source / "managed.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(release_artifacts.ReleaseArtifactError, "clean worktree"):
            self.fixture.build(self.root / "dirty-output")
        self.fixture.git("restore", "managed.txt")
        with self.assertRaisesRegex(release_artifacts.ReleaseArtifactError, "tag must equal"):
            release_artifacts.build_artifacts(
                self.source, self.root / "wrong-output", version="0.13.0",
                tag="v0.13.1", commit=self.fixture.commit,
            )

    def test_workflow_requires_both_platforms_before_tag_and_verified_draft(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn(
            "needs: [verify-candidate-linux, verify-candidate-windows]", workflow
        )
        self.assertIn(
            "needs: [stage-draft, verify-draft-linux, verify-draft-windows]", workflow
        )
        self.assertLess(workflow.index("stage-draft:"), workflow.index("ready-to-publish:"))
        self.assertNotIn("always()", workflow)
        self.assertEqual(workflow.count("contents: write"), 4)
        self.assertIn('-f "ref=refs/tags/$TAG"', workflow)
        staging = (ROOT / "scripts/stage-release.py").read_text(encoding="utf-8")
        self.assertIn("--verify-tag", staging)
        self.assertIn("python scripts/stage-release.py", workflow)
        stage = workflow.split("  stage-draft:", 1)[1].split(
            "  verify-draft-linux:", 1
        )[0]
        self.assertNotIn("gh release create", stage)
        self.assertNotIn("gh release view", stage)
        self.assertIn('echo "release_id=$RELEASE_ID"', stage)
        self.assertNotIn('--target "$RELEASE_COMMIT"', workflow)
        self.assertIn("retention-days: 7", workflow)
        build = workflow.split("  build-linux:", 1)[1].split(
            "  verify-candidate-linux:", 1
        )[0]
        self.assertNotIn("chmod +x", build)
        self.assertIn('test "$GITHUB_REF" = refs/heads/main', build)
        self.assertIn('test "$GITHUB_SHA" = "$RELEASE_COMMIT"', build)
        final = workflow.split("  ready-to-publish:", 1)[1]
        self.assertLess(
            final.index("actions/download-artifact@"),
            final.index('gh release download "$TAG"'),
        )
        self.assertLess(
            final.index("scripts/release-artifacts.py verify"),
            final.index('item["digest"] == "sha256:"'),
        )
        self.assertIn('diff --recursive --brief "$RUNNER_TEMP/candidate-assets"', final)
        self.assertIn('value["draft"] is True', final)
        self.assertIn('value["prerelease"] is False', final)
        self.assertIn("release_id: ${{ steps.stage.outputs.release_id }}", workflow)
        self.assertIn('"repos/$GITHUB_REPOSITORY/releases/$RELEASE_ID"', final)
        self.assertNotIn('releases/tags/$TAG', final)
        self.assertNotIn("\n  publish:", workflow)
        self.assertNotIn("immutable-releases", workflow)
        self.assertNotIn("gh api --method PATCH", workflow)
        self.assertNotIn("draft=false", workflow)
        self.assertNotIn("make_latest=true", workflow)
        self.assertNotIn("gh release verify", workflow)
        self.assertNotIn("already_published", workflow)
        self.assertNotIn("secrets.", workflow)
        action_references = [
            line.strip().split("uses: ", 1)[1].split(" #", 1)[0]
            for line in workflow.splitlines() if "uses: actions/" in line
        ]
        self.assertGreater(len(action_references), 0)
        for reference in action_references:
            self.assertRegex(reference, r"^actions/[a-z-]+@[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
