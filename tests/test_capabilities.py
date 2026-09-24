from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from contextos.capabilities import _runtime_specific_components, capability_report, render_capabilities
from contextos.cli import main as cli_main
from contextos.kernel import ContextOSError, runtime_manifest as load_runtime_manifest
from contextos.runtime_schema import validate_runtime_manifest


ROOT = Path(__file__).resolve().parents[1]


def descriptor(agent: str) -> dict:
    return json.loads((ROOT / "runtimes" / f"{agent}.json").read_text(encoding="utf-8"))


class CapabilitiesTest(unittest.TestCase):
    def test_fixture_json_and_text_agree_on_support_skills_and_install_state(self) -> None:
        codex_fixture = descriptor("codex")
        codex_fixture["support_tier"] = "experimental"
        codex_fixture["surfaces"]["cli"]["support_tier"] = "experimental"
        codex_fixture["surfaces"]["cli"]["capabilities"]["mcp"] = "unsupported"
        hermes_fixture = descriptor("hermes")
        for agent, fixture in (("codex", codex_fixture), ("hermes", hermes_fixture)):
            validate_runtime_manifest(fixture, runtime_id=agent, root=ROOT, check_paths=False)
        fixtures = {"codex": codex_fixture, "hermes": hermes_fixture}
        with patch("contextos.capabilities.runtime_manifest", side_effect=lambda root, agent, check_paths: (
            fixtures[agent] if agent in fixtures else load_runtime_manifest(root, agent, check_paths=check_paths)
        )), patch("contextos.capabilities._installed_components", return_value={
            "core", "portable-skills", "agents-instructions", "codex-adapter",
        }):
            report = capability_report(ROOT, ["hermes", "codex"])
        codex = report["agents"]["codex"]
        hermes = report["agents"]["hermes"]
        self.assertEqual("experimental", codex["support_tier"])
        self.assertEqual("experimental", codex["surfaces"]["cli"]["support_tier"])
        self.assertEqual(
            {"value": "unsupported", "install_state": "unsupported"},
            codex["surfaces"]["cli"]["capabilities"]["mcp"],
        )
        self.assertEqual(
            {"value": "adapter", "install_state": "not-installed", "required_components": ["hermes-adapter"]},
            hermes["surfaces"]["cli"]["capabilities"]["agent_skills"],
        )
        self.assertEqual("installed", codex["surfaces"]["cli"]["skills"]["setup"]["install_state"])
        self.assertEqual("installed", hermes["surfaces"]["cli"]["skills"]["setup"]["install_state"])
        self.assertEqual(
            ["context-end", "context-setup", "context-start", "context-update", "end",
             "migrate-gemini", "mine-gemini-workflows", "setup", "start", "update"],
            report["comparison"]["common_portable_skills"],
        )
        self.assertEqual(
            {"codex": "unsupported", "hermes": "native"},
            report["comparison"]["differing_capabilities"]["cli.mcp"],
        )
        self.assertIn("cli.mcp", report["comparison"]["per_agent_only"]["hermes"]["capabilities"])
        text = render_capabilities(report)
        for fact in ("codex) - experimental", "cli (cli) - experimental",
                     "mcp: unsupported [unsupported]", "agent_skills: adapter [not-installed] (requires hermes-adapter)",
                     "setup: portable-skills [installed]", "cli.mcp: codex=unsupported, hermes=native",
                     "common portable skills: context-end, context-setup"):
            self.assertIn(fact, text)

    def test_absent_installed_state_and_unsupported_surface(self) -> None:
        with patch("contextos.capabilities._installed_components", return_value=None):
            report = capability_report(ROOT, ["devin"])
        self.assertEqual("absent", report["installed_state"])
        self.assertEqual(
            "host-provided",
            report["agents"]["devin"]["surfaces"]["session"]["capabilities"]["agent_skills"]["install_state"],
        )
        self.assertEqual(
            {"value": "adapter", "install_state": "unknown-install-state", "required_components": ["devin-adapter"]},
            report["agents"]["devin"]["surfaces"]["session"]["capabilities"]["proposal_apply"],
        )
        self.assertEqual(
            "unsupported",
            report["agents"]["devin"]["surfaces"]["review"]["capabilities"]["agent_skills"]["install_state"],
        )
        self.assertIn("review (review) - compatibility", render_capabilities(report))
        self.assertIn("agent_skills: unsupported [unsupported]", render_capabilities(report))
        self.assertIn("unknown-install-state: installed-bundle.json is absent", render_capabilities(report))

    def test_capability_tiers_ignore_unrelated_missing_components(self) -> None:
        with patch("contextos.capabilities._installed_components", return_value={
            "core", "portable-skills", "codex-adapter",
        }):
            report = capability_report(ROOT, ["codex", "hermes"])
        codex = report["agents"]["codex"]["surfaces"]["cli"]["capabilities"]
        hermes = report["agents"]["hermes"]["surfaces"]["cli"]["capabilities"]
        self.assertEqual({"value": "native", "install_state": "host-provided"}, codex["mcp"])
        self.assertEqual({"value": "native", "install_state": "host-provided"}, hermes["native_memory"])
        self.assertEqual({"value": "advisory", "install_state": "host-provided"}, hermes["explicit_invocation"])
        self.assertEqual(
            {"value": "adapter", "install_state": "installed", "required_components": ["codex-adapter"]},
            codex["proposal_apply"],
        )
        self.assertEqual(
            {"value": "adapter", "install_state": "not-installed", "required_components": ["hermes-adapter"]},
            hermes["proposal_apply"],
        )
        self.assertEqual({"value": "unsupported", "install_state": "unsupported"}, codex["native_memory"])
        text = render_capabilities(report)
        self.assertIn("mcp: native [host-provided]", text)
        self.assertIn("proposal_apply: adapter [installed] (requires codex-adapter)", text)

    def test_runtime_specific_component_derivation_and_missing_gate(self) -> None:
        descriptors = {
            "one": {"components": ["core", "custom-bridge"]},
            "two": {"components": ["core", "other-bridge"]},
        }
        self.assertEqual({"custom-bridge"}, _runtime_specific_components("one", descriptors))
        descriptors["two"]["components"].append("custom-bridge")
        self.assertRaisesRegex(
            ContextOSError, "no runtime-specific components for agent one",
            _runtime_specific_components, "one", descriptors,
        )
        codex_fixture = descriptor("codex")
        codex_fixture["components"] = ["core", "portable-skills", "agents-instructions"]
        with patch("contextos.capabilities.runtime_manifest", side_effect=lambda root, agent, check_paths: (
            codex_fixture if agent == "codex" else load_runtime_manifest(root, agent, check_paths=check_paths)
        )), patch("contextos.capabilities._installed_components", return_value=None):
            self.assertRaisesRegex(
                ContextOSError, "no runtime-specific components for agent codex",
                capability_report, ROOT, ["codex"],
            )

    def test_comma_separated_and_repeated_agent_flags(self) -> None:
        for flags in (["--agent", "codex,hermes"], ["--agent", "codex", "--agent", "hermes"]):
            output = io.StringIO()
            with self.subTest(flags=flags), redirect_stdout(output), patch(
                "contextos.capabilities._installed_components", return_value=None,
            ):
                self.assertEqual(0, cli_main(["--root", str(ROOT), "capabilities", *flags, "--json"]))
            self.assertEqual(["codex", "hermes"], list(json.loads(output.getvalue())["agents"]))

    def test_selection_and_negative_controls(self) -> None:
        self.assertRaisesRegex(ContextOSError, "no agents selected", capability_report, ROOT, [])
        self.assertRaisesRegex(ContextOSError, "unknown agent id", capability_report, ROOT, ["other"])
        self.assertRaisesRegex(ContextOSError, "duplicate --agent", capability_report, ROOT, ["codex", "codex"])
        self.assertRaisesRegex(ContextOSError, "duplicate --agent", capability_report, ROOT, ["codex, codex"])
        self.assertRaisesRegex(ContextOSError, "empty ids", capability_report, ROOT, ["codex,"])
        with patch("contextos.capabilities.Path.exists", return_value=True), patch(
            "contextos.capabilities.load_workspace_config",
            return_value=({"agents": []}, True),
        ), patch("contextos.capabilities._installed_components", return_value=None):
            self.assertRaisesRegex(ContextOSError, "no agents selected", capability_report, ROOT, [])
        with patch("contextos.capabilities.Path.exists", return_value=True), patch(
            "contextos.capabilities.load_workspace_config",
            return_value=({"agents": ["codex", "hermes"]}, True),
        ), patch("contextos.capabilities._installed_components", return_value=None):
            self.assertEqual(["codex", "hermes"], list(capability_report(ROOT, [])["agents"]))
        malformed = descriptor("codex")
        malformed["surfaces"]["cli"]["capabilities"]["mcp"] = "invented"
        with patch("contextos.kernel.read_json", return_value=malformed):
            self.assertRaisesRegex(ContextOSError, "invalid runtime manifest", capability_report, ROOT, ["codex"])


if __name__ == "__main__":
    unittest.main()
