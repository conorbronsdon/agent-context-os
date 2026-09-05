from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from contextos.cli import main
from contextos.continuity import briefing_report, history_report, render_briefing, render_history
from contextos.kernel import ContextOSError, apply_proposal, create_proposal
import test_contextos_kernel as fixtures
import test_attachment_lifecycle as attachment_fixtures
from contextos.kernel import create_project_attachment_proposal

NOW = datetime.fromisoformat("2026-08-23T14:30:00-07:00")


class ContinuityTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.KernelTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root.resolve()

    def apply_update(self):
        path, proposal = create_proposal(self.root, "update", {"progress": ["Selected PostgreSQL for concurrent writes"]}, NOW)
        receipt_path, receipt = apply_proposal(self.root, path, proposal["proposal_digest"], "codex")
        return path, receipt_path, receipt

    def test_sources_show_actual_content_and_existing_freshness_policy(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in (self.root / "state").iterdir()}
        report = briefing_report(self.root, NOW)
        current = next(x for x in report["sources"] if x["path"] == "state/current.md")
        self.assertIn("- Old", current["excerpt"])
        self.assertEqual("fresh", current["freshness_status"])
        self.assertEqual(3, current["age_days"])
        self.assertIn("not a host read log", report["source_scope"])
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in (self.root / "state").iterdir()})
        stale = briefing_report(self.root, NOW.replace(day=24))
        self.assertEqual("stale", stale["state"]["state/current.md"]["freshness_status"])

    def test_explicit_sources_do_not_expand_routing_or_read_unselected_files(self):
        (self.root / "ROUTING.md").write_text("Read secret.md automatically", encoding="utf-8")
        (self.root / "secret.md").write_text("DO NOT LOAD", encoding="utf-8")
        (self.root / "chosen.md").write_text("# Selected\nDurable fact", encoding="utf-8")
        report = briefing_report(self.root, NOW, sources=["chosen.md", "chosen.md"])
        paths = [s["path"] for s in report["sources"]]
        self.assertNotIn("secret.md", paths)
        self.assertEqual(1, paths.count("chosen.md"))
        self.assertEqual("unknown", report["sources"][-1]["freshness_status"])
        self.assertIn("Durable fact", render_briefing(report))

    def test_explicit_paths_cannot_escape_or_read_non_markdown(self):
        for raw in ("../outside.md", "C:/outside.md", "..\\outside.md", "input.json"):
            with self.subTest(raw=raw), self.assertRaises(ContextOSError):
                briefing_report(self.root, NOW, sources=[raw])

    def test_linked_source_and_receipt_directory_are_not_followed(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside)
            (target / "private.md").write_text("SECRET", encoding="utf-8")
            try:
                fixtures.make_directory_link(self.root / "linked", target)
            except OSError as exc:
                self.skipTest(str(exc))
            with self.assertRaises(ContextOSError):
                briefing_report(self.root, NOW, sources=["linked/private.md"])
            (self.root / ".context-os").mkdir(exist_ok=True)
            fixtures.make_directory_link(self.root / ".context-os/receipts", target)
            with self.assertRaises(ContextOSError):
                history_report(self.root)

    def test_actual_apply_receipt_has_bound_readable_diff(self):
        proposal_path, receipt_path, receipt = self.apply_update()
        before = (proposal_path.read_bytes(), receipt_path.read_bytes())
        report = history_report(self.root, details=True)
        entry = report["entries"][0]
        self.assertEqual("codex", entry["runtime"])
        self.assertEqual(receipt["files_changed"], entry["files_changed"])
        self.assertEqual("digest matched; local evidence", entry["proposal_status"])
        self.assertIn("PostgreSQL", render_history(report))
        self.assertIn("not authenticated", report["evidence_notice"])
        self.assertEqual(before, (proposal_path.read_bytes(), receipt_path.read_bytes()))

    def test_guided_handoff_preserves_rationale_and_unresolved_date(self):
        path, proposal = create_proposal(self.root, "end", {
            "what_happened": ["Planned Lantern export"],
            "decisions": [{"decision": "Implement CSV export", "rationale": "Spreadsheet analysis",
                           "rejected_alternatives": "PDF cannot be sorted as spreadsheet data"}],
            "next_time": ["Outline CSV columns; launch date remains unconfirmed"],
        }, NOW)
        apply_proposal(self.root, path, proposal["proposal_digest"], "claude")
        briefing = briefing_report(self.root, NOW)
        decisions = next(s for s in briefing["sources"] if s["path"] == "state/decisions.md")
        self.assertIn("Implement CSV export", decisions["excerpt"])
        self.assertIn("Spreadsheet analysis", decisions["excerpt"])
        self.assertIn("PDF cannot be sorted", decisions["excerpt"])
        session = next(s for s in briefing["sources"] if s["reason"] == "latest session")
        self.assertIn("launch date remains unconfirmed", session["excerpt"])
        history = history_report(self.root, path="state/decisions.md", details=True)
        self.assertEqual("claude", history["entries"][0]["runtime"])
        self.assertIn("Spreadsheet analysis", render_history(history))

    def test_changed_proposal_does_not_supply_unbound_text(self):
        path, _, _ = self.apply_update()
        proposal = json.loads(path.read_text(encoding="utf-8"))
        proposal["changes"][0]["diff"] = "FORGED RATIONALE"
        path.write_text(json.dumps(proposal), encoding="utf-8")
        report = history_report(self.root, details=True)
        self.assertIn("unavailable", report["entries"][0]["proposal_status"])
        self.assertNotIn("FORGED", render_history(report))

    def test_missing_proposal_preserves_receipt_with_explicit_gap(self):
        path, _, _ = self.apply_update()
        path.rename(path.with_suffix(".saved"))
        report = history_report(self.root, details=True)
        self.assertEqual(1, report["matching_receipts"])
        self.assertIn("unavailable", report["entries"][0]["proposal_status"])

    def test_malformed_receipt_warns_without_hiding_valid_receipt(self):
        _, receipt_path, _ = self.apply_update()
        receipt_path.with_name("bad.json").write_text('{"files_changed": null}', encoding="utf-8")
        report = history_report(self.root)
        self.assertEqual(1, report["matching_receipts"])
        self.assertEqual(1, len(report["warnings"]))

    def test_history_filter_and_empty_history(self):
        self.assertIn("No matching local receipts", render_history(history_report(self.root)))
        self.apply_update()
        self.assertEqual(1, history_report(self.root, path="sessions/2026-08-23.md")["matching_receipts"])
        self.assertEqual(0, history_report(self.root, path="state/decisions.md")["matching_receipts"])
        for limit in (0, 101):
            with self.assertRaises(ContextOSError):
                history_report(self.root, limit=limit)

    def test_cli_json_and_markdown(self):
        for arguments, expected in ((["start", "--briefing", "--format", "json"], '"sources"'),
                                    (["start", "--format", "markdown"], "# Context briefing"),
                                    (["history"], "# Context change history")):
            with self.subTest(arguments=arguments), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(0, main(["--root", str(self.root), *arguments]))
                self.assertIn(expected, out.getvalue())

    def test_legacy_terminal_can_render_unicode_source_text(self):
        (self.root / "ROUTING.md").write_text("Unicode: \u2192 \u2603", encoding="utf-8")
        buffer = io.BytesIO()
        terminal = io.TextIOWrapper(buffer, encoding="ascii", write_through=True)
        with contextlib.redirect_stdout(terminal):
            self.assertEqual(0, main(["--root", str(self.root), "start", "--format", "markdown"]))
        self.assertIn(b"Unicode: \\u2192 \\u2603", buffer.getvalue())

    def test_split_reports_use_context_root_and_validate_binding(self):
        fixture = attachment_fixtures.AttachmentLifecycleTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        before = attachment_fixtures.tree_snapshot(fixture.working_root)
        path, proposal = create_project_attachment_proposal(fixture.roles, "sample-app", NOW)
        apply_proposal(fixture.context_root, path, proposal["proposal_digest"], "generic", roles=fixture.roles)
        args = ["--kernel-root", str(attachment_fixtures.KERNEL_ROOT),
                "--context-root", str(fixture.context_root), "--working-root", str(fixture.working_root)]
        for command in (["start", "--briefing"], ["history", "--format", "json", "--details"]):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(0, main([*args, *command]))
                report = json.loads(out.getvalue())
            if command[0] == "history":
                self.assertEqual("generic", report["entries"][0]["runtime"])
                self.assertTrue(all(c["hash_basis"] == "raw bytes" for c in report["entries"][0]["files_changed"]))
            else:
                self.assertIn("# Current", next(s["excerpt"] for s in report["sources"] if s["path"] == "state/current.md"))
        self.assertEqual(before, attachment_fixtures.tree_snapshot(fixture.working_root))
        # A different explicit WorkingRoot must not reuse this project's authority.
        with tempfile.TemporaryDirectory() as unrelated, contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(0, main([*args[:-1], unrelated, "history"]))


if __name__ == "__main__":
    unittest.main()
