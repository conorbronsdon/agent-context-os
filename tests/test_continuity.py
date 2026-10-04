from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch
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

    def test_revision_mismatch_points_to_new_snapshot_even_when_value_is_unchanged(self):
        path = self.root / "selected.md"
        old = "**Last Updated:** 2026-08-20\nUse CSV. Proposed by the agent.\n"
        path.write_text(old, encoding="utf-8")
        digest = hashlib.sha256(old.encode()).hexdigest()
        current = "**Last Updated:** 2026-08-23\nUse CSV. Reviewed by Demo reviewer.\n"
        path.write_bytes(current.replace("\n", "\r\n").encode())
        report = briefing_report(self.root, NOW, sources=["selected.md"],
                                  expected_revisions=[f"selected.md={digest}"])
        source = report["sources"][-1]
        self.assertEqual("selected.md", source["source_id"])
        self.assertEqual("mismatch", source["revision_check"]["status"])
        self.assertEqual(digest, source["revision_check"]["expected_sha256"])
        self.assertEqual(hashlib.sha256(current.encode()).hexdigest(), source["sha256"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source["sha256_raw"])
        self.assertEqual(0, source["age_days"])
        self.assertIn("Demo reviewer", source["excerpt"])
        self.assertIn("Revision check: mismatch", render_briefing(report))
        matched = briefing_report(self.root, NOW, sources=["selected.md"],
                                   expected_revisions=[f"selected.md={source['sha256']}"])
        self.assertEqual("matched", matched["sources"][-1]["revision_check"]["status"])

    def test_freshness_hash_and_excerpt_use_one_source_snapshot(self):
        # start_report has an earlier metadata inventory. A file may change
        # before its preview snapshot; the excerpt's date must describe it.
        path = self.root / "state/current.md"
        current = "**Last Updated:** 2026-08-23\nNew snapshot\n"
        from contextos.continuity import start_report as real_start
        def changed_after_inventory(*args, **kwargs):
            report = real_start(*args, **kwargs)
            path.write_text(current, encoding="utf-8")
            return report
        with patch("contextos.continuity.start_report", side_effect=changed_after_inventory):
            source = next(s for s in briefing_report(self.root, NOW)["sources"]
                          if s["path"] == "state/current.md")
        self.assertEqual(0, source["age_days"])
        self.assertEqual(hashlib.sha256(current.encode()).hexdigest(), source["sha256"])

    def test_unknown_future_and_unavailable_source_ages_are_explicit(self):
        (self.root / "unknown.md").write_text("No date", encoding="utf-8")
        (self.root / "future.md").write_text("**Last Updated:** 2026-08-25\nFuture", encoding="utf-8")
        report = briefing_report(self.root, NOW, sources=["unknown.md", "future.md", "missing.md"],
                                  expected_revisions=[f"missing.md={'0' * 64}"])
        self.assertEqual("unavailable", report["sources"][-1]["revision_check"]["status"])
        rendered = render_briefing(report)
        self.assertIn("Source age: unknown", rendered)
        self.assertIn("2 days in the future", rendered)
        self.assertNotIn("-2 days ago", rendered)

    def test_revision_checks_require_selected_sources_and_unambiguous_hashes(self):
        (self.root / "ROUTING.md").write_text("# Routing\n", encoding="utf-8")
        for specification in ("../outside.md=" + "0" * 64, "secret.md=" + "0" * 64,
                              "ROUTING.md=wrong", "ROUTING.md"):
            with self.subTest(specification=specification), self.assertRaises(ContextOSError):
                briefing_report(self.root, NOW, expected_revisions=[specification])
        with self.assertRaisesRegex(ContextOSError, "conflicting"):
            briefing_report(self.root, NOW, expected_revisions=["ROUTING.md=" + "0" * 64,
                                                               "ROUTING.md=" + "1" * 64])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(0, main(["--root", str(self.root), "start",
                                     "--expect-source-revision", "ROUTING.md=" + "0" * 64]))
        self.assertEqual("mismatch", json.loads(out.getvalue())["sources"][0]["revision_check"]["status"])

    def test_receipt_before_and_after_digests_match_real_content_and_reject_changed_dependency(self):
        path, proposal = create_proposal(self.root, "update", {"progress": ["Saved progress"]}, NOW)
        before = {c["path"]: (self.root / c["path"]).read_text(encoding="utf-8")
                  if (self.root / c["path"]).exists() else None for c in proposal["changes"]}
        _, receipt = apply_proposal(self.root, path, proposal["proposal_digest"], "codex")
        for change in receipt["files_changed"]:
            old = before[change["path"]]
            self.assertEqual(None if old is None else hashlib.sha256(old.encode()).hexdigest(),
                             change["sha256_before"])
            self.assertEqual(hashlib.sha256((self.root / change["path"]).read_text(encoding="utf-8").encode()).hexdigest(),
                             change["sha256_after"])
        path, proposal = create_proposal(self.root, "update", {"progress": ["Next progress"]}, NOW)
        target = self.root / proposal["changes"][0]["path"]
        target.write_text(target.read_text(encoding="utf-8") + "Concurrent change\n", encoding="utf-8")
        with self.assertRaises(ContextOSError):
            apply_proposal(self.root, path, proposal["proposal_digest"], "codex")
        self.assertFalse((self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json").exists())

    def test_content_target_changed_after_preflight_is_rejected_without_clobbering(self):
        # The first stale check passes; the source changes while apply stages
        # its transaction. The pre-mutation recheck must reject it, keep the
        # concurrent bytes and publish no receipt.
        path, proposal = create_proposal(self.root, "update", {"progress": ["Saved progress"]}, NOW)
        apply_proposal(self.root, path, proposal["proposal_digest"], "codex")
        path, proposal = create_proposal(self.root, "update", {"progress": ["Next progress"]}, NOW)
        target = next(self.root / change["path"] for change in proposal["changes"]
                      if (self.root / change["path"]).exists())
        from contextos import kernel
        original = kernel._create_agent_journal

        def mutate_after_staging(*args, **kwargs):
            result = original(*args, **kwargs)
            target.write_text(target.read_text(encoding="utf-8") + "Concurrent change\n", encoding="utf-8")
            return result

        with patch("contextos.kernel._create_agent_journal", side_effect=mutate_after_staging):
            with self.assertRaisesRegex(ContextOSError, "target changed during apply"):
                apply_proposal(self.root, path, proposal["proposal_digest"], "codex")
        self.assertTrue(target.read_text(encoding="utf-8").endswith("Concurrent change\n"))
        self.assertFalse((self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json").exists())

    def test_explicit_paths_cannot_escape_or_read_non_markdown(self):
        for raw in ("../outside.md", "C:/outside.md", "..\\outside.md", "input.json"):
            with self.subTest(raw=raw), self.assertRaises(ContextOSError):
                briefing_report(self.root, NOW, sources=[raw])

    def test_source_limit_counts_unique_explicit_sources(self):
        sources = [f"selected-{i}.md" for i in range(24)]
        self.assertEqual(29, len(briefing_report(self.root, NOW, sources=sources)["sources"]))
        self.assertEqual(6, len(briefing_report(self.root, NOW, sources=["missing.md"] * 30)["sources"]))
        with self.assertRaises(ContextOSError):
            briefing_report(self.root, NOW, sources=[*sources, "one-too-many.md"])

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

    def test_review_metadata_and_supersession_convention_preserve_both_decisions(self):
        for identifier, decision, predecessor in (("export-001", "Use CSV", "none"),
                                                  ("export-002", "Use JSON", "export-001")):
            path, proposal = create_proposal(self.root, "end", {
                "what_happened": ["Reviewed export format"],
                "decisions": [{"decision": f"{identifier}: {decision}",
                               "rationale": f"Review status: accepted after exact-proposal review; "
                                            f"Reviewed by: Demo reviewer (self-reported); Supersedes: {predecessor}",
                               "rejected_alternatives": "PDF"}],
                "next_time": [f"Use {identifier}; launch date unconfirmed"],
            }, NOW)
            apply_proposal(self.root, path, proposal["proposal_digest"], "claude")
        decisions = (self.root / "state/decisions.md").read_text(encoding="utf-8")
        self.assertIn("export-001: Use CSV", decisions)
        self.assertIn("export-002: Use JSON", decisions)
        self.assertIn("Supersedes: export-001", decisions)
        self.assertIn("Demo reviewer (self-reported)", decisions)
        history = history_report(self.root, path="state/decisions.md", details=True)
        self.assertEqual(2, history["matching_receipts"])
        self.assertIn("not authenticated", history["evidence_notice"])

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

    def test_receipts_file_produces_actionable_error(self):
        (self.root / ".context-os").mkdir(exist_ok=True)
        (self.root / ".context-os/receipts").write_text("not a directory", encoding="utf-8")
        with self.assertRaisesRegex(ContextOSError, "must be a directory"):
            history_report(self.root)
        with contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertNotEqual(0, main(["--root", str(self.root), "history"]))
        self.assertIn("must be a directory", error.getvalue())

    def test_control_characters_in_receipt_filename_cannot_inject_headings(self):
        _, valid_path, receipt = self.apply_update()
        # Simulate a POSIX-only filename on every platform; the valid sibling
        # must remain visible and the unsafe label must never be opened.
        unsafe_path = valid_path.with_name("bad\n# Forged.json")
        with patch.object(Path, "iterdir", return_value=iter([unsafe_path, valid_path])), \
                patch("contextos.continuity._object", return_value=receipt) as reader:
            report = history_report(self.root)
        self.assertEqual(1, reader.call_count)
        self.assertEqual(1, len(report["entries"]))
        self.assertEqual(1, len(report["warnings"]))
        self.assertNotIn("\n# Forged", render_history(report))

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
