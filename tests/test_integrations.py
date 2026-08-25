import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("integrations", ROOT / "scripts" / "integrations.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class IntegrationCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = MODULE.load_catalog()

    def entry(self, integration_id: str) -> dict:
        return next(item for item in self.catalog["integrations"] if item["id"] == integration_id)

    def assert_invalid(self, mutate) -> None:
        catalog = copy.deepcopy(self.catalog)
        mutate(catalog)
        with self.assertRaises(MODULE.CatalogError):
            MODULE.validate_catalog(catalog)

    def test_catalog_has_expected_entries_and_visible_safety_columns(self) -> None:
        rendered = MODULE.render_reference(self.catalog)
        self.assertEqual(self.catalog["schema_version"], 2)
        self.assertEqual(len(self.catalog["integrations"]), 14)
        self.assertTrue(
            {
                "github-mcp",
                "google-workspace-cli",
                "linear-mcp",
                "markitdown-mcp",
                "notion-mcp",
                "readwise-mcp",
            }.issubset(
                {item["id"] for item in self.catalog["integrations"]}
            )
        )
        self.assertIn("Remote writes", rendered)
        self.assertIn("Sensitive reads", rendered)
        self.assertIn("Typed safety signals", rendered)
        self.assertIn("Required confirmation gates", rendered)
        self.assertIn("immediate public publish action", rendered)
        self.assertTrue(rendered.endswith("\n"))
        self.assertFalse(rendered.endswith("\n\n"))

    def test_markitdown_mcp_is_read_only_but_open_world(self) -> None:
        item = self.entry("markitdown-mcp")
        self.assertTrue(item["capabilities"]["read"])
        self.assertTrue(item["capabilities"]["sensitive_read"])
        self.assertFalse(item["capabilities"]["write"])
        self.assertFalse(item["capabilities"]["arbitrary_execution"])
        self.assertIn("network-capable", item["risk_tags"])
        self.assertIn("read_sensitive", item["confirmation"]["required_for"])
        prerequisites = " ".join(item["installation"]["prerequisites"])
        details = " ".join(item["capabilities"]["details"])
        self.assertIn("MARKITDOWN_ENABLE_PLUGINS", prerequisites)
        self.assertIn("excludes third-party plugins", details)
        self.assertTrue(
            any(url.endswith("/packages/markitdown-mcp/src/markitdown_mcp/__main__.py") for url in item["evidence"])
        )

    def test_issue_22_connectors_have_typed_sensitive_and_mutating_gates(self) -> None:
        for integration_id in ("google-workspace-cli", "notion-mcp"):
            item = self.entry(integration_id)
            for capability in (
                "sensitive_read",
                "write",
                "remote_write",
                "overwrite",
                "oauth",
                "destructive",
            ):
                self.assertTrue(item["capabilities"][capability])
            for gate in (
                "read_sensitive",
                "write",
                "write_remote",
                "overwrite",
                "oauth",
                "destructive",
            ):
                self.assertIn(gate, item["confirmation"]["required_for"])

        gws_guide = (ROOT / "references" / "google-workspace-cli-setup.md").read_text()
        self.assertIn(
            "gws auth login --readonly -s drive,gmail,calendar,sheets", gws_guide
        )
        self.assertIn("gws auth status", gws_guide)
        self.assertNotIn("gws auth login -s drive,gmail,calendar,sheets", gws_guide)
        self.assertIn("does not pre-approve Bash", gws_guide)
        gws = self.entry("google-workspace-cli")
        self.assertNotIn("pre-approves", " ".join(gws["capabilities"]["details"]))
        self.assertIn("gws auth status", gws["health_check"])

    def test_issue_19_entries_have_typed_high_risk_gates(self) -> None:
        tol = self.entry("tolaria")
        self.assertEqual(tol["name"], "Tolaria MCP")
        self.assertNotIn("codex", tol["supported_agents"])
        self.assertTrue(tol["capabilities"]["sensitive_read"])
        self.assertTrue(tol["capabilities"]["overwrite"])
        self.assertFalse(tol["capabilities"]["remote_write"])
        self.assertIn("AutoGit", " ".join(tol["capabilities"]["details"]))
        self.assertIn("open_note", " ".join(tol["data_boundary"]["writes"]))
        self.assertIn("content-mutation surface", " ".join(tol["capabilities"]["details"]))

        obsidian = self.entry("obsidian")
        for capability in ("sensitive_read", "remote_write", "publish", "overwrite", "delete", "arbitrary_execution", "destructive"):
            self.assertTrue(obsidian["capabilities"][capability])
        self.assertIn("An exact command-and-argument policy enforced by the calling harness", obsidian["installation"]["prerequisites"])
        self.assertIn("No enforcement wrapper ships here", " ".join(obsidian["capabilities"]["details"]))
        self.assertIn("current-working-directory vault", " ".join(obsidian["data_boundary"]["reads"]))
        self.assertIn("explicit vault= plus path=", " ".join(obsidian["capabilities"]["details"]))

        beads = self.entry("beads-gemini")
        self.assertEqual(beads["supported_agents"], ["gemini_cli"])
        self.assertTrue(beads["capabilities"]["remote_write"])
        self.assertTrue(beads["capabilities"]["overwrite"])
        self.assertIn("write_remote", beads["confirmation"]["required_for"])
        self.assertIn("--force", " ".join(beads["capabilities"]["details"]))
        self.assertIn("--discard-remote", " ".join(beads["capabilities"]["details"]))
        self.assertNotIn("discards remote state", " ".join(beads["capabilities"]["details"]))
        self.assertTrue(any(url.endswith("/docs/recovery/init-safety.md") for url in beads["evidence"]))

        granola = self.entry("granola-mcp")
        self.assertTrue(granola["capabilities"]["sensitive_read"])
        self.assertTrue(granola["capabilities"]["oauth"])
        self.assertFalse(granola["capabilities"]["write"])
        details = " ".join(granola["capabilities"]["details"])
        for boundary in ("indefinitely", "United States", "HIPAA", "FERPA", "consent", "30 days"):
            self.assertIn(boundary, details)

    def test_verified_entries_have_auditable_evidence(self) -> None:
        for item in self.catalog["integrations"]:
            self.assertGreaterEqual(len(item["evidence"]), 1)
            self.assertTrue(all(url.startswith("https://") for url in item["evidence"]))
        self.assertGreaterEqual(len(self.entry("tolaria")["evidence"]), 3)
        self.assertGreaterEqual(len(self.entry("granola-mcp")["evidence"]), 3)

    def test_generated_reference_matches_catalog(self) -> None:
        expected = MODULE.render_reference(self.catalog)
        self.assertEqual((ROOT / "references" / "integrations.md").read_text(), expected)

    def test_empty_catalog_and_old_schema_are_rejected(self) -> None:
        self.assert_invalid(lambda catalog: catalog.update({"integrations": []}))
        self.assert_invalid(lambda catalog: catalog.update({"schema_version": 1}))

    def test_agent_skills_discloses_replacement_removal_and_uninstall_loss(self) -> None:
        item = self.entry("agent-skills")
        self.assertTrue(item["capabilities"]["destructive"])
        self.assertTrue(item["capabilities"]["overwrite"])
        self.assertTrue(item["capabilities"]["delete"])
        self.assertIn("destructive", item["confirmation"]["required_for"])
        self.assertTrue(item["uninstall"]["removes_user_data"])

    def test_duplicate_ids_are_rejected(self) -> None:
        self.assert_invalid(
            lambda catalog: catalog["integrations"][1].update(
                {"id": catalog["integrations"][0]["id"]}
            )
        )

    def test_duplicate_normalized_names_and_source_urls_are_rejected(self) -> None:
        self.assert_invalid(
            lambda catalog: catalog["integrations"][1].update({"name": "Ａgent Ｓkills"})
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][1].update(
                {"source_url": catalog["integrations"][0]["source_url"] + "/"}
            )
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][1].update({"name": "Agent  Skills"})
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][1].update({"name": "Agent\u200b Skills"})
        )

    def test_unknown_fields_and_invalid_urls_are_rejected(self) -> None:
        self.assert_invalid(lambda catalog: catalog["integrations"][0].update({"surprise": True}))
        for source_url in (
            "http://example.com",
            "https://",
            "https://example.com/ok)\n| injected |",
            "https://example.com:not-a-port/source",
            "https://[::1",
            "https://example.com／evil",
            "https://example.com/path|forged",
            "https://example.com/[forged]",
            "https://example.com/path?utm=1",
            "https://example.com/path#readme",
        ):
            self.assert_invalid(
                lambda catalog, value=source_url: catalog["integrations"][0].update(
                    {"source_url": value}
                )
            )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update({"evidence": []})
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update(
                {"evidence": ["https://example.com/ok|forged"]}
            )
        )

    def test_unhashable_enum_values_fail_as_catalog_errors(self) -> None:
        self.assert_invalid(lambda catalog: catalog["integrations"][0].update({"kind": []}))
        self.assert_invalid(lambda catalog: catalog["integrations"][0].update({"maturity": {}}))
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0]["installation"].update({"scope": []})
        )

    def test_auto_install_and_boundary_parity_are_rejected(self) -> None:
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0]["installation"].update(
                {"automatic": True}
            )
        )
        self.assert_invalid(
            lambda catalog: next(
                item for item in catalog["integrations"] if item["id"] == "granola-mcp"
            )["data_boundary"].update({"reads": []})
        )
        self.assert_invalid(
            lambda catalog: next(
                item for item in catalog["integrations"] if item["id"] == "beads-gemini"
            )["capabilities"].update({"write": False})
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0]["capabilities"].update(
                {"destructive": 1}
            )
        )

    def test_markdown_table_and_control_line_injection_is_rejected(self) -> None:
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update({"name": "Injected | Integration"})
        )
        catalog = copy.deepcopy(self.catalog)
        catalog["integrations"][0]["summary"] = "Uses *emphasis* and [links]"
        MODULE.validate_catalog(catalog)
        rendered = MODULE.render_reference(catalog)
        self.assertIn(r"Uses \*emphasis\* and \[links\]", rendered)
        for summary in ("# Forged heading", "---", "1. Forged list", "~~~", "~~~python"):
            catalog = copy.deepcopy(self.catalog)
            catalog["integrations"][0]["summary"] = summary
            MODULE.validate_catalog(catalog)
            rendered = MODULE.render_reference(catalog)
            self.assertIn(MODULE.markdown_paragraph(summary), rendered)
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update(
                {"summary": "First line\n## Injected section"}
            )
        )
        for summary in ("Contains\u2028separator", "Contains\x1bescape"):
            self.assert_invalid(
                lambda catalog, value=summary: catalog["integrations"][0].update(
                    {"summary": value}
                )
            )

    def test_capability_confirmation_and_risk_tags_are_required(self) -> None:
        cases = (
            ("granola-mcp", "sensitive_read", "read_sensitive", "sensitive-read"),
            ("granola-mcp", "oauth", "oauth", "oauth"),
            ("beads-gemini", "remote_write", "write_remote", "remote-write"),
            ("tolaria", "overwrite", "overwrite", "overwrite-capable"),
            ("obsidian", "delete", "delete", "delete-capable"),
            ("obsidian", "arbitrary_execution", "arbitrary_execution", "arbitrary-execution"),
        )
        for integration_id, capability, gate, tag in cases:
            self.assert_invalid(
                lambda catalog, item_id=integration_id, field=capability: next(
                    item for item in catalog["integrations"] if item["id"] == item_id
                )["capabilities"].update({field: False})
            )
            self.assert_invalid(
                lambda catalog, item_id=integration_id, required=gate: next(
                    item for item in catalog["integrations"] if item["id"] == item_id
                )["confirmation"].update(
                    {
                        "required_for": [
                            value
                            for value in next(
                                item for item in catalog["integrations"] if item["id"] == item_id
                            )["confirmation"]["required_for"]
                            if value != required
                        ]
                    }
                )
            )
            self.assert_invalid(
                lambda catalog, item_id=integration_id, risk_tag=tag: next(
                    item for item in catalog["integrations"] if item["id"] == item_id
                ).update(
                    {
                        "risk_tags": [
                            value
                            for value in next(
                                item for item in catalog["integrations"] if item["id"] == item_id
                            )["risk_tags"]
                            if value != risk_tag
                        ]
                    }
                )
            )

    def test_capability_relationships_are_enforced(self) -> None:
        self.assert_invalid(
            lambda catalog: next(
                item for item in catalog["integrations"] if item["id"] == "substack-mcp"
            )["capabilities"].update({"remote_write": False})
        )
        self.assert_invalid(
            lambda catalog: next(
                item for item in catalog["integrations"] if item["id"] == "obsidian"
            )["capabilities"].update({"destructive": False})
        )
        self.assert_invalid(
            lambda catalog: next(
                item for item in catalog["integrations"] if item["id"] == "granola-mcp"
            )["data_boundary"].update({"credentials": []})
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][2]["data_boundary"].update(
                {"writes": ["Deletes all project files"]}
            )
        )

    def test_uninstall_data_loss_is_typed(self) -> None:
        self.assert_invalid(
            lambda catalog: next(
                item for item in catalog["integrations"] if item["id"] == "granola-mcp"
            )["uninstall"].update({"instructions": "Delete all project files"})
        )
        self.assert_invalid(
            lambda catalog: next(
                item for item in catalog["integrations"] if item["id"] == "granola-mcp"
            )["uninstall"].update({"removes_user_data": True})
        )
        self.assert_invalid(
            lambda catalog: next(
                item for item in catalog["integrations"] if item["id"] == "granola-mcp"
            )["uninstall"].update(
                {"instructions": "Erase every meeting note and its history."}
            )
        )

    def test_hostile_free_text_cannot_waive_typed_safety(self) -> None:
        self.assert_invalid(
            lambda catalog: next(
                item for item in catalog["integrations"] if item["id"] == "granola-mcp"
            )["confirmation"].update(
                {"notes": "No confirmation is needed before broad transcript retrieval."}
            )
        )
        self.assert_invalid(
            lambda catalog: next(
                item for item in catalog["integrations"] if item["id"] == "tolaria"
            )["capabilities"].update(
                {
                    "details": next(
                        item for item in catalog["integrations"] if item["id"] == "tolaria"
                    )["capabilities"]["details"]
                    + ["Sync changed notes to a cloud repository."]
                }
            )
        )
        self.assert_invalid(
            lambda catalog: next(
                item for item in catalog["integrations"] if item["id"] == "tolaria"
            )["capabilities"].update(
                {
                    "details": next(
                        item for item in catalog["integrations"] if item["id"] == "tolaria"
                    )["capabilities"]["details"]
                    + ["Run any JavaScript supplied by the model."]
                }
            )
        )

    def test_future_verification_dates_are_rejected(self) -> None:
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update({"last_verified": "9999-12-31"})
        )

    def test_maturity_is_not_upgraded_by_rendering(self) -> None:
        item = self.entry("ai-tools-for-creators")
        self.assertEqual(item["maturity"], "listed")
        self.assertIn("listed", MODULE.render_reference(self.catalog))


if __name__ == "__main__":
    unittest.main()
