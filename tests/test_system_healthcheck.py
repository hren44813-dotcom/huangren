"""Offline health check contract tests for the full huangren data system."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import system_healthcheck  # noqa: E402


class AutomationSystemHealthTests(unittest.TestCase):
    """Check schema creation and source coverage without touching real database files."""

    def test_system_bootstraps_temporary_v13_and_supplier_db(self):
        """V9/V12/V13 and supplier database integrity pass in isolated scratch space."""
        with tempfile.TemporaryDirectory() as directory:
            result = system_healthcheck.run_healthcheck(capture_dir=Path(directory) / "empty")
        self.assertTrue(result["temporary_databases_only"])
        self.assertTrue(result["system_ok"], result["checks"])
        self.assertFalse(result["full_collection_ok"])
        self.assertEqual(result["checks"]["supplier_database"]["products_imported"], 16)
        self.assertFalse(result["checks"]["supplier_database"]["creates_verified_claims"])
        self.assertTrue(result["accepted"])

    def test_full_collection_gate_cannot_pass_on_empty_capture(self):
        """A healthy empty dev DB cannot be confused with full marketplace coverage."""
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "empty"
            result = system_healthcheck.run_healthcheck(
                capture_dir=capture, require_full_collection=True,
            )
            self.assertTrue(result["system_ok"])
            self.assertFalse(result["full_collection_ok"])
            self.assertFalse(result["accepted"])
            self.assertIn("no_page_checkpoints", result["checks"]["capture_coverage"]["failures"])
            self.assertFalse((Path(directory) / "knowledge.sqlite3").exists())
            self.assertFalse((Path(directory) / "supplier.sqlite3").exists())
