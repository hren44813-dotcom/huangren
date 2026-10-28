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
    build_listing_audit, enrich_detail_payload, is_challenge, normalize_url,
    parse_listing_item, render_detail_markdown, save_listing_outputs, write_detail_exports,
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


    def test_enrich_detail_extracts_jsonld_attributes_price_moq_and_sales(self):
        """Structured fields remain seller observations and keep source locators."""
        detail = {
            "title": "CL226 Cabinet Hinge",
            "canonical_url": "https://example.com/CL226",
            "image_urls": ["https://example.com/hinge.png"],
            "table_rows": [["Material", "SUS304"], ["Hole Distance", "40 mm", "Thickness", "2 mm"]],
            "definition_rows": [["Color", "Silver"]],
            "option_groups": [{"kind": "select", "group": "Color", "options": [
                {"label": "Silver", "value": "silver", "selected": True, "disabled": False}
            ]}],
            "json_ld": [{"script_index": 1, "data": {
                "@context": "https://schema.org", "@type": "Product", "name": "CL226 Cabinet Hinge",
                "sku": "CL226-304", "mpn": "CL226", "brand": {"@type": "Brand", "name": "Dele"},
                "offers": {"@type": "Offer", "price": "3.46", "priceCurrency": "CNY",
                           "availability": "https://schema.org/InStock"},
                "additionalProperty": [{"@type": "PropertyValue", "name": "Material", "value": "SUS304"}]
            }}],
            "json_ld_errors": [],
        }
        result = enrich_detail_payload(detail, "Price CN¥3.46-4.98; MOQ: 1 piece; 11 sold")
        self.assertEqual(result["structured_product"]["sku"], "CL226-304")
        self.assertEqual(result["structured_product"]["brand"], "Dele")
        self.assertEqual(result["structured_product"]["price_currency"], "CNY")
        self.assertEqual(result["visible_price_candidates"][0]["price_max"], 4.98)
        self.assertEqual(result["visible_moq"]["quantity"], 1)
        self.assertEqual(result["visible_sales_count"], 11)
        self.assertTrue(any(pair["key"] == "Material" for pair in result["attribute_pairs"]))
        self.assertTrue(result["detail_quality"]["has_json_ld_product"])
        self.assertEqual(result["detail_quality"]["status"], "captured_unverified")

    def test_render_detail_markdown_keeps_provenance_and_unverified_status(self):
        """V13-ready source text contains original URLs and explicit review status."""
        record = {
            "item_id": "abc123",
            "listing_title": "CL226 Cabinet Hinge",
            "listing_url": "https://example.com/listing",
            "detail_url": "https://example.com/detail",
            "captured_at": "2026-10-28T00:00:00+00:00",
            "verification_status": "visible_detail_page_observation_unverified",
            "detail_page": {"title": "CL226", "canonical_url": "https://example.com/canonical",
                            "structured_product": {"sku": "CL226-304", "brand": "Dele"},
                            "attribute_pairs": [{"key": "Material", "value": "SUS304", "source_locator": "table_row_1"}]},
        }
        markdown = render_detail_markdown(record, "Material SUS304")
        self.assertIn("https://example.com/detail", markdown)
        self.assertIn("未经独立验证", markdown)
        self.assertIn("CL226-304", markdown)
        self.assertIn("table_row_1", markdown)

    def test_listing_audit_reports_missing_pages_and_pagination_mismatch(self):
        """A visible 1/3 pagination marker must not be mistaken for a complete capture."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            pages = output / "pages"
            pages.mkdir()
            page = {
                "page_number": 1, "pagination_text": "1/3",
                "items": [{"product_url": "https://example.com/product-1"}],
            }
            (pages / "page_001.json").write_text(json.dumps(page), encoding="utf-8")
            audit = build_listing_audit(output)
            self.assertEqual(audit["expected_page_count"], 3)
            self.assertEqual(audit["missing_page_numbers"], [2, 3])
            self.assertFalse(audit["is_complete"])
            self.assertEqual(audit["status"], "partial")

    def test_detail_exports_write_index_attributes_and_coverage_audit(self):
        """Captured details become spreadsheet exports and one Markdown source per product."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            item_id = "0123456789abcdef"
            catalog = {"items": [{
                "item_id": item_id, "title": "CL226 Hinge",
                "product_url": "https://example.com/product",
            }]}
            (output / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
            details = output / "details"
            details.mkdir()
            record = {
                "item_id": item_id, "listing_title": "CL226 Hinge",
                "listing_url": "https://example.com/product",
                "detail_url": "https://example.com/detail",
                "captured_at": "2026-10-28T00:00:00+00:00",
                "verification_status": "visible_detail_page_observation_unverified",
                "detail_page": {
                    "title": "CL226 Hinge", "canonical_url": "https://example.com/detail",
                    "body_text_file": f"{item_id}.txt",
                    "table_rows": [["Material", "SUS304"]],
                    "definition_rows": [], "json_ld": [], "json_ld_errors": [],
                    "option_groups": [], "image_urls": ["https://example.com/hinge.png"],
                },
            }
            (details / f"{item_id}.json").write_text(json.dumps(record), encoding="utf-8")
            (details / f"{item_id}.txt").write_text("CL226 Hinge Material SUS304", encoding="utf-8")
            audit = write_detail_exports(output)
            self.assertTrue(audit["is_complete"])
            self.assertEqual(audit["valid_detail_count"], 1)
            self.assertTrue((output / "details_index.csv").exists())
            self.assertTrue((output / "detail_attributes.csv").exists())
            self.assertTrue((output / "details_markdown" / f"{item_id}.md").exists())
            with (output / "detail_attributes.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["attribute"], "Material")
            self.assertEqual(rows[0]["verification_status"], "seller_page_observation_unverified")


    def test_listing_audit_flags_empty_page_for_manual_review(self):
        """A page with no visible products must not pass the completeness audit."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            pages = output / "pages"
            pages.mkdir()
            (pages / "page_001.json").write_text(json.dumps({
                "page_number": 1, "pagination_text": "1/1", "items": []
            }), encoding="utf-8")
            audit = build_listing_audit(output)
            self.assertEqual(audit["missing_page_numbers"], [])
            self.assertEqual(audit["pages_with_no_visible_products"], [1])
            self.assertFalse(audit["is_complete"])

    def test_detail_audit_flags_empty_body_text_file(self):
        """An existing but empty text file does not count as a complete detail capture."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            item_id = "fedcba9876543210"
            (output / "catalog.json").write_text(json.dumps({"items": [{
                "item_id": item_id, "title": "MS705 Lock",
                "product_url": "https://example.com/MS705",
            }]}), encoding="utf-8")
            details = output / "details"
            details.mkdir()
            record = {
                "item_id": item_id, "listing_title": "MS705 Lock",
                "listing_url": "https://example.com/MS705", "detail_url": "https://example.com/detail",
                "captured_at": "2026-10-28T00:00:00+00:00",
                "detail_page": {"title": "MS705 Lock", "body_text_file": f"{item_id}.txt",
                                "table_rows": [], "definition_rows": [], "json_ld": [],
                                "json_ld_errors": [], "option_groups": [], "image_urls": []},
            }
            (details / f"{item_id}.json").write_text(json.dumps(record), encoding="utf-8")
            (details / f"{item_id}.txt").write_text("", encoding="utf-8")
            audit = write_detail_exports(output)
            self.assertEqual(audit["missing_body_text_item_ids"], [item_id])
            self.assertFalse(audit["is_complete"])


    def test_catalog_export_survives_corrupt_checkpoint_and_audits_it(self):
        """A corrupt checkpoint is reported instead of crashing the whole audit export."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            pages = output / "pages"
            pages.mkdir()
            (pages / "page_001.json").write_text(json.dumps({
                "page_number": 1, "pagination_text": "1/2",
                "items": [{"product_url": "https://example.com/item-1", "title": "Item 1"}],
            }), encoding="utf-8")
            (pages / "page_002.json").write_text("{broken json", encoding="utf-8")
            summary = save_listing_outputs(output)
            self.assertEqual(summary["captured_page_count"], 1)
            audit = json.loads((output / "catalog_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["status"], "partial")
            self.assertEqual(audit["missing_page_numbers"], [2])
            self.assertEqual(audit["invalid_page_files"][0]["file"], "page_002.json")


if __name__ == "__main__":
    unittest.main()
