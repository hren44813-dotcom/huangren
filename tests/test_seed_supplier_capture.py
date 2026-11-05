"""Tests for the first-page seed and resumable capture CLI flags."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class SupplierCaptureSeedTests(unittest.TestCase):
    def test_seed_creates_a_scoped_page_one_checkpoint_without_claiming_completeness(self):
        seed = load_script("seed_supplier_capture_test", "seed_supplier_capture.py")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "capture"
            with contextlib.redirect_stdout(io.StringIO()):
                code = seed.main(["--output", str(output)])
            self.assertEqual(code, 0)
            page = json.loads((output / "pages" / "page_001.json").read_text(encoding="utf-8"))
            catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
            self.assertEqual(page["pagination_text"], "1/139")
            self.assertEqual(page["visible_item_count"], 16)
            self.assertEqual(len(catalog["items"]), 16)
            self.assertFalse(catalog.get("complete_catalog", False))
            self.assertTrue(page["seeded_from_committed_snapshot"])

    def test_seed_refuses_to_overwrite_existing_capture_without_force(self):
        seed = load_script("seed_supplier_capture_test_no_overwrite", "seed_supplier_capture.py")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "capture"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(seed.main(["--output", str(output)]), 0)
                self.assertEqual(seed.main(["--output", str(output)]), 1)
                self.assertEqual(seed.main(["--output", str(output), "--force"]), 0)

    def test_listing_cli_exposes_explicit_refresh_mode(self):
        cli = load_script("supplier_capture_cli_test", "supplier_catalog_capture.py")
        args = cli.parse_args(["listing", "--refresh-existing", "--headless", "--no-prompt"])
        self.assertTrue(args.refresh_existing)
        self.assertTrue(args.headless)
        self.assertTrue(args.no_prompt)


if __name__ == "__main__":
    unittest.main()
