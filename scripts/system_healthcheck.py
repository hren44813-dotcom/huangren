"""Offline, non-destructive health check for the image, V13 and supplier subsystems."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecom_images.catalog_v12 import initialize_catalog  # noqa: E402
from ecom_images.database_v9 import integrity_report, open_database  # noqa: E402
from ecom_images.knowledge_ingest_v13 import initialize_ingestion  # noqa: E402
from ecom_images.knowledge_schema_v13 import initialize_knowledge  # noqa: E402
from ecom_images.supplier_catalog_db import (  # noqa: E402
    DEFAULT_SNAPSHOT, audit_supplier_db, sync_supplier_catalog,
)
from ecom_images.supplier_capture_validation import inspect_supplier_capture  # noqa: E402


def _db_checks(path: Path) -> dict[str, Any]:
    """Read schema versions and SQLite integrity without modifying any production DB."""
    with sqlite3.connect(path) as conn:
        integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
        fks = conn.execute("PRAGMA foreign_key_check").fetchall()
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {
            "jobs", "catalog_products", "catalog_skus", "knowledge_sources",
            "knowledge_document_segments", "knowledge_ingest_runs",
        }
        return {
            "ok": integrity == ["ok"] and not fks and required.issubset(tables),
            "integrity": integrity,
            "foreign_key_errors": len(fks),
            "missing_tables": sorted(required - tables),
            "table_count": len(tables),
        }


def run_healthcheck(*, capture_dir: str | Path | None = None,
                    require_full_collection: bool = False) -> dict[str, Any]:
    """Smoke-test temporary V13 and supplier databases; report live capture separately."""
    capture = Path(capture_dir) if capture_dir else ROOT / "data" / "supplier_captures" / "dgdeler"
    results: dict[str, Any] = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "temporary_databases_only": True,
        "requires_external_network": False,
        "checks": {},
    }
    with tempfile.TemporaryDirectory(prefix="huangren-health-") as directory:
        root = Path(directory)
        core_db = root / "knowledge.sqlite3"
        try:
            with open_database(core_db) as conn:
                conn.execute("SELECT 1")
            initialize_catalog(core_db)
            initialize_knowledge(core_db)
            initialize_ingestion(core_db)
            db_result = _db_checks(core_db)
            db_result["v9_integrity_ok"] = integrity_report(core_db)["ok"]
            db_result["ok"] = db_result["ok"] and db_result["v9_integrity_ok"]
            results["checks"]["knowledge_v13"] = db_result
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
            results["checks"]["knowledge_v13"] = {
                "ok": False, "error_type": type(exc).__name__, "error": str(exc),
            }

        supplier_db = root / "supplier.sqlite3"
        try:
            sync = sync_supplier_catalog(
                supplier_db, capture_dir=capture,
                snapshot_json=DEFAULT_SNAPSHOT, require_details=require_full_collection,
            )
            audit = audit_supplier_db(supplier_db)
            observed = sync["independent_capture_validation"]
            results["checks"]["supplier_database"] = {
                "ok": bool(audit["ok"]),
                "products_imported": sync["products_seen"],
                "observations_inserted": sync["observations_inserted"],
                "foreign_key_errors": len(audit["foreign_key_errors"]),
                "sqlite_integrity": audit["integrity_check"],
                "creates_verified_claims": sync["creates_verified_claims"],
            }
            results["checks"]["capture_coverage"] = {
                "ok": observed["status"] == "complete",
                "status": observed["status"],
                "expected_listing_pages": observed["expected_listing_pages"],
                "captured_listing_pages": observed["captured_listing_pages"],
                "catalog_products": observed["catalog_products"],
                "valid_detail_products": observed["valid_detail_products"],
                "failures": observed["failures"],
                "require_details": require_full_collection,
            }
        except (ValueError, RuntimeError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
            results["checks"]["supplier_database"] = {
                "ok": False, "error_type": type(exc).__name__, "error": str(exc),
            }
            results["checks"]["capture_coverage"] = {
                "ok": False, "status": "unknown", "failures": ["supplier_check_failed"],
            }

    results["system_ok"] = all(
        results["checks"].get(key, {}).get("ok", False)
        for key in ("knowledge_v13", "supplier_database")
    )
    results["full_collection_ok"] = results["checks"]["capture_coverage"]["ok"]
    results["accepted"] = results["system_ok"] and (
        not require_full_collection or results["full_collection_ok"]
    )
    results["note"] = (
        "Database integrity and automation readiness are distinct from full marketplace coverage."
    )
    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Accept optional capture directory, report path and full-collection gate."""
    parser = argparse.ArgumentParser(description="离线健康检查：V13、供应商 SQLite、采集覆盖率。")
    parser.add_argument("--capture-dir", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--require-full-collection", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Emit machine-readable report and return a failed status on broken core checks."""
    args = parse_args(argv)
    result = run_healthcheck(
        capture_dir=args.capture_dir,
        require_full_collection=args.require_full_collection,
    )
    if args.report:
        destination = args.report.expanduser().absolute()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
