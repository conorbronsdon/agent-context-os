import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Shell out to the interpreter running these tests, never a bare "python3".
#
# On Windows "python3" resolves to the Microsoft Store App Execution Alias — a
# stub that prints "Python was not found; run without arguments to install from
# the Microsoft Store" and exits WITHOUT running Python. Every test that shells
# out then reads empty stdout and dies on json.loads(""), which surfaces as
# "Expecting value: line 1 column 1 (char 0)" and looks like a helper bug rather
# than a missing interpreter. That took out 34 of 89 tests.
#
# sys.executable is also correct on POSIX and in a venv, where a bare "python3"
# can be a DIFFERENT interpreter than the one running the suite.
PYTHON = sys.executable


def _symlinks_available() -> bool:
    """Can this process actually create a symlink?

    Probed, not inferred from the OS name: Windows CAN create symlinks when the
    account holds SeCreateSymbolicLinkPrivilege (Developer Mode, or elevated).
    Gating on `os.name == "nt"` would permanently skip these on machines that are
    perfectly capable of running them, and these are security tests -- the cost of
    an unnecessary skip is a real hole in coverage.
    """
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "target").write_text("probe", encoding="utf-8")
        try:
            (base / "link").symlink_to(base / "target")
        except (OSError, NotImplementedError):
            return False
        return True


def _git_tracks_file_mode() -> bool:
    """Does Git record the executable bit on this filesystem?

    Git for Windows sets core.fileMode=false because NTFS has no exec bit to read,
    so a chmod is invisible and a test asserting "the mode change is detected" can
    never pass there. Probed against a scratch repo so the answer reflects the
    filesystem actually under test, not a guess.
    """
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True,
                           capture_output=True)
            value = subprocess.run(["git", "config", "core.fileMode"], cwd=tmp,
                                   capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return False
        return value != "false"


SYMLINKS_AVAILABLE = _symlinks_available()
GIT_TRACKS_FILE_MODE = _git_tracks_file_mode()



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
        # .resolve() matters: on Windows the temp root can come back as an 8.3
        # SHORT NAME (C:\Users\RUNNER~1\... on GitHub's runners). The fixture
        # records this path in .context-os/memory-directory, and the helper
        # rightly rejects a non-canonical binding -- so an unresolved tempdir
        # fails most of the suite with "must be canonical with no '..' or
        # symlinks", blaming the binding rather than the fixture. It reproduces
        # only where the account name exceeds 8 characters, which is why a local
        # Windows run can pass while CI does not.
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "repo"
        self.memory = self.root / "memory"
        self.repo.mkdir()
        self.memory.mkdir()
        run(["git", "init", "-q"], self.repo)
        run(["git", "config", "user.name", "Dream Test"], self.repo)
        run(["git", "config", "user.email", "dream@example.invalid"], self.repo)
        self.pin_line_endings(self.repo)
        run(["git", "init", "-q"], self.memory)
        run(["git", "config", "user.name", "Dream Memory"], self.memory)
        run(["git", "config", "user.email", "dream-memory@example.invalid"], self.memory)
        self.pin_line_endings(self.memory)
        (self.repo / ".context-os").mkdir()
        (self.repo / ".context-os" / "memory-directory").write_text(
            f"{self.memory}\n", encoding="utf-8"
        )
        identity = run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], self.repo
        ).stdout.strip()
        (self.memory / ".context-os-repository").write_text(f"{identity}\n", encoding="utf-8")
        (self.memory / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
        self.write_archive()
        (self.memory / "project_alpha.md").write_text(
            "---\nname: Project Alpha\ntype: project\n---\nalpha\n", encoding="utf-8"
        )
        (self.memory / "project_beta.md").write_text(
            "---\nname: Project Beta\ntype: project\n---\nbeta\n", encoding="utf-8"
        )
        run(["git", "add", "-A"], self.memory)
        run(["git", "commit", "-qm", "baseline"], self.memory)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def pin_line_endings(repo: Path) -> None:
        """Stop the host's Git config from rewriting bytes these tests hash.

        Git for Windows sets core.autocrlf=true at SYSTEM level, so a fixture repo
        inherits it even though nothing here asks for it. The suite then compares a
        digest of worktree bytes against the staged blob: Python's write_text()
        emits CRLF on Windows, autocrlf normalizes it back to LF on `git add`, the
        two digests differ, and the failure reads "staged bytes do not match the
        reviewed change digest" -- i.e. exactly like the tamper-detection working
        as designed, which is the worst possible disguise for an environment bug.

        Pinned per-repo rather than relying on a global, so the suite is
        deterministic regardless of how the developer's Git is configured.
        """
        run(["git", "config", "core.autocrlf", "false"], repo)
        run(["git", "config", "core.eol", "lf"], repo)

    @staticmethod
    def msys(path: Path) -> str:
        """Spell a native Windows path the way Git Bash would (drive letter to /c/... form)."""
        drive, rest = str(path).split(":", 1)
        return f"/{drive.lower()}{rest.replace(chr(92), '/')}"

    @unittest.skipUnless(os.name == "nt", "the binding is already native on POSIX")
    def test_msys_spelled_binding_is_accepted(self) -> None:
        (self.repo / ".context-os" / "memory-directory").write_text(
            self.msys(self.memory) + "\n", encoding="utf-8"
        )
        resolved = self.helper("resolve")
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        self.assertEqual(json.loads(resolved.stdout)["memory_dir"], str(self.memory))

    @unittest.skipUnless(os.name == "nt", "the marker is already native on POSIX")
    def test_msys_spelled_marker_is_accepted(self) -> None:
        identity = run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], self.repo
        ).stdout.strip()
        (self.memory / ".context-os-repository").write_text(
            self.msys(Path(identity).resolve()) + "\n", encoding="utf-8"
        )
        # resolve also demands a clean memory repo, so commit the rewritten marker
        # or this asserts on the wrong failure.
        run(["git", "add", "-A"], self.memory)
        run(["git", "commit", "-qm", "msys marker"], self.memory)
        resolved = self.helper("resolve")
        self.assertEqual(resolved.returncode, 0, resolved.stderr)

    @unittest.skipUnless(os.name == "nt", "Windows-only spelling")
    def test_a_wrong_marker_is_still_rejected_when_msys_spelled(self) -> None:
        """Translating the spelling must not become a way to smuggle a
        mismatched identity past the check."""
        (self.memory / ".context-os-repository").write_text(
            "/c/definitely/not/this/repo/.git\n", encoding="utf-8"
        )
        self.assertIn("marker", self.assert_rejects("resolve"))

    @unittest.skipUnless(os.name == "nt", "Windows-only spelling")
    def test_a_noncanonical_msys_path_is_still_rejected(self) -> None:
        """Translating the spelling must not translate away the '..' check.

        Uses <memory>/../memory, which RESOLVES to a real directory -- so it gets
        past the existence gate and has to be caught by the canonical check
        itself, rather than incidentally failing because the path is missing.
        """
        (self.repo / ".context-os" / "memory-directory").write_text(
            self.msys(self.memory) + "/../" + self.memory.name + "\n", encoding="utf-8"
        )
        self.assertIn("canonical", self.assert_rejects("resolve"))

    def helper(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        normalized = list(args)
        if (
            normalized
            and normalized[0] == "artifact"
            and "--for-create" not in normalized
            and "--for-commit" not in normalized
        ):
            normalized.append("--for-commit")
        return run([PYTHON, str(HELPER), *normalized], cwd or self.repo, check=False)

    def write_archive(self, *rows: str) -> None:
        (self.memory / "ARCHIVE.md").write_text(
            "# Archive\n\n| Date | Memory | Reason |\n|---|---|---|\n"
            + "".join(rows),
            encoding="utf-8",
        )

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
                PYTHON,
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

    @unittest.skipUnless(SYMLINKS_AVAILABLE, "needs symlink privilege (Windows: Developer Mode)")
    def test_artifact_rejects_symlinked_components(self) -> None:
        (self.memory / ".dreams").symlink_to(self.root)
        self.assertIn("symlink", self.assert_rejects("artifact", "2026-08-15T10-19-00Z"))

    @unittest.skipUnless(SYMLINKS_AVAILABLE, "needs symlink privilege (Windows: Developer Mode)")
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

    def test_change_allowlist_counts_both_sides_of_a_rename(self) -> None:
        (self.memory / "archive").mkdir()
        run(
            [
                "git",
                "mv",
                "project_alpha.md",
                "archive/project_alpha.md",
            ],
            self.memory,
        )

        destination_only = self.helper(
            "changes", "--allow", "archive/project_alpha.md"
        )
        self.assertNotEqual(destination_only.returncode, 0)
        self.assertIn("project_alpha.md", destination_only.stderr)

        reviewed = self.helper(
            "changes",
            "--allow",
            "project_alpha.md",
            "--allow",
            "archive/project_alpha.md",
        )
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        payload = json.loads(reviewed.stdout)
        self.assertEqual(
            payload["changed_paths"],
            ["archive/project_alpha.md", "project_alpha.md"],
        )

        staged = self.helper(
            "changes",
            "--staged",
            "--expect-digest",
            payload["change_digest"],
            "--allow",
            "project_alpha.md",
            "--allow",
            "archive/project_alpha.md",
        )
        self.assertEqual(staged.returncode, 0, staged.stderr)
        snapshot = json.loads(staged.stdout)
        self.assertEqual(snapshot["source"], "index")
        with (self.memory / ".git" / "info" / "exclude").open(
            "a", encoding="utf-8"
        ) as exclude:
            exclude.write("project_alpha.md\n")
        (self.memory / "project_alpha.md").write_text(
            "concurrent live resurrection\n", encoding="utf-8"
        )
        self.assertEqual(
            run(["git", "check-ignore", "project_alpha.md"], self.memory).returncode,
            0,
        )
        resurrected = self.helper(
            "commit",
            "--tree",
            snapshot["tree_sha"],
            "--base-head",
            snapshot["base_head"],
            "--head-ref",
            snapshot["head_ref"],
            "--expect-digest",
            payload["change_digest"],
            "--allow",
            "project_alpha.md",
            "--allow",
            "archive/project_alpha.md",
            "--message",
            "reviewed archive move",
        )
        self.assertNotEqual(resurrected.returncode, 0)
        self.assertIn("reviewed deleted paths reappeared", resurrected.stderr)
        (self.memory / "project_alpha.md").unlink()
        committed = self.helper(
            "commit",
            "--tree",
            snapshot["tree_sha"],
            "--base-head",
            snapshot["base_head"],
            "--head-ref",
            snapshot["head_ref"],
            "--expect-digest",
            payload["change_digest"],
            "--allow",
            "project_alpha.md",
            "--allow",
            "archive/project_alpha.md",
            "--message",
            "reviewed archive move",
        )
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.assertEqual(
            run(["git", "rev-parse", "HEAD^{tree}"], self.memory).stdout.strip(),
            snapshot["tree_sha"],
        )

    def test_staged_digest_rejects_same_path_replacement(self) -> None:
        target = self.memory / "project_alpha.md"
        target.write_text("reviewed replacement\n", encoding="utf-8")
        reviewed = self.helper("changes", "--allow", "project_alpha.md")
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        digest = json.loads(reviewed.stdout)["change_digest"]

        target.write_text("UNREVIEWED REPLACEMENT\n", encoding="utf-8")
        run(["git", "add", "--", "project_alpha.md"], self.memory)
        replaced = self.helper(
            "changes",
            "--staged",
            "--expect-digest",
            digest,
            "--allow",
            "project_alpha.md",
        )
        self.assertNotEqual(replaced.returncode, 0)
        self.assertIn("staged bytes do not match", replaced.stderr)

    def test_staged_digest_accepts_exact_reviewed_bytes_only(self) -> None:
        target = self.memory / "project_alpha.md"
        target.write_text("reviewed replacement\n", encoding="utf-8")
        reviewed = self.helper("changes", "--allow", "project_alpha.md")
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        digest = json.loads(reviewed.stdout)["change_digest"]
        run(["git", "add", "--", "project_alpha.md"], self.memory)

        staged = self.helper(
            "changes",
            "--staged",
            "--expect-digest",
            digest,
            "--allow",
            "project_alpha.md",
        )
        self.assertEqual(staged.returncode, 0, staged.stderr)
        self.assertEqual(json.loads(staged.stdout)["change_digest"], digest)

    @unittest.skipUnless(GIT_TRACKS_FILE_MODE, "git core.fileMode is false; no exec bit on this filesystem")
    def test_staged_digest_rejects_unreviewed_mode_change(self) -> None:
        target = self.memory / "project_alpha.md"
        target.write_text("reviewed replacement\n", encoding="utf-8")
        reviewed = self.helper("changes", "--allow", "project_alpha.md")
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        digest = json.loads(reviewed.stdout)["change_digest"]

        target.chmod(0o755)
        run(["git", "add", "--", "project_alpha.md"], self.memory)
        replaced = self.helper(
            "changes",
            "--staged",
            "--expect-digest",
            digest,
            "--allow",
            "project_alpha.md",
        )
        self.assertNotEqual(replaced.returncode, 0)
        self.assertIn("staged bytes do not match", replaced.stderr)

    def test_immutable_tree_surfaces_pre_snapshot_replacement(self) -> None:
        target = self.memory / "project_alpha.md"
        target.write_text("USER-REVIEWED RESULT\n", encoding="utf-8")
        target.write_text("UNREVIEWED PRE-SNAPSHOT REPLACEMENT\n", encoding="utf-8")
        candidate = self.helper("changes", "--allow", "project_alpha.md")
        self.assertEqual(candidate.returncode, 0, candidate.stderr)
        digest = json.loads(candidate.stdout)["change_digest"]
        run(["git", "add", "--", "project_alpha.md"], self.memory)
        snapshot = self.helper(
            "changes",
            "--staged",
            "--expect-digest",
            digest,
            "--allow",
            "project_alpha.md",
        )
        self.assertEqual(snapshot.returncode, 0, snapshot.stderr)
        payload = json.loads(snapshot.stdout)
        immutable_diff = run(
            ["git", "diff", payload["base_head"], payload["tree_sha"], "--"],
            self.memory,
        ).stdout
        self.assertIn("UNREVIEWED PRE-SNAPSHOT REPLACEMENT", immutable_diff)
        self.assertNotIn("USER-REVIEWED RESULT", immutable_diff)

    def test_tree_bound_commit_rejects_post_snapshot_index_replacement(self) -> None:
        target = self.memory / "project_alpha.md"
        target.write_text("USER-REVIEWED RESULT\n", encoding="utf-8")
        candidate = self.helper("changes", "--allow", "project_alpha.md")
        digest = json.loads(candidate.stdout)["change_digest"]
        run(["git", "add", "--", "project_alpha.md"], self.memory)
        snapshot = self.helper(
            "changes",
            "--staged",
            "--expect-digest",
            digest,
            "--allow",
            "project_alpha.md",
        )
        self.assertEqual(snapshot.returncode, 0, snapshot.stderr)
        payload = json.loads(snapshot.stdout)

        target.write_text("UNREVIEWED POST-SNAPSHOT REPLACEMENT\n", encoding="utf-8")
        run(["git", "add", "--", "project_alpha.md"], self.memory)
        rejected = self.helper(
            "commit",
            "--tree",
            payload["tree_sha"],
            "--base-head",
            payload["base_head"],
            "--head-ref",
            payload["head_ref"],
            "--expect-digest",
            digest,
            "--allow",
            "project_alpha.md",
            "--message",
            "reviewed memory update",
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("index changed", rejected.stderr)
        self.assertEqual(
            run(["git", "rev-parse", "HEAD"], self.memory).stdout.strip(),
            payload["base_head"],
        )

    def test_tree_bound_commit_rejects_post_snapshot_untracked_path(self) -> None:
        target = self.memory / "project_alpha.md"
        target.write_text("USER-REVIEWED RESULT\n", encoding="utf-8")
        candidate = self.helper("changes", "--allow", "project_alpha.md")
        digest = json.loads(candidate.stdout)["change_digest"]
        run(["git", "add", "--", "project_alpha.md"], self.memory)
        snapshot = self.helper(
            "changes",
            "--staged",
            "--expect-digest",
            digest,
            "--allow",
            "project_alpha.md",
        )
        payload = json.loads(snapshot.stdout)

        (self.memory / "unrelated-private.md").write_text(
            "must remain uncommitted\n", encoding="utf-8"
        )
        rejected = self.helper(
            "commit",
            "--tree",
            payload["tree_sha"],
            "--base-head",
            payload["base_head"],
            "--head-ref",
            payload["head_ref"],
            "--expect-digest",
            digest,
            "--allow",
            "project_alpha.md",
            "--message",
            "reviewed memory update",
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("untracked paths", rejected.stderr)
        self.assertIn("unrelated-private.md", rejected.stderr)
        self.assertEqual(
            run(["git", "rev-parse", "HEAD"], self.memory).stdout.strip(),
            payload["base_head"],
        )

    def test_tree_bound_commit_writes_exact_approved_tree(self) -> None:
        run(["git", "branch", "-m", "feature@local+safe"], self.memory)
        target = self.memory / "project_alpha.md"
        target.write_text("USER-REVIEWED RESULT\n", encoding="utf-8")
        candidate = self.helper("changes", "--allow", "project_alpha.md")
        digest = json.loads(candidate.stdout)["change_digest"]
        run(["git", "add", "--", "project_alpha.md"], self.memory)
        snapshot = self.helper(
            "changes",
            "--staged",
            "--expect-digest",
            digest,
            "--allow",
            "project_alpha.md",
        )
        payload = json.loads(snapshot.stdout)
        self.assertEqual(payload["head_ref"], "refs/heads/feature@local+safe")
        committed = self.helper(
            "commit",
            "--tree",
            payload["tree_sha"],
            "--base-head",
            payload["base_head"],
            "--head-ref",
            payload["head_ref"],
            "--expect-digest",
            digest,
            "--allow",
            "project_alpha.md",
            "--message",
            "reviewed memory update",
        )
        self.assertEqual(committed.returncode, 0, committed.stderr)
        result = json.loads(committed.stdout)
        self.assertEqual(result["tree_sha"], payload["tree_sha"])
        self.assertEqual(
            run(["git", "rev-parse", "HEAD^{tree}"], self.memory).stdout.strip(),
            payload["tree_sha"],
        )
        self.assertEqual(
            run(["git", "show", "HEAD:project_alpha.md"], self.memory).stdout,
            "USER-REVIEWED RESULT\n",
        )

    def test_tree_bound_commit_rejects_changed_symbolic_head(self) -> None:
        target = self.memory / "project_alpha.md"
        target.write_text("USER-REVIEWED RESULT\n", encoding="utf-8")
        candidate = self.helper("changes", "--allow", "project_alpha.md")
        digest = json.loads(candidate.stdout)["change_digest"]
        run(["git", "add", "--", "project_alpha.md"], self.memory)
        snapshot = self.helper(
            "changes",
            "--staged",
            "--expect-digest",
            digest,
            "--allow",
            "project_alpha.md",
        )
        payload = json.loads(snapshot.stdout)
        run(["git", "branch", "alternate", payload["base_head"]], self.memory)
        run(["git", "symbolic-ref", "HEAD", "refs/heads/alternate"], self.memory)
        rejected = self.helper(
            "commit",
            "--tree",
            payload["tree_sha"],
            "--base-head",
            payload["base_head"],
            "--head-ref",
            payload["head_ref"],
            "--expect-digest",
            digest,
            "--allow",
            "project_alpha.md",
            "--message",
            "reviewed memory update",
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("HEAD identity changed", rejected.stderr)
        self.assertEqual(
            run(["git", "rev-parse", "refs/heads/alternate"], self.memory).stdout.strip(),
            payload["base_head"],
        )

    def test_staged_snapshot_rejects_detached_head(self) -> None:
        run(["git", "checkout", "--detach"], self.memory)
        (self.memory / "project_alpha.md").write_text(
            "reviewed replacement\n", encoding="utf-8"
        )
        candidate = self.helper("changes", "--allow", "project_alpha.md")
        digest = json.loads(candidate.stdout)["change_digest"]
        run(["git", "add", "--", "project_alpha.md"], self.memory)
        staged = self.helper(
            "changes",
            "--staged",
            "--expect-digest",
            digest,
            "--allow",
            "project_alpha.md",
        )
        self.assertNotEqual(staged.returncode, 0)
        self.assertIn("requires HEAD to name a local branch", staged.stderr)

    def test_archive_state_handles_stamped_and_unstamped_resume(self) -> None:
        self.write_archive(
            "| 2026-08-10 | [project_alpha.md](archive/project_alpha.md) | retired |\n",
        )
        unstamped = self.helper(
            "archive-state", "project_alpha.md", "--today", "2026-08-15"
        )
        self.assertEqual(unstamped.returncode, 0, unstamped.stderr)
        first = json.loads(unstamped.stdout)
        self.assertEqual(first["status"], "resume")
        self.assertEqual(first["archive_date"], "2026-08-10")
        self.assertFalse(first["append_row"])
        self.assertTrue(first["insert_stamp"])

        (self.memory / "project_alpha.md").write_text(
            "---\narchived: 2026-08-10\n---\nalpha\n", encoding="utf-8"
        )
        stamped = self.helper(
            "archive-state", "project_alpha.md", "--today", "2026-08-15"
        )
        self.assertEqual(stamped.returncode, 0, stamped.stderr)
        second = json.loads(stamped.stdout)
        self.assertEqual(second["status"], "resume")
        self.assertFalse(second["append_row"])
        self.assertFalse(second["insert_stamp"])

        (self.memory / "project_alpha.md").write_text(
            "---\narchived: 2026-08-10\narchived: 2026-08-10\n---\nalpha\n",
            encoding="utf-8",
        )
        self.assertIn(
            "duplicate archived stamps",
            self.assert_rejects(
                "archive-state", "project_alpha.md", "--today", "2026-08-15"
            ),
        )

    def test_archive_state_ignores_archived_examples_outside_frontmatter(self) -> None:
        (self.memory / "project_alpha.md").write_text(
            "---\nname: Project Alpha\ntype: project\n---\n\n"
            "Example body text:\narchived: 2026-08-15\n\n"
            "```yaml\narchived: 2026-08-09\n```\n",
            encoding="utf-8",
        )
        state = self.helper(
            "archive-state", "project_alpha.md", "--today", "2026-08-15"
        )
        self.assertEqual(state.returncode, 0, state.stderr)
        payload = json.loads(state.stdout)
        self.assertEqual(payload["status"], "fresh")
        self.assertTrue(payload["insert_stamp"])

        (self.memory / "archive").mkdir()
        (self.memory / "project_alpha.md").replace(
            self.memory / "archive" / "project_alpha.md"
        )
        self.write_archive(
            "| 2026-08-15 | [Project Alpha](archive/project_alpha.md) | retired |\n",
        )
        completed = self.helper(
            "archive-state", "project_alpha.md", "--today", "2026-08-15"
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("completed archive stamp", completed.stderr)

    def test_archive_state_requires_closed_leading_frontmatter(self) -> None:
        for content, expected in (
            ("alpha\narchived: 2026-08-15\n", "must begin with YAML frontmatter"),
            ("---\nname: Alpha\narchived: 2026-08-15\n", "unterminated YAML frontmatter"),
            (
                "---\nname: Alpha\n\"archived\": 2026-08-15\n---\nalpha\n",
                "malformed archived field",
            ),
        ):
            with self.subTest(content=content):
                (self.memory / "project_alpha.md").write_text(
                    content, encoding="utf-8"
                )
                self.assertIn(
                    expected,
                    self.assert_rejects(
                        "archive-state", "project_alpha.md", "--today", "2026-08-15"
                    ),
                )

    def test_archive_state_matches_row_by_destination_and_validates_date(self) -> None:
        (self.memory / "project_alpha.md").write_text(
            "---\nname: Project Alpha\ntype: project\n---\nalpha\n",
            encoding="utf-8",
        )
        self.write_archive(
            "| 2026-08-10 | [Human-readable label](archive/project_alpha.md) | retired |\n",
        )
        state = self.helper(
            "archive-state", "project_alpha.md", "--today", "2026-08-15"
        )
        self.assertEqual(state.returncode, 0, state.stderr)
        payload = json.loads(state.stdout)
        self.assertEqual(payload["status"], "resume")
        self.assertEqual(payload["archive_date"], "2026-08-10")

        self.write_archive(
            "| 2026-08-10 | [Alpha \\| historical](archive/project_alpha.md) | first |\n",
        )
        escaped_label = self.helper(
            "archive-state", "project_alpha.md", "--today", "2026-08-15"
        )
        self.assertEqual(escaped_label.returncode, 0, escaped_label.stderr)
        escaped_payload = json.loads(escaped_label.stdout)
        self.assertEqual(escaped_payload["status"], "resume")
        self.assertFalse(escaped_payload["append_row"])

        self.write_archive(
            "| 2026-08-10 | [Alpha \\| historical](archive/project_alpha.md) | first |\n"
            "| 2026-08-15 | [Project Alpha](archive/project_alpha.md) | second |\n",
        )
        self.assertIn(
            "duplicate rows",
            self.assert_rejects(
                "archive-state", "project_alpha.md", "--today", "2026-08-15"
            ),
        )

        self.write_archive(
            "| 2026-08-10 | [Beta](archive/project_beta.md) | "
            "see archive/project_alpha.md for context |\n",
        )
        unrelated_reason = self.helper(
            "archive-state", "project_alpha.md", "--today", "2026-08-15"
        )
        self.assertEqual(unrelated_reason.returncode, 0, unrelated_reason.stderr)
        self.assertEqual(json.loads(unrelated_reason.stdout)["status"], "fresh")

        self.write_archive(
            "```markdown\n"
            "| 2026-08-10 | [Project Alpha](archive/project_alpha.md) | example |\n"
            "```\n"
        )
        fenced_row = self.helper(
            "archive-state", "project_alpha.md", "--today", "2026-08-15"
        )
        self.assertEqual(fenced_row.returncode, 0, fenced_row.stderr)
        self.assertEqual(json.loads(fenced_row.stdout)["status"], "fresh")

        for hidden_table in (
            "# Archive\n\n```md\n| Date | Memory | Reason |\n|---|---|---|\n"
            "| 2026-08-10 | [A](archive/project_alpha.md) | example |\n```\n",
            "# Archive\n\n<!--\n| Date | Memory | Reason |\n|---|---|---|\n"
            "| 2026-08-10 | [A](archive/project_alpha.md) | example |\n-->\n",
        ):
            with self.subTest(hidden_table=hidden_table):
                (self.memory / "ARCHIVE.md").write_text(
                    hidden_table, encoding="utf-8"
                )
                self.assertIn(
                    "canonical archive table",
                    self.assert_rejects(
                        "archive-state",
                        "project_alpha.md",
                        "--today",
                        "2026-08-15",
                    ),
                )

        for mixed_fence in (
            "# Archive\n\n```~example\n| Date | Memory | Reason |\n|---|---|---|\n"
            "| 2026-08-10 | [A](archive/project_alpha.md) | example |\n```\n```\n",
            "# Archive\n\n~~~`example\n| Date | Memory | Reason |\n|---|---|---|\n"
            "| 2026-08-10 | [A](archive/project_alpha.md) | example |\n~~~\n~~~\n",
        ):
            with self.subTest(mixed_fence=mixed_fence):
                (self.memory / "ARCHIVE.md").write_text(
                    mixed_fence, encoding="utf-8"
                )
                self.assertIn(
                    "unterminated fenced block",
                    self.assert_rejects(
                        "archive-state",
                        "project_alpha.md",
                        "--today",
                        "2026-08-15",
                    ),
                )

        self.write_archive(
            "| 2026-08-10 | [Project Alpha](archive/project_alpha.md) | retired |\n"
            "| 2026-08-10 | [Another label](archive/project_alpha.md) | duplicate |\n",
        )
        self.assertIn(
            "duplicate rows",
            self.assert_rejects(
                "archive-state", "project_alpha.md", "--today", "2026-08-15"
            ),
        )

        self.write_archive(
            "| 2026-02-30 | [Project Alpha](archive/project_alpha.md) | retired |\n",
        )
        self.assertIn(
            "not a valid calendar date",
            self.assert_rejects(
                "archive-state", "project_alpha.md", "--today", "2026-08-15"
            ),
        )

    def test_archive_state_rejects_noncanonical_dates(self) -> None:
        self.assertIn(
            "must match YYYY-MM-DD",
            self.assert_rejects(
                "archive-state", "project_alpha.md", "--today", "2026-8-5"
            ),
        )

        (self.memory / "project_alpha.md").write_text(
            "---\nname: Project Alpha\narchived: 2026-8-5\n---\nalpha\n",
            encoding="utf-8",
        )
        self.assertIn(
            "archive target archived date must match YYYY-MM-DD",
            self.assert_rejects(
                "archive-state", "project_alpha.md", "--today", "2026-08-05"
            ),
        )

        (self.memory / "project_alpha.md").write_text(
            "---\nname: Project Alpha\n---\nalpha\n", encoding="utf-8"
        )
        self.write_archive(
            "| 2026-8-5 | [Project Alpha](archive/project_alpha.md) | retired |\n",
        )
        self.assertIn(
            "archive index row date must match YYYY-MM-DD",
            self.assert_rejects(
                "archive-state", "project_alpha.md", "--today", "2026-08-05"
            ),
        )

    def test_archive_state_rejects_mismatched_stamp(self) -> None:
        self.write_archive(
            "| 2026-08-10 | [project_alpha.md](archive/project_alpha.md) | retired |\n",
        )
        (self.memory / "project_alpha.md").write_text(
            "---\narchived: 2026-08-09\n---\nalpha\n", encoding="utf-8"
        )
        self.assertIn(
            "does not match",
            self.assert_rejects(
                "archive-state", "project_alpha.md", "--today", "2026-08-15"
            ),
        )


if __name__ == "__main__":
    unittest.main()


WINDOWS = os.name == "nt"


class NativePathTests(unittest.TestCase):
    """docs/auto-memory.md builds both recorded paths in bash, so on Windows they
    arrive MSYS-spelled (/c/Users/...). These cover the translation AND, more
    importantly, that translating a path does not let a bad one through."""

    def setUp(self) -> None:
        spec = importlib.util.spec_from_file_location("validate_memory", HELPER)
        self.vm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.vm)

    @unittest.skipUnless(WINDOWS, "MSYS spellings only need translating on Windows")
    def test_translates_msys_and_cygwin_drive_forms(self) -> None:
        self.assertEqual(self.vm.native_path("/c/Users/me/memory"), r"C:\Users\me\memory")
        self.assertEqual(self.vm.native_path("/cygdrive/c/Users/me/memory"), r"C:\Users\me\memory")
        self.assertEqual(self.vm.native_path("/D/data"), r"D:\data")

    @unittest.skipUnless(WINDOWS, "Windows-only spelling")
    def test_leaves_native_windows_paths_untouched(self) -> None:
        for raw in (r"C:\Users\me\memory", "C:/Users/me/memory"):
            self.assertEqual(self.vm.native_path(raw), raw)

    @unittest.skipIf(WINDOWS, "on POSIX /c/... is a real path, not a drive")
    def test_is_a_no_op_on_posix(self) -> None:
        for raw in ("/c/Users/me/memory", "/cygdrive/c/x", "/home/me/memory"):
            self.assertEqual(self.vm.native_path(raw), raw)

    def test_does_not_invent_a_path_for_junk(self) -> None:
        """Untranslatable input must come back unchanged so the caller's own
        checks reject it, rather than being guessed into something plausible."""
        self.assertEqual(self.vm.native_path("relative/not/absolute"), "relative/not/absolute")
