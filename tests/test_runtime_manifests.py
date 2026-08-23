from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from contextos.kernel import ContextOSError, runtime_manifest


ROOT = Path(__file__).resolve().parents[1]


class RuntimeManifestTest(unittest.TestCase):
    def test_manifests_have_complete_lifecycle_and_capabilities(self) -> None:
        required_capabilities = {
            "agent_skills", "explicit_invocation", "project_hooks",
            "blocking_pre_tool_hook", "mcp", "native_memory", "proposal_apply",
        }
        for runtime in ("claude", "codex", "hermes"):
            with self.subTest(runtime=runtime):
                manifest = json.loads((ROOT / "runtimes" / f"{runtime}.json").read_text(encoding="utf-8"))
                self.assertEqual(1, manifest["schema_version"])
                self.assertEqual(runtime, manifest["runtime"])
                self.assertEqual({"setup", "start", "update", "end"}, set(manifest["invocation"]))
                self.assertEqual(required_capabilities, set(manifest["capabilities"]))
                self.assertTrue(manifest["install"]["next_steps"])

    def test_short_aliases_match_runtime_invocations(self) -> None:
        claude = json.loads((ROOT / "runtimes/claude.json").read_text())
        codex = json.loads((ROOT / "runtimes/codex.json").read_text())
        hermes = json.loads((ROOT / "runtimes/hermes.json").read_text())
        for name in ("setup", "start", "update", "end"):
            self.assertEqual(f"/{name}", claude["invocation"][name])
            self.assertEqual(f"${name}", codex["invocation"][name])
            self.assertEqual(f"/{name}", hermes["invocation"][name])

    def test_kernel_rejects_schema_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "runtimes").mkdir()
            manifest = json.loads((ROOT / "runtimes/codex.json").read_text(encoding="utf-8"))
            manifest["capabilities"]["mcp"] = "invented"
            (root / "runtimes/codex.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ContextOSError, "invalid runtime manifest"):
                runtime_manifest(root, "codex")


if __name__ == "__main__":
    unittest.main()
