from __future__ import annotations

import io
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from contextos.bundle_schema import BundleError
from contextos.cli import main as cli_main
from contextos.kernel import (
    ContextOSError,
    _recover_pending_agent_journals,
    apply_proposal,
    doctor,
)
from contextos.materializer import (
    INSTALLED_STATE_PATH,
    create_composition_proposal,
    create_guided_composition_proposal,
    create_materialization_proposal,
    prepare_materialization_preflight,
)
try:
    from tests.test_bundle_lock import BundleFixture, workspace
except ModuleNotFoundError:
    from test_bundle_lock import BundleFixture, workspace


NOW = datetime(2026, 8, 28, 18, 0, tzinfo=timezone.utc)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MaterializerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        current_root = self.root / "current-source"
        candidate_root = self.root / "candidate-source"
        current_root.mkdir()
        candidate_root.mkdir()
        self.current_fixture = BundleFixture(
            current_root,
            version="1.0.0",
            managed=b"binary\x00v1\n",
            addon=False,
        )
        self.candidate_fixture = BundleFixture(
            candidate_root,
            version="2.0.0",
            managed=b"binary\x00v2\n",
            addon=True,
        )
        self.current = self.current_fixture.verify(role="current")
        self.candidate = self.candidate_fixture.verify()
        self.target = self.root / "target"
        shutil.copytree(current_root, self.target)
        (self.target / "seed.txt").write_text("personal seed\n", encoding="utf-8")
        self.config = self.target / "contextos.workspace.json"
        self.config.write_text(
            json.dumps(workspace("fixture-template", "1.0.0"), indent=2) + "\n",
            encoding="utf-8",
        )

    def propose(self):
        return create_materialization_proposal(
            target_root=self.target,
            workspace_config_path=self.config,
            expected_config_sha256=digest(self.config),
            candidate=self.candidate,
            desired_components=["addon"],
            current=self.current,
            current_components=["core"],
            now=NOW,
        )

    def composition_input(self) -> tuple[Path, Path]:
        target = self.root / "clean-target"
        target.mkdir()
        config_input = self.root / "compose-workspace.json"
        config_input.write_text(
            json.dumps(workspace("fixture-template", "2.0.0"), indent=2) + "\n",
            encoding="utf-8",
        )
        return target, config_input

    def git_candidate(self, *, version: str, managed: bytes) -> BundleFixture:
        source = self.root / f"git-candidate-{version}"
        source.mkdir()
        return BundleFixture(
            source,
            version=version,
            managed=managed,
            addon=True,
            source_mode="git-index",
        )

    def assert_materialization_not_published(
        self,
        proposal: dict,
        *,
        managed_before: bytes,
        target: Path | None = None,
        config: Path | None = None,
    ) -> None:
        target = self.target if target is None else target
        config = self.config if config is None else config
        self.assertEqual(managed_before, (target / "managed.bin").read_bytes())
        self.assertFalse((target / "addon.txt").exists())
        self.assertEqual(
            "1.0.0",
            json.loads(config.read_text(encoding="utf-8"))["template"]["version"],
        )
        self.assertFalse(
            (
                target
                / ".context-os"
                / "receipts"
                / f"{proposal['proposal_id']}.json"
            ).exists()
        )

    def compose(self, target: Path, config_input: Path):
        return create_composition_proposal(
            target_root=target,
            workspace_config_path=target / "contextos.workspace.json",
            workspace_config_input_path=config_input,
            expected_config_input_sha256=digest(config_input),
            candidate=self.candidate,
            desired_components=["addon"],
            now=NOW,
        )

    def guided_cli(self, *arguments: str) -> dict:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, cli_main(list(arguments)))
        return json.loads(output.getvalue())

    def test_clean_composition_installs_config_binary_components_and_state(self) -> None:
        target, config_input = self.composition_input()
        (target / "seed.txt").write_text("personal seed\n", encoding="utf-8")
        proposal_path, proposal = self.compose(target, config_input)

        _receipt_path, receipt = apply_proposal(
            target, proposal_path, proposal["proposal_digest"], "generic"
        )

        self.assertEqual(b"binary\x00v2\n", (target / "managed.bin").read_bytes())
        self.assertEqual("addon 2.0.0\n", (target / "addon.txt").read_text())
        self.assertEqual("personal seed\n", (target / "seed.txt").read_text())
        self.assertEqual(
            workspace("fixture-template", "2.0.0"),
            json.loads((target / "contextos.workspace.json").read_text()),
        )
        self.assertEqual("compose", proposal["authorization"]["mode"])
        self.assertEqual("component-materialize", receipt["operation"])

    def test_schema_v2_doctor_reports_desired_vs_installed_drift(self) -> None:
        target = self.root / "v2-target"
        target.mkdir()
        desired = {
            "schema_version": 2,
            "agents": [],
            "composition": {"profile": "full-template", "extras": []},
            "paths": {
                "state_dir": "state",
                "sessions_dir": "sessions",
                "task_file": "TODO.md",
            },
            "template": {
                "source": self.candidate.name,
                "version": self.candidate.version,
                "bundle_sha256": self.candidate.digest,
            },
        }
        proposal_path, proposal = create_guided_composition_proposal(
            target_root=target,
            workspace_config=desired,
            candidate=self.candidate,
            desired_components=["core", "addon"],
            now=NOW,
        )
        apply_proposal(target, proposal_path, proposal["proposal_digest"], "generic")

        healthy = doctor(target)
        healthy_check = next(
            item
            for item in healthy["checks"]
            if item["name"] == "desired-installed-components"
        )
        self.assertEqual("pass", healthy_check["status"], healthy_check)
        self.assertEqual(
            "current", healthy["workspace"]["composition"]["status"]
        )

        installed_path = target / INSTALLED_STATE_PATH
        installed = json.loads(installed_path.read_text(encoding="utf-8"))
        installed["components"] = ["core"]
        installed_path.write_text(
            json.dumps(installed, indent=2) + "\n", encoding="utf-8"
        )
        drifted = doctor(target)
        drift_check = next(
            item
            for item in drifted["checks"]
            if item["name"] == "desired-installed-components"
        )
        self.assertEqual("fail", drift_check["status"])
        self.assertEqual(
            ["addon"],
            drifted["workspace"]["composition"]["missing_components"],
        )

    def test_guided_init_reconcile_remove_and_add_share_transaction_path(self) -> None:
        target = self.root / "guided-target"
        target.mkdir()
        common = (
            "--target", str(target),
            "--lock", str(self.candidate.lock_path),
            "--source", str(self.candidate.root),
            "--expect-sha256", self.candidate.digest,
            "--now", NOW.isoformat(),
        )
        initialized = self.guided_cli(
            "workspace", "init", *common,
            "--agents", "none", "--profile", "full-template",
        )
        self.assertEqual(["core", "addon"], initialized["desired_components"])
        apply_proposal(
            target,
            target / initialized["proposal"],
            initialized["proposal_digest"],
            "generic",
        )
        self.assertTrue((target / "addon.txt").is_file())

        (target / INSTALLED_STATE_PATH).unlink()
        reconciled = self.guided_cli("workspace", "reconcile", *common)
        self.assertEqual([], reconciled["current_components"])
        self.assertEqual(["core", "addon"], reconciled["desired_components"])
        apply_proposal(
            target,
            target / reconciled["proposal"],
            reconciled["proposal_digest"],
            "generic",
        )

        removed = self.guided_cli(
            "workspace", "update", *common,
            "--agents", "none", "--profile", "selected",
        )
        apply_proposal(
            target,
            target / removed["proposal"],
            removed["proposal_digest"],
            "generic",
        )
        self.assertFalse((target / "addon.txt").exists())

        added = self.guided_cli(
            "workspace", "update", *common,
            "--agents", "none", "--profile", "selected", "--extras", "addon",
        )
        apply_proposal(
            target,
            target / added["proposal"],
            added["proposal_digest"],
            "generic",
        )
        self.assertTrue((target / "addon.txt").is_file())
        self.assertTrue((target / INSTALLED_STATE_PATH).is_file())

        upgrade_root = self.root / "guided-upgrade-source"
        upgrade_root.mkdir()
        upgrade_fixture = BundleFixture(
            upgrade_root,
            version="3.0.0",
            managed=b"binary\x00v3\n",
            addon=True,
        )
        upgrade = upgrade_fixture.verify()
        upgraded = self.guided_cli(
            "workspace", "update",
            "--target", str(target),
            "--lock", str(upgrade.lock_path),
            "--source", str(upgrade.root),
            "--expect-sha256", upgrade.digest,
            "--current-lock", str(self.candidate.lock_path),
            "--current-source", str(self.candidate.root),
            "--expect-current-sha256", self.candidate.digest,
            "--agents", "none", "--profile", "selected", "--extras", "addon",
            "--now", NOW.isoformat(),
        )
        apply_proposal(
            target,
            target / upgraded["proposal"],
            upgraded["proposal_digest"],
            "generic",
        )
        self.assertEqual(b"binary\x00v3\n", (target / "managed.bin").read_bytes())
        self.assertEqual(
            upgrade.digest,
            json.loads(
                (target / "contextos.workspace.json").read_text(encoding="utf-8")
            )["template"]["bundle_sha256"],
        )

        moved = self.root / "moved-clean-clone"
        shutil.copytree(target, moved, ignore=shutil.ignore_patterns(".context-os"))
        moved_common = (
            "--target", str(moved),
            "--lock", str(upgrade.lock_path),
            "--source", str(upgrade.root),
            "--expect-sha256", upgrade.digest,
            "--now", NOW.isoformat(),
        )
        moved_reconcile = self.guided_cli(
            "workspace", "reconcile", *moved_common
        )
        apply_proposal(
            moved,
            moved / moved_reconcile["proposal"],
            moved_reconcile["proposal_digest"],
            "generic",
        )
        self.assertEqual(
            "current", doctor(moved)["workspace"]["composition"]["status"]
        )

    def test_selected_projection_has_one_owner_and_no_omitted_runtime_claims(self) -> None:
        source = self.root / "entry-source"
        source.mkdir()
        fixture = BundleFixture(
            source,
            version="4.0.0",
            managed=b"entry\n",
            addon=True,
            runtime_addon=False,
            entry_surfaces=True,
        )
        candidate = fixture.verify()
        target = self.root / "entry-target"
        target.mkdir()
        initialized = self.guided_cli(
            "workspace", "init",
            "--target", str(target),
            "--lock", str(fixture.lock_path),
            "--source", str(source),
            "--expect-sha256", candidate.digest,
            "--agents", "codex",
            "--profile", "selected",
            "--now", NOW.isoformat(),
        )
        generated_owners = {
            change["path"]: change["owner"]
            for change in initialized["changes"]
            if change["path"] in {"README.md", "AGENTS.md"}
        }
        self.assertEqual(
            {"README.md": "core", "AGENTS.md": "agents-instructions"},
            generated_owners,
        )
        initialized_proposal = json.loads(
            (target / initialized["proposal"]).read_text(encoding="utf-8")
        )
        guide_plan = next(
            action
            for action in initialized_proposal["authorization"]["plan"]["actions"]
            if action["path"] == "GUIDE.md"
        )
        self.assertNotEqual(
            guide_plan["desired"]["sha256_raw"],
            guide_plan["desired"]["sha256_text_lf"],
        )
        apply_proposal(
            target,
            target / initialized["proposal"],
            initialized["proposal_digest"],
            "generic",
        )
        readme = (target / "README.md").read_text(encoding="utf-8")
        agents = (target / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("owner=core", readme)
        self.assertIn("owner=agents-instructions", agents)
        self.assertIn("Codex", readme)
        self.assertIn("Codex", agents)
        self.assertNotIn("Hermes", readme)
        self.assertNotIn("Hermes", agents)
        guide = (target / "GUIDE.md").read_text(encoding="utf-8")
        self.assertIn("[managed payload](managed.bin)", guide)
        self.assertIn("the optional add-on is omitted", guide)
        self.assertNotIn("(addon.txt)", guide)
        self.assertFalse((target / "addon.txt").exists())

        upgrade_source = self.root / "entry-upgrade-source"
        upgrade_source.mkdir()
        upgrade_fixture = BundleFixture(
            upgrade_source,
            version="5.0.0",
            managed=b"entry v5\n",
            addon=True,
            runtime_addon=False,
            entry_surfaces=True,
        )
        upgrade = upgrade_fixture.verify()
        upgraded = self.guided_cli(
            "workspace", "update",
            "--target", str(target),
            "--lock", str(upgrade_fixture.lock_path),
            "--source", str(upgrade_source),
            "--expect-sha256", upgrade.digest,
            "--current-lock", str(fixture.lock_path),
            "--current-source", str(source),
            "--expect-current-sha256", candidate.digest,
            "--agents", "codex",
            "--profile", "selected",
            "--now", NOW.isoformat(),
        )
        apply_proposal(
            target,
            target / upgraded["proposal"],
            upgraded["proposal_digest"],
            "generic",
        )
        self.assertEqual(b"entry v5\n", (target / "managed.bin").read_bytes())
        self.assertIn(
            "[managed payload](managed.bin)",
            (target / "GUIDE.md").read_text(encoding="utf-8"),
        )

        core_target = self.root / "core-entry-target"
        core_target.mkdir()
        core_initialized = self.guided_cli(
            "workspace", "init",
            "--target", str(core_target),
            "--lock", str(fixture.lock_path),
            "--source", str(source),
            "--expect-sha256", candidate.digest,
            "--agents", "none",
            "--profile", "selected",
            "--now", NOW.isoformat(),
        )
        apply_proposal(
            core_target,
            core_target / core_initialized["proposal"],
            core_initialized["proposal_digest"],
            "generic",
        )
        core_readme = (core_target / "README.md").read_text(encoding="utf-8")
        self.assertIn("Core-only", core_readme)
        self.assertNotIn("Codex", core_readme)
        self.assertNotIn("Hermes", core_readme)
        self.assertFalse((core_target / "AGENTS.md").exists())

    def test_guided_legacy_yaml_and_schema_v1_migrate_transactionally(self) -> None:
        legacy_target = self.root / "legacy-yaml-target"
        legacy_target.mkdir()
        (legacy_target / "workspace.yaml").write_text(
            "state_dir: memory\nsessions_dir: handoffs\ntask_file: TASKS.md\n",
            encoding="utf-8",
        )
        common = (
            "--lock", str(self.candidate.lock_path),
            "--source", str(self.candidate.root),
            "--expect-sha256", self.candidate.digest,
            "--agents", "none", "--profile", "full-template",
            "--now", NOW.isoformat(),
        )
        initialized = self.guided_cli(
            "workspace", "init", "--target", str(legacy_target), *common
        )
        self.assertIn(
            "workspace.yaml",
            [change["path"] for change in initialized["changes"]],
        )
        apply_proposal(
            legacy_target,
            legacy_target / initialized["proposal"],
            initialized["proposal_digest"],
            "generic",
        )
        migrated = json.loads(
            (legacy_target / "contextos.workspace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(2, migrated["schema_version"])
        self.assertEqual("memory", migrated["paths"]["state_dir"])
        self.assertFalse((legacy_target / "workspace.yaml").exists())

        v1_target = self.root / "schema-v1-target"
        shutil.copytree(self.candidate.root, v1_target)
        v1_config = workspace(self.candidate.name, self.candidate.version)
        v1_config["agents"] = []
        (v1_target / "contextos.workspace.json").write_text(
            json.dumps(v1_config, indent=2) + "\n", encoding="utf-8"
        )
        updated = self.guided_cli(
            "workspace", "update", "--target", str(v1_target), *common
        )
        apply_proposal(
            v1_target,
            v1_target / updated["proposal"],
            updated["proposal_digest"],
            "generic",
        )
        migrated_v1 = json.loads(
            (v1_target / "contextos.workspace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(2, migrated_v1["schema_version"])
        self.assertEqual(
            self.candidate.digest, migrated_v1["template"]["bundle_sha256"]
        )

    def test_marker_only_core_profile_can_materialize_verified_product_authority(self) -> None:
        target = self.root / "marker-only-target"
        target.mkdir()
        config = target / "contextos.workspace.json"
        marker = workspace("fixture-template", "2.0.0")
        marker["agents"] = []
        config.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
        proposal_path, proposal = create_materialization_proposal(
            target_root=target,
            workspace_config_path=config,
            expected_config_sha256=digest(config),
            candidate=self.candidate,
            desired_components=["core"],
            current=None,
            current_components=(),
            now=NOW,
        )
        apply_proposal(target, proposal_path, proposal["proposal_digest"], "generic")

        self.assertEqual(marker, json.loads(config.read_text(encoding="utf-8")))
        self.assertTrue((target / "managed.bin").is_file())
        self.assertTrue((target / "components/manifest.json").is_file())
        self.assertTrue((target / INSTALLED_STATE_PATH).is_file())

    def test_marker_only_materialization_names_candidate_identity_mismatch(self) -> None:
        target = self.root / "mismatched-marker-target"
        target.mkdir()
        config = target / "contextos.workspace.json"
        marker = workspace("fixture-template", "1.0.0")
        marker["agents"] = []
        config.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(BundleError, "candidate bundle identity"):
            create_materialization_proposal(
                target_root=target,
                workspace_config_path=config,
                expected_config_sha256=digest(config),
                candidate=self.candidate,
                desired_components=["core"],
                current=None,
                current_components=(),
                now=NOW,
            )

    def test_git_index_upgrade_uses_verified_blobs_not_smudged_worktree(self) -> None:
        fixture = self.git_candidate(version="3.0.0", managed=b"index binary\x00v3\n")
        candidate = fixture.verify()
        (fixture.root / "managed.bin").write_bytes(b"smudged working tree\r\n")
        (fixture.root / "addon.txt").write_text(
            "filtered working tree\n", encoding="utf-8"
        )

        proposal_path, proposal = create_materialization_proposal(
            target_root=self.target,
            workspace_config_path=self.config,
            expected_config_sha256=digest(self.config),
            candidate=candidate,
            desired_components=["addon"],
            current=self.current,
            current_components=["core"],
            now=NOW,
        )
        apply_proposal(
            self.target, proposal_path, proposal["proposal_digest"], "generic"
        )

        self.assertEqual(b"index binary\x00v3\n", (self.target / "managed.bin").read_bytes())
        self.assertEqual(
            candidate.verified_bytes["addon.txt"],
            (self.target / "addon.txt").read_bytes(),
        )

    def test_git_index_cli_compose_propose_and_apply_use_index_bytes(self) -> None:
        fixture = self.git_candidate(version="3.0.0", managed=b"index line\n")
        (fixture.root / "managed.bin").write_bytes(b"index line\r\n")
        target = self.root / "cli-compose-target"
        target.mkdir()
        config_input = self.root / "cli-compose-workspace.json"
        config_input.write_text(
            json.dumps(workspace("fixture-template", "3.0.0"), indent=2) + "\n",
            encoding="utf-8",
        )
        compose_output = io.StringIO()
        with redirect_stdout(compose_output):
            self.assertEqual(
                0,
                cli_main([
                    "bundle", "compose",
                    "--lock", str(fixture.lock_path),
                    "--source", str(fixture.root),
                    "--expect-sha256", fixture.lock["bundle_sha256"],
                    "--source-mode", "git-index",
                    "--target", str(target),
                    "--workspace-config", str(target / "contextos.workspace.json"),
                    "--workspace-config-input", str(config_input),
                    "--expect-config-sha256", digest(config_input),
                    "--components", "addon",
                    "--now", NOW.isoformat(),
                ]),
            )
        compose_report = json.loads(compose_output.getvalue())
        self.assertEqual("git-index", compose_report["source_mode"])
        self.assertEqual(
            fixture.lock["bundle"]["source_git_commit"],
            compose_report["source_git_commit"],
        )
        apply_output = io.StringIO()
        with redirect_stdout(apply_output):
            self.assertEqual(
                0,
                cli_main([
                    "bundle", "apply",
                    "--target", str(target),
                    "--proposal", compose_report["proposal"],
                    "--confirm", compose_report["proposal_digest"],
                ]),
            )
        apply_report = json.loads(apply_output.getvalue())
        self.assertEqual("component-materialize", apply_report["operation"])
        self.assertIn(apply_report["validation"]["status"], {"pass", "warn", "fail"})
        self.assertEqual("profile", apply_report["validation"]["scope"])
        self.assertEqual(b"index line\n", (target / "managed.bin").read_bytes())

        propose_output = io.StringIO()
        with redirect_stdout(propose_output):
            self.assertEqual(
                0,
                cli_main([
                    "bundle", "propose",
                    "--lock", str(fixture.lock_path),
                    "--source", str(fixture.root),
                    "--expect-sha256", fixture.lock["bundle_sha256"],
                    "--source-mode", "git-index",
                    "--target", str(self.target),
                    "--workspace-config", str(self.config),
                    "--expect-config-sha256", digest(self.config),
                    "--components", "addon",
                    "--current-lock", str(self.current_fixture.lock_path),
                    "--current-source", str(self.current_fixture.root),
                    "--expect-current-sha256", self.current_fixture.lock["bundle_sha256"],
                    "--current-source-mode", "directory",
                    "--current-components", "core",
                    "--now", NOW.isoformat(),
                ]),
            )
        propose_report = json.loads(propose_output.getvalue())
        self.assertTrue(propose_report["proposal"].endswith(".json"))
        self.assertEqual("git-index", propose_report["source_mode"])
        self.assertEqual(
            fixture.lock["bundle"]["source_git_commit"],
            propose_report["source_git_commit"],
        )

    def test_git_index_commit_after_proposal_fails_before_target_writes(self) -> None:
        fixture = self.git_candidate(version="3.0.0", managed=b"index v3\n")
        candidate = fixture.verify()
        proposal_path, proposal = create_materialization_proposal(
            target_root=self.target,
            workspace_config_path=self.config,
            expected_config_sha256=digest(self.config),
            candidate=candidate,
            desired_components=["addon"],
            current=self.current,
            current_components=["core"],
            now=NOW,
        )
        before = (self.target / "managed.bin").read_bytes()
        (fixture.root / "managed.bin").write_bytes(b"committed v4\n")
        fixture.commit_all("change source after proposal")

        with self.assertRaisesRegex(BundleError, "does not match the local Git HEAD"):
            apply_proposal(
                self.target, proposal_path, proposal["proposal_digest"], "generic"
            )

        self.assert_materialization_not_published(proposal, managed_before=before)

    def test_git_index_staged_drift_before_apply_fails_before_target_writes(self) -> None:
        fixture = self.git_candidate(version="3.0.0", managed=b"index v3\n")
        candidate = fixture.verify()
        proposal_path, proposal = create_materialization_proposal(
            target_root=self.target,
            workspace_config_path=self.config,
            expected_config_sha256=digest(self.config),
            candidate=candidate,
            desired_components=["addon"],
            current=self.current,
            current_components=["core"],
            now=NOW,
        )
        before = (self.target / "managed.bin").read_bytes()
        (fixture.root / "managed.bin").write_bytes(b"staged v4\n")
        fixture._git("add", "managed.bin")

        with self.assertRaisesRegex(BundleError, "index differs from HEAD"):
            apply_proposal(
                self.target, proposal_path, proposal["proposal_digest"], "generic"
            )

        self.assert_materialization_not_published(proposal, managed_before=before)

    def test_git_index_staged_drift_after_journal_fails_before_target_writes(self) -> None:
        fixture = self.git_candidate(version="3.0.0", managed=b"index v3\n")
        candidate = fixture.verify()
        proposal_path, proposal = create_materialization_proposal(
            target_root=self.target,
            workspace_config_path=self.config,
            expected_config_sha256=digest(self.config),
            candidate=candidate,
            desired_components=["addon"],
            current=self.current,
            current_components=["core"],
            now=NOW,
        )
        before = (self.target / "managed.bin").read_bytes()
        kernel = __import__("contextos.kernel", fromlist=["_create_agent_journal"])
        original_create_journal = kernel._create_agent_journal

        def stage_source_drift(*args, **kwargs):
            result = original_create_journal(*args, **kwargs)
            (fixture.root / "managed.bin").write_bytes(b"staged v4\n")
            fixture._git("add", "managed.bin")
            return result

        with mock.patch(
            "contextos.kernel._create_agent_journal", side_effect=stage_source_drift
        ), self.assertRaisesRegex(
            (BundleError, ContextOSError), "index differs from HEAD"
        ):
            apply_proposal(
                self.target, proposal_path, proposal["proposal_digest"], "generic"
            )

        self.assert_materialization_not_published(proposal, managed_before=before)

    def test_git_index_commit_after_journal_fails_before_target_writes(self) -> None:
        fixture = self.git_candidate(version="3.0.0", managed=b"index v3\n")
        candidate = fixture.verify()
        proposal_path, proposal = create_materialization_proposal(
            target_root=self.target,
            workspace_config_path=self.config,
            expected_config_sha256=digest(self.config),
            candidate=candidate,
            desired_components=["addon"],
            current=self.current,
            current_components=["core"],
            now=NOW,
        )
        before = (self.target / "managed.bin").read_bytes()
        kernel = __import__("contextos.kernel", fromlist=["_create_agent_journal"])
        original_create_journal = kernel._create_agent_journal

        def commit_source_drift(*args, **kwargs):
            result = original_create_journal(*args, **kwargs)
            (fixture.root / "managed.bin").write_bytes(b"committed v4\n")
            fixture.commit_all("change source during apply")
            return result

        with mock.patch(
            "contextos.kernel._create_agent_journal", side_effect=commit_source_drift
        ), self.assertRaisesRegex(
            (BundleError, ContextOSError), "does not match the local Git HEAD"
        ):
            apply_proposal(
                self.target, proposal_path, proposal["proposal_digest"], "generic"
            )

        self.assert_materialization_not_published(proposal, managed_before=before)

    def test_git_index_current_staged_drift_after_journal_fails_before_target_writes(
        self,
    ) -> None:
        current_root = self.root / "git-current-source"
        current_root.mkdir()
        current_fixture = BundleFixture(
            current_root,
            version="1.0.0",
            managed=b"current index v1\n",
            addon=False,
            source_mode="git-index",
        )
        current = current_fixture.verify(role="current")
        target = self.root / "git-current-target"
        shutil.copytree(
            current_fixture.root,
            target,
            ignore=shutil.ignore_patterns(".git"),
        )
        config = target / "contextos.workspace.json"
        config.write_text(
            json.dumps(workspace("fixture-template", "1.0.0"), indent=2) + "\n",
            encoding="utf-8",
        )
        proposal_path, proposal = create_materialization_proposal(
            target_root=target,
            workspace_config_path=config,
            expected_config_sha256=digest(config),
            candidate=self.candidate,
            desired_components=["addon"],
            current=current,
            current_components=["core"],
            now=NOW,
        )
        before = (target / "managed.bin").read_bytes()
        kernel = __import__("contextos.kernel", fromlist=["_create_agent_journal"])
        original_create_journal = kernel._create_agent_journal

        def stage_current_source_drift(*args, **kwargs):
            result = original_create_journal(*args, **kwargs)
            (current_fixture.root / "managed.bin").write_bytes(b"staged current v2\n")
            current_fixture._git("add", "managed.bin")
            return result

        with mock.patch(
            "contextos.kernel._create_agent_journal",
            side_effect=stage_current_source_drift,
        ), self.assertRaisesRegex(
            (BundleError, ContextOSError), "index differs from HEAD"
        ):
            apply_proposal(target, proposal_path, proposal["proposal_digest"], "generic")

        self.assert_materialization_not_published(
            proposal,
            managed_before=before,
            target=target,
            config=config,
        )

    def test_git_index_apply_uses_two_context_passes_with_planner_end_rechecks(self) -> None:
        fixture = self.git_candidate(version="3.0.0", managed=b"index v3\n")
        candidate = fixture.verify()
        proposal_path, proposal = create_materialization_proposal(
            target_root=self.target,
            workspace_config_path=self.config,
            expected_config_sha256=digest(self.config),
            candidate=candidate,
            desired_components=["addon"],
            current=self.current,
            current_components=["core"],
            now=NOW,
        )
        materializer = __import__(
            "contextos.materializer", fromlist=["_materialization_context"]
        )
        bundle_schema = __import__(
            "contextos.bundle_schema", fromlist=["_git_repository_identity"]
        )

        with mock.patch(
            "contextos.materializer._materialization_context",
            wraps=materializer._materialization_context,
        ) as context_pass, mock.patch(
            "contextos.bundle_schema._git_repository_identity",
            wraps=bundle_schema._git_repository_identity,
        ) as repository_identity:
            apply_proposal(
                self.target, proposal_path, proposal["proposal_digest"], "generic"
            )

        self.assertEqual(2, context_pass.call_count)
        # Each context verifies the candidate at load and again at the planner's
        # end boundary; each verification checks Git identity before and after.
        self.assertEqual(8, repository_identity.call_count)

    def test_preflight_retains_only_candidate_write_payloads(self) -> None:
        _proposal_path, proposal = self.propose()
        materializer = __import__("contextos.materializer", fromlist=["verify_bundle"])
        original_verify = materializer.verify_bundle
        observations: list[tuple[str, set[str], set[str]]] = []

        def capture_verification(*args, **kwargs):
            verified = original_verify(*args, **kwargs)
            observations.append((
                kwargs.get("role", "candidate"),
                set(kwargs.get("retain_paths", ())),
                set(verified.verified_bytes),
            ))
            return verified

        with mock.patch(
            "contextos.materializer.verify_bundle", side_effect=capture_verification
        ):
            _created_at, payloads = prepare_materialization_preflight(
                self.target, proposal
            )

        expected_bundle_paths = {
            change["content_ref"]["path"]
            for change in proposal["changes"]
            if change["action"] == "write"
            and change["content_ref"]["kind"] == "bundle"
        }
        expected_write_paths = {
            change["path"]
            for change in proposal["changes"]
            if change["action"] == "write"
        }
        self.assertEqual(expected_write_paths, set(payloads))
        self.assertEqual([
            ("candidate", expected_bundle_paths, expected_bundle_paths),
            ("current", set(), set()),
        ], observations)

    def test_bundle_apply_rejects_non_materialization_proposal(self) -> None:
        proposal = self.target / "not-materialization.json"
        proposal.write_text('{"operation":"agent-config"}\n', encoding="utf-8")
        errors = io.StringIO()
        with redirect_stderr(errors):
            status = cli_main([
                "bundle", "apply", "--target", str(self.target),
                "--proposal", str(proposal), "--confirm", "unused",
            ])
        self.assertEqual(2, status)
        self.assertIn("only materialization proposals", errors.getvalue())

    def test_clean_composition_rejects_managed_collision(self) -> None:
        target, config_input = self.composition_input()
        (target / "managed.bin").write_bytes(b"local\n")
        with self.assertRaisesRegex(BundleError, "collides with a planned add"):
            self.compose(target, config_input)

    def test_clean_composition_requires_the_canonical_workspace_marker(self) -> None:
        target, config_input = self.composition_input()
        with self.assertRaisesRegex(BundleError, "must equal target_root"):
            create_composition_proposal(
                target_root=target,
                workspace_config_path=target / "notes/workspace.json",
                workspace_config_input_path=config_input,
                expected_config_input_sha256=digest(config_input),
                candidate=self.candidate,
                desired_components=["addon"],
                now=NOW,
            )

    def test_clean_composition_rejects_stale_installed_state_during_proposal(self) -> None:
        target, config_input = self.composition_input()
        state_path = target / INSTALLED_STATE_PATH
        state_path.parent.mkdir()
        state_path.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(BundleError, "explicit current bundle"):
            self.compose(target, config_input)

    def test_clean_composition_input_drift_fails_without_target_writes(self) -> None:
        target, config_input = self.composition_input()
        proposal_path, proposal = self.compose(target, config_input)
        config_input.write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(BundleError, "became stale"):
            apply_proposal(
                target, proposal_path, proposal["proposal_digest"], "generic"
            )

        self.assertFalse((target / "managed.bin").exists())
        self.assertFalse((target / "contextos.workspace.json").exists())

    def test_binary_upgrade_add_and_installed_state_use_shared_apply(self) -> None:
        proposal_path, proposal = self.propose()
        receipt_path, receipt = apply_proposal(
            self.target, proposal_path, proposal["proposal_digest"], "generic"
        )

        self.assertEqual(b"binary\x00v2\n", (self.target / "managed.bin").read_bytes())
        self.assertEqual("addon 2.0.0\n", (self.target / "addon.txt").read_text())
        self.assertEqual("personal seed\n", (self.target / "seed.txt").read_text())
        config = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual("2.0.0", config["template"]["version"])
        installed = json.loads(
            (self.target / INSTALLED_STATE_PATH).read_text(encoding="utf-8")
        )
        self.assertEqual(self.candidate.digest, installed["bundle"]["sha256"])
        self.assertEqual(["core", "addon"], installed["components"])
        self.assertEqual(
            proposal["authorization"]["plan"]["plan_digest"],
            installed["plan_digest"],
        )
        self.assertTrue(receipt_path.is_file())
        self.assertEqual("component-materialize", receipt["operation"])
        self.assertEqual(proposal["invariants"], receipt["invariants_checked"])

    def test_candidate_drift_after_proposal_fails_without_target_writes(self) -> None:
        proposal_path, proposal = self.propose()
        before = {
            path.relative_to(self.target).as_posix(): path.read_bytes()
            for path in self.target.rglob("*")
            if path.is_file() and ".context-os" not in path.parts
        }
        (self.candidate.root / "managed.bin").write_bytes(b"tampered\n")
        with self.assertRaisesRegex((BundleError, ContextOSError), "raw bytes"):
            apply_proposal(
                self.target, proposal_path, proposal["proposal_digest"], "generic"
            )
        after = {
            path.relative_to(self.target).as_posix(): path.read_bytes()
            for path in self.target.rglob("*")
            if path.is_file() and ".context-os" not in path.parts
        }
        self.assertEqual(before, after)

    def test_failure_after_binary_publication_rolls_back_replace_and_add(self) -> None:
        proposal_path, proposal = self.propose()
        original_publish = __import__(
            "contextos.kernel", fromlist=["_publish_exclusive"]
        )._publish_exclusive
        publications = 0
        injected = False

        def fail_after_binary_replace(source: Path, destination: Path):
            nonlocal publications, injected
            result = original_publish(source, destination)
            if (
                destination.is_relative_to(self.target.resolve())
                and ".context-os" not in destination.parts
            ):
                publications += 1
                if destination.name == "managed.bin" and not injected:
                    injected = True
                    raise OSError("injected materialization failure")
            return result

        with mock.patch(
            "contextos.kernel._publish_exclusive", side_effect=fail_after_binary_replace
        ), self.assertRaisesRegex(ContextOSError, "rolled back"):
            apply_proposal(
                self.target, proposal_path, proposal["proposal_digest"], "generic"
            )
        self.assertEqual(b"binary\x00v1\n", (self.target / "managed.bin").read_bytes())
        self.assertFalse((self.target / "addon.txt").exists())
        self.assertEqual("1.0.0", json.loads(self.config.read_text())["template"]["version"])
        self.assertFalse((self.target / INSTALLED_STATE_PATH).exists())
        self.assertGreater(publications, 1)

    def test_materialized_component_removal_preserves_seed_and_local_state(self) -> None:
        proposal_path, proposal = self.propose()
        apply_proposal(
            self.target, proposal_path, proposal["proposal_digest"], "generic"
        )
        next_root = self.root / "next-source"
        next_root.mkdir()
        next_fixture = BundleFixture(
            next_root,
            version="3.0.0",
            managed=b"binary\x00v3\n",
            addon=False,
        )
        next_candidate = next_fixture.verify()
        current = self.candidate_fixture.verify(role="current")
        next_path, next_proposal = create_materialization_proposal(
            target_root=self.target,
            workspace_config_path=self.config,
            expected_config_sha256=digest(self.config),
            candidate=next_candidate,
            desired_components=["core"],
            current=current,
            current_components=["addon"],
            now=NOW.replace(minute=1),
        )
        apply_proposal(
            self.target,
            next_path,
            next_proposal["proposal_digest"],
            "generic",
        )
        self.assertFalse((self.target / "addon.txt").exists())
        self.assertEqual(b"binary\x00v3\n", (self.target / "managed.bin").read_bytes())
        self.assertEqual("personal seed\n", (self.target / "seed.txt").read_text())
        installed = json.loads(
            (self.target / INSTALLED_STATE_PATH).read_text(encoding="utf-8")
        )
        self.assertEqual(["core"], installed["components"])
        self.assertEqual("3.0.0", installed["bundle"]["version"])

    def test_upgrade_rejects_installed_state_that_contradicts_current_components(self) -> None:
        proposal_path, proposal = self.propose()
        apply_proposal(
            self.target, proposal_path, proposal["proposal_digest"], "generic"
        )
        state_path = self.target / INSTALLED_STATE_PATH
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["components"] = ["core"]
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(BundleError, "contradicts current_components"):
            create_materialization_proposal(
                target_root=self.target,
                workspace_config_path=self.config,
                expected_config_sha256=digest(self.config),
                candidate=self.candidate_fixture.verify(),
                desired_components=["addon"],
                current=self.candidate_fixture.verify(role="current"),
                current_components=["addon"],
                now=NOW.replace(minute=2),
            )

    @unittest.skipUnless(os.name == "nt", "Windows case alias control")
    def test_upgrade_normalizes_case_aliased_config_source_key(self) -> None:
        proposal_path, proposal = create_materialization_proposal(
            target_root=Path(str(self.target).lower()),
            workspace_config_path=Path(str(self.config).lower()),
            expected_config_sha256=digest(self.config),
            candidate=self.candidate,
            desired_components=["addon"],
            current=self.current,
            current_components=["core"],
            now=NOW,
        )

        apply_proposal(
            self.target, proposal_path, proposal["proposal_digest"], "generic"
        )
        self.assertEqual(b"binary\x00v2\n", (self.target / "managed.bin").read_bytes())

    def test_committed_materialization_journal_recovers_without_source_policy_widening(self) -> None:
        proposal_path, proposal = self.propose()
        with mock.patch(
            "contextos.kernel._discard_agent_journal",
            side_effect=OSError("retain committed journal"),
        ):
            receipt_path, _receipt = apply_proposal(
                self.target, proposal_path, proposal["proposal_digest"], "generic"
            )
        journal = self.target / ".context-os/journals" / proposal["proposal_id"]
        self.assertTrue(receipt_path.is_file())
        self.assertTrue(journal.is_dir())

        _recover_pending_agent_journals(self.target)

        self.assertFalse(journal.exists())
        self.assertEqual(b"binary\x00v2\n", (self.target / "managed.bin").read_bytes())
