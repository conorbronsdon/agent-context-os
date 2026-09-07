"""Validate the optional plugin's distribution metadata, not host enforcement."""

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CodexPluginPackageTests(unittest.TestCase):
    def test_plugin_exposes_only_the_workspace_companion(self):
        manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "agent-context-os")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertNotIn("hooks", manifest)
        self.assertNotIn("mcpServers", manifest)
        skills = sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / "skills").glob("*/SKILL.md"))
        self.assertEqual(skills, ["skills/contextos-workspace/SKILL.md"])

    def test_plugin_files_are_not_managed_workspace_outputs(self):
        inventory = json.loads((ROOT / "components/manifest.json").read_text(encoding="utf-8"))
        owners = {
            entry["path"]: (component["id"], entry["policy"])
            for component in inventory["components"]
            for entry in component["paths"]
        }
        for path in (".codex-plugin/plugin.json", ".codexignore", "skills/contextos-workspace/SKILL.md"):
            self.assertEqual(owners[path], ("codex-adapter", "development"))
            self.assertTrue((ROOT / path).is_file())


if __name__ == "__main__":
    unittest.main()
