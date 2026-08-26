from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from unittest import mock

from contextos.cli import main as cli_main
from contextos.kernel import (
    ContextOSError,
    runtime_hook_payload,
    runtime_registry,
    runtime_surface,
)


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
                        self.assertTrue(surface["conformance_tests"])
                    for source in surface["skill_sources"]:
                        if source["scope"] == "repository":
                            self.assertTrue((ROOT / source["path"]).exists())

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

    def test_null_hook_surface_stays_silent_on_malformed_input(self) -> None:
        manifest = {"runtime": "fixture", "surfaces": {"messaging": {"hook_output": None}}}
        stdout = io.StringIO()
        with mock.patch("contextos.cli.discover_root", return_value=ROOT), mock.patch(
            "contextos.cli.runtime_manifest", return_value=manifest
        ), mock.patch("sys.stdin", io.StringIO("not-json")), contextlib.redirect_stdout(stdout):
            status = cli_main(
                ["hook", "pre-write", "--runtime", "fixture", "--surface", "messaging"]
            )
        self.assertEqual(0, status)
        self.assertEqual("", stdout.getvalue())

    def test_invalid_ambiguous_surface_stays_silent(self) -> None:
        manifest = {
            "runtime": "fixture",
            "surfaces": {
                "chat": {"hook_output": "system-message"},
                "cli": {"hook_output": "allow-message"},
            },
        }
        stdout = io.StringIO()
        with mock.patch("contextos.cli.discover_root", return_value=ROOT), mock.patch(
            "contextos.cli.runtime_manifest", return_value=manifest
        ), contextlib.redirect_stdout(stdout):
            status = cli_main(
                ["hook", "pre-write", "--runtime", "fixture", "--surface", "bogus"]
            )
        self.assertEqual(0, status)
        self.assertEqual("", stdout.getvalue())

    def test_manifest_load_failure_stays_silent_without_a_known_protocol(self) -> None:
        stdout = io.StringIO()
        with mock.patch("contextos.cli.discover_root", return_value=ROOT), mock.patch(
            "contextos.cli.runtime_manifest",
            side_effect=ContextOSError("missing runtime manifest"),
        ), contextlib.redirect_stdout(stdout):
            status = cli_main(["hook", "pre-write", "--runtime", "hermes"])
        self.assertEqual(0, status)
        self.assertEqual("", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
