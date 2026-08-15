import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "dream" / "validate-memory.py"


def run(command: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and completed.returncode:
        raise AssertionError(
            f"{command} failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


class DreamMemoryPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.memory = self.root / "memory"
        self.repo.mkdir()
        self.memory.mkdir()
        run(["git", "init", "-q"], self.repo)
        run(["git", "config", "user.name", "Dream Test"], self.repo)
        run(["git", "config", "user.email", "dream@example.invalid"], self.repo)
        run(["git", "init", "-q"], self.memory)
        run(["git", "config", "user.name", "Dream Memory"], self.memory)
        run(["git", "config", "user.email", "dream-memory@example.invalid"], self.memory)
        (self.repo / ".context-os").mkdir()
        (self.repo / ".context-os" / "memory-directory").write_text(
            f"{self.memory}\n", encoding="utf-8"
        )
        identity = run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], self.repo
        ).stdout.strip()
        (self.memory / ".context-os-repository").write_text(f"{identity}\n", encoding="utf-8")
        (self.memory / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
        (self.memory / "project_alpha.md").write_text("alpha\n", encoding="utf-8")
        (self.memory / "project_beta.md").write_text("beta\n", encoding="utf-8")
        run(["git", "add", "-A"], self.memory)
        run(["git", "commit", "-qm", "baseline"], self.memory)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def helper(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        normalized = list(args)
        if (
            normalized
            and normalized[0] == "artifact"
            and "--for-create" not in normalized
            and "--for-commit" not in normalized
        ):
            normalized.append("--for-commit")
        return run(["python3", str(HELPER), *normalized], cwd or self.repo, check=False)

    def write_artifact(
        self, proposals: list[dict[str, object]] | object, *, curator: str = "rot"
    ) -> Path:
        for previous in self.memory.glob(".dreams*"):
            if previous.is_symlink() or previous.is_file():
                previous.unlink()
            else:
                shutil.rmtree(previous)
        dream = self.memory / ".dreams" / "2026-08-15T10-19-00Z"
        dream.mkdir(parents=True)
        payload = {
            "curator": curator,
            "ran_at": "2026-08-15T10:19:00Z",
            "proposals": proposals,
        }
        (dream / "proposals.json").write_text(json.dumps(payload), encoding="utf-8")
        (dream / "REPORT.md").write_text("# Dream pass\n", encoding="utf-8")
        (dream / "inputs.json").write_text("{}\n", encoding="utf-8")
        return dream

    def valid_modify(self) -> dict[str, object]:
        return {
            "id": "rot-001",
            "action": "modify",
            "target": "project_alpha.md",
            "reasoning": "State changed.",
            "evidence": ["state/current.md: shipped"],
            "current_excerpt": "old",
            "proposed_excerpt": "new",
            "confidence": "high",
        }

    def assert_rejects(self, *args: str, cwd: Path | None = None) -> str:
        completed = self.helper(*args, cwd=cwd)
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        return completed.stderr

    def test_resolve_accepts_real_repo_and_linked_worktree_identity(self) -> None:
        resolved = self.helper("resolve")
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        data = json.loads(resolved.stdout)
        self.assertEqual(data["memory_dir"], str(self.memory))

        run(["git", "add", "-A"], self.repo)
        run(["git", "commit", "-qm", "baseline"], self.repo)
        linked = self.root / "linked"
        run(["git", "worktree", "add", "-q", str(linked)], self.repo)
        (linked / ".context-os").mkdir(exist_ok=True)
        (linked / ".context-os" / "memory-directory").write_text(
            f"{self.memory}\n", encoding="utf-8"
        )
        linked_resolved = self.helper("resolve", cwd=linked)
        self.assertEqual(linked_resolved.returncode, 0, linked_resolved.stderr)
        linked_data = json.loads(linked_resolved.stdout)
        self.assertEqual(linked_data["repository_identity"], data["repository_identity"])

    def test_artifact_accepts_valid_proposals_and_latest(self) -> None:
        self.write_artifact([self.valid_modify()])
        exact = self.helper("artifact", "2026-08-15T10-19-00Z")
        self.assertEqual(exact.returncode, 0, exact.stderr)
        self.assertEqual(json.loads(exact.stdout)["proposal_count"], 1)
        latest = self.helper("artifact", "latest")
        self.assertEqual(latest.returncode, 0, latest.stderr)
        self.assertEqual(json.loads(latest.stdout)["timestamp"], "2026-08-15T10-19-00Z")

        run(["git", "add", ".dreams"], self.memory)
        run(["git", "commit", "-qm", "dream artifact"], self.memory)
        clean_apply = run(
            [
                "python3",
                str(HELPER),
                "artifact",
                "2026-08-15T10-19-00Z",
            ],
            self.repo,
            check=False,
        )
        self.assertEqual(clean_apply.returncode, 0, clean_apply.stderr)

    def test_artifact_rejects_timestamp_escape_and_control_characters(self) -> None:
        self.assertIn("timestamp", self.assert_rejects("artifact", "../../outside"))
        self.assertIn("timestamp", self.assert_rejects("artifact", "2026-08-15T10-19-00Z\nx"))
        self.assertIn("timestamp", self.assert_rejects("artifact", "2026-99-99T99-99-99Z"))

    def test_artifact_rejects_symlinked_components(self) -> None:
        (self.memory / ".dreams").symlink_to(self.root)
        self.assertIn("symlink", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

    def test_proposals_reject_path_escape_absolute_and_symlink_targets(self) -> None:
        proposal = self.valid_modify()
        proposal["target"] = "../outside.md"
        self.write_artifact([proposal])
        self.assertIn("plain memory filename", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        (self.memory / ".dreams").rename(self.memory / ".dreams.bad")
        proposal = self.valid_modify()
        proposal["target"] = "/tmp/outside.md"
        self.write_artifact([proposal])
        self.assertIn("plain memory filename", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        (self.memory / ".dreams").rename(self.memory / ".dreams.bad2")
        (self.memory / "reference_link.md").symlink_to(self.root / "elsewhere.md")
        proposal = self.valid_modify()
        proposal["target"] = "reference_link.md"
        self.write_artifact([proposal])
        self.assertIn("symlink", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

    def test_proposals_reject_unknown_action_empty_evidence_and_extra_fields(self) -> None:
        proposal = self.valid_modify()
        proposal["action"] = "delete"
        self.write_artifact([proposal])
        self.assertIn("unknown action", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        (self.memory / ".dreams").rename(self.memory / ".dreams.bad")
        proposal = self.valid_modify()
        proposal["evidence"] = []
        self.write_artifact([proposal])
        self.assertIn("evidence", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        (self.memory / ".dreams").rename(self.memory / ".dreams.bad2")
        proposal = self.valid_modify()
        proposal["delete_path"] = "project_beta.md"
        self.write_artifact([proposal])
        self.assertIn("unknown fields", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        (self.memory / ".dreams").rename(self.memory / ".dreams.bad3")
        proposal = self.valid_modify()
        proposal["action"] = ["modify"]
        self.write_artifact([proposal])
        error = self.assert_rejects("artifact", "2026-08-15T10-19-00Z")
        self.assertIn("unknown action", error)
        self.assertNotIn("Traceback", error)

        (self.memory / ".dreams").rename(self.memory / ".dreams.bad4")
        proposal = self.valid_modify()
        proposal["confidence"] = {"level": "high"}
        self.write_artifact([proposal])
        error = self.assert_rejects("artifact", "2026-08-15T10-19-00Z")
        self.assertIn("unsupported confidence", error)
        self.assertNotIn("Traceback", error)

    def test_proposals_reject_missing_required_fields_without_keyerror(self) -> None:
        proposal = self.valid_modify()
        del proposal["target"]
        self.write_artifact([proposal])
        error = self.assert_rejects("artifact", "2026-08-15T10-19-00Z")
        self.assertIn("missing modify fields", error)
        self.assertNotIn("Traceback", error)

    def test_lint_modify_allows_empty_proposed_excerpt(self) -> None:
        proposal = self.valid_modify()
        proposal["target"] = "MEMORY.md"
        proposal["proposed_excerpt"] = ""
        proposal["check"] = "index_drift"
        self.write_artifact([proposal], curator="lint")
        completed = self.helper("artifact", "2026-08-15T10-19-00Z")
        self.assertEqual(completed.returncode, 0, completed.stderr)

        archive = {
            "id": "lint-002",
            "action": "archive",
            "target": "project_beta.md",
            "reasoning": "Finish a half-completed retirement.",
            "evidence": ["ARCHIVE.md has a row but the detail file is still live."],
            "archive_reason": "Complete the prior reviewed retirement.",
            "check": "index_drift",
            "confidence": "high",
        }
        self.write_artifact([archive], curator="lint")
        completed = self.helper("artifact", "2026-08-15T10-19-00Z")
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_add_and_split_reject_collisions(self) -> None:
        proposal = {
            "id": "pattern-001",
            "action": "add",
            "target": "project_alpha.md",
            "reasoning": "New recurring need.",
            "evidence": ["sessions/2026-08-15.md: repeated"],
            "proposed_content": "content",
            "index_line": "- [Alpha](project_alpha.md): content",
            "confidence": "medium",
        }
        self.write_artifact([proposal])
        self.assertIn("must not already exist", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        (self.memory / ".dreams").rename(self.memory / ".dreams.bad")
        proposal = {
            "id": "split-001",
            "action": "split",
            "target": "project_alpha.md",
            "reasoning": "Two concerns.",
            "evidence": ["project_alpha.md L1"],
            "original_index_line": "- [Alpha](project_alpha.md): alpha",
            "result_files": [
                {
                    "name": "project_alpha.md",
                    "purpose": "first",
                    "index_line": "- [Alpha](project_alpha.md): first",
                    "body": "first",
                },
                {
                    "name": "project_beta.md",
                    "purpose": "second",
                    "index_line": "- [Beta](project_beta.md): second",
                    "body": "second",
                },
            ],
            "confidence": "medium",
        }
        self.write_artifact([proposal], curator="split")
        self.assertIn("must not already exist", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

    def test_curator_action_ids_and_artifact_wide_collisions(self) -> None:
        add = {
            "id": "pattern-001",
            "action": "add",
            "target": "project_gamma.md",
            "reasoning": "Repeated need.",
            "evidence": ["session evidence"],
            "proposed_content": "gamma",
            "index_line": "- [Gamma](project_gamma.md): gamma",
            "confidence": "medium",
        }
        self.write_artifact([add])
        self.assertIn("not allowed for curator", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        first = self.valid_modify()
        second = self.valid_modify()
        second["reasoning"] = "Another excerpt."
        self.write_artifact([first, second])
        self.assertIn("duplicate proposal id", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        second["id"] = "rot-002"
        self.write_artifact([first, second])
        self.assertIn("mutation target collides", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        archive_one = {
            "id": "rot-archive-1",
            "action": "archive",
            "target": "project_alpha.md",
            "reasoning": "Retired.",
            "evidence": ["state says retired"],
            "archive_reason": "Retired after launch.",
            "confidence": "high",
        }
        archive_two = {**archive_one, "id": "rot-archive-2"}
        self.write_artifact([archive_one, archive_two])
        self.assertIn("mutation target collides", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

    def test_control_files_are_reserved_from_structural_actions(self) -> None:
        archive = {
            "id": "rot-archive-1",
            "action": "archive",
            "target": "MEMORY.md",
            "reasoning": "Hostile control-file move.",
            "evidence": ["hostile fixture"],
            "archive_reason": "Do not permit.",
            "confidence": "high",
        }
        self.write_artifact([archive])
        self.assertIn("control file", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        merge = {
            "id": "merge-001",
            "action": "merge",
            "targets": ["MEMORY.md", "project_alpha.md"],
            "survivor": "project_gamma.md",
            "reasoning": "Hostile control-file merge.",
            "evidence": ["hostile fixture"],
            "merged_body": "merged",
            "index_changes": {"remove": ["old alpha", "old beta"], "add": "new"},
            "archive_tombstones": ["old merged"],
            "net_index_lines": -1,
            "confidence": "medium",
        }
        self.write_artifact([merge], curator="merge")
        self.assertIn("control file", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        split = {
            "id": "split-001",
            "action": "split",
            "target": "MEMORY.md",
            "reasoning": "Hostile control-file split.",
            "evidence": ["hostile fixture"],
            "original_index_line": "- old",
            "result_files": [
                {
                    "name": "project_gamma.md",
                    "purpose": "gamma",
                    "index_line": "- gamma",
                    "body": "gamma",
                }
            ],
            "confidence": "medium",
        }
        self.write_artifact([split], curator="split")
        self.assertIn("control file", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        add = {
            "id": "pattern-001",
            "action": "add",
            "target": "ARCHIVE.md",
            "reasoning": "Hostile control-file creation.",
            "evidence": ["hostile fixture"],
            "proposed_content": "archive",
            "index_line": "- archive",
            "confidence": "medium",
        }
        self.write_artifact([add])
        self.assertIn("control file", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

    def test_merge_rejects_bad_index_tombstones_bool_and_survivor_collision(self) -> None:
        proposal = {
            "id": "merge-001",
            "action": "merge",
            "targets": ["project_alpha.md", "project_beta.md"],
            "survivor": "project_gamma.md",
            "reasoning": "Same topic.",
            "evidence": ["alpha", "beta"],
            "merged_body": "merged",
            "index_changes": {"remove": ["old alpha", "old beta"], "add": "new"},
            "archive_tombstones": ["alpha merged", "beta merged"],
            "net_index_lines": -1,
            "confidence": "medium",
        }
        self.write_artifact([proposal], curator="merge")
        completed = self.helper("artifact", "2026-08-15T10-19-00Z")
        self.assertEqual(completed.returncode, 0, completed.stderr)

        (self.memory / ".dreams").rename(self.memory / ".dreams.bad")
        (self.memory / "project_gamma.md").write_text("collision\n", encoding="utf-8")
        self.write_artifact([proposal], curator="merge")
        self.assertIn("must not already exist", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        (self.memory / ".dreams").rename(self.memory / ".dreams.bad2")
        (self.memory / "project_gamma.md").unlink()
        proposal["survivor"] = "project_alpha.md"
        proposal["archive_tombstones"] = ["beta merged"]
        proposal["net_index_lines"] = True
        self.write_artifact([proposal], curator="merge")
        self.assertIn("net_index_lines", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        (self.memory / ".dreams").rename(self.memory / ".dreams.bad3")
        proposal["net_index_lines"] = -1
        proposal["index_changes"] = {"remove": "old", "add": "new"}
        self.write_artifact([proposal], curator="merge")
        self.assertIn("index_changes", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        (self.memory / ".dreams").rename(self.memory / ".dreams.bad4")
        proposal["index_changes"] = {"remove": ["old"], "add": "new"}
        proposal["archive_tombstones"] = []
        self.write_artifact([proposal], curator="merge")
        self.assertIn("archive_tombstones", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        proposal["archive_tombstones"] = ["beta merged"]
        proposal["index_changes"] = {"remove": ["old", "old"], "add": "new"}
        self.write_artifact([proposal], curator="merge")
        self.assertIn("must be unique", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        proposal["index_changes"] = {"remove": ["old", "older"], "add": "new"}
        proposal["net_index_lines"] = 0
        self.write_artifact([proposal], curator="merge")
        self.assertIn("must match", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

    def test_proposals_reject_malformed_top_level_schema(self) -> None:
        self.write_artifact({"id": "not-a-list"})
        self.assertIn("proposals array", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        (self.memory / ".dreams").rename(self.memory / ".dreams.bad")
        dream = self.write_artifact([self.valid_modify()])
        payload = json.loads((dream / "proposals.json").read_text(encoding="utf-8"))
        del payload["curator"]
        (dream / "proposals.json").write_text(json.dumps(payload), encoding="utf-8")
        self.assertIn("missing fields", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        (self.memory / ".dreams").rename(self.memory / ".dreams.bad2")
        dream = self.write_artifact([self.valid_modify()])
        payload = json.loads((dream / "proposals.json").read_text(encoding="utf-8"))
        payload["curator"] = "future-unreviewed-curator"
        (dream / "proposals.json").write_text(json.dumps(payload), encoding="utf-8")
        self.assertIn("shipped curator", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        (self.memory / ".dreams").rename(self.memory / ".dreams.bad3")
        dream = self.write_artifact([self.valid_modify()])
        payload = json.loads((dream / "proposals.json").read_text(encoding="utf-8"))
        payload["ran_at"] = "not-a-date"
        (dream / "proposals.json").write_text(json.dumps(payload), encoding="utf-8")
        self.assertIn("ran_at", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

        (self.memory / ".dreams").rename(self.memory / ".dreams.bad4")
        dream = self.write_artifact([self.valid_modify()])
        payload = json.loads((dream / "proposals.json").read_text(encoding="utf-8"))
        payload["curator"] = ["rot"]
        (dream / "proposals.json").write_text(json.dumps(payload), encoding="utf-8")
        error = self.assert_rejects("artifact", "2026-08-15T10-19-00Z")
        self.assertIn("shipped curator", error)
        self.assertNotIn("Traceback", error)

    def test_binding_rejects_noncanonical_path_marker_mismatch_and_remote(self) -> None:
        (self.repo / ".context-os" / "memory-directory").write_text(
            f"{self.memory / '..' / 'memory'}\n", encoding="utf-8"
        )
        self.assertIn("canonical", self.assert_rejects("resolve"))

        (self.repo / ".context-os" / "memory-directory").write_text(
            f"{self.memory}\n", encoding="utf-8"
        )
        (self.memory / ".context-os-repository").write_text("/wrong/git/dir\n", encoding="utf-8")
        self.assertIn("marker", self.assert_rejects("resolve"))

        identity = run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], self.repo
        ).stdout.strip()
        (self.memory / ".context-os-repository").write_text(f"{identity}\n", encoding="utf-8")
        run(["git", "remote", "add", "origin", "https://example.invalid/memory.git"], self.memory)
        self.assertIn("remotes", self.assert_rejects("resolve"))

    def test_binding_rejects_missing_directory_without_traceback(self) -> None:
        (self.repo / ".context-os" / "memory-directory").write_text(
            f"{self.root / 'missing'}\n", encoding="utf-8"
        )
        error = self.assert_rejects("resolve")
        self.assertIn("existing directory", error)
        self.assertNotIn("Traceback", error)

    def test_clean_binding_rejects_tracked_staged_and_untracked_memory_changes(self) -> None:
        (self.memory / "project_alpha.md").write_text("dirty tracked\n", encoding="utf-8")
        self.assertIn("must be clean", self.assert_rejects("resolve"))
        run(["git", "restore", "project_alpha.md"], self.memory)

        (self.memory / "project_alpha.md").write_text("dirty staged\n", encoding="utf-8")
        run(["git", "add", "project_alpha.md"], self.memory)
        self.assertIn("must be clean", self.assert_rejects("resolve"))
        run(["git", "restore", "--staged", "project_alpha.md"], self.memory)
        run(["git", "restore", "project_alpha.md"], self.memory)

        (self.memory / "unrelated-private-draft.md").write_text("private\n", encoding="utf-8")
        error = self.assert_rejects("resolve")
        self.assertIn("unrelated-private-draft.md", error)
        (self.memory / "unrelated-private-draft.md").unlink()

    def test_change_allowlist_rejects_concurrent_and_staged_unrelated_paths(self) -> None:
        applied = self.memory / ".dreams" / "2026-08-15T10-19-00Z" / "applied.json"
        applied.parent.mkdir(parents=True)
        applied.write_text("{}\n", encoding="utf-8")
        unrelated = self.memory / "unrelated-private-draft.md"
        unrelated.write_text("private\n", encoding="utf-8")

        rejected = self.helper(
            "changes",
            "--allow",
            ".dreams/2026-08-15T10-19-00Z/applied.json",
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("outside the reviewed allowlist", rejected.stderr)

        run(["git", "add", "unrelated-private-draft.md"], self.memory)
        staged = self.helper(
            "changes",
            "--allow",
            ".dreams/2026-08-15T10-19-00Z/applied.json",
        )
        self.assertNotEqual(staged.returncode, 0)
        self.assertIn("unrelated-private-draft.md", staged.stderr)

        run(["git", "restore", "--staged", "unrelated-private-draft.md"], self.memory)
        unrelated.unlink()
        accepted = self.helper(
            "changes",
            "--allow",
            ".dreams/2026-08-15T10-19-00Z/applied.json",
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(
            json.loads(accepted.stdout)["changed_paths"],
            [".dreams/2026-08-15T10-19-00Z/applied.json"],
        )

        overbroad = self.helper(
            "changes",
            "--allow",
            ".dreams/2026-08-15T10-19-00Z/applied.json",
            "--allow",
            "project_alpha.md",
        )
        self.assertNotEqual(overbroad.returncode, 0)
        self.assertIn("did not change", overbroad.stderr)

        traversal = self.helper("changes", "--allow", "../outside.md")
        self.assertNotEqual(traversal.returncode, 0)
        self.assertIn("canonical relative path", traversal.stderr)


if __name__ == "__main__":
    unittest.main()
