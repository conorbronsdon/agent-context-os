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

    def test_duplicate_ids_are_rejected(self) -> None:
        self.assert_invalid(
            lambda catalog: catalog["integrations"][1].update(
                {"id": catalog["integrations"][0]["id"]}
            )
        )

    def test_unknown_fields_and_invalid_urls_are_rejected(self) -> None:
        self.assert_invalid(lambda catalog: catalog["integrations"][0].update({"surprise": True}))
        self.assert_invalid(
            lambda catalog: catalog["integrations"][0].update({"source_url": "http://example.com"})
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

    def test_maturity_is_not_upgraded_by_rendering(self) -> None:
        item = next(
            item for item in self.catalog["integrations"] if item["id"] == "ai-tools-for-creators"
        )
        self.assertEqual(item["maturity"], "listed")
        self.assertIn("listed", MODULE.render_reference(self.catalog))


if __name__ == "__main__":
    unittest.main()
