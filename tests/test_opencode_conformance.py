from __future__ import annotations

import json
import importlib.util
import tempfile
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
