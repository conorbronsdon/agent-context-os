from __future__ import annotations

import json
import unittest
from pathlib import Path

from adapters.hermes import live_conformance as live


ROOT = Path(__file__).resolve().parents[1]


class HermesConformanceTest(unittest.TestCase):
    def test_lifecycle_is_complete_and_canonical(self) -> None:
        descriptor = json.loads((ROOT / "runtimes/hermes.json").read_text(encoding="utf-8"))
        self.assertEqual("experimental", descriptor["support_tier"])
        self.assertEqual({phase: f"/{phase}" for phase in live.PHASES},
                         descriptor["surfaces"]["cli"]["invocation"])
        self.assertEqual(8, len(live.SKILLS))
        for phase in live.PHASES:
            alias = (ROOT / ".agents/skills" / phase / "SKILL.md").read_text(encoding="utf-8")
            core = (ROOT / ".agents/skills" / f"context-{phase}" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(f"../context-{phase}/SKILL.md", alias)
            self.assertIn("bash scripts/contextos.sh", core)
            if phase == "start":
                self.assertIn("read-only", core)
            else:
                self.assertIn("--confirm <digest>", core)
                self.assertIn("proposal", core)

    def test_hook_and_memory_boundaries(self) -> None:
        descriptor = json.loads((ROOT / "runtimes/hermes.json").read_text(encoding="utf-8"))
        surface = descriptor["surfaces"]["cli"]
        self.assertEqual("allow-message", surface["hook_output"])
        self.assertEqual("advisory", surface["capabilities"]["blocking_pre_tool_hook"])
        hooks = (ROOT / "adapters/hermes/hooks.example.yaml").read_text(encoding="utf-8")
        self.assertIn("session-start", hooks)
        self.assertIn("pre-write", hooks)
        guide = (ROOT / "adapters/hermes/README.md").read_text(encoding="utf-8")
        for phrase in ("MEMORY.md", "USER.md", "host-local", "advisory", "exact-digest", "HERMES_HOME"):
            self.assertIn(phrase, guide)


if __name__ == "__main__":
    unittest.main()
