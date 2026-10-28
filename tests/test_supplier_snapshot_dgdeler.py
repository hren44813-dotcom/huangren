"""Regression checks for the DGDeler supplier research snapshots."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs" / "supplier-research"

class DgdelerSupplierSnapshotTests(unittest.TestCase):
    def load_json(self, filename):
        """Load and return a supplier snapshot JSON file."""
        with (RESEARCH / filename).open(encoding="utf-8") as stream:
            return json.load(stream)

    def test_alibaba_snapshot_keeps_unverified_scope_explicit(self):
        """The Alibaba snapshot must not claim raw HTML integrity or verified specs."""
        data = self.load_json("dgdeler_supplier_profile_2026-10-28.json")
        self.assertEqual(data["source"]["source_url"], "https://dgdeler.en.alibaba.com/")
        self.assertFalse(data["source"]["raw_html_saved"])
        self.assertIsNone(data["source"]["raw_html_sha256"])
        self.assertEqual(data["v13_ingestion_recommendation"]["authority_level"], "unverified")
        self.assertTrue(all(item["products_extracted"] is False for item in data["category_links"]))

    def test_cross_source_snapshot_records_conflicts_and_product_model_scope(self):
        """Conflicting company claims and model-only observations must stay unresolved."""
        data = self.load_json("dgdeler_cross_source_verification_2026-10-28.json")
        fields = {item["field"] for item in data["claims_requiring_reconciliation"]}
        self.assertIn("staff_count", fields)
        self.assertIn("factory_area", fields)
        self.assertIn("quality_certification", fields)
        self.assertEqual(data["v13_ingestion_recommendation"]["authority_level"], "unverified")
        self.assertEqual(
            data["product_model_strings"]["handle_category"]["status"],
            "model_strings_only_no_product_specifications_verified",
        )
        self.assertTrue(data["v13_ingestion_recommendation"]["do_not_auto_accept_parameters"])

if __name__ == "__main__":
    unittest.main()
