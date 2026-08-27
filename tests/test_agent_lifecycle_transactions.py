from __future__ import annotations

import ctypes
import json
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

from contextos.cli import main as cli_main
from contextos.kernel import (
    ContextOSError,
    _agent_change,
    _create_agent_journal,
    _discard_agent_journal,
    _fsync_directory,
    _prepare_publication_anchor,
    _publish_exclusive,
    _recover_pending_agent_journals,
    _rmtree_readonly_artifacts,
    _restore_transaction_target,
    _transaction_slot,
    _unlink_readonly_artifact,
    apply_proposal,
    agent_list_report,
    canonical_json,
    create_agent_activation_proposal,
    create_proposal,
    create_workspace_migration_proposal,
    create_workspace_setup_proposal,
    doctor,
    raw_file_digest,
    read_json,
    safe_repo_path,
    sha256_bytes,
    sha256_text,
)
from contextos.workspace_schema import WorkspaceConfigError


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-08-25T12:00:00-07:00")


class AgentLifecycleTransactionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for directory in ("state", "sessions", "runtimes", "components", "workspace"):
            (self.root / directory).mkdir()
        (self.root / "AGENTS.md").write_text("# Fixture\n", encoding="utf-8")
        (self.root / "TODO.md").write_text("# Tasks\n", encoding="utf-8")
        (self.root / "workspace.yaml").write_text(
            "state_dir: state\n", encoding="utf-8"
        )
        for relative in (
            "components/manifest.json",
            "runtimes/schema.json",
            "runtimes/claude.json",
            "runtimes/codex.json",
            "runtimes/hermes.json",
            "workspace/schema.json",
        ):
            target = self.root / relative
            target.write_bytes((ROOT / relative).read_bytes())

    def propose(self, agents=("claude",)):
        path, document = create_workspace_migration_proposal(self.root, agents, NOW)
        self.assertIsNotNone(path)
        self.assertIsNotNone(document)
        return path, document

    def apply(self, path: Path, proposal: dict):
        return apply_proposal(
            self.root, path, proposal["proposal_digest"], "generic"
        )

    def resign(self, path: Path, proposal: dict) -> None:
        unsigned = dict(proposal)
        unsigned.pop("proposal_digest", None)
        proposal["proposal_digest"] = sha256_text(canonical_json(unsigned))
        path.write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")

    def assert_no_transaction_artifacts(self) -> None:
        for folder in ("receipts", "staging", "journals"):
            path = self.root / ".context-os" / folder
            if path.exists():
                self.assertEqual([], list(path.iterdir()), folder)
        self.assertFalse((self.root / ".context-os/apply.lock").exists())

    def test_legacy_migration_is_atomic_write_delete_with_evidence(self) -> None:
        legacy = self.root / "workspace.yaml"
        legacy.write_text("state_dir: custom-state\n", encoding="utf-8")
        path, proposal = self.propose(("claude", "codex"))
        self.assertEqual("agent-config", proposal["workflow"])
        self.assertEqual("workspace-migrate", proposal["operation"])
        self.assertEqual(
            ["contextos.workspace.json", "workspace.yaml"],
            [change["path"] for change in proposal["changes"]],
        )
        self.assertEqual(
            ["write", "delete"],
            [change["action"] for change in proposal["changes"]],
        )
        self.assertIsNone(proposal["authorization"]["before_agents"])
        self.assertEqual(
            ["claude", "codex"], proposal["authorization"]["after_agents"]
        )

        receipt_path, receipt = self.apply(path, proposal)
        self.assertTrue(receipt_path.is_file())
        self.assertFalse(legacy.exists())
        configured = json.loads(
            (self.root / "contextos.workspace.json").read_text(encoding="utf-8")
        )
        self.assertEqual("custom-state", configured["paths"]["state_dir"])
        self.assertEqual("self-reported", receipt["runtime_identity"])
        self.assertFalse(receipt["confirmation"]["human_authenticated"])
        self.assertEqual(
            ["workspace-config", "legacy-workspace-config"],
            [change["owner"] for change in receipt["files_changed"]],
        )
        self.assertNotIn("after_text", receipt["files_changed"][0])

    def test_agent_lifecycle_rejects_link_like_component_authority(self) -> None:
        inventory = self.root / "components/manifest.json"
        with mock.patch(
            "contextos.kernel._is_link_like",
            side_effect=lambda path: path == inventory,
        ):
            with self.assertRaisesRegex(ContextOSError, "symlink or reparse point"):
                create_workspace_migration_proposal(self.root, ("claude",), NOW)

    def test_legacy_shadowed_yaml_noop_and_scope_boundaries(self) -> None:
        path, proposal = self.propose(("claude",))
        self.assertEqual(
            ["contextos.workspace.json", "workspace.yaml"],
            [c["path"] for c in proposal["changes"]],
        )
        self.apply(path, proposal)

        (self.root / "workspace.yaml").write_text("state_dir: state\n", encoding="utf-8")
        path, proposal = create_workspace_migration_proposal(
            self.root, ("claude",), NOW.replace(second=1)
        )
        self.assertEqual(["workspace.yaml"], [c["path"] for c in proposal["changes"]])
        self.apply(path, proposal)
        path, proposal = create_workspace_migration_proposal(
            self.root, ("claude",), NOW.replace(second=2)
        )
        self.assertIsNone(path)
        self.assertIsNone(proposal)
        with self.assertRaisesRegex(ContextOSError, "cannot change an existing agent set"):
            create_workspace_migration_proposal(
                self.root, ("claude", "codex"), NOW.replace(second=3)
            )

        (self.root / "contextos.workspace.json").unlink()
        with self.assertRaisesRegex(ContextOSError, "requires legacy"):
            create_workspace_migration_proposal(
                self.root, ("claude",), NOW.replace(second=4)
            )

    def test_cli_proposes_without_writing_tracked_configuration(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                0,
                cli_main([
                    "--root",
                    str(self.root),
                    "workspace",
                    "propose-migration",
                    "--agents",
                    "claude,codex",
                    "--now",
                    NOW.isoformat(),
                ]),
            )
        report = json.loads(output.getvalue())
        self.assertFalse(report["writes"])
        self.assertEqual("agent-config", report["workflow"])
        self.assertEqual("workspace-migrate", report["operation"])
        self.assertEqual(
            ["contextos.workspace.json", "workspace.yaml"],
            [change["path"] for change in report["changes"]],
        )
        self.assertFalse((self.root / "contextos.workspace.json").exists())
        self.assertTrue((self.root / report["proposal"]).is_file())

    def test_setup_proposal_creates_core_only_config_without_legacy_yaml(self) -> None:
        (self.root / "workspace.yaml").unlink()

        path, proposal = create_workspace_setup_proposal(self.root, (), NOW)

        self.assertIsNotNone(path)
        self.assertIsNotNone(proposal)
        assert path is not None and proposal is not None
        self.assertEqual("workspace-setup", proposal["operation"])
        self.assertEqual(["contextos.workspace.json"], [
            change["path"] for change in proposal["changes"]
        ])
        self.assertIsNone(proposal["authorization"]["before_agents"])
        self.assertEqual([], proposal["authorization"]["after_agents"])
        self.apply(path, proposal)
        configured = json.loads(
            (self.root / "contextos.workspace.json").read_text(encoding="utf-8")
        )
        self.assertEqual([], configured["agents"])

    def test_setup_proposal_is_additive_idempotent_and_never_shrinks(self) -> None:
        path, proposal = self.propose(("claude",))
        self.apply(path, proposal)

        for requested in (("claude",), ()):
            path, proposal = create_workspace_setup_proposal(
                self.root, requested, NOW.replace(second=1)
            )
            self.assertIsNone(path)
            self.assertIsNone(proposal)

        path, proposal = create_workspace_setup_proposal(
            self.root, ("codex",), NOW.replace(second=2)
        )
        self.assertIsNotNone(path)
        self.assertIsNotNone(proposal)
        assert path is not None and proposal is not None
        self.assertEqual(
            ["claude", "codex"], proposal["authorization"]["after_agents"]
        )
        self.apply(path, proposal)

        path, proposal = create_workspace_setup_proposal(
            self.root, (), NOW.replace(second=3)
        )
        self.assertIsNone(path)
        self.assertIsNone(proposal)
        configured = json.loads(
            (self.root / "contextos.workspace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(["claude", "codex"], configured["agents"])

    def test_setup_proposal_validates_before_forming_the_additive_union(self) -> None:
        for requested, message in (
            (("claude", "claude"), "duplicate"),
            (("missing",), "unknown"),
            (("CLAUDE",), "lowercase"),
        ):
            with self.subTest(requested=requested), self.assertRaisesRegex(
                WorkspaceConfigError, message
            ):
                create_workspace_setup_proposal(self.root, requested, NOW)

    def test_cli_setup_selection_is_additive_and_alias_is_deprecated(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                0,
                cli_main([
                    "--root", str(self.root), "workspace", "propose-setup",
                    "--agent", "claude", "--now", NOW.isoformat(),
                ]),
            )
        report = json.loads(output.getvalue())
        self.assertEqual("proposed", report["action"])
        self.assertIn("deprecated", " ".join(report["notices"]))
        self.assertEqual(["claude"], report["authorization"]["after_agents"])
        self.assertFalse((self.root / "contextos.workspace.json").exists())

    def test_agent_enable_disable_are_exact_idempotent_config_only_changes(self) -> None:
        protected_before = {
            relative: (self.root / relative).read_bytes()
            for relative in ("AGENTS.md", "TODO.md", "components/manifest.json")
        }
        path, proposal = self.propose(("claude",))
        self.apply(path, proposal)
        local_sentinels = {
            ".context-os/hosts.json": b'{"schema_version":1,"hosts":{}}\n',
            ".context-os/native-memory.txt": b"machine-local bytes\r\n",
        }
        for relative, content in local_sentinels.items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            protected_before[relative] = content

        path, proposal = create_agent_activation_proposal(
            self.root, "codex", True, NOW.replace(second=1)
        )
        self.assertIsNotNone(path)
        self.assertIsNotNone(proposal)
        assert path is not None and proposal is not None
        self.assertEqual("agent-enable", proposal["operation"])
        self.assertEqual(
            ["contextos.workspace.json"],
            [change["path"] for change in proposal["changes"]],
        )
        self.assertEqual(["claude"], proposal["authorization"]["before_agents"])
        self.assertEqual(
            ["claude", "codex"], proposal["authorization"]["after_agents"]
        )
        self.apply(path, proposal)
        self.assertEqual(
            (None, None),
            create_agent_activation_proposal(
                self.root, "codex", True, NOW.replace(second=2)
            ),
        )

        path, proposal = create_agent_activation_proposal(
            self.root, "claude", False, NOW.replace(second=3)
        )
        self.assertIsNotNone(path)
        self.assertIsNotNone(proposal)
        assert path is not None and proposal is not None
        self.assertEqual("agent-disable", proposal["operation"])
        self.assertEqual(
            ["claude", "codex"], proposal["authorization"]["before_agents"]
        )
        self.assertEqual(["codex"], proposal["authorization"]["after_agents"])
        self.apply(path, proposal)
        self.assertEqual(
            (None, None),
            create_agent_activation_proposal(
                self.root, "claude", False, NOW.replace(second=4)
            ),
        )

        path, proposal = create_agent_activation_proposal(
            self.root, "codex", False, NOW.replace(second=5)
        )
        assert path is not None and proposal is not None
        self.assertEqual([], proposal["authorization"]["after_agents"])
        self.apply(path, proposal)
        configured = json.loads(
            (self.root / "contextos.workspace.json").read_text(encoding="utf-8")
        )
        self.assertEqual([], configured["agents"])
        for relative, before in protected_before.items():
            self.assertEqual(before, (self.root / relative).read_bytes(), relative)

    def test_crafted_disable_cannot_remove_more_than_one_runtime(self) -> None:
        path, proposal = self.propose(("claude", "codex"))
        self.apply(path, proposal)
        path, proposal = create_agent_activation_proposal(
            self.root, "claude", False, NOW.replace(second=1)
        )
        assert path is not None and proposal is not None
        after_config = json.loads(proposal["changes"][0]["after_text"])
        after_config["agents"] = []
        after_text = json.dumps(after_config, indent=2) + "\n"
        proposal["changes"][0] = _agent_change(
            self.root,
            "agent-disable",
            "contextos.workspace.json",
            action="write",
            after_text=after_text,
        )
        self.resign(path, proposal)

        with self.assertRaisesRegex(ContextOSError, "remove exactly one"):
            self.apply(path, proposal)

    def test_crafted_activation_cannot_rewrite_workspace_paths(self) -> None:
        path, proposal = self.propose(("claude",))
        self.apply(path, proposal)
        path, proposal = create_agent_activation_proposal(
            self.root, "codex", True, NOW.replace(second=1)
        )
        assert path is not None and proposal is not None
        after_config = json.loads(proposal["changes"][0]["after_text"])
        after_config["paths"]["state_dir"] = "redirected-state"
        after_text = json.dumps(after_config, indent=2) + "\n"
        proposal["changes"][0] = _agent_change(
            self.root,
            "agent-enable",
            "contextos.workspace.json",
            action="write",
            after_text=after_text,
        )
        self.resign(path, proposal)

        with self.assertRaisesRegex(ContextOSError, "may change only agents"):
            self.apply(path, proposal)

    def test_crafted_migration_cannot_bypass_disable_or_setup_semantics(self) -> None:
        path, proposal = self.propose(("claude",))
        self.apply(path, proposal)
        path, proposal = create_workspace_setup_proposal(
            self.root, ("codex",), NOW.replace(second=1)
        )
        assert path is not None and proposal is not None
        proposal["operation"] = "workspace-migrate"
        self.resign(path, proposal)

        with self.assertRaisesRegex(ContextOSError, "cannot change tracked configuration"):
            self.apply(path, proposal)

    def test_activation_committed_journal_recovers_with_its_exact_operation(self) -> None:
        path, proposal = self.propose(("claude",))
        self.apply(path, proposal)
        path, proposal = create_agent_activation_proposal(
            self.root, "codex", True, NOW.replace(second=1)
        )
        assert path is not None and proposal is not None
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        with mock.patch(
            "contextos.kernel._discard_agent_journal",
            side_effect=OSError("retain committed activation journal"),
        ):
            receipt, _ = self.apply(path, proposal)
        self.assertTrue(receipt.exists())
        self.assertTrue(journal.exists())

        with self.assertRaisesRegex(ContextOSError, "existing receipt"):
            self.apply(path, proposal)
        self.assertFalse(journal.exists())

    def test_agent_activation_rejects_unknown_unconfigured_and_stale_state(self) -> None:
        with self.assertRaisesRegex(ContextOSError, "missing runtime manifest"):
            create_agent_activation_proposal(self.root, "missing", True, NOW)
        with self.assertRaisesRegex(ContextOSError, "requires contextos.workspace.json"):
            create_agent_activation_proposal(self.root, "claude", True, NOW)

        path, proposal = self.propose(("claude",))
        self.apply(path, proposal)
        path, proposal = create_agent_activation_proposal(
            self.root, "codex", True, NOW.replace(second=1)
        )
        assert path is not None and proposal is not None
        config_path = self.root / "contextos.workspace.json"
        current = json.loads(config_path.read_text(encoding="utf-8"))
        current["agents"] = ["claude", "hermes"]
        config_path.write_text(
            json.dumps(current, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        with self.assertRaisesRegex(ContextOSError, "stale"):
            self.apply(path, proposal)

    def test_agent_list_and_cli_alias_report_activation_without_writes(self) -> None:
        path, proposal = self.propose(("claude",))
        self.apply(path, proposal)
        report = agent_list_report(self.root)
        statuses = {item["id"]: item for item in report["agents"]}
        self.assertTrue(statuses["claude"]["enabled"])
        self.assertFalse(statuses["codex"]["enabled"])
        self.assertFalse(statuses["claude"]["locally_registered"])

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                0,
                cli_main([
                    "--root", str(self.root), "agent", "add",
                    "--runtime", "codex", "--now", NOW.replace(second=1).isoformat(),
                ]),
            )
        proposal_report = json.loads(output.getvalue())
        self.assertEqual("agent-enable", proposal_report["operation"])
        self.assertIn("alias", " ".join(proposal_report["notices"]))
        configured = json.loads(
            (self.root / "contextos.workspace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(["claude"], configured["agents"])

        local = self.root / ".context-os"
        (local / "runtime.json").write_text(
            json.dumps({
                "schema_version": 1,
                "runtime": "codex",
                "installed_at": "2026-08-20T12:00:00+00:00",
                "source_manifest_sha256": "a" * 64,
            }),
            encoding="utf-8",
        )
        legacy_report = agent_list_report(self.root)
        legacy_statuses = {item["id"]: item for item in legacy_report["agents"]}
        self.assertTrue(legacy_statuses["codex"]["locally_registered"])
        self.assertEqual("codex", legacy_report["legacy_local_runtime"])

    def test_activation_recovery_rejects_legacy_path_under_enable_operation(self) -> None:
        path, proposal = self.propose()
        backups = {
            safe_repo_path(self.root, item["path"]): (
                safe_repo_path(self.root, item["path"]).read_bytes()
                if safe_repo_path(self.root, item["path"]).exists()
                else None
            )
            for item in proposal["changes"]
        }
        modes = {
            target: target.stat().st_mode & 0o7777 if target.exists() else None
            for target in backups
        }
        receipt = self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json"
        journal = _create_agent_journal(self.root, proposal, backups, modes, receipt)
        manifest = read_json(journal / "journal.json")
        manifest["operation"] = "agent-enable"
        (journal / "journal.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

        with self.assertRaisesRegex(ContextOSError, "path is not recoverable"):
            _recover_pending_agent_journals(self.root)

    def test_exact_digest_tamper_and_unowned_path_fail_before_writes(self) -> None:
        path, proposal = self.propose()
        with self.assertRaisesRegex(ContextOSError, "exactly match"):
            apply_proposal(self.root, path, "wrong", "generic")
        self.assertFalse((self.root / "contextos.workspace.json").exists())

        tampered = read_json(path)
        tampered["changes"][0]["path"] = "AGENTS.md"
        self.resign(path, tampered)
        with self.assertRaisesRegex(ContextOSError, "unowned or component path"):
            apply_proposal(
                self.root, path, tampered["proposal_digest"], "generic"
            )
        self.assertEqual("# Fixture\n", (self.root / "AGENTS.md").read_text())

    def test_crafted_dotdot_proposal_id_cannot_collapse_local_state(self) -> None:
        path, proposal = self.propose()
        sentinel = self.root / ".context-os/receipts/keep.json"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_text("{}\n", encoding="utf-8")
        crafted = path.with_name("...json")
        path.rename(crafted)
        proposal["proposal_id"] = ".."
        self.resign(crafted, proposal)

        with self.assertRaisesRegex(ContextOSError, "proposal_id has an invalid format"):
            self.apply(crafted, proposal)
        self.assertEqual("{}\n", sentinel.read_text(encoding="utf-8"))
        self.assertTrue(crafted.exists())

    def test_agent_change_reports_directory_target_as_context_error(self) -> None:
        target = self.root / "contextos.workspace.json"
        target.mkdir()
        with self.assertRaisesRegex(ContextOSError, "regular file"):
            _agent_change(
                self.root,
                "workspace-migrate",
                "contextos.workspace.json",
                action="write",
                after_text="{}\n",
            )

    def test_raw_target_and_source_staleness_fail_closed(self) -> None:
        path, proposal = self.propose(("claude",))
        legacy = self.root / "workspace.yaml"
        legacy.write_bytes(legacy.read_bytes().replace(b"\n", b"\r\n"))
        with self.assertRaisesRegex(ContextOSError, "target changed"):
            self.apply(path, proposal)

        legacy.write_text("state_dir: state\n", encoding="utf-8", newline="\n")
        path, proposal = create_workspace_migration_proposal(
            self.root, ("claude",), NOW.replace(second=2)
        )
        self.assertIsNotNone(path)
        self.assertIsNotNone(proposal)
        source = self.root / "components/manifest.json"
        source.write_bytes(source.read_bytes() + b" ")
        with self.assertRaisesRegex(ContextOSError, "source changed"):
            self.apply(path, proposal)

    def test_shared_lock_and_concurrent_apply_allow_at_most_one_writer(self) -> None:
        path, proposal = self.propose()
        entered = threading.Event()
        release = threading.Event()
        original = _create_agent_journal

        def delayed(*args, **kwargs):
            result = original(*args, **kwargs)
            entered.set()
            self.assertTrue(release.wait(timeout=5))
            return result

        with mock.patch("contextos.kernel._create_agent_journal", side_effect=delayed):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(self.apply, path, proposal)
                self.assertTrue(entered.wait(timeout=5))
                second = pool.submit(self.apply, path, proposal)
                with self.assertRaisesRegex(ContextOSError, "apply is active"):
                    second.result(timeout=5)
                release.set()
                first.result(timeout=5)
        self.assertTrue((self.root / "contextos.workspace.json").is_file())

    def test_delete_failure_rolls_back_exact_bytes_and_cleans_artifacts(self) -> None:
        legacy = self.root / "workspace.yaml"
        original = b"state_dir: custom-state\r\n"
        legacy.write_bytes(original)
        protected = (self.root / "AGENTS.md").read_bytes()
        path, proposal = self.propose()
        original_replace = os.replace

        def fail_legacy(source, destination, *args, **kwargs):
            if Path(source) == legacy.resolve():
                raise OSError("injected delete failure")
            return original_replace(source, destination, *args, **kwargs)

        with mock.patch("contextos.kernel.os.replace", side_effect=fail_legacy):
            with self.assertRaisesRegex(ContextOSError, "rolled back"):
                self.apply(path, proposal)
        self.assertFalse((self.root / "contextos.workspace.json").exists())
        self.assertEqual(original, legacy.read_bytes())
        self.assertEqual(protected, (self.root / "AGENTS.md").read_bytes())
        self.assert_no_transaction_artifacts()

    def test_rollback_preserves_unrecognized_concurrent_target_bytes(self) -> None:
        legacy = self.root / "workspace.yaml"
        path, proposal = self.propose()
        target = self.root / "contextos.workspace.json"
        concurrent = b"concurrent user bytes\n"
        original_replace = os.replace

        def race_then_fail(source, destination, *args, **kwargs):
            if Path(source) == legacy.resolve():
                target.write_bytes(concurrent)
                raise OSError("injected delete failure after concurrent write")
            return original_replace(source, destination, *args, **kwargs)

        with mock.patch("contextos.kernel.os.replace", side_effect=race_then_fail):
            with self.assertRaisesRegex(ContextOSError, "rollback was incomplete"):
                self.apply(path, proposal)
        self.assertEqual(concurrent, target.read_bytes())
        self.assertTrue(legacy.exists())
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        self.assertTrue(journal.is_dir())

    def test_rollback_move_does_not_clobber_a_late_path_racer(self) -> None:
        legacy = self.root / "workspace.yaml"
        path, proposal = self.propose()
        target = self.root / "contextos.workspace.json"
        concurrent = b"late concurrent user bytes\n"
        original_replace = os.replace
        original_read_bytes = Path.read_bytes

        def fail_legacy(source, destination, *args, **kwargs):
            if Path(source) == legacy.resolve():
                raise OSError("force rollback after first publication")
            return original_replace(source, destination, *args, **kwargs)

        def race_after_capture_read(candidate: Path):
            content = original_read_bytes(candidate)
            if candidate.name.endswith(".current") and candidate.parent.name == "rollback":
                target.write_bytes(concurrent)
            return content

        with mock.patch("contextos.kernel.os.replace", side_effect=fail_legacy), mock.patch(
            "pathlib.Path.read_bytes", autospec=True, side_effect=race_after_capture_read
        ):
            with self.assertRaisesRegex(ContextOSError, "rollback was incomplete"):
                self.apply(path, proposal)
        self.assertEqual(concurrent, target.read_bytes())
        self.assertTrue(legacy.exists())
        self.assertTrue(
            (self.root / ".context-os/journals" / proposal["proposal_id"]).is_dir()
        )

    def test_rollback_and_recovery_preserve_a_non_file_racer(self) -> None:
        legacy = self.root / "workspace.yaml"
        path, proposal = self.propose()
        target = self.root / "contextos.workspace.json"
        original_replace = os.replace

        def install_directory_racer(source, destination, *args, **kwargs):
            if Path(source) == legacy.resolve():
                target.unlink()
                target.mkdir()
                (target / "racer.txt").write_text("preserve me\n", encoding="utf-8")
                raise OSError("force rollback with a directory racer")
            return original_replace(source, destination, *args, **kwargs)

        with mock.patch(
            "contextos.kernel.os.replace", side_effect=install_directory_racer
        ):
            with self.assertRaisesRegex(ContextOSError, "rollback was incomplete"):
                self.apply(path, proposal)
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        self.assertEqual(
            "preserve me\n",
            (target / "racer.txt").read_text(encoding="utf-8"),
        )
        self.assertTrue(journal.is_dir())

        with self.assertRaisesRegex(ContextOSError, "non-file target"):
            self.apply(path, proposal)
        self.assertEqual(
            "preserve me\n",
            (target / "racer.txt").read_text(encoding="utf-8"),
        )
        self.assertTrue(journal.is_dir())

    def test_captured_late_non_file_racer_survives_recovery_retry(self) -> None:
        legacy = self.root / "workspace.yaml"
        path, proposal = self.propose()
        target = self.root / "contextos.workspace.json"
        legacy_resolved = legacy.resolve()
        target_resolved = target.resolve()
        original_replace = os.replace

        def race_during_capture(source, destination, *args, **kwargs):
            source_path = Path(source).resolve()
            destination_path = Path(destination).resolve()
            if source_path == legacy_resolved:
                raise OSError("force rollback after first publication")
            if (
                source_path == target_resolved
                and destination_path.name.endswith(".current")
            ):
                target.unlink()
                target.mkdir()
                (target / "racer.txt").write_text("captured\n", encoding="utf-8")
            return original_replace(source, destination, *args, **kwargs)

        with mock.patch(
            "contextos.kernel.os.replace", side_effect=race_during_capture
        ):
            with self.assertRaisesRegex(ContextOSError, "rollback was incomplete"):
                self.apply(path, proposal)
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        capture_dir = next((journal / "rollback").glob("*.current"))
        captured = capture_dir / "racer.txt"
        self.assertEqual("captured\n", captured.read_text(encoding="utf-8"))
        self.assertFalse(target.exists())

        with self.assertRaisesRegex(ContextOSError, "rollback capture is link-like or non-file"):
            self.apply(path, proposal)
        self.assertEqual("captured\n", captured.read_text(encoding="utf-8"))
        self.assertTrue(journal.is_dir())

    def test_recovery_resumes_a_durable_regular_capture(self) -> None:
        legacy = self.root / "workspace.yaml"
        legacy_before = legacy.read_bytes()
        path, proposal = self.propose()
        backups = {
            safe_repo_path(self.root, item["path"]): (
                safe_repo_path(self.root, item["path"]).read_bytes()
                if safe_repo_path(self.root, item["path"]).exists()
                else None
            )
            for item in proposal["changes"]
        }
        modes = {
            target: target.stat().st_mode & 0o7777 if target.exists() else None
            for target in backups
        }
        receipt = self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json"
        journal = _create_agent_journal(self.root, proposal, backups, modes, receipt)
        target = self.root / "contextos.workspace.json"
        target.write_bytes(proposal["changes"][0]["after_text"].encode("utf-8"))
        _prepare_publication_anchor(
            self.root,
            journal,
            target,
            slot=_transaction_slot(0, "contextos.workspace.json"),
            expected_hash=proposal["changes"][0]["after_raw_sha256"],
        )
        legacy.unlink()
        rollback = journal / "rollback"
        rollback.mkdir()
        slot = _transaction_slot(0, "contextos.workspace.json")
        capture = rollback / f"{slot}.current"
        os.replace(target, capture)
        _fsync_directory(capture.parent)
        _fsync_directory(target.parent)

        _recover_pending_agent_journals(self.root)

        self.assertFalse(target.exists())
        self.assertEqual(legacy_before, legacy.read_bytes())
        self.assertFalse(journal.exists())
        receipt_path, _ = self.apply(path, proposal)
        self.assertTrue(receipt_path.is_file())
        self.assertFalse(legacy.exists())

    def test_journal_slot_identity_mismatch_fails_closed(self) -> None:
        path, proposal = self.propose()
        backups = {
            safe_repo_path(self.root, item["path"]): (
                safe_repo_path(self.root, item["path"]).read_bytes()
                if safe_repo_path(self.root, item["path"]).exists()
                else None
            )
            for item in proposal["changes"]
        }
        modes = {
            target: target.stat().st_mode & 0o7777 if target.exists() else None
            for target in backups
        }
        legacy_before = (self.root / "workspace.yaml").read_bytes()
        receipt = self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json"
        journal = _create_agent_journal(self.root, proposal, backups, modes, receipt)
        manifest = read_json(journal / "journal.json")
        manifest["entries"][1]["slot"] = manifest["entries"][0]["slot"]
        (journal / "journal.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

        with self.assertRaisesRegex(ContextOSError, "slot identity mismatch"):
            _recover_pending_agent_journals(self.root)
        self.assertFalse((self.root / "contextos.workspace.json").exists())
        self.assertEqual(legacy_before, (self.root / "workspace.yaml").read_bytes())
        self.assertTrue(journal.is_dir())

    def test_recovery_preserves_different_inode_target_capture_ambiguity(self) -> None:
        path, proposal = self.propose()
        backups = {
            safe_repo_path(self.root, item["path"]): (
                safe_repo_path(self.root, item["path"]).read_bytes()
                if safe_repo_path(self.root, item["path"]).exists()
                else None
            )
            for item in proposal["changes"]
        }
        modes = {
            target: target.stat().st_mode & 0o7777 if target.exists() else None
            for target in backups
        }
        receipt = self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json"
        journal = _create_agent_journal(self.root, proposal, backups, modes, receipt)
        target = self.root / "contextos.workspace.json"
        after = proposal["changes"][0]["after_text"].encode("utf-8")
        target.write_bytes(after)
        rollback = journal / "rollback"
        rollback.mkdir()
        capture = rollback / f"{_transaction_slot(0, 'contextos.workspace.json')}.current"
        capture.write_bytes(after)
        self.assertFalse(os.path.samefile(target, capture))

        with self.assertRaisesRegex(ContextOSError, "target/capture ambiguity"):
            _recover_pending_agent_journals(self.root)
        self.assertEqual(after, target.read_bytes())
        self.assertEqual(after, capture.read_bytes())
        self.assertTrue(journal.is_dir())

    def test_recovery_cleans_a_redundant_same_inode_capture(self) -> None:
        path, proposal = self.propose()
        backups = {
            safe_repo_path(self.root, item["path"]): (
                safe_repo_path(self.root, item["path"]).read_bytes()
                if safe_repo_path(self.root, item["path"]).exists()
                else None
            )
            for item in proposal["changes"]
        }
        modes = {
            target: target.stat().st_mode & 0o7777 if target.exists() else None
            for target in backups
        }
        legacy = self.root / "workspace.yaml"
        before = legacy.read_bytes()
        receipt = self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json"
        journal = _create_agent_journal(self.root, proposal, backups, modes, receipt)
        rollback = journal / "rollback"
        rollback.mkdir()
        capture = rollback / f"{_transaction_slot(1, 'workspace.yaml')}.current"
        os.link(legacy, capture)
        self.assertTrue(os.path.samefile(legacy, capture))

        _recover_pending_agent_journals(self.root)

        self.assertEqual(before, legacy.read_bytes())
        self.assertFalse(journal.exists())

    def test_receipt_failure_rolls_back_mixed_transaction(self) -> None:
        legacy = self.root / "workspace.yaml"
        original = b"state_dir: state\n"
        legacy.write_bytes(original)
        path, proposal = self.propose()
        original_link = os.link

        def fail_receipt(source, destination, *args, **kwargs):
            if Path(destination).parent.name == "receipts":
                raise OSError("injected receipt failure")
            return original_link(source, destination, *args, **kwargs)

        with mock.patch("contextos.kernel.os.link", side_effect=fail_receipt):
            with self.assertRaisesRegex(ContextOSError, "rolled back"):
                self.apply(path, proposal)
        self.assertFalse((self.root / "contextos.workspace.json").exists())
        self.assertEqual(original, legacy.read_bytes())
        self.assert_no_transaction_artifacts()

    def test_durable_journal_recovers_partial_crash_before_reapply(self) -> None:
        legacy = self.root / "workspace.yaml"
        legacy_bytes = b"state_dir: state\n"
        legacy.write_bytes(legacy_bytes)
        path, proposal = self.propose()
        changes = proposal["changes"]
        backups = {
            safe_repo_path(self.root, item["path"]): (
                safe_repo_path(self.root, item["path"]).read_bytes()
                if safe_repo_path(self.root, item["path"]).exists()
                else None
            )
            for item in changes
        }
        modes = {
            target: target.stat().st_mode & 0o7777 if target.exists() else None
            for target in backups
        }
        receipt = self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json"
        journal = _create_agent_journal(self.root, proposal, backups, modes, receipt)
        target = self.root / "contextos.workspace.json"
        target.write_bytes(
            changes[0]["after_text"].encode("utf-8")
        )
        _prepare_publication_anchor(
            self.root,
            journal,
            target,
            slot=_transaction_slot(0, "contextos.workspace.json"),
            expected_hash=changes[0]["after_raw_sha256"],
        )
        legacy.unlink()

        lock = self.root / ".context-os/apply.lock"
        lock.write_text("pid=999999\n", encoding="utf-8")
        with self.assertRaisesRegex(ContextOSError, "stale lock"):
            self.apply(path, proposal)
        lock.unlink()

        self.apply(path, proposal)
        self.assertFalse(legacy.exists())
        self.assertTrue((self.root / "contextos.workspace.json").exists())
        self.assertFalse((self.root / ".context-os/journals" / proposal["proposal_id"]).exists())

    def test_resigned_diff_and_invariant_claims_are_rejected(self) -> None:
        path, proposal = self.propose()
        proposal["changes"][0]["diff"] = ""
        self.resign(path, proposal)
        with self.assertRaisesRegex(ContextOSError, "displayed diff"):
            self.apply(path, proposal)

        path.unlink()
        path, proposal = self.propose()
        proposal["invariants"] = ["everything-is-fine"]
        self.resign(path, proposal)
        with self.assertRaisesRegex(ContextOSError, "invariants are invalid"):
            self.apply(path, proposal)

    def test_sources_are_revalidated_after_journal_construction(self) -> None:
        path, proposal = self.propose()
        source = self.root / "components/manifest.json"
        original = _create_agent_journal

        def mutate_after_journal(*args, **kwargs):
            result = original(*args, **kwargs)
            source.write_bytes(source.read_bytes() + b" ")
            return result

        with mock.patch(
            "contextos.kernel._create_agent_journal",
            side_effect=mutate_after_journal,
        ):
            with self.assertRaisesRegex(ContextOSError, "source changed"):
                self.apply(path, proposal)
        self.assertFalse((self.root / "contextos.workspace.json").exists())
        self.assertTrue((self.root / "workspace.yaml").exists())
        self.assert_no_transaction_artifacts()

    def test_post_write_verification_failure_rolls_back(self) -> None:
        path, proposal = self.propose()
        target = self.root / "contextos.workspace.json"
        target_resolved = target.resolve()
        original = raw_file_digest

        def fail_after_publish(candidate: Path):
            if Path(candidate).resolve() == target_resolved and candidate.exists():
                raise OSError("injected post-write hash failure")
            return original(candidate)

        with mock.patch(
            "contextos.kernel.raw_file_digest", side_effect=fail_after_publish
        ):
            with self.assertRaisesRegex(ContextOSError, "rolled back"):
                self.apply(path, proposal)
        self.assertFalse(target.exists())
        self.assertTrue((self.root / "workspace.yaml").exists())
        self.assert_no_transaction_artifacts()

    def test_agent_post_write_snapshot_rejects_inode_swap(self) -> None:
        path, proposal = self.propose()
        target = self.root / "contextos.workspace.json"
        target_resolved = target.resolve()
        real_publish = _publish_exclusive
        armed = False
        raced = False

        def arm_after_publish(source, destination):
            nonlocal armed
            result = real_publish(source, destination)
            if Path(destination) == target_resolved:
                armed = True
            return result

        real_samestat = os.path.samestat

        def reject_published_path_identity(left, right):
            nonlocal raced
            if (
                armed
                and not raced
                and real_samestat(right, target_resolved.stat())
            ):
                raced = True
                return False
            return real_samestat(left, right)

        with mock.patch(
            "contextos.kernel._publish_exclusive", side_effect=arm_after_publish
        ), mock.patch(
            "contextos.kernel.os.path.samestat",
            side_effect=reject_published_path_identity,
        ):
            with self.assertRaisesRegex(ContextOSError, "rolled back"):
                self.apply(path, proposal)
        self.assertTrue(raced)
        self.assertFalse(target.exists())
        self.assertTrue((self.root / "workspace.yaml").exists())
        self.assertFalse(
            (self.root / ".context-os/journals" / proposal["proposal_id"]).exists()
        )
        self.assertFalse(
            (self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json").exists()
        )

    def test_receipt_publication_never_overwrites_a_racer(self) -> None:
        path, proposal = self.propose()
        receipt = self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json"
        receipt_resolved = receipt.resolve()
        original = os.link

        def race_receipt(source, destination, *args, **kwargs):
            if Path(destination).resolve() == receipt_resolved:
                receipt.write_text("{}\n", encoding="utf-8")
            return original(source, destination, *args, **kwargs)

        with mock.patch("contextos.kernel.os.link", side_effect=race_receipt):
            with self.assertRaisesRegex(ContextOSError, "concurrently created path"):
                self.apply(path, proposal)
        self.assertEqual("{}\n", receipt.read_text(encoding="utf-8"))
        self.assertFalse((self.root / "contextos.workspace.json").exists())
        self.assertTrue((self.root / "workspace.yaml").exists())

    def test_receipt_replacement_before_directory_sync_is_not_committed(self) -> None:
        path, proposal = self.propose()
        receipt = self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json"
        receipt_parent_resolved = receipt.parent.resolve()
        real_sync = _fsync_directory
        replaced = False

        def replace_before_sync(directory: Path):
            nonlocal replaced
            if (
                Path(directory).resolve() == receipt_parent_resolved
                and receipt.is_file()
                and not replaced
            ):
                replacement = receipt.with_suffix(".replacement")
                replacement.write_text("{}\n", encoding="utf-8")
                os.replace(replacement, receipt)
                replaced = True
            return real_sync(directory)

        with mock.patch(
            "contextos.kernel._fsync_directory", side_effect=replace_before_sync
        ):
            with self.assertRaisesRegex(ContextOSError, "receipt changed"):
                self.apply(path, proposal)
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        self.assertEqual("{}\n", receipt.read_text(encoding="utf-8"))
        self.assertTrue(journal.is_dir())
        self.assertTrue((self.root / "contextos.workspace.json").is_file())
        self.assertFalse((self.root / "workspace.yaml").exists())

    def test_recovery_rejects_a_receipt_replaced_after_commit(self) -> None:
        path, proposal = self.propose()
        with mock.patch(
            "contextos.kernel._discard_agent_journal",
            side_effect=OSError("retain committed journal"),
        ):
            receipt, _ = self.apply(path, proposal)
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        equivalent = json.dumps(read_json(receipt), separators=(",", ":")) + "\n"
        replacement = receipt.with_suffix(".replacement")
        replacement.write_text(equivalent, encoding="utf-8")
        os.replace(replacement, receipt)

        with self.assertRaisesRegex(ContextOSError, "durable anchor"):
            _recover_pending_agent_journals(self.root)
        self.assertTrue(journal.is_dir())
        self.assertTrue(receipt.is_file())

    def test_publication_fails_closed_when_hard_links_are_unsupported(self) -> None:
        path, proposal = self.propose()
        with mock.patch(
            "contextos.kernel.os.link",
            side_effect=OSError("hard links unavailable"),
        ):
            with self.assertRaisesRegex(ContextOSError, "atomic no-clobber publication"):
                self.apply(path, proposal)
        self.assertFalse((self.root / "contextos.workspace.json").exists())
        self.assertTrue((self.root / "workspace.yaml").exists())
        self.assert_no_transaction_artifacts()

    def test_transient_link_failure_retains_then_recovers_forward_capture(self) -> None:
        target = self.root / "contextos.workspace.json"
        legacy = self.root / "workspace.yaml"
        before = legacy.read_bytes()
        _, seed = self.propose()
        target.write_text(
            json.dumps(json.loads(seed["changes"][0]["after_text"]), separators=(",", ":")),
            encoding="utf-8",
        )
        target_before = target.read_bytes()
        path, proposal = self.propose()
        self.assertIsNotNone(proposal["changes"][0]["before_raw_sha256"])
        original_link = os.link
        target_failures = 0

        def fail_forward_and_first_restore(source, destination, *args, **kwargs):
            nonlocal target_failures
            if Path(destination) == target.resolve() and target_failures < 2:
                target_failures += 1
                raise OSError("transient link failure")
            return original_link(source, destination, *args, **kwargs)

        with mock.patch(
            "contextos.kernel.os.link", side_effect=fail_forward_and_first_restore
        ):
            with self.assertRaisesRegex(ContextOSError, "rollback was incomplete"):
                self.apply(path, proposal)
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        self.assertFalse(target.exists())
        self.assertTrue(journal.is_dir())

        _recover_pending_agent_journals(self.root)

        self.assertEqual(target_before, target.read_bytes())
        self.assertEqual(before, legacy.read_bytes())
        self.assertFalse(journal.exists())

    def test_target_publication_never_removes_a_racers_file(self) -> None:
        path, proposal = self.propose()
        target = self.root / "contextos.workspace.json"
        original = os.link

        def race_target(source, destination, *args, **kwargs):
            if Path(destination) == target.resolve():
                target.write_bytes(b"concurrent user bytes\n")
            return original(source, destination, *args, **kwargs)

        with mock.patch("contextos.kernel.os.link", side_effect=race_target):
            with self.assertRaisesRegex(ContextOSError, "concurrently created path"):
                self.apply(path, proposal)
        self.assertEqual(b"concurrent user bytes\n", target.read_bytes())
        self.assertTrue((self.root / "workspace.yaml").exists())

    def test_target_publication_never_claims_equal_bytes_from_a_racer(self) -> None:
        path, proposal = self.propose()
        target = self.root / "contextos.workspace.json"
        original = os.link
        raced_identity = None

        def race_target(source, destination, *args, **kwargs):
            nonlocal raced_identity
            if Path(destination) == target.resolve():
                target.write_bytes(Path(source).read_bytes())
                metadata = target.stat()
                raced_identity = (metadata.st_dev, metadata.st_ino)
            return original(source, destination, *args, **kwargs)

        with mock.patch("contextos.kernel.os.link", side_effect=race_target):
            with self.assertRaisesRegex(ContextOSError, "rollback was incomplete"):
                self.apply(path, proposal)
        metadata = target.stat()
        self.assertEqual(raced_identity, (metadata.st_dev, metadata.st_ino))
        self.assertEqual(
            proposal["changes"][0]["after_text"].encode("utf-8"),
            target.read_bytes(),
        )
        self.assertTrue((self.root / "workspace.yaml").exists())
        self.assertTrue(
            (self.root / ".context-os/journals" / proposal["proposal_id"]).is_dir()
        )
        self.assertFalse(
            (self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json").exists()
        )

    def test_delete_capture_preserves_a_racers_bytes(self) -> None:
        path, proposal = self.propose()
        legacy = self.root / "workspace.yaml"
        concurrent = b"state_dir: concurrent-state\n"
        original = os.replace

        def race_delete(source, destination, *args, **kwargs):
            if (
                Path(source) == legacy.resolve()
                and Path(destination).parent.name == "forward"
            ):
                legacy.write_bytes(concurrent)
            return original(source, destination, *args, **kwargs)

        with mock.patch("contextos.kernel.os.replace", side_effect=race_delete):
            with self.assertRaisesRegex(ContextOSError, "forward capture"):
                self.apply(path, proposal)
        self.assertEqual(concurrent, legacy.read_bytes())
        self.assertFalse((self.root / "contextos.workspace.json").exists())

    def test_incomplete_journal_build_is_discarded_before_mutation(self) -> None:
        path, proposal = self.propose()
        building = (
            self.root
            / ".context-os/journals"
            / f".{proposal['proposal_id']}.building"
        )
        (building / "backups").mkdir(parents=True)
        (building / "backups/0.bin").write_bytes(b"partial")

        self.apply(path, proposal)
        self.assertFalse(building.exists())
        self.assertTrue((self.root / "contextos.workspace.json").exists())

    def test_proposal_json_rejects_duplicates_constants_and_boolean_version(self) -> None:
        path, proposal = self.propose()
        raw = path.read_text(encoding="utf-8")
        path.write_text(
            raw.replace(
                '"schema_version": 1,',
                '"schema_version": 1, "schema_version": 1,',
                1,
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ContextOSError, "duplicate JSON object key"):
            self.apply(path, proposal)

        path.unlink()
        path, proposal = self.propose()
        proposal["schema_version"] = True
        self.resign(path, proposal)
        with self.assertRaisesRegex(ContextOSError, "unsupported schema version"):
            apply_proposal(self.root, path, proposal["proposal_digest"], "generic")

        path.unlink()
        path, proposal = self.propose()
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                '"created_at":', '"extra_constant": NaN, "created_at":', 1
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ContextOSError, "JSON constant"):
            self.apply(path, proposal)

    def test_post_receipt_cleanup_failure_keeps_committed_state(self) -> None:
        path, proposal = self.propose()
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        with mock.patch(
            "contextos.kernel._discard_agent_journal",
            side_effect=OSError("injected cleanup failure"),
        ):
            receipt_path, _ = self.apply(path, proposal)
        self.assertTrue(receipt_path.exists())
        self.assertTrue(journal.exists())
        self.assertTrue((self.root / "contextos.workspace.json").exists())
        self.assertFalse((self.root / "workspace.yaml").exists())

        journal_check = next(
            check
            for check in doctor(self.root)["checks"]
            if check["name"] == "transaction-journals"
        )
        self.assertEqual("warn", journal_check["status"])
        with self.assertRaisesRegex(ContextOSError, "existing receipt"):
            self.apply(path, proposal)
        self.assertFalse(journal.exists())

    def test_publication_preserves_existing_modes_and_uses_safe_defaults(self) -> None:
        target = self.root / "sessions/2026-08-25.md"
        target.write_text(
            "# Session — 2026-08-25\n\n## Update: 10:00\n- Began\n",
            encoding="utf-8",
        )
        modes = (0o444, 0o600, 0o640, 0o644) if os.name != "nt" else (0o444, 0o666)
        for index, expected_mode in enumerate(modes):
            with self.subTest(mode=oct(expected_mode)):
                os.chmod(target, expected_mode)
                path, proposal = create_proposal(
                    self.root,
                    "update",
                    {"progress": [f"Mode pass {index}"]},
                    NOW,
                )
                receipt, _ = self.apply(path, proposal)
                self.assertIn(
                    "sessions/2026-08-25.md",
                    [change["path"] for change in proposal["changes"]],
                )
                actual_mode = target.stat().st_mode & 0o7777
                if os.name == "nt":
                    self.assertEqual(
                        bool(expected_mode & 0o200), bool(actual_mode & 0o200)
                    )
                else:
                    self.assertEqual(expected_mode, actual_mode)
                    self.assertEqual(0o600, receipt.stat().st_mode & 0o7777)
        if os.name != "nt":
            self.assertEqual(expected_mode, target.stat().st_mode & 0o7777)
        self.assertEqual(0, target.stat().st_mode & 0o111)

    def test_readonly_hardlink_unlink_preserves_surviving_inode_mode(self) -> None:
        survivor = self.root / "state/current.md"
        survivor.write_bytes(b"shared inode\n")
        artifact = self.root / ".context-os/readonly-artifact"
        artifact.parent.mkdir()
        os.link(survivor, artifact)
        os.chmod(survivor, 0o444)

        with mock.patch(
            "contextos.kernel.os.chmod",
            side_effect=AssertionError("shared-inode cleanup must not chmod"),
        ):
            _unlink_readonly_artifact(artifact)

        self.assertFalse(artifact.exists())
        self.assertEqual(b"shared inode\n", survivor.read_bytes())
        if os.name == "nt":
            self.assertFalse(survivor.stat().st_mode & 0o200)
        else:
            self.assertEqual(0o444, survivor.stat().st_mode & 0o7777)

    @unittest.skipUnless(os.name == "nt", "Windows read-only fallback")
    def test_readonly_single_link_uses_safe_unsupported_api_fallback(self) -> None:
        artifact = self.root / ".context-os/single-readonly-artifact"
        artifact.parent.mkdir()
        artifact.write_bytes(b"single inode\n")
        os.chmod(artifact, 0o444)

        with mock.patch(
            "contextos.kernel._windows_unlink_readonly",
            side_effect=ctypes.WinError(87),
        ):
            _unlink_readonly_artifact(artifact)

        self.assertFalse(artifact.exists())

    @unittest.skipUnless(os.name == "nt", "Windows read-only fallback")
    def test_readonly_shared_inode_fails_cleanly_when_api_is_unsupported(self) -> None:
        survivor = self.root / "state/current.md"
        survivor.write_bytes(b"shared fallback inode\n")
        artifact = self.root / ".context-os/shared-readonly-artifact"
        artifact.parent.mkdir()
        os.link(survivor, artifact)
        os.chmod(survivor, 0o444)

        with mock.patch(
            "contextos.kernel._windows_unlink_readonly",
            side_effect=ctypes.WinError(87),
        ), self.assertRaisesRegex(ContextOSError, "shared inode"):
            _unlink_readonly_artifact(artifact)

        self.assertTrue(artifact.exists())
        self.assertEqual(b"shared fallback inode\n", survivor.read_bytes())
        self.assertFalse(survivor.stat().st_mode & 0o200)

    @unittest.skipUnless(os.name == "nt", "Windows read-only fallback")
    def test_readonly_sharing_violation_never_enters_chmod_fallback(self) -> None:
        artifact = self.root / ".context-os/sharing-violation-artifact"
        artifact.parent.mkdir()
        artifact.write_bytes(b"held inode\n")
        os.chmod(artifact, 0o444)

        with mock.patch(
            "contextos.kernel._windows_unlink_readonly",
            side_effect=ctypes.WinError(32),
        ), mock.patch(
            "contextos.kernel.os.chmod",
            side_effect=AssertionError("sharing violations must not chmod"),
        ), self.assertRaisesRegex(ContextOSError, "cannot atomically remove"):
            _unlink_readonly_artifact(artifact)

        self.assertTrue(artifact.exists())
        self.assertFalse(artifact.stat().st_mode & 0o200)

    @unittest.skipUnless(os.name == "nt", "Windows read-only fallback")
    def test_readonly_tree_uses_safe_single_link_unsupported_api_fallback(self) -> None:
        tree = self.root / ".context-os/staging/unsupported-tree"
        artifact = tree / "artifact"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"single tree inode\n")
        os.chmod(artifact, 0o444)

        with mock.patch(
            "contextos.kernel._windows_unlink_readonly",
            side_effect=ctypes.WinError(87),
        ):
            _rmtree_readonly_artifacts(tree)

        self.assertFalse(tree.exists())

    @unittest.skipUnless(os.name == "nt", "Windows read-only fallback")
    def test_readonly_tree_best_effort_suppresses_sharing_violation(self) -> None:
        tree = self.root / ".context-os/staging/held-tree"
        artifact = tree / "artifact"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"held tree inode\n")
        os.chmod(artifact, 0o444)

        with mock.patch(
            "contextos.kernel._windows_unlink_readonly",
            side_effect=ctypes.WinError(32),
        ), mock.patch(
            "contextos.kernel.os.chmod",
            side_effect=AssertionError("sharing violations must not chmod"),
        ):
            _rmtree_readonly_artifacts(tree, ignore_errors=True)

        self.assertTrue(artifact.exists())
        self.assertFalse(artifact.stat().st_mode & 0o200)

    def test_readonly_hardlink_tree_cleanup_preserves_workspace_mode(self) -> None:
        survivor = self.root / "state/current.md"
        survivor.write_bytes(b"shared tree inode\n")
        tree = self.root / ".context-os/staging/readonly-tree"
        artifact = tree / "state/current.md"
        artifact.parent.mkdir(parents=True)
        os.link(survivor, artifact)
        os.chmod(survivor, 0o444)

        _rmtree_readonly_artifacts(tree)

        self.assertFalse(tree.exists())
        self.assertEqual(b"shared tree inode\n", survivor.read_bytes())
        if os.name == "nt":
            self.assertFalse(survivor.stat().st_mode & 0o200)
        else:
            self.assertEqual(0o444, survivor.stat().st_mode & 0o7777)

    def _assert_restore_build_crash_recovers(self, crash_stage: str) -> None:
        before = b"before-state\n"
        after = b"after-state\n"
        mode = (
            0o444
            if crash_stage == "publish"
            else 0o640
            if os.name != "nt"
            else 0o666
        )
        target = self.root / "state/current.md"
        journal = self.root / ".context-os/journals/recovery-fixture"
        work_dir = journal / "rollback"
        anchor = journal / "publications/0000-fixture.after"
        work_dir.mkdir(parents=True)
        anchor.parent.mkdir()
        anchor.write_bytes(after)
        os.chmod(anchor, mode)
        capture = work_dir / "0000-fixture.current"
        os.link(anchor, capture)
        script = r'''
import os
import sys
from pathlib import Path
from unittest import mock
import contextos.kernel as kernel

root = Path(sys.argv[1])
target = Path(sys.argv[2])
anchor = Path(sys.argv[3])
work_dir = Path(sys.argv[4])
crash_stage = sys.argv[5]
mode = int(sys.argv[6], 8)
before = b"before-state\n"
after = b"after-state\n"
real_write = kernel._write_exclusive_bytes
real_publish = kernel._publish_exclusive

def crash_write(path, content, **kwargs):
    candidate = Path(path)
    if crash_stage == "write" and candidate.name.endswith(".before.building"):
        descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, content[: max(1, len(content) // 2)])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os._exit(88)
    return real_write(path, content, **kwargs)

def crash_mode(*args, **kwargs):
    if crash_stage == "chmod":
        os._exit(89)

def crash_publish(source, destination):
    result = real_publish(source, destination)
    if crash_stage == "publish" and Path(destination).name.endswith(".before"):
        os._exit(90)
    return result

mode_patch = (
    mock.patch("contextos.kernel.os.fchmod", side_effect=crash_mode)
    if os.name != "nt" and hasattr(os, "fchmod")
    else mock.patch("contextos.kernel.os.chmod", side_effect=crash_mode)
)
with mock.patch("contextos.kernel._write_exclusive_bytes", side_effect=crash_write), \
     mock.patch("contextos.kernel._publish_exclusive", side_effect=crash_publish), \
     mode_patch:
    kernel._restore_transaction_target(
        root,
        target,
        before,
        mode,
        kernel.sha256_bytes(after),
        anchor,
        work_dir=work_dir,
        slot="0000-fixture",
    )
'''
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(self.root),
                str(target),
                str(anchor),
                str(work_dir),
                crash_stage,
                oct(mode),
            ],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(
            {"write": 88, "chmod": 89, "publish": 90}[crash_stage],
            result.returncode,
            [path.relative_to(journal).as_posix() for path in journal.rglob("*")]
            if journal.exists()
            else "journal was retired",
        )
        building = list((journal / "rollback").glob(".*.before.building"))
        self.assertEqual(1, len(building))

        _restore_transaction_target(
            self.root,
            target,
            before,
            mode,
            sha256_bytes(after),
            anchor,
            work_dir=work_dir,
            slot="0000-fixture",
        )

        self.assertEqual(before, target.read_bytes())
        self.assertEqual(mode, target.stat().st_mode & 0o7777)
        self.assertFalse(building[0].exists())
        self.assertFalse(capture.exists())

    def test_process_death_during_restore_bytes_is_resumable(self) -> None:
        self._assert_restore_build_crash_recovers("write")

    def test_process_death_before_restore_chmod_is_resumable(self) -> None:
        self._assert_restore_build_crash_recovers("chmod")

    def test_process_death_after_restore_publication_is_resumable(self) -> None:
        self._assert_restore_build_crash_recovers("publish")

    def test_foreign_final_restore_payload_blocks_without_clobbering(self) -> None:
        before = b"before-state\n"
        after = b"after-state\n"
        mode = 0o640 if os.name != "nt" else 0o666
        target = self.root / "state/current.md"
        journal = self.root / ".context-os/journals/recovery-fixture"
        work_dir = journal / "rollback"
        anchor = journal / "publications/0000-fixture.after"
        work_dir.mkdir(parents=True)
        anchor.parent.mkdir()
        anchor.write_bytes(after)
        os.chmod(anchor, mode)
        capture = work_dir / "0000-fixture.current"
        os.link(anchor, capture)
        restore = work_dir / "0000-fixture.before"
        restore.write_bytes(b"foreign\n")

        with self.assertRaisesRegex(ContextOSError, "restore payload mismatch"):
            _restore_transaction_target(
                self.root,
                target,
                before,
                mode,
                sha256_bytes(after),
                anchor,
                work_dir=work_dir,
                slot="0000-fixture",
            )

        self.assertEqual(b"foreign\n", restore.read_bytes())
        self.assertFalse(target.exists())
        self.assertTrue(capture.exists())

    def test_committed_journal_retains_evidence_when_target_is_missing(self) -> None:
        path, proposal = self.propose()
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        with mock.patch(
            "contextos.kernel._discard_agent_journal",
            side_effect=OSError("retain committed journal"),
        ):
            receipt, _ = self.apply(path, proposal)
        target = self.root / "contextos.workspace.json"
        target.unlink()

        with self.assertRaisesRegex(ContextOSError, "restore it from .*publications"):
            _recover_pending_agent_journals(self.root)

        self.assertTrue(receipt.is_file())
        self.assertTrue(journal.is_dir())

    def test_receipt_directory_is_synced_before_journal_retirement(self) -> None:
        path, proposal = self.propose()
        receipt_parent = self.root / ".context-os/receipts"
        events: list[str] = []
        original_sync = _fsync_directory
        original_discard = _discard_agent_journal

        def record_sync(candidate: Path):
            if candidate == receipt_parent:
                events.append("receipt-synced")
            return original_sync(candidate)

        def record_discard(root: Path, journal: Path):
            events.append("journal-retired")
            return original_discard(root, journal)

        with mock.patch("contextos.kernel._fsync_directory", side_effect=record_sync), mock.patch(
            "contextos.kernel._discard_agent_journal", side_effect=record_discard
        ):
            self.apply(path, proposal)
        self.assertLess(events.index("receipt-synced"), events.index("journal-retired"))

    def test_receipt_sync_failure_keeps_committed_state_and_journal(self) -> None:
        path, proposal = self.propose()
        receipt = self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json"
        receipt_parent = receipt.parent
        original_sync = _fsync_directory

        def fail_receipt_sync(candidate: Path):
            if candidate == receipt_parent:
                raise OSError("injected receipt directory sync failure")
            return original_sync(candidate)

        with mock.patch("contextos.kernel._fsync_directory", side_effect=fail_receipt_sync):
            with self.assertRaisesRegex(ContextOSError, "receipt commit point"):
                self.apply(path, proposal)
        self.assertTrue(receipt.is_file())
        self.assertTrue((self.root / "contextos.workspace.json").is_file())
        self.assertFalse((self.root / "workspace.yaml").exists())
        self.assertTrue(
            (self.root / ".context-os/journals" / proposal["proposal_id"]).is_dir()
        )
        _recover_pending_agent_journals(self.root)
        self.assertTrue(receipt.is_file())
        self.assertFalse(
            (self.root / ".context-os/journals" / proposal["proposal_id"]).exists()
        )

    def test_commit_record_without_receipt_rolls_back_after_process_death(self) -> None:
        path, proposal = self.propose()
        legacy = self.root / "workspace.yaml"
        legacy_before = legacy.read_bytes()
        script = r'''
import os
import sys
from pathlib import Path
from unittest import mock
import contextos.kernel as kernel

root = Path(sys.argv[1])
proposal = Path(sys.argv[2])
digest = sys.argv[3]
real_publish = kernel._publish_exclusive

def crash_before_receipt(source, destination):
    if Path(destination).parent.name == "receipts":
        os._exit(88)
    return real_publish(source, destination)

with mock.patch("contextos.kernel._publish_exclusive", side_effect=crash_before_receipt):
    kernel.apply_proposal(root, proposal, digest, "generic")
'''
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(self.root),
                str(path),
                proposal["proposal_digest"],
            ],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(88, result.returncode)
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        self.assertTrue((journal / "commit.json").is_file())
        self.assertTrue((journal / "receipt.anchor").is_file())
        self.assertFalse(
            (self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json").exists()
        )
        (self.root / ".context-os/apply.lock").unlink()

        _recover_pending_agent_journals(self.root)

        self.assertFalse((self.root / "contextos.workspace.json").exists())
        self.assertEqual(legacy_before, legacy.read_bytes())
        self.assertFalse(journal.exists())

    def test_committed_malformed_journal_is_a_clean_recovery_error(self) -> None:
        path, proposal = self.propose()
        receipt_path, _ = self.apply(path, proposal)
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        journal.mkdir(parents=True)
        malformed = {
            "journal_version": 2,
            "schema_version": 1,
            "workflow": "agent-config",
            "operation": "workspace-migrate",
            "created_at": proposal["created_at"],
            "proposal_id": proposal["proposal_id"],
            "proposal_digest": proposal["proposal_digest"],
            "receipt": receipt_path.relative_to(self.root).as_posix(),
            "invariants": proposal["invariants"],
            "agent_evidence": {
                "authorization": proposal["authorization"],
                "source_hashes": proposal["source_hashes"],
            },
            "entries": [{}],
        }
        (journal / "journal.json").write_text(
            json.dumps(malformed), encoding="utf-8"
        )
        next_path, next_proposal = create_workspace_migration_proposal(
            self.root, ("claude",), NOW
        )
        self.assertIsNone(next_path)
        self.assertIsNone(next_proposal)
        with self.assertRaisesRegex(ContextOSError, "invalid journal entry"):
            apply_proposal(self.root, path, proposal["proposal_digest"], "generic")
        self.assertTrue(journal.exists())

        malformed["entries"] = [{
            "ordinal": 0,
            "slot": _transaction_slot(0, "contextos.workspace.json"),
            "path": "contextos.workspace.json",
            "action": "write",
            "owner": "workspace-config",
            "policy": "managed",
            "existed": False,
            "mode": None,
            "before_sha256_raw": [],
            "after_sha256_raw": "0" * 64,
            "backup": None,
            "receipt_entry": {
                "action": "write",
                "path": "contextos.workspace.json",
                "owner": "workspace-config",
                "policy": "managed",
                "sha256_before_raw": None,
                "sha256_after_raw": "0" * 64,
            },
        }]
        (journal / "journal.json").write_text(
            json.dumps(malformed), encoding="utf-8"
        )
        with self.assertRaisesRegex(ContextOSError, "invalid journal entry"):
            apply_proposal(self.root, path, proposal["proposal_digest"], "generic")

    def test_recovery_refuses_unrecognized_post_crash_edits(self) -> None:
        path, proposal = self.propose()
        changes = proposal["changes"]
        backups = {
            safe_repo_path(self.root, item["path"]): (
                safe_repo_path(self.root, item["path"]).read_bytes()
                if safe_repo_path(self.root, item["path"]).exists()
                else None
            )
            for item in changes
        }
        modes = {
            target: target.stat().st_mode & 0o7777 if target.exists() else None
            for target in backups
        }
        receipt = self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json"
        _create_agent_journal(self.root, proposal, backups, modes, receipt)
        (self.root / "contextos.workspace.json").write_text(
            '{"third_party": true}\n', encoding="utf-8"
        )
        (self.root / "workspace.yaml").unlink()

        with self.assertRaisesRegex(ContextOSError, "unrecognized post-crash edit"):
            self.apply(path, proposal)
        self.assertEqual(
            '{"third_party": true}\n',
            (self.root / "contextos.workspace.json").read_text(encoding="utf-8"),
        )
        self.assertFalse((self.root / "workspace.yaml").exists())

    def test_recovery_reports_a_missing_backup_without_native_traceback(self) -> None:
        path, proposal = self.propose()
        backups = {
            safe_repo_path(self.root, item["path"]): (
                safe_repo_path(self.root, item["path"]).read_bytes()
                if safe_repo_path(self.root, item["path"]).exists()
                else None
            )
            for item in proposal["changes"]
        }
        modes = {
            target: target.stat().st_mode & 0o7777 if target.exists() else None
            for target in backups
        }
        receipt = self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json"
        journal = _create_agent_journal(self.root, proposal, backups, modes, receipt)
        manifest = read_json(journal / "journal.json")
        backup = next(entry["backup"] for entry in manifest["entries"] if entry["backup"])
        (journal / backup).unlink()

        with self.assertRaisesRegex(ContextOSError, "cannot read journal backup"):
            self.apply(path, proposal)
        self.assertTrue(journal.is_dir())

    def test_replay_existing_receipt_and_generic_path_widening_are_rejected(self) -> None:
        path, proposal = self.propose()
        self.apply(path, proposal)
        with self.assertRaisesRegex(ContextOSError, "existing receipt"):
            self.apply(path, proposal)

        with self.assertRaisesRegex(ContextOSError, "approved context paths"):
            create_proposal(
                self.root,
                "setup",
                {"files": {"contextos.workspace.json": "{}"}},
                NOW,
            )

    def test_alias_and_local_artifact_symlinks_fail_closed(self) -> None:
        alias = self.root / "ContextOS.Workspace.json"
        alias.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ContextOSError, "filename collision"):
            self.propose()
        alias.unlink()

        outside = self.root / "outside"
        outside.mkdir()
        local = self.root / ".context-os"
        try:
            local.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation is unavailable")
        with self.assertRaisesRegex(ContextOSError, "symlink"):
            self.propose()
        self.assertEqual([], list(outside.iterdir()))


if __name__ == "__main__":
    unittest.main()
