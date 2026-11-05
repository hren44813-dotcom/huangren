"""Focused offline regressions for review findings in supplier capture and evidence gates."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecom_images.supplier_capture.listing import parse_listing_item
from ecom_images.supplier_capture.detail import enrich_detail_payload
from ecom_images.supplier_db.helpers import _models
from ecom_images.image_evidence_gate_v13 import _contains_value


class SupplierReviewRegressionTests(unittest.TestCase):
    def test_plain_english_words_are_not_model_codes(self):
        source = "https://dgdeler.en.alibaba.com/productlist.html"
        samples = {
            "Glass Door Hinge CL226": ["CL226"],
            "Clear Cabinet Hinge": [],
            "Clamping Fixture": [],
            "GL1-336 and MS705-3 hinge": ["GL1-336", "MS705-3"],
            "Industrial CL263n and HC01": ["CL263N", "HC01"],
        }
        for title, expected in samples.items():
            with self.subTest(title=title):
                row = parse_listing_item(
                    {"title": title, "url": "https://example.com/item", "card_text": ""},
                    1, source,
                )
                self.assertEqual(row["model_hints"], sorted(expected))
                self.assertEqual(_models({"title": title}), expected)
        self.assertEqual(
            _models({"title": "Glass Door Hinge CL226", "model_hints": ["GLASS", "CL226"]}),
            ["CL226"],
        )
        self.assertEqual(_models({"title": "Clear Cabinet Hinge", "model_hints": ["CLEAR"]}), [])

    def test_empty_table_cells_never_shift_attributes(self):
        raw = {"table_rows": [
            ["Material", "", "Finish", "Zinc"],
            ["Hole Distance", "40 mm", "Thickness", "2 mm"],
            ["Material", "", "Finish"],
        ]}
        result = enrich_detail_payload(raw, "")
        actual = [(entry["key"], entry["value"]) for entry in result["attribute_pairs"]]
        self.assertEqual(actual, [
            ("Finish", "Zinc"), ("Hole Distance", "40 mm"), ("Thickness", "2 mm"),
        ])

    def test_numeric_value_and_unit_are_checked_as_a_pair(self):
        approved = ("6 N.m", "6N.m", "6.0 N.m", "Rated torque: 6 N·m")
        rejected = ("6 kN.m", "6 pcs, 8 N.m", "16 N.m", "6 N.mm", "6 kgf.cm")
        for copy in approved:
            with self.subTest(approved=copy):
                self.assertTrue(_contains_value(copy, "6", "N.m"))
        for copy in rejected:
            with self.subTest(rejected=copy):
                self.assertFalse(_contains_value(copy, "6", "N.m"))

    def test_import_reference_snapshots_when_detail_folder_is_missing(self):
        spec = importlib.util.spec_from_file_location(
            "import_supplier_capture_missing_details",
            ROOT / "scripts" / "import_supplier_capture_v13.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            absent = base / "not_yet_collected"
            database = base / "sources.sqlite3"
            args = [
                "--capture-dir", str(absent),
                "--database", str(database),
                "--include-reference-snapshots",
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(args + ["--dry-run"]), 0)
                self.assertEqual(module.main(args), 0)
            self.assertFalse(absent.exists())
            with sqlite3.connect(database) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM knowledge_sources").fetchone()[0], 3)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM knowledge_claims").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
