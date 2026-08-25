from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from contextos.kernel import (
    ContextOSError, install_runtime, runtime_hook_payload, runtime_ids,
    runtime_manifest, runtime_registry,
)
from contextos.runtime_schema import (
    CAPABILITY_KEYS,
    RUNTIME_DESCRIPTOR_SCHEMA_VERSION,
    RuntimeManifestError,
    runtime_schema_document,
    validate_runtime_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


def load(runtime: str) -> dict:
    return json.loads((ROOT / "runtimes" / f"{runtime}.json").read_text(encoding="utf-8"))


class RuntimeManifestTest(unittest.TestCase):
    def test_registry_discovers_and_validates_every_descriptor(self) -> None:
        self.assertEqual(["claude", "codex", "hermes"], runtime_ids(ROOT))
        registry = runtime_registry(ROOT)
        self.assertEqual({"claude", "codex", "hermes"}, set(registry))
        self.assertNotIn("generic", registry)
        for runtime, manifest in registry.items():
            with self.subTest(runtime=runtime):
                self.assertEqual(RUNTIME_DESCRIPTOR_SCHEMA_VERSION, manifest["schema_version"])
                self.assertEqual(runtime, manifest["runtime"])
                for surface in manifest["surfaces"].values():
                    self.assertEqual(CAPABILITY_KEYS, set(surface["capabilities"]))

    def test_short_aliases_match_cli_surface_invocations(self) -> None:
        for runtime, prefix in (("claude", "/"), ("codex", "$"), ("hermes", "/")):
            invocation = load(runtime)["surfaces"]["cli"]["invocation"]
            for name in ("setup", "start", "update", "end"):
                self.assertEqual(f"{prefix}{name}", invocation[name])

    def test_checked_in_schema_matches_authoritative_contract(self) -> None:
        actual = json.loads((ROOT / "runtimes/schema.json").read_text(encoding="utf-8"))
        self.assertEqual(runtime_schema_document(), actual)

    def test_mutation_sentinel_rejects_unknown_capability_value(self) -> None:
        manifest = load("codex")
        manifest["surfaces"]["cli"]["capabilities"]["mcp"] = "invented"
        with self.assertRaisesRegex(RuntimeManifestError, "capabilities.mcp"):
            validate_runtime_manifest(manifest, runtime_id="codex", root=ROOT)

    def test_probe_contract_rejects_executable_arguments(self) -> None:
        manifest = load("codex")
        manifest["surfaces"]["cli"]["binary_probes"][0]["args"] = ["-c", "do_work()"]
        with self.assertRaisesRegex(RuntimeManifestError, "unknown args"):
            validate_runtime_manifest(manifest, runtime_id="codex", root=ROOT)

    def test_contract_rejects_unknown_keys_claims_future_and_mismatch(self) -> None:
        manifest = load("codex")
        mutations = []
        unknown = copy.deepcopy(manifest)
        unknown["surprise"] = True
        mutations.append((unknown, "codex", "unknown surprise"))
        future = copy.deepcopy(manifest)
        future["evidence"]["checked_on"] = "2999-01-01"
        mutations.append((future, "codex", "future"))
        compact_date = copy.deepcopy(manifest)
        compact_date["evidence"]["checked_on"] = "20260824"
        mutations.append((compact_date, "codex", "YYYY-MM-DD"))
        week_date = copy.deepcopy(manifest)
        week_date["evidence"]["checked_on"] = "2026-W35-1"
        mutations.append((week_date, "codex", "YYYY-MM-DD"))
        uncovered = copy.deepcopy(manifest)
        support_ids = {
            source["id"] for source in uncovered["evidence"]["sources"]
            if "support" in source["claims"]
        }
        uncovered["evidence"]["sources"] = [
            source for source in uncovered["evidence"]["sources"]
            if source["id"] not in support_ids
        ]
        for surface in uncovered["surfaces"].values():
            surface["evidence"] = [
                evidence_id for evidence_id in surface["evidence"]
                if evidence_id not in support_ids
            ]
        mutations.append((uncovered, "codex", "does not cover claims"))
        unknown_claim = copy.deepcopy(manifest)
        unknown_claim["evidence"]["sources"][0]["claims"].append("magic")
        mutations.append((unknown_claim, "codex", "unsupported value"))
        for candidate, runtime_id, message in mutations:
            with self.subTest(message=message), self.assertRaisesRegex(RuntimeManifestError, message):
                validate_runtime_manifest(candidate, runtime_id=runtime_id, root=ROOT, today=date(2026, 8, 24))
        with self.assertRaisesRegex(RuntimeManifestError, "reserved"):
            validate_runtime_manifest(manifest, runtime_id="generic", root=ROOT)
        with self.assertRaisesRegex(RuntimeManifestError, "match filename"):
            validate_runtime_manifest(manifest, runtime_id="other", root=ROOT)

    def test_operational_validation_ignores_clock_skew_but_keeps_date_shape(self) -> None:
        manifest = load("codex")
        validate_runtime_manifest(
            manifest, runtime_id="codex", root=ROOT, today=date(2020, 1, 1),
            check_paths=False,
        )
        manifest["evidence"]["checked_on"] = "20260824"
        with self.assertRaisesRegex(RuntimeManifestError, "YYYY-MM-DD"):
            validate_runtime_manifest(
                manifest, runtime_id="codex", root=ROOT, check_paths=False
            )

    def test_logical_sources_reject_posix_absolute_paths_on_every_platform(self) -> None:
        manifest = load("codex")
        manifest["surfaces"]["cli"]["instruction_sources"][0] = {
            "scope": "workspace", "role": "canonical", "path": "/etc/passwd",
            "precedence": 100,
        }
        with self.assertRaisesRegex(RuntimeManifestError, "safe logical relative path"):
            validate_runtime_manifest(manifest, runtime_id="codex", root=ROOT)

    def test_generic_is_apply_only_not_a_descriptor(self) -> None:
        with self.assertRaisesRegex(ContextOSError, "invalid runtime id"):
            runtime_manifest(ROOT, "generic")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ContextOSError, "invalid runtime id"):
                install_runtime(root, "generic")
            self.assertFalse((root / ".context-os/runtime.json").exists())

    def test_hook_envelopes_come_from_surface_descriptors(self) -> None:
        self.assertEqual(
            {"systemMessage": "notice"}, runtime_hook_payload(load("claude"), ["notice"])
        )
        self.assertEqual(
            {"action": "allow", "message": "notice"},
            runtime_hook_payload(load("hermes"), ["notice"]),
        )

    def test_new_descriptor_is_discovered_without_code_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "runtimes").mkdir()
            (root / "docs").mkdir()
            (root / "tests").mkdir()
            (root / "docs/onboarding.md").write_text("# Onboarding\n", encoding="utf-8")
            (root / "tests/conformance.py").write_text("# fixture\n", encoding="utf-8")
            manifest = load("codex")
            manifest["runtime"] = "future-agent"
            manifest["display_name"] = "Future Agent"
            manifest["onboarding_doc"] = "docs/onboarding.md"
            surface = manifest["surfaces"]["cli"]
            surface["conformance_tests"] = ["tests/conformance.py"]
            for source in manifest["evidence"]["sources"]:
                if source["type"] == "conformance":
                    source["location"] = "tests/conformance.py"
            surface["instruction_sources"] = [
                {"scope": "workspace", "role": "canonical", "path": "AGENTS.md", "precedence": 100}
            ]
            surface["skill_sources"] = [
                {"scope": "workspace", "role": "skills", "path": "skills", "precedence": 100}
            ]
            (root / "runtimes/future-agent.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(["future-agent"], runtime_ids(root))
            self.assertEqual("Future Agent", runtime_registry(root)["future-agent"]["display_name"])
            target, installed = install_runtime(root, "future-agent")
            self.assertTrue(target.is_file())
            self.assertEqual("future-agent", installed["runtime"])
            self.assertEqual({"systemMessage": "notice"}, runtime_hook_payload(manifest, ["notice"]))

    def test_openclaw_spike_supports_precedence_and_multiple_surfaces(self) -> None:
        manifest = load("hermes")
        manifest["runtime"] = "openclaw-spike"
        manifest["display_name"] = "OpenClaw Spike"
        manifest["support_tier"] = "experimental"
        cli = manifest["surfaces"].pop("cli")
        cli["support_tier"] = "experimental"
        cli["instruction_sources"] = [
            {"scope": "workspace", "role": "canonical", "path": "AGENTS.md", "precedence": 100},
            {"scope": "user", "role": "persona", "path": "SOUL.md", "precedence": 80},
            {"scope": "user", "role": "persona", "path": "USER.md", "precedence": 75},
            {"scope": "user", "role": "memory", "path": "MEMORY.md", "precedence": 70},
        ]
        cli["skill_sources"] = [
            {"scope": "workspace", "role": "skills", "path": ".agents/skills", "precedence": 100},
            {"scope": "user", "role": "skills", "path": "skills", "precedence": 50},
        ]
        messaging = copy.deepcopy(cli)
        messaging["kind"] = "messaging"
        messaging["hook_output"] = None
        cli["binary_probes"].append(
            {"purpose": "native-doctor", "candidates": ["openclaw", "openclaw-agent"]}
        )
        manifest["surfaces"] = {"cli": cli, "messaging": messaging}
        manifest["evidence"]["tested_versions"] = []
        validate_runtime_manifest(manifest, runtime_id="openclaw-spike", root=ROOT)
        self.assertIn("skill_allowlists", cli["capabilities"])
        self.assertIn("execution_authorization", cli["capabilities"])


if __name__ == "__main__":
    unittest.main()
