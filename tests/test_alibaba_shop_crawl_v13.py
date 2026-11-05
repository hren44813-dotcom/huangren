from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "scripts"))
import crawl_alibaba_shop_v13 as crawler


class AlibabaShopCrawlerTests(unittest.TestCase):
    def test_url_canonicalization_keeps_shop_and_removes_tracking(self):
        url = crawler.canonical_url(
            "http://dgdeler.en.alibaba.com/productlist.html?spm=a2700.x&productId=123#top"
        )
        self.assertEqual(url, "https://dgdeler.en.alibaba.com/productlist.html?productId=123")
        self.assertIsNone(crawler.canonical_url("https://example.com/product-detail/x.html"))
        self.assertIsNone(crawler.canonical_url("javascript:alert(1)"))

    def test_page_classification_does_not_invent_product_identity(self):
        self.assertEqual(crawler.classify_page("https://dgdeler.en.alibaba.com/productlist.html", "Lock"), "listing_or_category")
        self.assertEqual(crawler.classify_page("https://dgdeler.en.alibaba.com/product-detail/test.html", "Handle"), "possible_product_detail")
        self.assertEqual(crawler.classify_page("https://dgdeler.en.alibaba.com/company_profile.html", "Company"), "company_profile")
        self.assertEqual(crawler.classify_page("https://dgdeler.en.alibaba.com/unknown.html", "Product"), "other_store_page")

    def test_extracts_only_literal_fields_and_leaves_missing_fields_missing(self):
        values = crawler.extract_literal_candidates(
            "Model: MS705 | Material: Zinc alloy | Dimensions: 20 x 22.5 mm | MOQ: 10 pcs"
        )
        self.assertEqual(values["model_or_sku"], "MS705")
        self.assertEqual(values["material"], "Zinc alloy")
        self.assertEqual(values["dimensions"], "20 x 22.5 mm")
        self.assertEqual(values["moq"], "10 pcs")
        self.assertNotIn("price", values)
        self.assertNotIn("specification", values)

    def test_captcha_page_is_reported_and_never_imported_as_product(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def fake_fetch(url, timeout):
                return 200, "<html><title>Captcha</title>Sorry, we have detected unusual traffic</html>", url
            with patch.object(crawler, "initialize_ingestion"), patch.object(crawler, "import_document") as importer:
                report = crawler.crawl(
                    crawler.DEFAULT_START, max_pages=2, delay=0, database=root / "db.sqlite3",
                    output_dir=root / "out", fetcher=fake_fetch,
                )
            self.assertTrue(report["captcha_blocked"])
            self.assertEqual(report["pages_imported"], 0)
            self.assertEqual(report["pages"][0]["status"], "blocked")
            self.assertEqual(importer.call_count, 0)
            self.assertTrue((root / "out" / "crawl-report.json").is_file())
            self.assertTrue((root / "out" / "page-inventory.csv").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
