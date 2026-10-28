"""Regression and schema-compatibility tests for the supplier module split."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecom_images import supplier_catalog_capture as legacy_capture  # noqa: E402
from ecom_images import supplier_catalog_db as legacy_db  # noqa: E402
from ecom_images.supplier_capture import audit, browser_js, detail, export, listing  # noqa: E402
from ecom_images.supplier_db import helpers, reports, schema, service, writes  # noqa: E402
from ecom_images.catalog_v12 import initialize_catalog  # noqa: E402
from ecom_images.database_v9 import open_database  # noqa: E402
from ecom_images.knowledge_ingest_v13 import initialize_ingestion  # noqa: E402
from ecom_images.knowledge_schema_v13 import initialize_knowledge  # noqa: E402


class SupplierRefactorCompatibilityTests(unittest.TestCase):
    """Preserve historical import paths, local databases and V13 evidence isolation."""

    def test_legacy_import_paths_are_stable(self):
        """Existing scripts and tests continue to invoke the exact same implementation."""
        self.assertIs(legacy_db.initialize_supplier_db, schema.initialize_supplier_db)
        self.assertIs(legacy_db.sync_supplier_catalog, service.sync_supplier_catalog)
        self.assertIs(legacy_db.audit_supplier_db, reports.audit_supplier_db)
        self.assertIs(legacy_db._load_inputs, helpers._load_inputs)
        self.assertIs(legacy_db._insert_detail, writes._insert_detail)
        self.assertIs(legacy_capture.parse_listing_item, listing.parse_listing_item)
        self.assertIs(legacy_capture.enrich_detail_payload, detail.enrich_detail_payload)
        self.assertIs(legacy_capture.write_detail_exports, audit.write_detail_exports)
        self.assertIs(legacy_capture.save_listing_outputs, export.save_listing_outputs)
        self.assertEqual(legacy_capture.DETAIL_JS, browser_js.DETAIL_JS)

    def test_supplier_schema_v1_reopens_without_migration_or_data_loss(self):
        """Initialization must not overwrite existing V1 observations or append-only guards."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "supplier.sqlite3"
            legacy_db.initialize_supplier_db(path)
            with sqlite3.connect(path) as conn:
                original_schema = {
                    row[0]: row[1] for row in conn.execute(
                        "SELECT name,sql FROM sqlite_master WHERE type IN ('table','trigger')"
                        " AND name LIKE 'supplier_catalog_%'"
                    )
                }
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertIn("supplier_catalog_observations_no_update", original_schema)
                conn.execute(
                    """INSERT INTO supplier_catalog_suppliers
                    (id, platform, name, storefront_url, created_utc, updated_utc)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    ("historical-supplier", "Alibaba.com", "Existing Supplier",
                     "https://existing.alibaba.com", "2026-10-01", "2026-10-01"),
                )
                conn.execute(
                    """INSERT INTO supplier_catalog_products
                    (id, supplier_id, product_url, title, first_seen_utc, last_seen_utc)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    ("historical-product", "historical-supplier",
                     "https://www.alibaba.com/product-detail/Existing_123.html",
                     "Original historical product", "2026-10-01", "2026-10-01"),
                )
                conn.commit()
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(conn.execute(
                    "SELECT value FROM supplier_catalog_meta WHERE key='schema_version'"
                ).fetchone()[0], "1")
            legacy_db.initialize_supplier_db(path)
            schema.initialize_supplier_db(path)
            with sqlite3.connect(path) as conn:
                after = {
                    row[0]: row[1] for row in conn.execute(
                        "SELECT name,sql FROM sqlite_master WHERE type IN ('table','trigger')"
                        " AND name LIKE 'supplier_catalog_%'"
                    )
                }
                self.assertEqual(original_schema, after)
                self.assertEqual(conn.execute(
                    "SELECT title FROM supplier_catalog_products WHERE id=?",
                    ("historical-product",),
                ).fetchone()[0], "Original historical product")
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_reject_unknown_database_version_and_preserve_existing_file(self):
        """Never run destructive DDL against a database with an unknown version."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "foreign.sqlite3"
            with sqlite3.connect(path) as conn:
                conn.execute("CREATE TABLE important_legacy_data (value TEXT)")
                conn.execute("INSERT INTO important_legacy_data(value) VALUES ('keep me')")
                conn.execute("PRAGMA user_version=77")
            with self.assertRaises(RuntimeError):
                legacy_db.initialize_supplier_db(path)
            with sqlite3.connect(path) as conn:
                self.assertEqual(
                    conn.execute("SELECT value FROM important_legacy_data").fetchone()[0],
                    "keep me",
                )
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 77)

    def test_v13_knowledge_database_remains_separate_from_supplier_sqlite(self):
        """The supplier schema must not mutate the V13 evidence/source database."""
        with tempfile.TemporaryDirectory() as tmp:
            v13_path = Path(tmp) / "knowledge.sqlite3"
            supplier_path = Path(tmp) / "supplier.sqlite3"
            with open_database(v13_path):
                pass
            initialize_catalog(v13_path)
            initialize_knowledge(v13_path)
            initialize_ingestion(v13_path)
            with sqlite3.connect(v13_path) as conn:
                original = conn.execute(
                    "SELECT name,sql FROM sqlite_master WHERE type='table'"
                ).fetchall()
                self.assertTrue(any(x[0] == "knowledge_sources" for x in original))
                version = conn.execute("PRAGMA user_version").fetchone()[0]
            legacy_db.initialize_supplier_db(supplier_path)
            with sqlite3.connect(v13_path) as conn:
                self.assertEqual(original, conn.execute(
                    "SELECT name,sql FROM sqlite_master WHERE type='table'"
                ).fetchall())
                self.assertEqual(version, conn.execute("PRAGMA user_version").fetchone()[0])
                self.assertFalse(any(x[0] == "supplier_catalog_products" for x in original))
            with sqlite3.connect(supplier_path) as conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_refactored_supplier_modules_stay_under_300_lines(self):
        """Prevent future monolithic regressions in the refactored supplier subsystem."""
        files = [
            ROOT / "src/ecom_images/supplier_catalog_db.py",
            ROOT / "src/ecom_images/supplier_catalog_capture.py",
            ROOT / "scripts/supplier_catalog_capture.py",
            *sorted((ROOT / "src/ecom_images/supplier_db").glob("*.py")),
            *sorted((ROOT / "src/ecom_images/supplier_capture").glob("*.py")),
        ]
        self.assertGreaterEqual(len(files), 12)
        for file in files:
            with self.subTest(file=file.name):
                self.assertLessEqual(
                    len(file.read_text(encoding="utf-8").splitlines()),
                    300,
                )


if __name__ == "__main__":
    unittest.main()
