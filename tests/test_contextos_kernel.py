from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock
from datetime import datetime
from pathlib import Path

from contextos.kernel import (
    ContextOSError,
    apply_proposal,
    create_proposal,
    doctor,
    hook_report,
    install_runtime,
    read_json,
    canonical_json,
    sha256_text,
    start_report,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-08-23T14:30:00-07:00")


class KernelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "state").mkdir()
        (self.root / "sessions").mkdir()
        (self.root / "runtimes").mkdir()
        (self.root / "AGENTS.md").write_text("# Test workspace\n", encoding="utf-8")
        (self.root / "TODO.md").write_text("# Tasks\n", encoding="utf-8")
        (self.root / "state" / "current.md").write_text(
            "# Current State\n\n**Last Updated:** 2026-08-20\n\n## Active priorities\n\n- Old\n",
            encoding="utf-8",
        )
        (self.root / "state" / "current-log.md").write_text(
            "# current.md update log\n\nPrevious dates follow.\n\n2026-08-18\n",
            encoding="utf-8",
        )
        (self.root / "state" / "decisions.md").write_text(
            "# Decisions Log\n\n| Date | Decision | Context / rationale | Rejected alternatives |\n"
            "|---|---|---|---|\n",
            encoding="utf-8",
        )
        for name in ("blockers.md", "weekly-priorities.md"):
            (self.root / "state" / name).write_text(
                f"# {name}\n\n**Last Updated:** 2026-08-20\n", encoding="utf-8"
            )
        for runtime in ("claude", "codex", "hermes"):
            source = ROOT / "runtimes" / f"{runtime}.json"
            (self.root / "runtimes" / f"{runtime}.json").write_bytes(source.read_bytes())

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _input(self, value: dict) -> Path:
        path = self.root / "input.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def _propose(self, workflow: str, payload: dict):
        return create_proposal(self.root, workflow, payload, NOW)

    def _apply(self, path: Path, document: dict, runtime: str = "codex"):
        return apply_proposal(self.root, path, document["proposal_digest"], runtime)

    def test_update_propose_apply_writes_receipt_and_history_once(self) -> None:
        current = (
            "# Current State\n\n**Last Updated:** 2026-08-20\n\n"
            "## Active priorities\n\n- New\n"
        )
        proposal_path, proposal = self._propose(
            "update", {"progress": ["Built the kernel"], "current_markdown": current}
        )
        self.assertTrue(proposal["proposal_id"].startswith("20260823T143000-update-"))
        self.assertFalse((self.root / "sessions" / "2026-08-23.md").exists())
        receipt_path, receipt = self._apply(proposal_path, proposal)
        self.assertTrue(receipt_path.exists())
        self.assertEqual("codex", receipt["runtime"])
        self.assertIn("**Last Updated:** 2026-08-23", (self.root / "state/current.md").read_text())
        history = (self.root / "state/current-log.md").read_text()
        self.assertEqual(1, sum(line == "2026-08-20" for line in history.splitlines()))
        self.assertIn("## Update: 14:30", (self.root / "sessions/2026-08-23.md").read_text())

        second_path, second = create_proposal(
            self.root,
            "update",
            {"progress": ["Ran tests"], "current_markdown": (self.root / "state/current.md").read_text()},
            datetime.fromisoformat("2026-08-23T16:00:00-07:00"),
        )
        self._apply(second_path, second)
        history = (self.root / "state/current-log.md").read_text()
        self.assertEqual(1, sum(line == "2026-08-20" for line in history.splitlines()))
        session = (self.root / "sessions/2026-08-23.md").read_text()
        self.assertIn("## Update: 14:30", session)
        self.assertIn("## Update: 16:00", session)

    def test_end_appends_session_and_decision(self) -> None:
        existing = self.root / "sessions/2026-08-23.md"
        existing.write_text("# Session — 2026-08-23\n\n## Update: 10:00\n- Began\n", encoding="utf-8")
        proposal_path, proposal = self._propose(
            "end",
            {
                "what_happened": ["Finished deterministic apply"],
                "decisions": [{
                    "decision": "Use proposal | apply",
                    "rationale": "Exact review",
                    "rejected_alternatives": "Direct writes",
                }],
                "next_time": ["Add runtime smoke tests"],
            },
        )
        self._apply(proposal_path, proposal, "hermes")
        session = existing.read_text(encoding="utf-8")
        self.assertIn("## Session 14:30", session)
        self.assertIn("Finished deterministic apply", session)
        decisions = (self.root / "state/decisions.md").read_text(encoding="utf-8")
        self.assertIn("Use proposal \\| apply", decisions)

    def test_exact_confirmation_and_optimistic_hashes_fail_closed(self) -> None:
        proposal_path, proposal = self._propose("update", {"progress": ["One"]})
        with self.assertRaisesRegex(ContextOSError, "exactly match"):
            apply_proposal(self.root, proposal_path, "wrong", "claude")
        (self.root / "sessions/2026-08-23.md").write_text("parallel writer\n", encoding="utf-8")
        with self.assertRaisesRegex(ContextOSError, "stale proposal"):
            self._apply(proposal_path, proposal, "claude")

    def test_apply_lock_fails_closed_and_survives_no_write(self) -> None:
        proposal_path, proposal = self._propose("update", {"progress": ["One"]})
        lock = self.root / ".context-os/apply.lock"
        lock.write_text("pid=other\n", encoding="utf-8")
        with self.assertRaisesRegex(ContextOSError, "stale lock"):
            self._apply(proposal_path, proposal)
        self.assertFalse((self.root / "sessions/2026-08-23.md").exists())

    def test_partial_apply_failure_rolls_back_prior_paths(self) -> None:
        current_before = (self.root / "state/current.md").read_bytes()
        history_before = (self.root / "state/current-log.md").read_bytes()
        proposal_path, proposal = self._propose(
            "update",
            {
                "progress": ["One"],
                "current_markdown": "# Current State\n\n**Last Updated:** 2026-08-20\n\n- Changed\n",
            },
        )
        real_replace = os.replace
        calls = 0

        def fail_second(source, target):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected replacement failure")
            return real_replace(source, target)

        with mock.patch("contextos.kernel.os.replace", side_effect=fail_second):
            with self.assertRaisesRegex(ContextOSError, "rolled back"):
                self._apply(proposal_path, proposal)
        self.assertEqual(current_before, (self.root / "state/current.md").read_bytes())
        self.assertEqual(history_before, (self.root / "state/current-log.md").read_bytes())
        self.assertFalse((self.root / "sessions/2026-08-23.md").exists())
        self.assertFalse(any((self.root / ".context-os/receipts").glob("*.json")))

    def test_tampered_proposal_is_rejected(self) -> None:
        proposal_path, proposal = self._propose("update", {"progress": ["One"]})
        tampered = read_json(proposal_path)
        tampered["changes"][0]["after_text"] += "tampered\n"
        proposal_path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaisesRegex(ContextOSError, "digest"):
            self._apply(proposal_path, proposal)

    def test_setup_requires_explicit_populated_replacement(self) -> None:
        (self.root / "identity").mkdir()
        target = self.root / "identity/who-i-am.md"
        target.write_text("# Ada\n\nReal biography.\n", encoding="utf-8")
        with self.assertRaisesRegex(ContextOSError, "replace_populated"):
            self._propose("setup", {"files": {"identity/who-i-am.md": "# Changed"}})
        path, proposal = self._propose(
            "setup",
            {
                "files": {"identity/who-i-am.md": "# Changed {{TODAY}}"},
                "replace_populated": ["identity/who-i-am.md"],
            },
        )
        self._apply(path, proposal)
        self.assertEqual("# Changed 2026-08-23\n", target.read_text(encoding="utf-8"))

    def test_setup_rejects_path_escape_and_unapproved_root(self) -> None:
        with self.assertRaisesRegex(ContextOSError, "escapes"):
            self._propose("setup", {"files": {"../outside.md": "no"}})
        with self.assertRaisesRegex(ContextOSError, "approved context paths"):
            self._propose("setup", {"files": {"scripts/unsafe.py": "no"}})

    def test_apply_revalidates_workflow_paths_for_handcrafted_proposal(self) -> None:
        proposal_path, proposal = self._propose("update", {"progress": ["One"]})
        proposal["changes"][0]["path"] = ".git/hooks/pre-commit"
        unsigned = dict(proposal)
        unsigned.pop("proposal_digest")
        proposal["proposal_digest"] = sha256_text(canonical_json(unsigned))
        proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
        with self.assertRaisesRegex(ContextOSError, "reserved"):
            self._apply(proposal_path, proposal)

    def test_apply_rejects_setup_replacement_bypass(self) -> None:
        (self.root / "identity").mkdir()
        target = self.root / "identity/who-i-am.md"
        proposal_path, proposal = self._propose(
            "setup", {"files": {"identity/who-i-am.md": "# Initial"}}
        )
        target.write_text("# Existing\n\nReal [Your Name] biography.\n", encoding="utf-8")
        proposal["changes"][0]["before_sha256"] = sha256_text(target.read_text(encoding="utf-8"))
        unsigned = dict(proposal)
        unsigned.pop("proposal_digest")
        proposal["proposal_digest"] = sha256_text(canonical_json(unsigned))
        proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
        with self.assertRaisesRegex(ContextOSError, "replacement approval"):
            self._apply(proposal_path, proposal)

    def test_end_missing_decision_log_is_clean_error(self) -> None:
        (self.root / "state/decisions.md").unlink()
        with self.assertRaisesRegex(ContextOSError, "decision log does not exist"):
            self._propose(
                "end",
                {"what_happened": ["One"], "decisions": [{"decision": "Keep it deterministic"}]},
            )

    def test_start_is_read_only_and_reports_staleness(self) -> None:
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        report = start_report(self.root, NOW)
        after = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertFalse(report["state"]["state/current.md"]["stale"])
        self.assertEqual(3, report["state"]["state/current.md"]["age_days"])

    def test_install_and_doctor_are_machine_local(self) -> None:
        target, installed = install_runtime(self.root, "hermes")
        self.assertEqual(self.root / ".context-os/runtime.json", target)
        self.assertEqual("hermes", installed["runtime"])
        report = doctor(self.root, "hermes")
        self.assertIn(report["status"], {"pass", "warn"})
        self.assertFalse(any(item["status"] == "fail" for item in report["checks"]))
        manifest = json.loads((self.root / "runtimes/hermes.json").read_text())
        manifest["capabilities"]["mcp"] = "advisory"
        (self.root / "runtimes/hermes.json").write_text(json.dumps(manifest), encoding="utf-8")
        drift = doctor(self.root, "hermes")
        drift_check = next(item for item in drift["checks"] if item["name"] == "runtime-manifest-drift")
        self.assertEqual("warn", drift_check["status"])

    def test_doctor_uses_configured_state_and_selected_manifest_only(self) -> None:
        custom = self.root / "custom-state"
        (self.root / "state").rename(custom)
        (self.root / "workspace.yaml").write_text("state_dir: custom-state\n", encoding="utf-8")
        (self.root / "runtimes/codex.json").unlink()
        report = doctor(self.root, "hermes")
        self.assertFalse(any(item["status"] == "fail" for item in report["checks"]))
        self.assertTrue(any(item["name"] == "file:custom-state/current.md" for item in report["checks"]))

    def test_runtime_manifest_is_required_for_receipt_claim(self) -> None:
        proposal_path, proposal = self._propose("update", {"progress": ["One"]})
        os.remove(self.root / "runtimes/codex.json")
        with self.assertRaisesRegex(ContextOSError, "missing runtime manifest"):
            self._apply(proposal_path, proposal)

    def test_hook_must_fire_and_must_not_fire_controls(self) -> None:
        must_fire = hook_report(
            self.root, "pre-write", {"tool_input": {"file_path": str(self.root / "state/current.md")}}
        )
        self.assertEqual(1, len(must_fire["findings"]))
        must_not_fire = hook_report(
            self.root, "pre-write", {"tool_input": {"file_path": str(self.root / "README.md")}}
        )
        self.assertEqual([], must_not_fire["findings"])

    def test_hook_handles_relative_paths_and_codex_patch_commands(self) -> None:
        relative = hook_report(self.root, "pre-write", {"args": {"path": "state/blockers.md"}})
        self.assertEqual(1, len(relative["findings"]))
        patch = "*** Begin Patch\n*** Update File: state/current-log.md\n@@\n-old\n+new\n*** End Patch"
        codex = hook_report(self.root, "pre-write", {"tool_input": {"command": patch}})
        self.assertEqual(1, len(codex["findings"]))

    def test_session_hook_surfaces_placeholder_but_not_initialized_state(self) -> None:
        (self.root / "state/current.md").write_text(
            "# Current\n\n**Last Updated:** [DATE]\n", encoding="utf-8"
        )
        self.assertTrue(hook_report(self.root, "session-start", {})["findings"])
        (self.root / "state/current.md").write_text(
            "# Current\n\n**Last Updated:** 2026-08-23\n", encoding="utf-8"
        )
        self.assertEqual([], hook_report(self.root, "session-start", {})["findings"])


if __name__ == "__main__":
    unittest.main()
