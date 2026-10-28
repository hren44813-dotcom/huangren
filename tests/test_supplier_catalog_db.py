"""Offline tests for the normalized supplier catalog database."""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.supplier_catalog_db import (  # noqa: E402
    audit_supplier_db, export_supplier_db, initialize_supplier_db, list_supplier_products,
    open_supplier_db, sync_supplier_catalog,
)


class SupplierCatalogDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capture = self.root / "capture"
        self.capture.mkdir()
        self.db = self.root / "local" / "supplier_catalog.sqlite3"
        self.snapshot = self.root / "snapshot.json"
        self.write_snapshot()

    def item(self, *, price="CN¥3.46-4.98", captured="2026-10-28", sales=11):
        return {
            "position": 1, "title": "CL226 40mm 50mm 60mm Cabinet Door Hinge",
            "models": ["CL226"], "category_guess": "hinge",
            "price_text": price,
            "price_min_cny": float(price.replace("CN¥", "").split("-")[0]),
            "price_max_cny": float(price.replace("CN¥", "").split("-")[-1]),
            "price_currency": "CNY", "moq_quantity": 1, "moq_unit": "piece",
            "sales_count_displayed": sales,
            "sales_status": "displayed_on_captured_listing" if sales is not None else "not_displayed_on_captured_listing",
            "product_url": "https://www.alibaba.com/product-detail/CL226_1601801131375.html?tracking=1",
            "image_asset_label": "CL226.png_480x480.jpg",
            "source_url": "https://dgdeler.en.alibaba.com/productlist.html",
            "captured_at": captured,
            "title_claims_unverified": ["40mm", "50mm", "60mm"],
        }

    def write_snapshot(self, items=None):
        data = {
            "schema_version": "1.0",
            "snapshot_id": "test-snapshot",
            "captured_at": "2026-10-28",
            "source": {
                "platform": "Alibaba.com",
                "supplier": "Dongguan Dele Hardware Technology Co., Ltd.",
                "url": "https://dgdeler.en.alibaba.com/productlist.html?tracking=1",
                "canonical_url": "https://dgdeler.en.alibaba.com/productlist.html",
                "displayed_pagination": "1/139",
                "visible_item_count": 1,
            },
            "items": items if items is not None else [self.item()],
        }
        self.snapshot.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_snapshot_import_creates_normalized_rows_and_preserves_null_semantics(self):
        summary = sync_supplier_catalog(self.db, capture_dir=self.capture, snapshot_json=self.snapshot)
        self.assertEqual(summary["products_seen"], 1)
        self.assertEqual(summary["observations_inserted"], 1)
        self.assertEqual(summary["status"], "partial")
        audit = audit_supplier_db(self.db)
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["counts"]["supplier_catalog_products"], 1)
        with open_supplier_db(self.db) as conn:
            row = conn.execute("SELECT * FROM supplier_catalog_observations").fetchone()
            self.assertEqual(row["price_currency"], "CNY")
            self.assertEqual(row["price_min"], 3.46)
            self.assertEqual(row["sales_count_displayed"], 11)
            self.assertEqual(row["verification_status"], "seller_listing_observation_unverified")
            self.assertEqual(conn.execute("SELECT model_code FROM supplier_catalog_model_mentions").fetchone()[0], "CL226")

    def test_reimport_is_idempotent_but_price_change_creates_history(self):
        first = sync_supplier_catalog(self.db, capture_dir=self.capture, snapshot_json=self.snapshot)
        second = sync_supplier_catalog(self.db, capture_dir=self.capture, snapshot_json=self.snapshot)
        self.assertEqual(first["observations_inserted"], 1)
        self.assertEqual(second["observations_inserted"], 0)
        self.assertEqual(second["observations_unchanged"], 1)
        self.write_snapshot([self.item(price="CN¥3.80-5.10", captured="2026-10-29")])
        third = sync_supplier_catalog(self.db, capture_dir=self.capture, snapshot_json=self.snapshot)
        self.assertEqual(third["observations_inserted"], 1)
        with open_supplier_db(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM supplier_catalog_observations").fetchone()[0], 2)

    def test_unshown_sales_stays_null_and_search_finds_model(self):
        self.write_snapshot([self.item(sales=None)])
        sync_supplier_catalog(self.db, capture_dir=self.capture, snapshot_json=self.snapshot)
        results = list_supplier_products(self.db, query="CL226")
        self.assertEqual(len(results), 1)
        with open_supplier_db(self.db) as conn:
            row = conn.execute("SELECT sales_count_displayed,sales_status FROM supplier_catalog_observations").fetchone()
            self.assertIsNone(row["sales_count_displayed"])
            self.assertEqual(row["sales_status"], "not_displayed_on_captured_listing")

    def test_append_only_observations_reject_update_and_delete(self):
        sync_supplier_catalog(self.db, capture_dir=self.capture, snapshot_json=self.snapshot)
        with open_supplier_db(self.db) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE supplier_catalog_observations SET price_min=0")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM supplier_catalog_observations")

    def test_detail_attributes_and_options_are_indexed_with_provenance(self):
        item = self.item()
        item["item_id"] = "a" * 16
        (self.capture / "catalog.json").write_text(json.dumps({
            "supplier": "Dongguan Dele Hardware Technology Co., Ltd.",
            "source_url": "https://dgdeler.en.alibaba.com/productlist.html",
            "updated_at": "2026-10-28",
            "items": [{
                "item_id": item["item_id"], "title": item["title"],
                "product_url": "https://www.alibaba.com/product-detail/CL226_1601801131375.html",
                "price_text": item["price_text"], "price_min": 3.46, "price_max": 4.98,
                "price_currency": "CNY", "moq_quantity": 1, "moq_unit": "piece",
                "sales_count_displayed": 11, "sales_status": "displayed",
                "model_hints": ["CL226"], "captured_at": "2026-10-28",
            }],
        }, ensure_ascii=False), encoding="utf-8")
        details = self.capture / "details"
        details.mkdir()
        detail_record = {
            "item_id": item["item_id"], "listing_title": item["title"],
            "listing_url": "https://www.alibaba.com/product-detail/CL226_1601801131375.html",
            "detail_url": "https://www.alibaba.com/product-detail/CL226_1601801131375.html",
            "captured_at": "2026-10-28T00:00:00+00:00",
            "verification_status": "visible_detail_page_observation_unverified",
            "detail_page": {
                "title": "CL226 hinge", "canonical_url": "https://www.alibaba.com/product-detail/CL226_1601801131375.html",
                "body_text_file": f"{item['item_id']}.txt",
                "table_rows": [["Material", "SUS304"]], "definition_rows": [],
                "json_ld": [], "json_ld_errors": [], "option_groups": [{
                    "kind": "choice", "group": "Color", "options": [
                        {"label": "Black", "value": "black", "selected": True, "disabled": False}
                    ],
                }], "image_urls": ["https://example.com/hinge.png"],
            },
        }
        (details / f"{item['item_id']}.json").write_text(json.dumps(detail_record), encoding="utf-8")
        (details / f"{item['item_id']}.txt").write_text("CL226 hinge Material SUS304", encoding="utf-8")
        pages = self.capture / "pages"
        pages.mkdir()
        (pages / "page_001.json").write_text(json.dumps({
            "page_number": 1, "pagination_text": "1/1",
            "items": [{"product_url": "https://www.alibaba.com/product-detail/CL226_1601801131375.html"}],
        }), encoding="utf-8")
        (self.capture / "catalog_audit.json").write_text(json.dumps({"status": "complete"}), encoding="utf-8")
        (self.capture / "details_audit.json").write_text(json.dumps({"status": "complete"}), encoding="utf-8")
        summary = sync_supplier_catalog(self.db, capture_dir=self.capture, snapshot_json=None, require_details=True)
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["details_inserted"], 1)
        with open_supplier_db(self.db) as conn:
            attr = conn.execute("SELECT attribute,value,source_locator FROM supplier_catalog_attributes").fetchone()
            option = conn.execute("SELECT group_name,option_label,is_selected FROM supplier_catalog_options").fetchone()
            self.assertEqual((attr["attribute"], attr["value"]), ("Material", "SUS304"))
            self.assertEqual(option["group_name"], "Color")
            self.assertEqual(option["option_label"], "Black")
            self.assertEqual(option["is_selected"], 1)

    def test_invalid_page_checkpoint_is_logged_and_marks_run_partial(self):
        pages = self.capture / "pages"
        pages.mkdir()
        (pages / "page_001.json").write_text("{bad json", encoding="utf-8")
        summary = sync_supplier_catalog(self.db, capture_dir=self.capture, snapshot_json=self.snapshot)
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["errors"], 1)
        audit = audit_supplier_db(self.db)
        self.assertEqual(audit["counts"]["supplier_catalog_errors"], 1)

    def test_export_writes_product_history_attributes_and_audit(self):
        sync_supplier_catalog(self.db, capture_dir=self.capture, snapshot_json=self.snapshot)
        result = export_supplier_db(self.db, self.root / "exports")
        self.assertTrue(result["audit"]["ok"])
        self.assertTrue((self.root / "exports" / "supplier_products.csv").is_file())
        self.assertTrue((self.root / "exports" / "supplier_price_history.csv").is_file())
        with (self.root / "exports" / "supplier_products.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["latest_price_text"], "CN¥3.46-4.98")

    def test_dry_run_does_not_create_database(self):
        result = sync_supplier_catalog(self.db, capture_dir=self.capture, snapshot_json=self.snapshot, dry_run=True)
        self.assertEqual(result["status"], "preview")
        self.assertFalse(self.db.exists())


    def test_listing_only_run_can_be_complete_without_detail_collection(self):
        """A listing-only workflow must not be failed by an intentionally skipped detail stage."""
        pages = self.capture / "pages"
        pages.mkdir()
        item = self.item()
        (pages / "page_001.json").write_text(json.dumps({
            "page_number": 1, "source_url": "https://dgdeler.en.alibaba.com/productlist.html",
            "page_url": "https://dgdeler.en.alibaba.com/productlist.html",
            "captured_at": "2026-10-28", "pagination_text": "1/1",
            "items": [{
                "title": item["title"], "product_url": "https://www.alibaba.com/product-detail/CL226_1601801131375.html",
                "price_text": item["price_text"], "price_min": 3.46, "price_max": 4.98,
                "price_currency": "CNY", "moq_quantity": 1, "moq_unit": "piece",
                "sales_count_displayed": 11, "sales_status": "displayed", "model_hints": ["CL226"],
                "captured_at": "2026-10-28",
            }],
        }), encoding="utf-8")
        self.write_snapshot([item])
        (self.capture / "catalog.json").write_text(json.dumps({
            "supplier": "Dongguan Dele Hardware Technology Co., Ltd.",
            "source_url": "https://dgdeler.en.alibaba.com/productlist.html",
            "items": [item],
        }), encoding="utf-8")
        (self.capture / "catalog_audit.json").write_text(json.dumps({"status": "complete"}), encoding="utf-8")
        (self.capture / "details_audit.json").write_text(json.dumps({"status": "partial"}), encoding="utf-8")
        summary = sync_supplier_catalog(self.db, capture_dir=self.capture, snapshot_json=self.snapshot)
        self.assertEqual(summary["status"], "complete")
        self.assertFalse(summary["detail_collection_requested"])
        self.assertEqual(summary["detail_audit_status"], "not_requested")

    def test_requested_but_incomplete_detail_collection_makes_run_partial(self):
        """An explicit marker prevents a failed detail stage from being treated as skipped."""
        self.write_snapshot()
        (self.capture / "catalog_audit.json").write_text(json.dumps({"status": "complete"}), encoding="utf-8")
        (self.capture / "details_audit.json").write_text(json.dumps({"status": "partial"}), encoding="utf-8")
        (self.capture / "details_collection_requested.json").write_text(json.dumps({"requested": True}), encoding="utf-8")
        summary = sync_supplier_catalog(self.db, capture_dir=self.capture, snapshot_json=self.snapshot)
        self.assertEqual(summary["status"], "partial")
        self.assertTrue(summary["detail_collection_requested"])
        self.assertEqual(summary["detail_audit_status"], "partial")


    def test_forged_complete_audit_does_not_override_real_missing_pages(self):
        """Legacy reports cannot grant a complete run without all real checkpoint files."""
        (self.capture / "catalog_audit.json").write_text(json.dumps({"status": "complete"}), encoding="utf-8")
        (self.capture / "details_audit.json").write_text(json.dumps({"status": "complete"}), encoding="utf-8")
        summary = sync_supplier_catalog(self.db, capture_dir=self.capture, snapshot_json=self.snapshot)
        self.assertEqual(summary["status"], "partial")
        self.assertIn("no_page_checkpoints", summary["independent_validation_failures"])
        self.assertEqual(summary["listing_audit_status"], "partial")

    def test_sync_require_details_cannot_call_listing_only_complete(self):
        """Requiring detail coverage fails even if one listing page is fully captured."""
        pages = self.capture / "pages"
        pages.mkdir()
        item = self.item()
        (pages / "page_001.json").write_text(json.dumps({
            "page_number": 1, "pagination_text": "1/1", "items": [item],
        }), encoding="utf-8")
        summary = sync_supplier_catalog(self.db, capture_dir=self.capture, snapshot_json=self.snapshot,
                                        require_details=True)
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["detail_audit_status"], "partial")
        self.assertEqual(len(summary["independent_capture_validation"]["missing_detail_ids"]), 1)


if __name__ == "__main__":
    unittest.main()
