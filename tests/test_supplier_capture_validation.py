"""Regression tests for independent supplier collection completeness checks."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ecom_images.supplier_capture_validation import inspect_supplier_capture


class SupplierCaptureValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.url = "https://www.alibaba.com/product-detail/CL226_1601801131375.html"
        self.item = {"item_id": "cl226-id", "product_url": self.url, "title": "CL226"}
        (self.root / "pages").mkdir()
        self.put_json("catalog.json", {"items": [self.item]})
        self.put_json("pages/page_001.json", {
            "page_number": 1, "pagination_text": "1/1", "items": [self.item],
        })

    def put_json(self, name, obj):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj), encoding="utf-8")

    def put_detail(self, *, text="Original supplier details", listing_url=None):
        (self.root / "details").mkdir(exist_ok=True)
        (self.root / "details" / "cl226-id.txt").write_text(text, encoding="utf-8")
        self.put_json("details/cl226-id.json", {
            "item_id": "cl226-id", "listing_url": listing_url or self.url,
            "detail_page": {"title": "CL226", "body_text_file": "cl226-id.txt"},
        })

    def test_valid_listing_only_is_complete_but_details_can_be_required(self):
        listing = inspect_supplier_capture(self.root)
        self.assertEqual(listing["status"], "complete")
        self.assertEqual(listing["detail_status"], "not_requested")
        required = inspect_supplier_capture(self.root, require_details=True)
        self.assertEqual(required["status"], "partial")
        self.assertEqual(required["missing_detail_ids"], ["cl226-id"])

    def test_valid_details_pass_full_capture(self):
        self.put_detail()
        result = inspect_supplier_capture(self.root, require_details=True)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["valid_detail_products"], 1)

    def test_forged_audit_json_cannot_make_a_missing_page_complete(self):
        self.put_json("pages/page_001.json", {
            "page_number": 1, "pagination_text": "1/139", "items": [self.item],
        })
        self.put_json("catalog_audit.json", {"status": "complete"})
        self.put_json("details_audit.json", {"status": "complete"})
        result = inspect_supplier_capture(self.root)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["expected_listing_pages"], 139)
        self.assertEqual(len(result["missing_listing_pages"]), 138)

    def test_mismatched_and_corrupt_page_mark_partial(self):
        self.put_json("pages/page_001.json", {
            "page_number": 2, "pagination_text": "1/1", "items": [self.item],
        })
        result = inspect_supplier_capture(self.root)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["invalid_pages"])

    def test_catalog_orphan_and_missing_detail_are_reported(self):
        self.put_json("catalog.json", {"items": [self.item, {
            "item_id": "extra", "product_url": "https://www.alibaba.com/product-detail/Other_999.html",
        }]})
        self.put_detail()
        result = inspect_supplier_capture(self.root, require_details=True)
        self.assertIn("catalog_page_product_mismatch", result["failures"])
        self.assertIn("extra", result["missing_detail_ids"])

    def test_detail_empty_body_and_wrong_source_fail_closed(self):
        self.put_detail(text="")
        result = inspect_supplier_capture(self.root, require_details=True)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["invalid_details"])
        self.put_detail(listing_url="https://www.alibaba.com/product-detail/Other_999.html")
        result = inspect_supplier_capture(self.root, require_details=True)
        self.assertIn("invalid_or_orphan_detail", result["failures"])

    def test_unresolved_capture_error_blocks_completion(self):
        self.put_detail()
        self.put_json("details/capture_errors.json", [{"item_id": "cl226-id", "error_type": "RuntimeError"}])
        result = inspect_supplier_capture(self.root, require_details=True)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["unresolved_detail_capture_errors"], 1)
