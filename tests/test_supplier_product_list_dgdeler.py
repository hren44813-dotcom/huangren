"""Regression tests for the DGDeler Alibaba product-list snapshot."""
import csv
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "docs" / "supplier-research"

class DgdelerProductListSnapshotTests(unittest.TestCase):
    def load_json(self):
        """Load the captured product-list JSON snapshot."""
        with (DATA_DIR / "dgdeler_product_list_page1_2026-10-28.json").open(encoding="utf-8") as stream:
            return json.load(stream)

    def test_snapshot_has_sixteen_visible_items_and_source_scope(self):
        """The snapshot only claims the 16 visible items, not all supplier products."""
        data = self.load_json()
        self.assertEqual(data["source"]["visible_item_count"], 16)
        self.assertEqual(len(data["items"]), 16)
        self.assertEqual(data["source"]["displayed_pagination"], "1/139")
        self.assertIsNone(data["source"]["total_product_count"])
        self.assertFalse(data["source"]["raw_html_saved"])

    def test_each_item_preserves_link_price_moq_and_claim_status(self):
        """Each visible item has source traceability and does not promote title claims to facts."""
        data = self.load_json()
        for item in data["items"]:
            with self.subTest(position=item["position"]):
                self.assertTrue(item["product_url"].startswith("https://www.alibaba.com/product-detail/"))
                self.assertTrue(item["price_text"].startswith("CN¥"))
                self.assertGreaterEqual(item["moq_quantity"], 1)
                self.assertEqual(item["title_claims_status"], "seller_listing_claims_unverified")
                self.assertEqual(item["source_url"], data["source"]["url"])
                if item["sales_count_displayed"] is None:
                    self.assertEqual(item["sales_status"], "not_displayed_on_captured_listing")
                else:
                    self.assertGreaterEqual(item["sales_count_displayed"], 0)

    def test_csv_rows_match_json_items(self):
        """The assistant/ops CSV export must have one row per JSON product."""
        with (DATA_DIR / "dgdeler_product_list_page1_2026-10-28.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows[0]["product_url"], self.load_json()["items"][0]["product_url"])

if __name__ == "__main__":
    unittest.main()
