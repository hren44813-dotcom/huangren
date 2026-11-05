"""First-batch safety regression tests: measurement units, observations and capture truth."""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecom_images.image_evidence_gate_v13 import _contains_value
from ecom_images.model_evidence_v13.normalize import _unit_key, _value_key
from ecom_images.supplier_capture.audit import build_listing_audit
from ecom_images.supplier_capture_validation import inspect_supplier_capture
from ecom_images.supplier_catalog_db import sync_supplier_catalog, export_supplier_db, open_supplier_db


class MeasurementGateTests(unittest.TestCase):
    def test_si_case_is_not_interchangeable(self):
        self.assertTrue(_contains_value("Rated torque 6 mN.m", "6", "mN.m"))
        self.assertTrue(_contains_value("Rated torque 6 MN·m", "6", "MN.m"))
        for wrong in ("6 MN.m", "6 N.m", "6 nN.m", "6 kN.m", "16 mN.m", "6 pcs and 8 mN.m"):
            with self.subTest(wrong=wrong):
                self.assertFalse(_contains_value(wrong, "6", "mN.m"))
        self.assertFalse(_contains_value("6 mN.m", "6", "MN.m"))

    def test_conflict_unit_keys_keep_si_magnitude(self):
        self.assertNotEqual(_unit_key("MN.m"), _unit_key("mN.m"))
        self.assertNotEqual(_value_key({"normalized_value_json": "6", "unit": "MN.m"}),
                            _value_key({"normalized_value_json": "6", "unit": "mN.m"}))
        self.assertEqual(_unit_key("N·m"), _unit_key("N.m"))


class PriceChronologyTests(unittest.TestCase):
    def test_old_import_cannot_replace_newest_price_or_current_product(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "empty_capture"
            capture.mkdir()
            db = root / "supplier.sqlite3"
            snap = root / "snapshot.json"
            url = "https://www.alibaba.com/product-detail/CL226_1601801131375.html"

            def sync_at(timestamp: str, price: float, title: str):
                item = {
                    "title": title, "product_url": url, "price_text": f"CN¥{price:.2f}",
                    "price_min_cny": price, "price_max_cny": price, "price_currency": "CNY",
                    "captured_at": timestamp, "models": ["CL226"],
                }
                snap.write_text(json.dumps({
                    "source": {"url": "https://dgdeler.en.alibaba.com/productlist.html"},
                    "items": [item],
                }), encoding="utf-8")
                return sync_supplier_catalog(db, capture_dir=capture, snapshot_json=snap)

            sync_at("2026-10-29T12:00:00+00:00", 20, "CL226 latest title")
            sync_at("2026-10-28T12:00:00+00:00", 10, "CL226 old title")
            export_supplier_db(db, root / "exports")
            with (root / "exports" / "supplier_products.csv").open(encoding="utf-8-sig", newline="") as handle:
                products = list(csv.DictReader(handle))
            self.assertEqual(len(products), 1)
            self.assertEqual(products[0]["latest_price_text"], "CN¥20.00")
            self.assertEqual(products[0]["latest_price_min"], "20.0")
            with open_supplier_db(db) as conn:
                product = conn.execute("SELECT title,first_seen_utc,last_seen_utc FROM supplier_catalog_products").fetchone()
                self.assertEqual(product["title"], "CL226 latest title")
                self.assertEqual(product["first_seen_utc"], "2026-10-28T12:00:00+00:00")
                self.assertEqual(product["last_seen_utc"], "2026-10-29T12:00:00+00:00")


class SupplierCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "pages").mkdir()
        self.url = "https://www.alibaba.com/product-detail/CL226_1601801131375.html"
        self.item = {"item_id": "cl226-id", "title": "CL226", "product_url": self.url}

    def listing(self, pagination=None):
        record = {"page_number": 1, "items": [self.item]}
        if pagination is not None:
            record["pagination_text"] = pagination
        (self.root / "pages" / "page_001.json").write_text(json.dumps(record), encoding="utf-8")
        (self.root / "catalog.json").write_text(json.dumps({"items": [self.item]}), encoding="utf-8")

    def test_unknown_total_cannot_pass_local_audit(self):
        self.listing()
        audit = build_listing_audit(self.root)
        self.assertFalse(audit["is_complete"])
        self.assertEqual(audit["status"], "partial")
        self.assertIsNone(audit["expected_page_count"])
        self.assertFalse(audit["pagination_total_known"])

    def test_known_total_remains_complete(self):
        self.listing("1/1")
        audit = build_listing_audit(self.root)
        self.assertTrue(audit["is_complete"])
        self.assertEqual(audit["expected_page_count"], 1)

    def test_login_redirect_is_not_a_valid_product_detail(self):
        self.listing("1/1")
        details = self.root / "details"
        details.mkdir()
        (details / "cl226-id.txt").write_text("Please sign in to continue", encoding="utf-8")
        record = {
            "item_id": "cl226-id", "listing_url": self.url,
            "detail_url": "https://login.alibaba.com/",
            "detail_page": {"body_text_file": "cl226-id.txt", "title": "Login"},
        }
        path = details / "cl226-id.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        failure = inspect_supplier_capture(self.root, require_details=True)
        self.assertEqual(failure["status"], "partial")
        self.assertEqual(failure["valid_detail_products"], 0)
        self.assertIn("invalid_or_orphan_detail", failure["failures"])
        for destination in ("https://www.alibaba.com/", "https://evil.example/product-detail/CL226"):
            with self.subTest(destination=destination):
                record["detail_url"] = destination
                path.write_text(json.dumps(record), encoding="utf-8")
                self.assertEqual(inspect_supplier_capture(self.root, require_details=True)["status"], "partial")
        record["detail_url"] = self.url
        path.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(inspect_supplier_capture(self.root, require_details=True)["status"], "complete")


if __name__ == "__main__":
    unittest.main()
