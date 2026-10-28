"""Integration test for fresh, unverified V13 supplier Markdown imports."""
from __future__ import annotations

import contextlib
import importlib.util
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
