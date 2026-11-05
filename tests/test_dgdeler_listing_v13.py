from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_dgdeler_listing_v13 import DEFAULT_SNAPSHOT, _safe_https_url, render_item_markdown


class DGDelerListingV13Tests(unittest.TestCase):
    def test_existing_page_one_snapshot_is_16_items_and_has_product_urls(self):
        snapshot = json.loads(DEFAULT_SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["source"]["displayed_pagination"], "1/139")
        self.assertEqual(len(snapshot["items"]), 16)
        for item in snapshot["items"]:
            self.assertTrue(_safe_https_url(item["product_url"], product=True).startswith("https://www.alibaba.com/product-detail/"))

    def test_render_keeps_observed_listing_fields_and_marks_unseen_fields(self):
        snapshot = json.loads(DEFAULT_SNAPSHOT.read_text(encoding="utf-8"))
        item = next(row for row in snapshot["items"] if "GL1-336" in row.get("title", ""))
        rendered = render_item_markdown(item, snapshot)
        self.assertIn("GL1-336", rendered)
        self.assertIn("CN¥16.33", rendered)
        self.assertIn("SKU/变体选项：未在当前商品列表快照中显示", rendered)
        self.assertIn("材质：未在当前商品列表快照中显示", rendered)
        self.assertIn("尺寸/孔距/外形：未在当前商品列表快照中显示", rendered)
        self.assertIn("详情页 MOQ 与阶梯数量：未在当前商品列表快照中显示", rendered)
        self.assertIn(item["product_url"], rendered)

    def test_non_alibaba_and_non_product_detail_urls_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "HTTPS Alibaba"):
            _safe_https_url("https://example.com/product-detail/x.html", product=True)
        with self.assertRaisesRegex(ValueError, "product-detail"):
            _safe_https_url("https://www.alibaba.com/product/x.html", product=True)

    def test_dry_run_reports_listing_coverage_without_touching_database(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "should-not-exist.sqlite3"
            run = subprocess.run(
                [sys.executable, str(ROOT / "scripts/import_dgdeler_listing_v13.py"),
                 "--snapshot-json", str(DEFAULT_SNAPSHOT), "--database", str(db), "--dry-run"],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(run.stdout)
            self.assertEqual(result["unique_products"], 16)
            self.assertFalse(result["creates_claims"])
            self.assertFalse(result["creates_sku_mappings"])
            self.assertFalse(db.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
