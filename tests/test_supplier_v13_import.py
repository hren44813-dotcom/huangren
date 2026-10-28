"""Integration test for fresh, unverified V13 supplier Markdown imports."""
from __future__ import annotations

import contextlib
import importlib.util
import json
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SupplierV13ImportTests(unittest.TestCase):
    """Ensure import works on a fresh DB and cannot auto-create accepted claims."""

    def test_fresh_v13_import_is_unverified_and_idempotent(self):
        spec = importlib.util.spec_from_file_location(
            "import_supplier_capture_v13_test", ROOT / "scripts" / "import_supplier_capture_v13.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "details_markdown"
            capture.mkdir()
            (capture / "cl226.md").write_text(
                "# CL226 supplier page\n\nMaterial: SUS304\nSource: https://www.alibaba.com/product-detail/CL226_123.html\n"
                "Supplier claim, not independently verified.\n",
                encoding="utf-8",
            )
            db = root / "v13.sqlite3"
            args = ["--capture-dir", str(capture), "--database", str(db)]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(args), 0)
                self.assertEqual(module.main(args), 0)
            with sqlite3.connect(db) as conn:
                source = conn.execute(
                    "SELECT source_kind,authority_level FROM knowledge_sources"
                ).fetchone()
                self.assertEqual(source, ("supplier_document", "unverified"))
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM knowledge_sources").fetchone()[0], 1)
                self.assertGreater(conn.execute(
                    "SELECT COUNT(*) FROM knowledge_document_segments"
                ).fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM knowledge_claims").fetchone()[0], 0)
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                metadata = json.loads(conn.execute("SELECT metadata_json FROM knowledge_sources").fetchone()[0])
                self.assertEqual(metadata["source_url"], "https://www.alibaba.com/product-detail/CL226_123.html")

    def test_reference_snapshots_import_with_original_urls_and_no_claims(self):
        """Import the already captured listing/profile summaries with explicit provenance."""
        spec = importlib.util.spec_from_file_location(
            "import_supplier_capture_reference_test", ROOT / "scripts" / "import_supplier_capture_v13.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "empty_details"
            capture.mkdir()
            db = root / "v13.sqlite3"
            args = ["--capture-dir", str(capture), "--database", str(db), "--include-reference-snapshots"]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(args), 0)
            with sqlite3.connect(db) as conn:
                rows = conn.execute(
                    "SELECT original_filename,source_kind,authority_level,metadata_json FROM knowledge_sources"
                ).fetchall()
                self.assertEqual(len(rows), 3)
                by_name = {row[0]: row for row in rows}
                listing = by_name["dgdeler_product_list_page1_2026-10-28.md"]
                self.assertEqual(listing[1:3], ("other", "unverified"))
                listing_metadata = json.loads(listing[3])
                self.assertEqual(listing_metadata["page_kind"], "product_listing_snapshot")
                self.assertEqual(listing_metadata["source_url"], "https://dgdeler.en.alibaba.com/productlist.html?spm=a2700.shop_index.88.6.84326737Gvoopq")
                profile = by_name["dgdeler_supplier_profile_2026-10-28.md"]
                self.assertEqual(json.loads(profile[3])["source_url"], "https://dgdeler.en.alibaba.com/")
                categories = by_name["dgdeler_store_category_index_2026-10-28.md"]
                self.assertEqual(categories[1:3], ("other", "unverified"))
                category_metadata = json.loads(categories[3])
                self.assertEqual(category_metadata["page_kind"], "store_category_index_snapshot")
                self.assertEqual(category_metadata["source_url"], "https://dgdeler.en.alibaba.com/")
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM knowledge_claims").fetchone()[0], 0)
