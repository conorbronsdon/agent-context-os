from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

from adapters.hermes import live_conformance as live


ROOT = Path(__file__).resolve().parents[1]


class HermesConformanceTest(unittest.TestCase):
    def test_tracked_docs_use_namespaced_hermes_commands(self) -> None:
        listed = subprocess.run(["git", "ls-files", "-z", "--", "*.md"], cwd=ROOT,
                                capture_output=True, check=True).stdout
        short = re.compile(r"`/(?:setup|start|update|end)`")
        for raw in listed.split(b"\0"):
            if not raw:
                continue
            path = ROOT / raw.decode("utf-8")
            content = path.read_text(encoding="utf-8")
            hermes_column = None
            for line in content.splitlines():
                if line.startswith("|"):
                    cells = [cell.strip() for cell in line.strip("|").split("|")]
                    headers = [i for i, cell in enumerate(cells)
                               if re.fullmatch(r"Hermes(?: \(experimental\))?", cell)]
                    if headers:
                        hermes_column = headers[0]
                    elif hermes_column is not None and len(cells) > hermes_column:
                        self.assertFalse(short.search(cells[hermes_column]), f"{path}: {line}")
                elif line.strip() and not line.startswith("|"):
                    hermes_column = None
            prose = re.compile(r"(?i)(?:run|invoke|type|use)\s+`/(?:setup|start|update|end)`\s+in\s+[^,.]*Hermes|Hermes[^,.]*(?:run|invoke|type|use)\s+`/(?:setup|start|update|end)`")
            self.assertIsNone(prose.search(content), str(path))

    def test_lifecycle_is_complete_and_canonical(self) -> None:
        descriptor = json.loads((ROOT / "runtimes/hermes.json").read_text(encoding="utf-8"))
        self.assertEqual("experimental", descriptor["support_tier"])
        self.assertEqual({phase: f"/context-{phase}" for phase in live.PHASES},
                         descriptor["surfaces"]["cli"]["invocation"])
        guide = (ROOT / "adapters/hermes/README.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for phase in live.PHASES:
            self.assertIn(f"/context-{phase}", guide)
            self.assertIn(f"/context-{phase}", agents)
            self.assertIn(f"/context-{phase}", readme)
        self.assertIn("hermes skills list --source local", guide)
        self.assertIn("hermes skills list --source local", agents)
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

    def test_short_alias_claim_is_only_a_hint(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        guide = (ROOT / "adapters/hermes/README.md").read_text(encoding="utf-8")
        self.assertIn("Alias invocation needs a future live control", agents)
        self.assertIn("their invocation still needs a live control", guide)


if __name__ == "__main__":
    unittest.main()
