from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "adapters/openclaw/sync_skills.py"
SPEC = importlib.util.spec_from_file_location("openclaw_skill_sync", SCRIPT)
assert SPEC and SPEC.loader
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)


class OpenClawSkillSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name) / "workspace"
        self.workspace.mkdir()

    def _run(self, command: str) -> tuple[int, dict]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), command, "--workspace", str(self.workspace)],
            cwd=ROOT, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=False,
        )
        self.assertTrue(result.stdout, result.stderr)
        return result.returncode, json.loads(result.stdout)

    def _sync(self) -> dict:
        code, report = self._run("sync")
        self.assertEqual(0, code, report)
        return report

    def _check(self) -> dict:
        code, report = self._run("check")
        self.assertIn(code, (0, 1), report)
        return report

    def test_initial_sync_and_current_check_record_per_file_provenance(self) -> None:
        initial = self._check()
        self.assertFalse(initial["current"])
        self.assertIn("missing_manifest", {item["kind"] for item in initial["findings"]})
        report = self._sync()
        self.assertEqual(list(SYNC.SKILLS), report["skills"])
        manifest = json.loads((self.workspace / SYNC.MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(report["source_git_sha"], manifest["source_git_sha"])
        self.assertEqual(set(SYNC.SKILLS), set(manifest["skills"]))
        self.assertTrue(all(files for files in manifest["skills"].values()))
        self.assertTrue(self._check()["current"])

    def test_changed_missing_and_extra_target_files_are_reported_then_refreshed(self) -> None:
        self._sync()
        skills = self.workspace / ".agents/skills"
        (skills / "setup/SKILL.md").write_text("changed", encoding="utf-8")
        (skills / "start/SKILL.md").unlink()
        (skills / "update/EXTRA.md").write_text("extra", encoding="utf-8")
        unrelated = skills / "my-private-skill/SKILL.md"
        unrelated.parent.mkdir()
        unrelated.write_text("private", encoding="utf-8")
        report = self._check()
        findings = {(item["kind"], item["path"]) for item in report["findings"]}
        self.assertIn(("changed", ".agents/skills/setup/SKILL.md"), findings)
        self.assertIn(("missing", ".agents/skills/start/SKILL.md"), findings)
        self.assertIn(("extra", ".agents/skills/update/EXTRA.md"), findings)
        self._sync()
        self.assertEqual("private", unrelated.read_text(encoding="utf-8"))
        self.assertTrue(self._check()["current"])

    def test_stale_source_sha_and_file_inventory_are_reported(self) -> None:
        source_root = Path(self.temporary.name) / "source-skills"
        source_root.mkdir()
        shutil.copytree(ROOT / ".agents/skills/setup", source_root / "setup")
        with (
            mock.patch.object(SYNC, "SOURCE_ROOT", source_root),
            mock.patch.object(SYNC, "SKILLS", ("setup",)),
            mock.patch.object(SYNC, "_git_sha", return_value="1" * 40),
        ):
            SYNC.sync(self.workspace)
        source_file = source_root / "setup/SKILL.md"
        source_file.write_text(source_file.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        with (
            mock.patch.object(SYNC, "SOURCE_ROOT", source_root),
            mock.patch.object(SYNC, "SKILLS", ("setup",)),
            mock.patch.object(SYNC, "_git_sha", return_value="2" * 40),
        ):
            findings = {item["kind"] for item in SYNC.check(self.workspace)["findings"]}
        self.assertIn("stale_source_sha", findings)
        self.assertIn("stale_source_files", findings)

    def test_target_skill_symlink_is_rejected(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        skills = self.workspace / ".agents/skills"
        skills.mkdir(parents=True)
        external = Path(self.temporary.name) / "external"
        external.mkdir()
        try:
            os.symlink(external, skills / "setup", target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        code, report = self._run("sync")
        self.assertEqual(2, code)
        self.assertIn("symlink or reparse", report["error"])

    def test_nested_target_symlink_is_rejected_before_replacement(self) -> None:
        self._sync()
        external = Path(self.temporary.name) / "external"
        external.write_text("external", encoding="utf-8")
        link = self.workspace / ".agents/skills/setup/nested-link"
        try:
            os.symlink(external, link)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        original = (self.workspace / ".agents/skills/setup/SKILL.md").read_bytes()
        code, report = self._run("sync")
        self.assertEqual(2, code)
        self.assertIn("symlink or reparse", report["error"])
        self.assertEqual(original, (self.workspace / ".agents/skills/setup/SKILL.md").read_bytes())

    def test_source_symlink_is_rejected(self) -> None:
        source = Path(self.temporary.name) / "source"
        source.mkdir()
        external = Path(self.temporary.name) / "external-file"
        external.write_text("external", encoding="utf-8")
        try:
            os.symlink(external, source / "SKILL.md")
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        with mock.patch.object(SYNC, "SOURCE_ROOT", source.parent), mock.patch.object(SYNC, "SKILLS", (source.name,)):
            with self.assertRaises(SYNC.SyncError):
                SYNC.sync(self.workspace)

    def test_failed_replacement_rolls_back_all_managed_skills_and_manifest(self) -> None:
        SYNC.sync(self.workspace)
        before = {
            skill: SYNC._inventory(self.workspace / ".agents/skills" / skill, label="test")
            for skill in SYNC.SKILLS
        }
        manifest_before = (self.workspace / SYNC.MANIFEST_NAME).read_bytes()
        real_replace = os.replace
        replacements = 0

        def fail_mid_swap(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
            nonlocal replacements
            source_path = Path(source)
            if source_path.parent.name == "stage":
                replacements += 1
                if replacements == 3:
                    raise OSError("injected replacement failure")
            real_replace(source, destination)

        with mock.patch.object(SYNC.os, "replace", side_effect=fail_mid_swap):
            with self.assertRaisesRegex(SYNC.SyncError, "rolled back"):
                SYNC.sync(self.workspace)
        after = {
            skill: SYNC._inventory(self.workspace / ".agents/skills" / skill, label="test")
            for skill in SYNC.SKILLS
        }
        self.assertEqual(before, after)
        self.assertEqual(manifest_before, (self.workspace / SYNC.MANIFEST_NAME).read_bytes())


if __name__ == "__main__":
    unittest.main()
