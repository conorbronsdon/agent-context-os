from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "adapters/cursor/live_conformance.py"
SPEC = importlib.util.spec_from_file_location("contextos_cursor_live", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
live = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = live
SPEC.loader.exec_module(live)


class CursorLiveHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.binary = self.root / ("agent.cmd" if os.name == "nt" else "agent")
        self.binary.write_text("fixture", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_fixture_has_explicit_skill_and_deny_precedence(self) -> None:
        workspace = self.root / "workspace"
        canaries = {"root": "ROOT", "nested": "NESTED", "skill": "SKILL"}
        live.write_fixture(workspace, canaries)
        live.write_permissions(workspace)
        skill = (workspace / ".agents/skills/contextos-live-explicit/SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("disable-model-invocation: true", skill)
        config = json.loads((workspace / ".cursor/cli.json").read_text(encoding="utf-8"))
        self.assertEqual(["Write(*)"], config["permissions"]["allow"])
        self.assertEqual(
            ["Write(denied.txt)", "Shell(*)"], config["permissions"]["deny"]
        )
        self.assertEqual("disposable\n", (workspace / live.DISPOSABLE_MARKER).read_text())

    def test_snapshot_reports_only_real_mutations(self) -> None:
        workspace = self.root / "workspace"
        live.write_fixture(workspace, {"root": "R", "nested": "N", "skill": "S"})
        before = live.snapshot(workspace)
        (workspace / "allowed.txt").write_text("ALLOWED_CONTROL\n", encoding="utf-8")
        self.assertEqual({"allowed.txt"}, live.changed_paths(before, live.snapshot(workspace)))

    def test_preflight_requires_exact_version_flags_and_authentication(self) -> None:
        responses = iter([
            live.CommandResult([], 0, "2026.08.31-4057e58\n", ""),
            live.CommandResult([], 0, "--print --force --workspace --trust", ""),
            live.CommandResult([], 0, "Logged in", ""),
        ])
        harness = live.CursorHarness(
            self.binary, "2026.08.31-4057e58", "a" * 40,
            runner=lambda *_: next(responses),
        )
        harness.preflight()
        self.assertTrue(harness.evidence.controls["authenticated"])

    def test_preflight_rejects_unauthenticated_cli(self) -> None:
        responses = iter([
            live.CommandResult([], 0, "2026.08.31-4057e58\n", ""),
            live.CommandResult([], 0, "--print --force --workspace --trust", ""),
            live.CommandResult([], 0, "Not logged in", ""),
        ])
        harness = live.CursorHarness(
            self.binary, "2026.08.31-4057e58", "a" * 40,
            runner=lambda *_: next(responses),
        )
        with self.assertRaisesRegex(live.HarnessError, "not authenticated"):
            harness.preflight()

    def test_require_canary_rejects_benign_success_without_evidence(self) -> None:
        with self.assertRaisesRegex(live.HarnessError, "did not return"):
            live.require_canary(live.CommandResult([], 0, "ordinary", ""), "CANARY", "root")

    def test_write_evidence_is_create_only(self) -> None:
        target = self.root / "evidence.json"
        evidence = live.Evidence(
            expected_version="v1", source_sha="a" * 40,
            binary_version="v1", controls={"control": True},
        )
        live.write_evidence(target, evidence)
        self.assertEqual("cursor", json.loads(target.read_text())["runtime"])
        with self.assertRaisesRegex(live.HarnessError, "refusing to overwrite"):
            live.write_evidence(target, evidence)

    def test_main_requires_explicit_model_traffic_opt_in(self) -> None:
        with mock.patch.object(live, "repository_source_sha") as source:
            with redirect_stderr(io.StringIO()):
                status = live.main([
                    "--binary", str(self.binary),
                    "--expected-version", "v1",
                    "--source-sha", "a" * 40,
                    "--evidence", str(self.root / "evidence.json"),
                ])
        self.assertEqual(1, status)
        source.assert_not_called()

    def test_source_sha_requires_clean_worktree(self) -> None:
        responses = iter([
            live.CommandResult([], 0, " M file\n", ""),
        ])
        with self.assertRaisesRegex(live.HarnessError, "clean source commit"):
            live.repository_source_sha(lambda *_: next(responses))

    def test_source_does_not_invoke_built_in_update(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn('"/update"', source)
        self.assertIn('"short_update_alias_not_invoked": True', source)
        self.assertIn('"headless_ask_mode_preserves_files": True', source)
        self.assertIn('"headless_without_force_is_write_capable": True', source)


if __name__ == "__main__":
    unittest.main()
