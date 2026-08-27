from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock
from datetime import date, datetime
from pathlib import Path

from contextos.kernel import (
    ContextOSError,
    apply_proposal,
    create_proposal,
    discover_root,
    doctor,
    hook_report,
    install_runtime,
    migrate_legacy_runtime_state,
    read_json,
    runtime_manifest,
    canonical_json,
    sha256_text,
    start_report,
)
from contextos.component_schema import load_component_manifest, resolved_component_paths
from contextos.workspace_schema import render_workspace_config


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-08-23T14:30:00-07:00")


def make_directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise OSError(result.stderr or result.stdout)
    else:
        link.symlink_to(target, target_is_directory=True)


def root_config(*, canonical: bool = True, agents: list[str] | None = None) -> str:
    value = {
        "schema_version": 1,
        "mode": "full-template",
        "agents": agents or [],
        "paths": {
            "state_dir": "state",
            "sessions_dir": "sessions",
            "task_file": "TODO.md",
        },
        "template": {"version": "0.12.0", "source": "test"},
    }
    if canonical:
        return render_workspace_config(value)
    return json.dumps(value, separators=(",", ":"))


class RootDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        # Hosted Windows may spell TEMP with an 8.3 short path, while
        # discover_root() intentionally returns the resolved canonical path.
        self.root = Path(self.temporary.name).resolve()

    def write_json(self, root: Path, content: str | None = None) -> Path:
        marker = root / "contextos.workspace.json"
        marker.write_text(content or root_config(), encoding="utf-8")
        return marker

    def test_json_marker_supports_minimal_core_only_workspace(self) -> None:
        self.write_json(self.root)
        child = self.root / "uncreated-state-parent"
        child.mkdir()
        self.assertEqual(self.root, discover_root(child))
        self.assertEqual(self.root, discover_root(self.root / "contextos.workspace.json"))

    def test_valid_noncanonical_json_is_still_a_root(self) -> None:
        self.write_json(self.root, root_config(canonical=False))
        self.assertEqual(self.root, discover_root(self.root))

    def test_configured_agent_requires_only_its_registry_descriptor(self) -> None:
        self.write_json(self.root, root_config(agents=["claude"]))
        with self.assertRaisesRegex(ContextOSError, "unknown runtime"):
            discover_root(self.root)
        runtimes = self.root / "runtimes"
        runtimes.mkdir()
        shutil.copyfile(ROOT / "runtimes" / "claude.json", runtimes / "claude.json")
        self.assertEqual(self.root, discover_root(self.root))

    def test_legacy_compound_markers_remain_supported(self) -> None:
        for companion, is_directory in (("state", True), ("workspace.yaml", False)):
            with self.subTest(companion=companion):
                root = self.root / companion.replace(".", "-")
                root.mkdir()
                (root / "AGENTS.md").write_text("# fixture\n", encoding="utf-8")
                if is_directory:
                    (root / companion).mkdir()
                else:
                    (root / companion).write_text("state_dir: state\n", encoding="utf-8")
                self.assertEqual(root, discover_root(root))

    def test_partial_and_near_name_markers_are_false_positives(self) -> None:
        fixtures = (
            ("agents-only", "AGENTS.md", False),
            ("state-only", "state", True),
            ("yaml-only", "workspace.yaml", False),
            ("near-json", "contextos.workspace.json.bak", False),
        )
        for name, marker, is_directory in fixtures:
            with self.subTest(name=name):
                root = self.root / name
                root.mkdir()
                (root / ".git").mkdir()
                if is_directory:
                    (root / marker).mkdir()
                else:
                    (root / marker).write_text("fixture\n", encoding="utf-8")
                with self.assertRaisesRegex(ContextOSError, "repository boundary"):
                    discover_root(root)

    def test_nearest_root_wins_across_json_and_legacy_markers(self) -> None:
        self.write_json(self.root)
        inner = self.root / "inner"
        inner.mkdir()
        (inner / "AGENTS.md").write_text("# fixture\n", encoding="utf-8")
        (inner / "state").mkdir()
        leaf = inner / "leaf"
        leaf.mkdir()
        self.assertEqual(inner, discover_root(leaf))

        nested = inner / "nested"
        nested.mkdir()
        self.write_json(nested)
        self.assertEqual(nested, discover_root(nested))

    def test_invalid_inner_json_never_falls_back_to_legacy_or_outer_root(self) -> None:
        self.write_json(self.root)
        inner = self.root / "inner"
        inner.mkdir()
        (inner / "AGENTS.md").write_text("# fixture\n", encoding="utf-8")
        (inner / "state").mkdir()
        self.write_json(inner, "{")
        with self.assertRaisesRegex(ContextOSError, "invalid tracked"):
            discover_root(inner)

    def test_nested_git_directory_and_file_stop_ascent(self) -> None:
        self.write_json(self.root)
        for name, git_content in (("repo", None), ("worktree", "gitdir: elsewhere\n")):
            with self.subTest(name=name):
                nested = self.root / name
                nested.mkdir()
                if git_content is None:
                    (nested / ".git").mkdir()
                else:
                    (nested / ".git").write_text(git_content, encoding="utf-8")
                leaf = nested / "leaf"
                leaf.mkdir()
                with self.assertRaisesRegex(ContextOSError, "repository boundary"):
                    discover_root(leaf)
                self.write_json(nested)
                self.assertEqual(nested, discover_root(leaf))

    def test_invalid_marker_types_and_portable_aliases_fail_closed(self) -> None:
        marker = self.root / "contextos.workspace.json"
        marker.mkdir()
        with self.assertRaisesRegex(ContextOSError, "regular file"):
            discover_root(self.root)
        marker.rmdir()

        alias = self.root / "ContextOS.Workspace.json"
        alias.write_text(root_config(), encoding="utf-8")
        with self.assertRaisesRegex(ContextOSError, "filename collision"):
            discover_root(self.root)

    def test_symlink_marker_fails_without_using_its_target(self) -> None:
        outside = self.root / "outside.json"
        outside.write_text(root_config(), encoding="utf-8")
        nested = self.root / "nested"
        nested.mkdir()
        marker = nested / "contextos.workspace.json"
        try:
            marker.symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation is unavailable")
        with self.assertRaisesRegex(ContextOSError, "must not be a symlink"):
            discover_root(nested)
        with self.assertRaisesRegex(ContextOSError, "must not be a symlink"):
            discover_root(marker)

    def test_symlinked_directory_start_cannot_bypass_repository_boundary(self) -> None:
        self.write_json(self.root)
        nested = self.root / "nested"
        nested.mkdir()
        (nested / ".git").mkdir()
        linked = nested / "linked"
        try:
            make_directory_link(linked, self.root)
        except OSError:
            self.skipTest("directory link creation is unavailable")
        with self.assertRaisesRegex(ContextOSError, "escape repository boundary"):
            discover_root(linked)

    def test_symlinked_ancestor_without_git_boundary_remains_compatible(self) -> None:
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        workspace = real_parent / "workspace"
        workspace.mkdir()
        self.write_json(workspace)
        linked_parent = self.root / "linked-parent"
        try:
            make_directory_link(linked_parent, real_parent)
        except OSError:
            self.skipTest("directory link creation is unavailable")
        self.assertEqual(workspace, discover_root(linked_parent / "workspace"))

    def test_internal_directory_link_remains_within_repository_boundary(self) -> None:
        repository = self.root / "repo"
        repository.mkdir()
        (repository / ".git").mkdir()
        (repository / "AGENTS.md").write_text("# fixture\n", encoding="utf-8")
        (repository / "state").mkdir()
        docs = repository / "docs"
        deep = docs / "deep"
        deep.mkdir(parents=True)
        linked = repository / "linked-docs"
        try:
            make_directory_link(linked, docs)
        except OSError:
            self.skipTest("directory link creation is unavailable")
        self.assertEqual(repository, discover_root(linked / "deep"))

    def test_link_to_repository_entrypoint_remains_compatible(self) -> None:
        repository = self.root / "repo"
        repository.mkdir()
        (repository / ".git").mkdir()
        (repository / "AGENTS.md").write_text("# fixture\n", encoding="utf-8")
        (repository / "state").mkdir()
        current = self.root / "current"
        try:
            make_directory_link(current, repository)
        except OSError:
            self.skipTest("directory link creation is unavailable")
        self.assertEqual(repository, discover_root(current / "state"))

    def test_alias_scan_skips_intermediate_and_unrelated_ancestors(self) -> None:
        workspace = self.root / "workspace"
        workspace.mkdir()
        self.write_json(workspace)
        intermediate = workspace / "intermediate"
        child = intermediate / "child"
        child.mkdir(parents=True)
        original_iterdir = Path.iterdir

        def guarded_iterdir(path: Path):
            if path == intermediate:
                raise PermissionError("traverse-only fixture")
            return original_iterdir(path)

        with mock.patch.object(Path, "iterdir", guarded_iterdir):
            self.assertEqual(workspace, discover_root(child))

        if os.name == "nt":
            return
        unrelated = self.root / "unrelated"
        leaf = unrelated / "leaf"
        leaf.mkdir(parents=True)
        (unrelated / "ContextOS.Workspace.json").write_text(
            "not a workspace\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ContextOSError, "could not find a Context OS root"):
            discover_root(leaf)

    @unittest.skipIf(os.name == "nt", "Windows aliases trailing dots at creation time")
    def test_windows_trailing_dot_filename_alias_fails_portably(self) -> None:
        alias = self.root / "contextos.workspace.json."
        alias.write_text(root_config(), encoding="utf-8")
        with self.assertRaisesRegex(ContextOSError, "filename collision"):
            discover_root(self.root)

    def test_existing_file_start_uses_parent_and_missing_start_is_rejected(self) -> None:
        self.write_json(self.root)
        child = self.root / "child"
        child.mkdir()
        source = child / "input.txt"
        source.write_text("fixture\n", encoding="utf-8")
        self.assertEqual(self.root, discover_root(source))
        with self.assertRaisesRegex(ContextOSError, "does not exist"):
            discover_root(child / "missing")
        with self.assertRaisesRegex(ContextOSError, "does not exist"):
            discover_root(child / "contextos.workspace.json")


class KernelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "state").mkdir()
        (self.root / "sessions").mkdir()
        (self.root / "runtimes").mkdir()
        (self.root / "AGENTS.md").write_text("# Test workspace\n", encoding="utf-8")
        (self.root / "CLAUDE.md").write_text("# Test workspace\n", encoding="utf-8")
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
        for directory in (
            ".agents", ".claude", "adapters", "components", "docs", "tests"
        ):
            shutil.copytree(ROOT / directory, self.root / directory)

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

    def _write_undated_state(self, *filenames: str) -> None:
        for filename in filenames:
            (self.root / "state" / filename).write_text(
                f"# {filename}\n\n**Last Updated:** [DATE]\n",
                encoding="utf-8",
            )

    def _configure_profile(self, *agents: str) -> None:
        (self.root / "contextos.workspace.json").write_text(
            root_config(agents=list(agents)), encoding="utf-8"
        )

    def _materialize_components(self, *component_ids: str) -> None:
        manifest = load_component_manifest(
            ROOT / "components" / "manifest.json", root=ROOT, check_paths=False
        )
        for record in resolved_component_paths(manifest, component_ids):
            source = ROOT / record["path"]
            target = self.root / record["path"]
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

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

    def test_end_advances_freshness_for_changed_weekly_priorities_and_blockers(self) -> None:
        blockers = (self.root / "state/blockers.md").read_text(encoding="utf-8") + "\n- Waiting on review\n"
        weekly = (self.root / "state/weekly-priorities.md").read_text(encoding="utf-8") + "\n- Ship readiness fix\n"
        proposal_path, proposal = self._propose(
            "end",
            {
                "what_happened": ["Updated lifecycle state"],
                "blockers_markdown": blockers,
                "weekly_priorities_markdown": weekly,
            },
        )
        self._apply(proposal_path, proposal)
        for filename in ("blockers.md", "weekly-priorities.md"):
            content = (self.root / "state" / filename).read_text(encoding="utf-8")
            self.assertIn("**Last Updated:** 2026-08-23", content)
            self.assertEqual(1, content.count("**Last Updated:**"))

    def test_end_upgrades_legacy_dated_state_without_freshness_metadata(self) -> None:
        blockers = "# Blockers\n\n- Waiting on review\n"
        weekly = "# Weekly Priorities\n\n**Week of:** 2026-08-18\n\n1. Ship fix\n"
        proposal_path, proposal = self._propose(
            "end",
            {
                "what_happened": ["Updated legacy lifecycle state"],
                "blockers_markdown": blockers,
                "weekly_priorities_markdown": weekly,
            },
        )
        self._apply(proposal_path, proposal)
        for filename in ("blockers.md", "weekly-priorities.md"):
            content = (self.root / "state" / filename).read_text(encoding="utf-8")
            self.assertIn("**Last Updated:** 2026-08-23", content)
            self.assertEqual(1, content.count("**Last Updated:**"))
        weekly_content = (self.root / "state/weekly-priorities.md").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            weekly_content.index("**Week of:**"),
            weekly_content.index("**Last Updated:**"),
        )

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
        with self.assertRaisesRegex(ContextOSError, "canonical lexical path"):
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
        with self.assertRaisesRegex(ContextOSError, "metadata or local host state"):
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
        self.assertEqual("fresh", report["state"]["state/current.md"]["freshness_status"])
        self.assertTrue(report["initialized"])
        self.assertIsNone(report["next_action"])

    def test_fresh_clone_reports_setup_required_from_real_templates(self) -> None:
        self._write_undated_state("current.md", "weekly-priorities.md", "blockers.md")

        report = start_report(self.root, NOW)
        self.assertFalse(report["initialized"])
        self.assertIn("setup workflow", report["next_action"])
        for item in report["state"].values():
            self.assertEqual("unknown", item["freshness_status"])
            self.assertIsNone(item["stale"])

        diagnosis = doctor(self.root)
        initialization = next(
            item for item in diagnosis["checks"] if item["name"] == "initialization-state"
        )
        self.assertEqual("warn", initialization["status"])
        self.assertIn("guided setup required", initialization["detail"])

    def test_future_dated_state_is_not_treated_as_initialized(self) -> None:
        (self.root / "state/current.md").write_text(
            "# Current State\n\n**Last Updated:** 2099-01-01\n",
            encoding="utf-8",
        )

        report = start_report(self.root, NOW)
        current = report["state"]["state/current.md"]
        self.assertEqual("future", current["freshness_status"])
        self.assertLess(current["age_days"], 0)
        self.assertIsNone(current["stale"])
        self.assertFalse(report["initialized"])
        messages = [
            finding["message"] for finding in hook_report(self.root, "session-start", {})["findings"]
        ]
        self.assertTrue(any("not initialized" in message for message in messages), messages)

        diagnosis = doctor(self.root)
        initialization = next(
            item for item in diagnosis["checks"] if item["name"] == "initialization-state"
        )
        self.assertEqual("warn", initialization["status"])
        self.assertIn("state/current.md", initialization["detail"])

    def test_invalid_or_unreadable_dates_are_unknown_in_every_readiness_consumer(self) -> None:
        current = self.root / "state/current.md"
        for content in (
            b"# Current State\n\n**Last Updated:** 2026-13-01\n",
            b"# Current State\n\n**Last Updated:** \xff\n",
        ):
            current.write_bytes(content)
            report = start_report(self.root, NOW)
            self.assertFalse(report["initialized"])
            self.assertEqual("unknown", report["state"]["state/current.md"]["freshness_status"])
            self.assertTrue(hook_report(self.root, "session-start", {})["findings"])
            initialization = next(
                item for item in doctor(self.root)["checks"]
                if item["name"] == "initialization-state"
            )
            self.assertEqual("warn", initialization["status"])

    def test_readiness_predicate_is_shared_by_start_doctor_and_hook(self) -> None:
        """current.md gates readiness, and all three consumers must agree on it."""
        self._write_undated_state("weekly-priorities.md", "blockers.md")

        # current.md is dated; the other two are untouched shipped templates.
        report = start_report(self.root, NOW)
        self.assertTrue(report["initialized"])
        self.assertIsNone(report["next_action"])
        self.assertEqual([], hook_report(self.root, "session-start", {})["findings"])
        initialization = next(
            item for item in doctor(self.root)["checks"] if item["name"] == "initialization-state"
        )
        self.assertEqual("pass", initialization["status"])

        # Reverting current.md to the template must flip all three together.
        self._write_undated_state("current.md")
        self.assertFalse(start_report(self.root, NOW)["initialized"])
        messages = [
            finding["message"] for finding in hook_report(self.root, "session-start", {})["findings"]
        ]
        self.assertTrue(any("not initialized" in message for message in messages), messages)
        initialization = next(
            item for item in doctor(self.root)["checks"] if item["name"] == "initialization-state"
        )
        self.assertEqual("warn", initialization["status"])

    def test_unset_optional_state_is_reported_without_blocking_readiness(self) -> None:
        """An empty blockers file is a valid steady state, not an unfinished setup."""
        self._write_undated_state("blockers.md")
        report = start_report(self.root, NOW)
        self.assertTrue(report["initialized"])
        self.assertEqual("unknown", report["state"]["state/blockers.md"]["freshness_status"])
        freshness = next(
            item for item in doctor(self.root)["checks"] if item["name"] == "state-freshness"
        )
        self.assertEqual("warn", freshness["status"])
        self.assertIn("state/blockers.md", freshness["detail"])

    def test_next_action_names_the_command_to_run(self) -> None:
        self._write_undated_state("current.md")
        self.assertIn("scripts/setup.sh", start_report(self.root, NOW)["next_action"])

    def test_setup_stamps_freshness_on_tracked_state_files(self) -> None:
        """A completed setup must report as initialized without hand-written dates."""
        payload = {
            "files": {
                "state/current.md": (
                    "# Current State\n\n## Active priorities\n\n1. Ship the fix\n"
                ),
                "state/blockers.md": (
                    "# Blockers\n\n**Last Updated:** [DATE]\n\n- Waiting on review\n"
                ),
            },
            "replace_populated": ["state/current.md", "state/blockers.md"],
        }
        proposal_path, proposal = self._propose("setup", payload)
        self._apply(proposal_path, proposal)
        for filename in ("current.md", "blockers.md"):
            content = (self.root / "state" / filename).read_text(encoding="utf-8")
            self.assertIn("**Last Updated:** 2026-08-23", content)
            self.assertEqual(1, content.count("**Last Updated:**"))
        self.assertTrue(start_report(self.root, NOW)["initialized"])
    def test_install_and_doctor_are_machine_local(self) -> None:
        self._materialize_components("hermes-adapter")
        target, installed = install_runtime(self.root, "hermes")
        self.assertEqual(self.root / ".context-os/hosts.json", target)
        self.assertEqual("hermes", installed["runtime"])
        self.assertFalse((self.root / "contextos.workspace.json").exists())
        report = doctor(self.root, "hermes")
        self.assertIn(report["status"], {"pass", "warn"})
        self.assertFalse(any(item["status"] == "fail" for item in report["checks"]))
        manifest = json.loads((self.root / "runtimes/hermes.json").read_text())
        manifest["support_summary"] += " (updated)"
        (self.root / "runtimes/hermes.json").write_text(json.dumps(manifest), encoding="utf-8")
        drift = doctor(self.root, "hermes")
        drift_check = next(item for item in drift["checks"] if item["name"] == "runtime-manifest-drift")
        self.assertEqual("warn", drift_check["status"])

    def test_legacy_runtime_migrates_only_to_atomic_local_host_state(self) -> None:
        local = self.root / ".context-os"
        local.mkdir()
        digest = "a" * 64
        legacy = {
            "schema_version": 1,
            "runtime": "hermes",
            "installed_at": "2026-08-20T12:00:00+00:00",
            "source_manifest_sha256": digest,
            "next_steps": ["Launch Hermes"],
        }
        legacy_path = local / "runtime.json"
        legacy_path.write_text(json.dumps(legacy), encoding="utf-8")

        target, state, changed, migrated = migrate_legacy_runtime_state(self.root)
        self.assertTrue(changed)
        self.assertEqual("hermes", migrated)
        self.assertEqual(
            {
                "installed_at": legacy["installed_at"],
                "source_manifest_sha256": digest,
            },
            state["hosts"]["hermes"],
        )
        self.assertTrue(target.exists())
        self.assertFalse(legacy_path.exists())
        self.assertFalse((self.root / "contextos.workspace.json").exists())

        before = target.read_bytes()
        _, repeated, repeated_changed, repeated_runtime = migrate_legacy_runtime_state(
            self.root
        )
        self.assertFalse(repeated_changed)
        self.assertIsNone(repeated_runtime)
        self.assertEqual(state, repeated)
        self.assertEqual(before, target.read_bytes())

    def test_local_host_migration_rejects_conflict_and_preserves_bytes(self) -> None:
        local = self.root / ".context-os"
        local.mkdir()
        legacy = {
            "schema_version": 1,
            "runtime": "hermes",
            "installed_at": "2026-08-20T12:00:00+00:00",
            "source_manifest_sha256": "a" * 64,
        }
        (local / "runtime.json").write_text(json.dumps(legacy), encoding="utf-8")
        hosts = {
            "schema_version": 1,
            "hosts": {
                "hermes": {
                    "installed_at": "2026-08-21T12:00:00+00:00",
                    "source_manifest_sha256": "b" * 64,
                }
            },
        }
        hosts_path = local / "hosts.json"
        hosts_path.write_text(json.dumps(hosts), encoding="utf-8")
        before = hosts_path.read_bytes()
        with self.assertRaisesRegex(ContextOSError, "conflicts"):
            migrate_legacy_runtime_state(self.root)
        self.assertEqual(before, hosts_path.read_bytes())

    def test_malformed_legacy_runtime_never_creates_host_state(self) -> None:
        local = self.root / ".context-os"
        local.mkdir()
        (local / "runtime.json").write_text(
            '{"schema_version": 1, "runtime": "hermes"}', encoding="utf-8"
        )
        with self.assertRaisesRegex(ContextOSError, "missing legacy fields"):
            migrate_legacy_runtime_state(self.root)
        self.assertFalse((local / "hosts.json").exists())

    def test_local_host_state_preserves_multiple_installs_and_noop_timestamp(self) -> None:
        _, first = install_runtime(self.root, "hermes")
        _, second = install_runtime(self.root, "codex")
        _, repeated = install_runtime(self.root, "hermes")
        state = json.loads(
            (self.root / ".context-os/hosts.json").read_text(encoding="utf-8")
        )
        self.assertEqual(["codex", "hermes"], list(state["hosts"]))
        self.assertEqual(first["installed_at"], repeated["installed_at"])
        self.assertFalse(repeated["host_state_changed"])
        self.assertEqual("codex", second["runtime"])

    def test_concurrent_host_install_fails_busy_without_losing_updates(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        original_write = __import__(
            "contextos.kernel", fromlist=["write_generated_file"]
        ).write_generated_file

        def delayed_write(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(timeout=5))
            return original_write(*args, **kwargs)

        with mock.patch("contextos.kernel.write_generated_file", side_effect=delayed_write):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(install_runtime, self.root, "claude")
                self.assertTrue(entered.wait(timeout=5))
                second = pool.submit(install_runtime, self.root, "codex")
                with self.assertRaisesRegex(ContextOSError, "host-state update"):
                    second.result(timeout=5)
                release.set()
                first.result(timeout=5)

        install_runtime(self.root, "codex")
        state = json.loads(
            (self.root / ".context-os/hosts.json").read_text(encoding="utf-8")
        )
        self.assertEqual(["claude", "codex"], list(state["hosts"]))

    def test_malformed_local_host_state_is_a_structured_doctor_failure(self) -> None:
        local = self.root / ".context-os"
        local.mkdir()
        (local / "hosts.json").write_text("{", encoding="utf-8")
        report = doctor(self.root)
        check = next(item for item in report["checks"] if item["name"] == "local-host-state")
        self.assertEqual("fail", check["status"])
        self.assertTrue(
            all(
                runtime["local_onboarding"]["status"] == "unknown"
                for runtime in report["runtimes"].values()
            )
        )

    def test_local_host_write_failure_preserves_previous_bytes(self) -> None:
        local = self.root / ".context-os"
        local.mkdir()
        hosts_path = local / "hosts.json"
        original = '{"schema_version": 1, "hosts": {}}\n'
        hosts_path.write_text(original, encoding="utf-8")
        legacy = {
            "schema_version": 1,
            "runtime": "historical-host",
            "installed_at": "2026-08-20T12:00:00+00:00",
            "source_manifest_sha256": "a" * 64,
        }
        (local / "runtime.json").write_text(json.dumps(legacy), encoding="utf-8")
        with mock.patch(
            "contextos.kernel.write_generated_file",
            side_effect=OSError("injected replace failure"),
        ), self.assertRaisesRegex(ContextOSError, "injected replace failure"):
            migrate_legacy_runtime_state(self.root)
        self.assertEqual(original, hosts_path.read_text(encoding="utf-8"))

    def test_local_host_state_rejects_symlinked_parent(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        local = self.root / ".context-os"
        try:
            local.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation is unavailable")
        with self.assertRaisesRegex(ContextOSError, "symlink"):
            install_runtime(self.root, "hermes")
        self.assertFalse((outside / "hosts.json").exists())

    def test_doctor_uses_configured_state_and_selected_manifest_only(self) -> None:
        self._materialize_components("hermes-adapter")
        custom = self.root / "custom-state"
        (self.root / "state").rename(custom)
        (self.root / "workspace.yaml").write_text("state_dir: custom-state\n", encoding="utf-8")
        (self.root / "runtimes/codex.json").unlink()
        report = doctor(self.root, "hermes")
        self.assertFalse(any(item["status"] == "fail" for item in report["checks"]))
        self.assertTrue(any(item["name"] == "file:custom-state/current.md" for item in report["checks"]))
        self.assertEqual(["hermes"], list(report["runtimes"]))

    def test_empty_profile_keeps_every_shipped_runtime_inert(self) -> None:
        self._materialize_components("core")
        self._configure_profile()
        manifest = json.loads(
            (self.root / "runtimes/claude.json").read_text(encoding="utf-8")
        )
        manifest["unknown"] = True
        (self.root / "runtimes/claude.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

        report = doctor(self.root)

        self.assertEqual("profile", report["scope"])
        self.assertEqual([], report["workspace"]["configured_agents"])
        self.assertFalse(any(item["status"] == "fail" for item in report["checks"]))
        self.assertEqual("invalid-descriptor", report["runtimes"]["claude"]["support"]["status"])
        self.assertEqual(
            {
                "status": "unconfigured",
                "inert": True,
                "validation_scope": False,
            },
            report["runtimes"]["claude"]["configuration"],
        )

    def test_profile_scope_comes_from_tracked_agents_not_local_hosts(self) -> None:
        self._materialize_components("hermes-adapter")
        install_runtime(self.root, "codex")
        self._configure_profile("hermes")
        manifest = json.loads(
            (self.root / "runtimes/codex.json").read_text(encoding="utf-8")
        )
        manifest["unknown"] = True
        (self.root / "runtimes/codex.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

        report = doctor(self.root)
        names = {item["name"] for item in report["checks"]}

        self.assertFalse(any(item["status"] == "fail" for item in report["checks"]))
        self.assertIn("manifest:hermes", names)
        self.assertNotIn("manifest:codex", names)
        self.assertTrue(report["runtimes"]["codex"]["configuration"]["inert"])
        self.assertEqual(
            "configured", report["runtimes"]["codex"]["local_onboarding"]["status"]
        )

    def test_profile_materialization_blocks_only_configured_adapters(self) -> None:
        self._materialize_components("claude-adapter", "codex-adapter")
        (self.root / ".codex/hooks.json").unlink()
        self._configure_profile("codex")

        configured = doctor(self.root)
        check = next(
            item for item in configured["checks"] if item["name"] == "components:codex"
        )
        self.assertEqual("fail", check["status"])

        self._configure_profile("claude")
        inert = doctor(self.root)
        self.assertFalse(any(item["status"] == "fail" for item in inert["checks"]))
        self.assertEqual("partial", inert["runtimes"]["codex"]["components"]["status"])

    def test_profile_missing_user_owned_seed_warns_but_managed_path_still_fails(self) -> None:
        self._materialize_components("hermes-adapter")
        self._configure_profile("hermes")
        (self.root / "content/log.md").unlink()

        seed_report = doctor(self.root)
        seed_check = next(
            item
            for item in seed_report["checks"]
            if item["name"] == "components:hermes"
        )
        self.assertEqual("warn", seed_check["status"])
        self.assertFalse(any(item["status"] == "fail" for item in seed_report["checks"]))
        self.assertIn(
            "content/log.md",
            seed_report["runtimes"]["hermes"]["components"]["missing_by_policy"]["seed"],
        )
        maintainer_check = next(
            item
            for item in doctor(self.root, all_runtimes=True)["checks"]
            if item["name"] == "components:hermes"
        )
        self.assertEqual("fail", maintainer_check["status"])

        (self.root / "AGENTS.md").unlink()
        managed_report = doctor(self.root)
        managed_check = next(
            item
            for item in managed_report["checks"]
            if item["name"] == "components:hermes"
        )
        self.assertEqual("fail", managed_check["status"])

    def test_profile_missing_core_state_seed_warns_without_failing(self) -> None:
        self._materialize_components("hermes-adapter")
        self._configure_profile("hermes")
        (self.root / "state/current.md").unlink()

        report = doctor(self.root)
        file_check = next(
            item
            for item in report["checks"]
            if item["name"] == "file:state/current.md"
        )
        component_check = next(
            item
            for item in report["checks"]
            if item["name"] == "components:hermes"
        )
        self.assertEqual("warn", file_check["status"])
        self.assertEqual("warn", component_check["status"])
        self.assertFalse(any(item["status"] == "fail" for item in report["checks"]))

    def test_availability_is_independent_from_support_and_onboarding(self) -> None:
        self._materialize_components("hermes-adapter")
        self._configure_profile("hermes")
        with mock.patch(
            "contextos.kernel.shutil.which",
            side_effect=lambda command: "git-path" if command == "git" else None,
        ):
            report = doctor(self.root)
        runtime = report["runtimes"]["hermes"]
        self.assertEqual("supported", runtime["support"]["status"])
        self.assertEqual("unavailable", runtime["local_availability"]["status"])
        self.assertEqual("not-configured", runtime["local_onboarding"]["status"])
        self.assertFalse(any(item["status"] == "fail" for item in report["checks"]))

    def test_evidence_freshness_boundary_is_deterministic(self) -> None:
        self._materialize_components("hermes-adapter")
        self._configure_profile("hermes")
        path = self.root / "runtimes/hermes.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["evidence"]["checked_on"] = "2026-05-27"
        path.write_text(json.dumps(manifest), encoding="utf-8")

        fresh = doctor(self.root, today=date(2026, 8, 25))["runtimes"]["hermes"]["evidence"]
        self.assertEqual(("fresh", 90, 90), (fresh["status"], fresh["age_days"], fresh["stale_after_days"]))

        manifest["evidence"]["checked_on"] = "2026-05-26"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        stale_report = doctor(self.root, today=date(2026, 8, 25))
        stale = stale_report["runtimes"]["hermes"]["evidence"]
        self.assertEqual(("stale", 91), (stale["status"], stale["age_days"]))
        self.assertEqual(
            "warn",
            next(
                item
                for item in stale_report["checks"]
                if item["name"] == "runtime-evidence:hermes"
            )["status"],
        )

        manifest["evidence"]["checked_on"] = "2026-08-26"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        skew_report = doctor(self.root, today=date(2026, 8, 25))
        skew = skew_report["runtimes"]["hermes"]["evidence"]
        self.assertEqual(("fresh", -1), (skew["status"], skew["age_days"]))
        self.assertFalse(any(item["status"] == "fail" for item in skew_report["checks"]))

        future_report = doctor(self.root, today=date(2026, 8, 24))
        future = future_report["runtimes"]["hermes"]["evidence"]
        self.assertEqual(("future", -2), (future["status"], future["age_days"]))
        self.assertEqual(
            "warn",
            next(
                item
                for item in future_report["checks"]
                if item["name"] == "runtime-evidence:hermes"
            )["status"],
        )

    def test_agents_instruction_is_required_only_by_selected_closure(self) -> None:
        self._materialize_components("claude-adapter", "hermes-adapter")
        (self.root / "AGENTS.md").unlink()
        self._configure_profile("claude")
        claude = doctor(self.root)
        self.assertFalse(any(item["status"] == "fail" for item in claude["checks"]))
        self.assertNotIn("file:AGENTS.md", {item["name"] for item in claude["checks"]})

        self._configure_profile("hermes")
        hermes = doctor(self.root)
        check = next(
            item for item in hermes["checks"] if item["name"] == "components:hermes"
        )
        self.assertEqual("fail", check["status"])

    def test_all_scope_reports_only_shipped_registry_runtimes(self) -> None:
        install_runtime(self.root, "hermes")
        hosts_path = self.root / ".context-os/hosts.json"
        hosts = json.loads(hosts_path.read_text(encoding="utf-8"))
        hosts["hosts"]["orphan"] = dict(hosts["hosts"]["hermes"])
        hosts_path.write_text(json.dumps(hosts), encoding="utf-8")

        report = doctor(self.root, all_runtimes=True)
        self.assertEqual({"claude", "codex", "hermes"}, set(report["runtimes"]))

    def test_bare_doctor_validates_all_manifests_during_setup(self) -> None:
        manifest = json.loads((self.root / "runtimes/claude.json").read_text(encoding="utf-8"))
        manifest["unknown"] = True
        (self.root / "runtimes/claude.json").write_text(json.dumps(manifest), encoding="utf-8")
        report = doctor(self.root)
        check = next(item for item in report["checks"] if item["name"] == "manifest:claude")
        self.assertEqual("fail", check["status"])

    def test_bare_doctor_preserves_single_installed_runtime_scope(self) -> None:
        install_runtime(self.root, "hermes")
        manifest = json.loads(
            (self.root / "runtimes/claude.json").read_text(encoding="utf-8")
        )
        manifest["unknown"] = True
        (self.root / "runtimes/claude.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        report = doctor(self.root)
        names = {item["name"] for item in report["checks"]}
        self.assertEqual("legacy", report["scope"])
        self.assertIn("manifest:hermes", names)
        self.assertNotIn("manifest:claude", names)
        components = next(
            item for item in report["checks"] if item["name"] == "components:hermes"
        )
        self.assertEqual("warn", components["status"])
        self.assertFalse(any(item["status"] == "fail" for item in report["checks"]))

    def test_bare_doctor_checks_drift_for_every_installed_host(self) -> None:
        install_runtime(self.root, "hermes")
        install_runtime(self.root, "codex")
        manifest = json.loads(
            (self.root / "runtimes/hermes.json").read_text(encoding="utf-8")
        )
        manifest["install"]["next_steps"].append("drift")
        (self.root / "runtimes/hermes.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        report = doctor(self.root)
        checks = {item["name"]: item for item in report["checks"]}
        self.assertEqual("warn", checks["runtime-manifest-drift:hermes"]["status"])
        self.assertEqual("pass", checks["runtime-manifest-drift:codex"]["status"])

    def test_doctor_warns_about_host_state_lock_with_recovery_guidance(self) -> None:
        local = self.root / ".context-os"
        local.mkdir()
        (local / "hosts.lock").write_text("pid=999999\n", encoding="utf-8")
        report = doctor(self.root)
        check = next(
            item for item in report["checks"] if item["name"] == "host-state-lock"
        )
        self.assertEqual("warn", check["status"])
        self.assertIn("confirming no install or migration is running", check["detail"])

    def test_doctor_fails_closed_on_linked_apply_lock(self) -> None:
        local = self.root / ".context-os"
        local.mkdir()
        lock = local / "apply.lock"
        with tempfile.TemporaryDirectory() as external:
            try:
                make_directory_link(lock, Path(external))
            except OSError:
                self.skipTest("directory link creation is unavailable")
            try:
                report = doctor(self.root)
            finally:
                lock.rmdir() if os.name == "nt" else lock.unlink()

        check = next(
            item for item in report["checks"] if item["name"] == "transaction-lock"
        )
        self.assertEqual("fail", check["status"])
        self.assertIn("symlink or reparse point", check["detail"])

    def test_doctor_reports_dangling_local_artifact_link_without_crashing(self) -> None:
        proposals = self.root / ".context-os/proposals"
        proposals.mkdir(parents=True)
        artifact = proposals / "dangling.json"
        try:
            artifact.symlink_to(self.root / "missing-artifact.json")
        except OSError:
            self.skipTest("symlink creation is unavailable")

        report = doctor(self.root)
        check = next(
            item
            for item in report["checks"]
            if item["name"] == "local-artifact-retention"
        )
        self.assertEqual("warn", check["status"])
        self.assertIn("link-like artifact ignored", check["detail"])

    def test_doctor_fails_closed_on_linked_artifact_directory(self) -> None:
        outside = Path(self.temp.name) / "outside-proposals"
        outside.mkdir()
        proposals = self.root / ".context-os/proposals"
        proposals.parent.mkdir(parents=True, exist_ok=True)
        if not make_directory_link(proposals, outside):
            self.skipTest("directory link creation is unavailable")
        try:
            report = doctor(self.root)
        finally:
            proposals.rmdir() if os.name == "nt" else proposals.unlink()
        check = next(
            item
            for item in report["checks"]
            if item["name"] == "local-artifact-retention"
        )
        self.assertEqual("fail", check["status"])
        self.assertIn("cannot inspect proposals", check["detail"])

    def test_core_only_profile_checks_managed_core_materialization(self) -> None:
        self._materialize_components("core")
        self._configure_profile()
        (self.root / "docs/getting-started.md").unlink()

        report = doctor(self.root)

        check = next(
            item for item in report["checks"] if item["name"] == "components:core"
        )
        self.assertEqual("fail", check["status"])
        self.assertIn("docs/getting-started.md", check["detail"])

    def test_core_only_profile_reports_shadowed_directory_as_a_failure(self) -> None:
        self._materialize_components("core")
        self._configure_profile()
        shutil.rmtree(self.root / "docs")
        (self.root / "docs").write_text("not a directory\n", encoding="utf-8")

        report = doctor(self.root)

        check = next(
            item for item in report["checks"] if item["name"] == "components:core"
        )
        self.assertEqual("fail", check["status"])
        self.assertEqual("fail", report["status"])

    def test_maintainer_scope_includes_development_component_paths(self) -> None:
        report = doctor(self.root, all_runtimes=True)

        missing = report["runtimes"]["claude"]["components"]["missing_by_policy"]
        self.assertIn("CONTRIBUTING.md", missing["development"])

    def test_doctor_normalizes_an_unresolved_root(self) -> None:
        unresolved = self.root / "nested" / ".."

        report = doctor(unresolved)

        self.assertIn(report["status"], {"pass", "warn"})

    def test_doctor_reports_linked_state_file_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as external:
            outside = Path(external) / "outside-current.md"
            outside.write_text("# external\n", encoding="utf-8")
            current = self.root / "state/current.md"
            current.unlink()
            try:
                current.symlink_to(outside)
            except OSError:
                self.skipTest("symlink creation is unavailable")
            report = doctor(self.root)
        check = next(
            item for item in report["checks"] if item["name"] == "file:state/current.md"
        )
        self.assertEqual("fail", check["status"])
        self.assertIn("symlink or reparse point", check["detail"])

    def test_doctor_reports_linked_state_directory_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as external:
            outside = Path(external) / "outside-state"
            (self.root / "state").rename(outside)
            state = self.root / "state"
            try:
                state.symlink_to(outside, target_is_directory=True)
            except OSError:
                outside.rename(state)
                self.skipTest("directory symlink creation is unavailable")
            report = doctor(self.root)
        self.assertEqual("fail", report["status"])
        self.assertEqual("invalid", report["scope"])
        self.assertTrue(
            any(
                "symlink or reparse point" in item["detail"]
                for item in report["checks"]
            )
        )

    def test_doctor_reports_external_links_for_every_configurable_seed_path(self) -> None:
        with tempfile.TemporaryDirectory() as external:
            external_root = Path(external)
            cases = (
                (self.root / "sessions", external_root / "sessions", True),
                (self.root / "TODO.md", external_root / "TODO.md", False),
            )
            for target, outside, is_directory in cases:
                with self.subTest(path=target.name):
                    target.rename(outside)
                    try:
                        target.symlink_to(outside, target_is_directory=is_directory)
                    except OSError:
                        outside.rename(target)
                        self.skipTest("symlink creation is unavailable")
                    report = doctor(self.root)
                    self.assertEqual("fail", report["status"])
                    self.assertEqual("invalid", report["scope"])
                    self.assertTrue(
                        any(
                            missing == target.name
                            or missing.startswith(target.name + "/")
                            for runtime in report["runtimes"].values()
                            for missing in runtime["components"]["missing_paths"]
                        )
                    )
                    target.unlink()
                    outside.rename(target)

    def test_doctor_fails_closed_on_linked_local_state_root(self) -> None:
        outside = self.root / "outside-context-os"
        outside.mkdir()
        local = self.root / ".context-os"
        try:
            local.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlink creation is unavailable")

        report = doctor(self.root)
        checks = {item["name"]: item for item in report["checks"]}
        self.assertEqual("fail", checks["local-host-state"]["status"])
        self.assertEqual("fail", checks["transaction-journals"]["status"])
        self.assertEqual("fail", checks["host-state-lock"]["status"])

    def test_bare_doctor_fails_when_registry_is_empty(self) -> None:
        shutil.rmtree(self.root / "runtimes")
        report = doctor(self.root)
        check = next(item for item in report["checks"] if item["name"] == "manifest-registry")
        self.assertEqual("fail", check["status"])

    def test_doctor_handles_runtime_without_a_cli_surface(self) -> None:
        self._materialize_components("hermes-adapter")
        path = self.root / "runtimes/hermes.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        cloud = manifest["surfaces"].pop("cli")
        cloud["kind"] = "cloud"
        review = json.loads(json.dumps(cloud))
        review["kind"] = "review"
        manifest["surfaces"] = {"cloud": cloud, "review": review}
        manifest["evidence"]["tested_versions"] = [
            {"surface": "cloud", "version": "fixture"},
            {"surface": "review", "version": "fixture"},
        ]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with mock.patch(
            "contextos.kernel.shutil.which",
            side_effect=lambda command: "git-path" if command == "git" else None,
        ):
            report = doctor(self.root, "hermes")
        self.assertFalse(any(item["status"] == "fail" for item in report["checks"]), report)
        self.assertTrue(
            any(item["name"].startswith("runtime:hermes:cloud:") for item in report["checks"])
        )

    def test_doctor_never_executes_descriptor_probe_commands(self) -> None:
        self._materialize_components("hermes-adapter")
        with mock.patch("contextos.kernel.shutil.which", return_value="resolved-command"), mock.patch(
            "contextos.kernel.subprocess.run",
            side_effect=AssertionError("descriptor probe executed a process"),
        ) as run:
            report = doctor(self.root, "hermes")
        run.assert_not_called()
        self.assertTrue(
            any(item["name"] == "runtime:hermes:cli:version" for item in report["checks"])
        )

    def test_runtime_manifest_is_required_for_receipt_claim(self) -> None:
        proposal_path, proposal = self._propose("update", {"progress": ["One"]})
        os.remove(self.root / "runtimes/codex.json")
        with self.assertRaisesRegex(ContextOSError, "missing runtime manifest"):
            self._apply(proposal_path, proposal)

    def test_apply_does_not_require_maintainer_docs_or_tests(self) -> None:
        proposal_path, proposal = self._propose("update", {"progress": ["One"]})
        for directory in ("docs", "tests", ".agents"):
            shutil.rmtree(self.root / directory)
        receipt_path, _ = self._apply(proposal_path, proposal)
        self.assertTrue(receipt_path.is_file())
        with self.assertRaisesRegex(ContextOSError, "path does not exist"):
            runtime_manifest(self.root, "codex")

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
