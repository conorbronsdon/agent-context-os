from __future__ import annotations

import json
import io
import os
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

import contextos.kernel as kernel
from contextos.cli import main as cli_main
from contextos.kernel import (
    ContextOSError,
    _create_agent_journal,
    apply_proposal,
    canonical_json,
    create_proposal,
    create_workspace_migration_proposal,
    doctor,
    raw_file_digest,
    read_json,
    safe_repo_path,
    sha256_text,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-08-25T12:00:00-07:00")


class AgentLifecycleTransactionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        # Hosted Windows can expose TEMP through an 8.3 short path while
        # safe_repo_path() returns the resolved long path. Keep fault-injection
        # path comparisons canonical so an injected failure cannot silently
        # miss the operation it is meant to prove.
        self.root = Path(self.temporary.name).resolve()
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
        self.assertEqual(
            proposal["changes"][0]["after_mode"],
            receipt["files_changed"][0]["mode_after"],
        )
        self.assertIsNone(receipt["files_changed"][0]["mode_before"])

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not portable on Windows")
    def test_published_content_is_non_executable_and_artifacts_are_private(self) -> None:
        path, proposal = self.propose()
        receipt_path, _ = self.apply(path, proposal)

        self.assertEqual(
            0o644,
            (self.root / "contextos.workspace.json").stat().st_mode & 0o7777,
        )
        self.assertEqual(0o600, receipt_path.stat().st_mode & 0o7777)
        self.assertEqual(0o600, path.stat().st_mode & 0o7777)

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

    def test_proposal_reports_directory_target_as_context_error(self) -> None:
        target = self.root / "contextos.workspace.json"
        target.mkdir()
        with self.assertRaisesRegex(ContextOSError, "regular file"):
            self.propose()

    def test_proposal_reports_non_utf8_target_as_context_error(self) -> None:
        target = self.root / "contextos.workspace.json"
        target.write_bytes(b"\xff")
        with self.assertRaisesRegex(ContextOSError, "valid UTF-8"):
            self.propose()

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
            if Path(source) == legacy:
                raise OSError("injected delete failure")
            return original_replace(source, destination, *args, **kwargs)

        with mock.patch("contextos.kernel.os.replace", side_effect=fail_legacy):
            with self.assertRaisesRegex(ContextOSError, "rolled back"):
                self.apply(path, proposal)
        self.assertFalse((self.root / "contextos.workspace.json").exists())
        self.assertEqual(original, legacy.read_bytes())
        self.assertEqual(protected, (self.root / "AGENTS.md").read_bytes())
        self.assert_no_transaction_artifacts()

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

    def test_target_directory_fsync_failure_rolls_back_owned_publication(self) -> None:
        path, proposal = self.propose()
        target = self.root / "contextos.workspace.json"
        original_fsync = kernel._fsync_directory
        failed = False

        def fail_after_publication(directory):
            nonlocal failed
            if not failed and Path(directory) == self.root and target.exists():
                failed = True
                raise OSError("injected target directory fsync failure")
            return original_fsync(directory)

        with mock.patch(
            "contextos.kernel._fsync_directory", side_effect=fail_after_publication
        ):
            with self.assertRaisesRegex(ContextOSError, "rolled back"):
                self.apply(path, proposal)
        self.assertTrue(failed)
        self.assertFalse(target.exists())
        self.assertTrue((self.root / "workspace.yaml").exists())
        self.assert_no_transaction_artifacts()

    def test_delete_directory_fsync_failure_restores_captured_inode(self) -> None:
        path, proposal = self.propose()
        legacy = self.root / "workspace.yaml"
        original = legacy.read_bytes()
        original_fsync = kernel._fsync_directory
        failed = False

        def fail_after_capture(directory):
            nonlocal failed
            if not failed and Path(directory) == self.root and not legacy.exists():
                failed = True
                raise OSError("injected delete directory fsync failure")
            return original_fsync(directory)

        with mock.patch(
            "contextos.kernel._fsync_directory", side_effect=fail_after_capture
        ):
            with self.assertRaisesRegex(ContextOSError, "rolled back"):
                self.apply(path, proposal)
        self.assertTrue(failed)
        self.assertEqual(original, legacy.read_bytes())
        self.assertFalse((self.root / "contextos.workspace.json").exists())
        self.assert_no_transaction_artifacts()

    def test_receipt_directory_fsync_failure_keeps_committed_state_and_journal(self) -> None:
        path, proposal = self.propose()
        receipt = self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json"
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        original_fsync = kernel._fsync_directory
        failed = False

        def fail_after_receipt_link(directory):
            nonlocal failed
            if (
                not failed
                and Path(directory) == receipt.parent
                and receipt.exists()
            ):
                failed = True
                raise OSError("injected receipt directory fsync failure")
            return original_fsync(directory)

        with mock.patch(
            "contextos.kernel._fsync_directory", side_effect=fail_after_receipt_link
        ):
            with self.assertRaisesRegex(ContextOSError, "commit point"):
                self.apply(path, proposal)
        self.assertTrue(failed)
        self.assertTrue(receipt.exists())
        self.assertTrue(journal.exists())
        self.assertTrue((self.root / "contextos.workspace.json").exists())
        self.assertFalse((self.root / "workspace.yaml").exists())

        recovery_failed = False

        def fail_recovery_receipt_sync(directory):
            nonlocal recovery_failed
            if not recovery_failed and Path(directory) == receipt.parent:
                recovery_failed = True
                raise OSError("injected recovery receipt fsync failure")
            return original_fsync(directory)

        with mock.patch(
            "contextos.kernel._fsync_directory",
            side_effect=fail_recovery_receipt_sync,
        ):
            with self.assertRaisesRegex(
                OSError, "injected recovery receipt fsync failure"
            ):
                self.apply(path, proposal)
        self.assertTrue(recovery_failed)
        self.assertTrue(journal.exists())

        with self.assertRaisesRegex(ContextOSError, "existing receipt"):
            self.apply(path, proposal)
        self.assertFalse(journal.exists())

    def test_receipt_commit_accepts_equivalent_target_replacement(self) -> None:
        path, proposal = self.propose()
        target = self.root / "contextos.workspace.json"
        receipt = self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json"
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        expected = proposal["changes"][0]["after_text"].encode("utf-8")
        original_link = os.link
        replaced = False

        def replace_target_before_receipt(source, destination, *args, **kwargs):
            nonlocal replaced
            result = original_link(source, destination, *args, **kwargs)
            if not replaced and Path(destination) == receipt:
                foreign = self.root / "foreign-workspace.json"
                foreign.write_bytes(expected)
                foreign.chmod(proposal["changes"][0]["after_mode"])
                os.replace(foreign, target)
                replaced = True
            return result

        with mock.patch(
            "contextos.kernel.os.link", side_effect=replace_target_before_receipt
        ):
            receipt_path, result = self.apply(path, proposal)

        self.assertTrue(replaced)
        self.assertEqual(proposal["proposal_id"], result["proposal_id"])
        self.assertEqual(expected, target.read_bytes())
        self.assertEqual(receipt, receipt_path)
        self.assertTrue(receipt.exists())
        self.assertFalse(journal.exists())

    def test_journal_rejects_backup_bytes_not_bound_to_the_proposal(self) -> None:
        path, proposal = self.propose()
        original = _create_agent_journal
        legacy_bytes = (self.root / "workspace.yaml").read_bytes()

        def poison_backup(root, document, backups, modes, receipt):
            backups[self.root / "workspace.yaml"] = b"attacker-controlled\n"
            return original(root, document, backups, modes, receipt)

        with mock.patch(
            "contextos.kernel._create_agent_journal", side_effect=poison_backup
        ):
            with self.assertRaisesRegex(ContextOSError, "backup changed"):
                self.apply(path, proposal)
        self.assertEqual(legacy_bytes, (self.root / "workspace.yaml").read_bytes())
        self.assertFalse((self.root / "contextos.workspace.json").exists())
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
        _create_agent_journal(self.root, proposal, backups, modes, receipt)
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        os.link(
            journal / "publications/0.after",
            self.root / "contextos.workspace.json",
        )
        os.replace(legacy, journal / "forward/1.current")

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
        original = raw_file_digest

        def fail_after_publish(candidate: Path):
            if candidate == target and candidate.exists():
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

    def test_receipt_publication_never_overwrites_a_racer(self) -> None:
        path, proposal = self.propose()
        receipt = self.root / ".context-os/receipts" / f"{proposal['proposal_id']}.json"
        original = os.link

        def race_receipt(source, destination, *args, **kwargs):
            if Path(destination) == receipt:
                receipt.write_text("{}\n", encoding="utf-8")
            return original(source, destination, *args, **kwargs)

        with mock.patch("contextos.kernel.os.link", side_effect=race_receipt):
            with self.assertRaisesRegex(ContextOSError, "concurrently created path"):
                self.apply(path, proposal)
        self.assertEqual("{}\n", receipt.read_text(encoding="utf-8"))
        self.assertFalse((self.root / "contextos.workspace.json").exists())
        self.assertTrue((self.root / "workspace.yaml").exists())

    def test_target_publication_never_removes_a_racers_file(self) -> None:
        path, proposal = self.propose()
        target = self.root / "contextos.workspace.json"
        original = os.link

        def race_target(source, destination, *args, **kwargs):
            if Path(destination) == target:
                target.write_bytes(b"concurrent user bytes\n")
            return original(source, destination, *args, **kwargs)

        with mock.patch("contextos.kernel.os.link", side_effect=race_target):
            with self.assertRaisesRegex(ContextOSError, "concurrently created path"):
                self.apply(path, proposal)
        self.assertEqual(b"concurrent user bytes\n", target.read_bytes())
        self.assertTrue((self.root / "workspace.yaml").exists())

    def test_delete_capture_preserves_a_racers_bytes(self) -> None:
        path, proposal = self.propose()
        legacy = self.root / "workspace.yaml"
        concurrent = b"state_dir: concurrent-state\n"
        original = os.replace

        def race_delete(source, destination, *args, **kwargs):
            if Path(source) == legacy and Path(destination).parent.name == "forward":
                legacy.write_bytes(concurrent)
            return original(source, destination, *args, **kwargs)

        with mock.patch("contextos.kernel.os.replace", side_effect=race_delete):
            with self.assertRaisesRegex(ContextOSError, "changed during capture"):
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

    def test_committed_journal_is_retained_when_a_target_is_missing(self) -> None:
        path, proposal = self.propose()
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        with mock.patch(
            "contextos.kernel._discard_agent_journal",
            side_effect=OSError("injected cleanup failure"),
        ):
            self.apply(path, proposal)
        target = self.root / "contextos.workspace.json"
        target.unlink()

        with self.assertRaisesRegex(
            ContextOSError, "journal retained for recovery: contextos.workspace.json"
        ):
            self.apply(path, proposal)

        self.assertTrue(journal.is_dir())
        self.assertFalse(target.exists())
        journal_check = next(
            check
            for check in doctor(self.root)["checks"]
            if check["name"] == "transaction-journals"
        )
        self.assertIn("restore the reported path", journal_check["detail"])
        self.assertIn("do not delete the journal", journal_check["detail"])

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not portable on Windows")
    def test_committed_journal_is_retained_when_target_mode_is_stale(self) -> None:
        path, proposal = self.propose()
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        with mock.patch(
            "contextos.kernel._discard_agent_journal",
            side_effect=OSError("injected cleanup failure"),
        ):
            self.apply(path, proposal)
        target = self.root / "contextos.workspace.json"
        target.chmod(0o600)

        with self.assertRaisesRegex(ContextOSError, "invalid publication anchor"):
            self.apply(path, proposal)

        self.assertTrue(journal.is_dir())
        self.assertEqual(0o600, target.stat().st_mode & 0o7777)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not portable on Windows")
    def test_mode_drift_invalidates_the_proposal_before_mutation(self) -> None:
        legacy = self.root / "workspace.yaml"
        path, proposal = self.propose()
        legacy.chmod(0o600)

        with self.assertRaisesRegex(ContextOSError, "target mode changed"):
            self.apply(path, proposal)

        self.assertTrue(legacy.exists())
        self.assertFalse((self.root / "contextos.workspace.json").exists())

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

        with self.assertRaisesRegex(ContextOSError, "concurrent target"):
            self.apply(path, proposal)
        self.assertEqual(
            '{"third_party": true}\n',
            (self.root / "contextos.workspace.json").read_text(encoding="utf-8"),
        )
        self.assertFalse((self.root / "workspace.yaml").exists())

    def test_recovery_preserves_an_exact_byte_foreign_target(self) -> None:
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
        target = self.root / "contextos.workspace.json"
        target.write_bytes(changes[0]["after_text"].encode("utf-8"))

        with self.assertRaisesRegex(ContextOSError, "concurrent target"):
            self.apply(path, proposal)

        self.assertEqual(
            changes[0]["after_text"].encode("utf-8"), target.read_bytes()
        )
        self.assertTrue(
            (self.root / ".context-os/journals" / proposal["proposal_id"]).exists()
        )

    @unittest.skipUnless(os.name == "nt", "Windows permission semantics only")
    def test_windows_committed_recovery_rejects_readonly_mode_drift(self) -> None:
        path, proposal = self.propose()
        journal = self.root / ".context-os/journals" / proposal["proposal_id"]
        with mock.patch(
            "contextos.kernel._discard_agent_journal",
            side_effect=OSError("injected cleanup failure"),
        ):
            self.apply(path, proposal)
        target = self.root / "contextos.workspace.json"
        target.chmod(0o444)
        self.addCleanup(lambda: target.chmod(0o666) if target.exists() else None)

        with self.assertRaisesRegex(ContextOSError, "invalid publication anchor"):
            self.apply(path, proposal)

        self.assertTrue(journal.exists())
        self.assertFalse(target.stat().st_mode & 0o200)

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
