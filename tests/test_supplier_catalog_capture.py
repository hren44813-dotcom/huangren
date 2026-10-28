"""Offline tests for supplier catalog parsing and export helpers."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.supplier_catalog_capture import (  # noqa: E402
    is_challenge, normalize_url, parse_listing_item, save_listing_outputs,
)


class SupplierCatalogCaptureTests(unittest.TestCase):
    """Validate parsing without requiring a browser or external network."""

    def test_parse_price_range_moq_sales_and_model_hint(self):
        """Extract visible listing facts while keeping claims unverified."""
        item = parse_listing_item({
            "title": "CL226 40mm Cabinet Door Hinge",
            "url": "https://www.alibaba.com/product-detail/CL226_123.html?spm=tracking#top",
            "image_url": "https://example.com/hinge.png",
            "card_text": "CL226 40mm Cabinet Door Hinge CN¥3.46-4.98 Min. order 1 piece 11 sold Delivery by Nov 21",
        }, 2, "https://dgdeler.en.alibaba.com/productlist.html")
        self.assertEqual(item["product_url"], "https://www.alibaba.com/product-detail/CL226_123.html")
        self.assertEqual(item["model_hints"], ["CL226"])
        self.assertEqual(item["price_min"], 3.46)
        self.assertEqual(item["price_max"], 4.98)
        self.assertEqual(item["price_currency"], "CNY")
        self.assertEqual(item["moq_quantity"], 1)
        self.assertEqual(item["sales_count_displayed"], 11)
        self.assertEqual(item["sales_status"], "displayed")
        self.assertEqual(item["verification_status"], "seller_listing_observation_unverified")

    def test_missing_sales_is_not_zero(self):
        """Missing sales information remains null rather than being imputed."""
        item = parse_listing_item({
            "title": "MS858-1C Lock",
            "url": "https://www.alibaba.com/product-detail/MS858.html",
            "card_text": "MS858-1C Lock CN¥59.93 Min. order 1 piece",
        }, 1, "https://dgdeler.en.alibaba.com/productlist.html")
        self.assertIsNone(item["sales_count_displayed"])
        self.assertEqual(item["sales_status"], "not_displayed_not_zero")

    def test_normalize_url_and_challenge_detection(self):
        """Tracking parameters are removed and CAPTCHA pages are flagged for humans."""
        self.assertEqual(normalize_url("https://example.com/item?id=2#x"), "https://example.com/item")
        self.assertEqual(normalize_url(""), "")
        self.assertTrue(is_challenge("Please slide to verify", "https://example.com"))
        self.assertFalse(is_challenge("Product title and price", "https://example.com"))

    def test_catalog_export_deduplicates_and_writes_csv(self):
        """Checkpoint merging produces one row per unique product URL."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / "pages").mkdir()
            row = parse_listing_item({
                "title": "CL226 Hinge",
                "url": "https://www.alibaba.com/product-detail/CL226.html",
                "card_text": "CL226 Hinge CN¥3.46 Min. order 1 piece",
            }, 1, "https://dgdeler.en.alibaba.com/productlist.html")
            page = {"items": [row, dict(row)], "visible_item_count": 2}
            (output / "pages" / "page_001.json").write_text(json.dumps(page), encoding="utf-8")
            summary = save_listing_outputs(output)
            self.assertEqual(summary["captured_page_count"], 1)
            self.assertEqual(summary["unique_product_count"], 1)
            catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
            self.assertEqual(len(catalog["items"]), 1)
            with (output / "catalog.csv").open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 1)


if __name__ == "__main__":
    unittest.main()
