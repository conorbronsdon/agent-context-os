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

    def assert_invalid(self, mutate) -> None:
        catalog = copy.deepcopy(self.catalog)
        mutate(catalog)
        with self.assertRaises(MODULE.CatalogError):
            MODULE.validate_catalog(catalog)

    def test_catalog_is_sorted_only_at_render_time_and_has_unique_ids(self) -> None:
        rendered = MODULE.render_reference(self.catalog)
        self.assertEqual(len(self.catalog["integrations"]), 4)
        self.assertIn("Substack MCP", rendered)
        self.assertIn("immediate public publish action", rendered)

    def test_generated_reference_matches_catalog(self) -> None:
        expected = MODULE.render_reference(self.catalog)
        self.assertEqual((ROOT / "references" / "integrations.md").read_text(), expected)

    def test_agent_skills_discloses_replacement_and_removal(self) -> None:
        item = next(item for item in self.catalog["integrations"] if item["id"] == "agent-skills")
        self.assertTrue(item["capabilities"]["destructive"])
        self.assertIn("destructive", item["confirmation"]["required_for"])
        self.assertIn("replacement", item["risk_tags"])
        self.assertIn("removal", item["risk_tags"])

    def test_duplicate_ids_are_rejected(self) -> None:
        self.assert_invalid(
            lambda catalog: catalog["integrations"][1].update(
                {"id": catalog["integrations"][0]["id"]}
            )
        )

    def test_duplicate_normalized_names_and_source_urls_are_rejected(self) -> None:
        self.assert_invalid(
            lambda catalog: catalog["integrations"][1].update(
                {"name": "Ａgent Ｓkills"}
            )
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
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update({"source_url": "http://example.com"})
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update({"source_url": "https://"})
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update(
                {"source_url": "https://example.com/ok)\n| injected |"}
            )
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update(
                {"source_url": "https://example.com:not-a-port/source"}
            )
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update(
                {"source_url": "https://[::1"}
            )
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update(
                {"source_url": "https://example.com／evil"}
            )
        )
        for source_url in (
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

    def test_unhashable_enum_values_fail_as_catalog_errors(self) -> None:
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update({"kind": []})
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update({"maturity": {}})
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0]["installation"].update(
                {"scope": []}
            )
        )

    def test_markdown_table_and_control_line_injection_is_rejected(self) -> None:
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update(
                {"name": "Injected | Integration"}
            )
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

    def test_auto_install_and_missing_risk_boundaries_are_rejected(self) -> None:
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0]["installation"].update({"automatic": True})
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][3]["confirmation"].update(
                {"required_for": ["credential_setup", "external_install", "write"]}
            )
        )

    def test_capability_and_data_boundary_contradictions_are_rejected(self) -> None:
        self.assert_invalid(
            lambda catalog: catalog["integrations"][2]["data_boundary"].update(
                {"writes": ["Deletes all project files"]}
            )
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][3]["capabilities"].update(
                {"write": False}
            )
        )
        self.assert_invalid(
            lambda catalog: catalog["integrations"][3]["data_boundary"].update(
                {"reads": []}
            )
        )

    def test_future_verification_dates_are_rejected(self) -> None:
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update(
                {"last_verified": "9999-12-31"}
            )
        )

    def test_maturity_is_not_upgraded_by_rendering(self) -> None:
        item = next(
            item for item in self.catalog["integrations"] if item["id"] == "ai-tools-for-creators"
        )
        self.assertEqual(item["maturity"], "listed")
        self.assertIn("listed", MODULE.render_reference(self.catalog))


if __name__ == "__main__":
    unittest.main()
