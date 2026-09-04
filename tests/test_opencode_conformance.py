from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = json.loads((ROOT / "runtimes/opencode.json").read_text(encoding="utf-8"))
LIFECYCLE = ("setup", "start", "update", "end")


def load_live_module():
    path = ROOT / "adapters/opencode/live_conformance.py"
    spec = importlib.util.spec_from_file_location("opencode_live_conformance", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load OpenCode live conformance module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OpenCodeAdapterTest(unittest.TestCase):
    def test_descriptor_is_first_class_and_repository_native(self) -> None:
        self.assertEqual("first-class", DESCRIPTOR["support_tier"])
        self.assertEqual("native-project-discovery", DESCRIPTOR["install"]["mode"])
        self.assertEqual({"cli"}, set(DESCRIPTOR["surfaces"]))
        surface = DESCRIPTOR["surfaces"]["cli"]
        self.assertEqual("first-class", surface["support_tier"])
        self.assertEqual(["AGENTS.md"], [item["path"] for item in surface["instruction_sources"]])
        self.assertEqual(
            [".agents/skills"], [item["path"] for item in surface["skill_sources"]]
        )
        self.assertEqual(
            {name: f"/context-{name}" for name in LIFECYCLE}, surface["invocation"]
        )

    def test_typed_commands_route_to_one_exact_portable_skill(self) -> None:
        for name in LIFECYCLE:
            with self.subTest(name=name):
                path = ROOT / f".opencode/commands/context-{name}.md"
                text = path.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\n"))
                self.assertEqual(1, text.count(f"`context-{name}`"))
                self.assertIn("Use the `skill` tool", text)
                for other in set(LIFECYCLE) - {name}:
                    self.assertNotIn(f"context-{other}", text)
                self.assertIn("$ARGUMENTS", text)

    def test_adapter_does_not_claim_or_install_unverified_host_state(self) -> None:
        surface = DESCRIPTOR["surfaces"]["cli"]
        self.assertEqual("native", surface["capabilities"]["agent_skills"])
        self.assertEqual("adapter", surface["capabilities"]["explicit_invocation"])
        self.assertEqual("native", surface["capabilities"]["skill_allowlists"])
        self.assertEqual("native", surface["capabilities"]["execution_authorization"])
        self.assertEqual("adapter", surface["capabilities"]["proposal_apply"])
        for capability in ("project_hooks", "blocking_pre_tool_hook", "native_memory"):
            self.assertEqual("unsupported", surface["capabilities"][capability])
        self.assertIsNone(surface["hook_output"])
        for path in (
            "opencode.json",
            ".opencode/opencode.json",
            ".opencode/plugins",
            ".opencode/plugin",
        ):
            self.assertFalse((ROOT / path).exists(), path)

    def test_guide_names_permission_privacy_memory_and_apply_boundaries(self) -> None:
        guide = " ".join(
            (ROOT / "adapters/opencode/README.md").read_text(encoding="utf-8").split()
        )
        for required in (
            "last matching OpenCode permission wins",
            "permission to run shell or edit tools is not approval",
            "Do not use `opencode --auto`",
            "ships no `opencode.json`",
            "ships no OpenCode plugin or hook",
            "Free, trial, and contributor routes may log prompts",
            "no Context OS native-memory bridge",
            "cannot pass on a generic textual answer",
            "exact reviewed commit",
        ):
            with self.subTest(required=required):
                self.assertIn(required, guide)

    def test_read_only_digest_covers_local_lifecycle_artifacts(self) -> None:
        live = load_live_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "AGENTS.md").write_text("# Fixture\n", encoding="utf-8")
            before = live.tree_digest(root)
            proposal = root / ".context-os/proposals/unapproved.json"
            proposal.parent.mkdir(parents=True)
            proposal.write_text("{}\n", encoding="utf-8")
            self.assertNotEqual(before, live.tree_digest(root))

    def test_read_only_digest_covers_empty_directories(self) -> None:
        live = load_live_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = live.tree_digest(root)
            (root / "unexpected-empty-directory").mkdir()
            self.assertNotEqual(before, live.tree_digest(root))

    def test_read_only_digest_excludes_only_opencode_generated_dependencies(self) -> None:
        live = load_live_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".opencode").mkdir()
            before = live.tree_digest(root)
            (root / ".opencode" / ".gitignore").write_text(
                "node_modules\n", encoding="utf-8"
            )
            dependency = root / ".opencode" / "node_modules" / "host-package"
            dependency.mkdir(parents=True)
            (dependency / "index.js").write_text("export {};\n", encoding="utf-8")
            self.assertEqual(before, live.tree_digest(root))
            (root / ".context-os").mkdir()
            self.assertNotEqual(before, live.tree_digest(root))

    @unittest.skipIf(os.name == "nt", "Windows does not preserve POSIX mode changes")
    def test_read_only_digest_covers_mode_changes(self) -> None:
        live = load_live_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "AGENTS.md"
            target.write_text("# Fixture\n", encoding="utf-8")
            before = live.tree_digest(root)
            target.chmod(0o755)
            self.assertNotEqual(before, live.tree_digest(root))

    def test_exact_checkout_binding_rejects_dirty_fixture_source(self) -> None:
        live = load_live_module()
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            target = repo / "AGENTS.md"
            target.write_text("# Fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "AGENTS.md"], cwd=repo, check=True)
            subprocess.run(
                [
                    "git", "-c", "user.name=Context OS", "-c",
                    "user.email=context-os@example.invalid", "commit", "-qm", "fixture",
                ],
                cwd=repo, check=True,
            )
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                text=True, capture_output=True,
            ).stdout.strip()
            self.assertEqual(commit, live.verify_exact_clean_checkout(repo, commit))
            target.write_text("# Dirty fixture\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "must be clean"):
                live.verify_exact_clean_checkout(repo, commit)

    def test_fixture_materializes_verified_commit_not_worktree_bytes(self) -> None:
        live = load_live_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            fixture = root / "fixture"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            target = repo / "AGENTS.md"
            target.write_text("# Committed fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "AGENTS.md"], cwd=repo, check=True)
            subprocess.run(
                [
                    "git", "-c", "user.name=Context OS", "-c",
                    "user.email=context-os@example.invalid", "commit", "-qm", "fixture",
                ],
                cwd=repo, check=True,
            )
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                text=True, capture_output=True,
            ).stdout.strip()
            target.write_text("# Uncommitted replacement\n", encoding="utf-8")
            live.copy_tracked_fixture(repo, fixture, commit)
            self.assertEqual(
                "# Committed fixture\n",
                (fixture / "AGENTS.md").read_text(encoding="utf-8"),
            )

    def test_run_scrubs_inherited_configuration_overrides(self) -> None:
        live = load_live_module()
        inherited = {
            name: "host-value"
            for name in (*live.CONFIG_OVERRIDE_ENV, *live.ISOLATED_HOST_PATH_ENV)
        }
        completed = subprocess.CompletedProcess([], 0, "", "")
        with patch.dict(os.environ, inherited), patch.object(
            live.subprocess, "run", return_value=completed
        ) as mocked:
            live.run(Path("opencode"), ROOT, "--version")
        environment = mocked.call_args.kwargs["env"]
        self.assertEqual("1", environment["OPENCODE_PURE"])
        for name in live.CONFIG_OVERRIDE_ENV:
            self.assertNotIn(name, environment)
        for name in live.ISOLATED_HOST_PATH_ENV:
            self.assertIn(name, environment)
            self.assertNotEqual("host-value", environment[name])

    def test_fixture_path_rejects_windows_drive_relative_names(self) -> None:
        live = load_live_module()
        completed = subprocess.CompletedProcess(
            [], 0, b"100644 blob " + b"0" * 40 + b"\tC:escape\0", b""
        )
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            live.subprocess, "run", return_value=completed
        ):
            root = Path(temporary)
            with self.assertRaisesRegex(RuntimeError, "unsafe tracked path"):
                live.copy_tracked_fixture(root, root / "fixture", "0" * 40)

    def test_exact_skill_read_resolves_relative_to_fixture(self) -> None:
        live = load_live_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_name = "context-start"
            event = json.dumps(
                {
                    "type": "tool_use",
                    "part": {
                        "tool": "read",
                        "state": {
                            "input": {
                                "filePath": f".agents/skills/{skill_name}/SKILL.md"
                            }
                        },
                    },
                }
            )
            self.assertTrue(live.tool_loaded_exact_skill(event, root, skill_name))

    def test_positive_control_requires_exact_bash_command(self) -> None:
        live = load_live_module()
        exact = json.dumps(
            {
                "type": "tool_use",
                "part": {
                    "tool": "bash",
                    "state": {
                        "input": {"command": "echo CONTEXTOS_POSITIVE_SENTINEL"}
                    },
                },
            }
        )
        extra = exact + "\n" + exact.replace("echo ", "echo extra && ", 1)
        self.assertEqual(
            ["echo CONTEXTOS_POSITIVE_SENTINEL"], live.bash_commands(exact)
        )
        self.assertEqual(2, len(live.bash_commands(extra)))


if __name__ == "__main__":
    unittest.main()
