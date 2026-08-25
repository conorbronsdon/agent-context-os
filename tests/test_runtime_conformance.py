from __future__ import annotations

import unittest
from pathlib import Path

from contextos.kernel import runtime_hook_payload, runtime_registry, runtime_surface


ROOT = Path(__file__).resolve().parents[1]


class RuntimeConformanceTest(unittest.TestCase):
    """Must-work adapter controls; authenticated host launches remain opt-in."""

    def test_first_class_surfaces_expose_complete_lifecycle(self) -> None:
        for runtime, manifest in runtime_registry(ROOT).items():
            for surface_id, surface in manifest["surfaces"].items():
                with self.subTest(runtime=runtime, surface=surface_id):
                    if surface["support_tier"] == "first-class":
                        self.assertTrue(all(surface["invocation"].values()))
                        self.assertEqual("adapter", surface["capabilities"]["proposal_apply"])

    def test_registered_hook_envelopes_are_renderable(self) -> None:
        registry = runtime_registry(ROOT)
        self.assertEqual(
            {"systemMessage": "control"},
            runtime_hook_payload(registry["claude"], ["control"], "cli"),
        )
        self.assertEqual(
            {"systemMessage": "control"},
            runtime_hook_payload(registry["codex"], ["control"], "cli"),
        )
        self.assertEqual(
            {"action": "allow", "message": "control"},
            runtime_hook_payload(registry["hermes"], ["control"], "cli"),
        )

    def test_every_registered_surface_is_explicitly_selectable(self) -> None:
        for manifest in runtime_registry(ROOT).values():
            for surface_id, expected in manifest["surfaces"].items():
                self.assertIs(expected, runtime_surface(manifest, surface_id))


if __name__ == "__main__":
    unittest.main()
