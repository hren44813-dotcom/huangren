"""Offline regression tests for isolated supplier batches and safe checkpoint recovery."""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.supplier_capture.batch import (
    start_batch, read_batch, reusable_page, reusable_detail,
)
from ecom_images.supplier_capture.export import save_listing_outputs
from ecom_images.supplier_capture.audit import write_detail_exports
from ecom_images.supplier_capture_validation import inspect_supplier_capture
from ecom_images.supplier_db.helpers import _load_inputs
from ecom_images.supplier_capture.runner_helpers import click_page_number

SCRIPT = ROOT / "scripts" / "supplier_catalog_capture.py"
spec = importlib.util.spec_from_file_location("supplier_catalog_capture_cli_recovery", SCRIPT)
capture_cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture_cli)

URL1 = "https://www.alibaba.com/product-detail/CL226_123.html"
URL2 = "https://www.alibaba.com/product-detail/MS705_456.html"


def item(item_id, url, page):
    return {"item_id": item_id, "product_url": url, "title": item_id, "page_number": page}


def checkpoint(page, total, product, *, batch=None):
    return {"page_number": page, "pagination_text": f"{page}/{total}",
            "items": [product], **({"capture_batch_id": batch["batch_id"]} if batch else {})}


class BatchIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "pages").mkdir()
        self.old1 = item("CL226", URL1, 1)
        self.old2 = item("MS705", URL2, 2)
        self.write_page(1, checkpoint(1, 2, self.old1))
        self.write_page(2, checkpoint(2, 2, self.old2))
        save_listing_outputs(self.root)

    def write_page(self, number, content):
        (self.root / "pages" / f"page_{number:03d}.json").write_text(
            json.dumps(content), encoding="utf-8"
        )

    def test_new_batch_excludes_old_checkpoints_and_snapshot_from_current_catalog(self):
        batch = start_batch(self.root)
        self.assertEqual(read_batch(self.root)["batch_id"], batch["batch_id"])
        initially = save_listing_outputs(self.root)
        self.assertEqual(initially["unique_product_count"], 0)
        self.assertEqual(initially["stale_page_count"], 2)
        self.assertEqual(initially["audit_status"], "partial")
        self.write_page(1, checkpoint(1, 2, self.old1, batch=batch))
        intermediate = save_listing_outputs(self.root)
        self.assertEqual(intermediate["unique_product_count"], 1)
        self.assertEqual(intermediate["stale_page_count"], 1)
        self.assertEqual(intermediate["missing_page_count"], 1)
        self.assertEqual(inspect_supplier_capture(self.root)["status"], "partial")
        old_snapshot = self.root / "old_snapshot.json"
        old_snapshot.write_text(json.dumps({"source": {"url": "https://dgdeler.en.alibaba.com/productlist.html"},
                                            "items": [self.old2]}), encoding="utf-8")
        catalog, pages, details, errors = _load_inputs(self.root, old_snapshot)
        self.assertEqual([row["product_url"] for row in catalog["items"]], [URL1])
        self.assertEqual([path.name for path, record in pages], ["page_001.json"])
        self.assertFalse(details)
        self.assertFalse(errors)
        self.write_page(2, checkpoint(2, 2, self.old2, batch=batch))
        final = save_listing_outputs(self.root)
        self.assertEqual(final["unique_product_count"], 2)
        self.assertEqual(final["stale_page_count"], 0)
        self.assertEqual(inspect_supplier_capture(self.root)["status"], "complete")

    def test_page_resume_checks_nonempty_valid_current_batch_records(self):
        batch = start_batch(self.root)
        self.assertFalse(reusable_page(checkpoint(1, 2, self.old1), 1, batch))
        self.assertTrue(reusable_page(checkpoint(1, 2, self.old1, batch=batch), 1, batch))
        self.assertFalse(reusable_page(checkpoint(1, 2, self.old1, batch=batch), 2, batch))
        self.assertFalse(reusable_page({"page_number": 1, "pagination_text": "1/2", "items": [],
                                        "capture_batch_id": batch["batch_id"]}, 1, batch))
        untrusted = item("bad", "http://127.0.0.1/product-detail/test", 1)
        self.assertFalse(reusable_page(checkpoint(1, 2, untrusted, batch=batch), 1, batch))

    def test_corrupt_manifest_never_uses_old_pages_as_new(self):
        (self.root / "listing_batch.json").write_text("{broken", encoding="utf-8")
        report = inspect_supplier_capture(self.root)
        self.assertEqual(report["status"], "partial")
        self.assertIn("invalid_capture_batch_manifest", report["failures"])
        with self.assertRaises(ValueError):
            save_listing_outputs(self.root)

    def test_stale_catalog_cannot_be_imported_as_current_batch(self):
        batch = start_batch(self.root)
        catalog, pages, details, errors = _load_inputs(self.root, None)
        self.assertEqual(catalog["items"], [])
        self.assertFalse(pages)
        self.assertTrue(any(e["stage"] == "capture_batch" for e in errors))
        report = inspect_supplier_capture(self.root)
        self.assertIn("catalog_capture_batch_mismatch", report["failures"])


class DetailRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.batch = start_batch(self.root)
        self.item_id = "CL226"
        self.item = item(self.item_id, URL1, 1)
        (self.root / "catalog.json").write_text(
            json.dumps({"capture_batch_id": self.batch["batch_id"], "items": [self.item]}),
            encoding="utf-8",
        )
        self.details = self.root / "details"
        self.details.mkdir()
        self.json_path = self.details / f"{self.item_id}.json"
        self.text_path = self.details / f"{self.item_id}.txt"
        self.error_path = self.details / "capture_errors.json"
        self.args = argparse.Namespace(output=self.root, delay=0, retries=0, limit=0,
                                       no_prompt=True, headless=True, save_html=False,
                                       profile_dir=self.root / ".profile")

    def record(self, batch=None):
        data = {"item_id": self.item_id, "listing_url": URL1, "detail_url": URL1,
                "detail_page": {"title": "CL226", "body_text_file": "CL226.txt"}}
        if batch is not None:
            data["capture_batch_id"] = batch["batch_id"]
        return data

    class FakePage:
        def __init__(self):
            self.visited = []
            self.url = ""
        def goto(self, url, **kwargs):
            self.url = url
            self.visited.append(url)
        def wait_for_timeout(self, delay):
            pass
        def evaluate(self, js):
            return {"title": "CL226", "body_text": "Real industrial hinge material SUS304"}

    class FakeContext:
        def close(self):
            pass

    class FakePlaywright:
        def stop(self):
            pass

    def run_details(self):
        page = self.FakePage()
        with patch.object(capture_cli, "launch_browser", return_value=(
                self.FakePlaywright(), self.FakeContext(), page)), contextlib.redirect_stdout(io.StringIO()):
            code = capture_cli.run_details(self.args)
        return code, page

    def test_valid_detail_resume_persists_cleared_error_even_when_skipped(self):
        self.json_path.write_text(json.dumps(self.record(self.batch)), encoding="utf-8")
        self.text_path.write_text("Material: SUS304", encoding="utf-8")
        self.error_path.write_text(json.dumps([{"item_id": self.item_id,
            "capture_batch_id": self.batch["batch_id"], "error_type": "OldFailure"}]), encoding="utf-8")
        code, page = self.run_details()
        self.assertEqual(code, 0)
        self.assertEqual(page.visited, ["https://dgdeler.en.alibaba.com/productlist.html"])
        self.assertEqual(json.loads(self.error_path.read_text(encoding="utf-8")), [])

    def test_empty_detail_is_recaptured_and_old_batch_cannot_be_reused(self):
        self.json_path.write_text(json.dumps(self.record()), encoding="utf-8")
        self.text_path.write_text("", encoding="utf-8")
        self.assertFalse(reusable_detail(self.record(), item_id=self.item_id, listing_url=URL1,
                                         text="old data", batch=self.batch))
        code, page = self.run_details()
        self.assertEqual(code, 0)
        self.assertIn(URL1, page.visited)
        self.assertEqual(json.loads(self.json_path.read_text(encoding="utf-8"))["capture_batch_id"],
                         self.batch["batch_id"])
        self.assertIn("SUS304", self.text_path.read_text(encoding="utf-8"))

    def test_old_batch_detail_is_not_current_complete(self):
        self.json_path.write_text(json.dumps(self.record()), encoding="utf-8")
        self.text_path.write_text("Old material", encoding="utf-8")
        report = write_detail_exports(self.root)
        self.assertFalse(report["is_complete"])
        self.assertEqual(report["missing_item_ids"], [self.item_id])


class PaginationNavigationTests(unittest.TestCase):
    def test_empty_product_links_after_click_are_not_success(self):
        class FakePage:
            def evaluate(self, code, *args):
                return True if "target =>" in code else ""
            def wait_for_function(self, *args, **kwargs):
                raise TimeoutError("no product links")
            def wait_for_timeout(self, *args):
                pass
        self.assertFalse(click_page_number(FakePage(), 2, "old-link"))


if __name__ == "__main__":
    unittest.main()
