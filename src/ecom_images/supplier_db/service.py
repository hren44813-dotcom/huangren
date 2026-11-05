"""Supplier capture synchronizer and run audit events."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from ..supplier_capture_validation import inspect_supplier_capture
from ..supplier_catalog_capture import normalize_url
from .schema import DEFAULT_DB, DEFAULT_CAPTURE_DIR, DEFAULT_SNAPSHOT, SUPPLIER_URL, initialize_supplier_db, supplier_connection, _now, _id, _json
from .helpers import _load_inputs, _item_url, _first, _as_int, _manifest
from .writes import _upsert_supplier, _record_error, _insert_page, _upsert_product, _insert_observation, _insert_detail
from .reports import audit_supplier_db

def sync_supplier_catalog(path: str | Path = DEFAULT_DB, *,
                          capture_dir: str | Path = DEFAULT_CAPTURE_DIR,
                          snapshot_json: str | Path | None = DEFAULT_SNAPSHOT,
                          dry_run: bool = False, require_details: bool = False) -> dict:
    """Load capture checkpoints, listing observations and detail evidence into normalized SQLite."""
    capture = Path(capture_dir).expanduser().absolute()
    snapshot = Path(snapshot_json).expanduser().absolute() if snapshot_json else None
    catalog, pages, details, errors = _load_inputs(capture, snapshot)
    items = [item for item in catalog.get("items", []) if isinstance(item, dict) and _item_url(item)]
    unique_items = {_item_url(item): item for item in items}
    items = list(unique_items.values())
    source_url = str(_first(catalog, "source_url", default=(catalog.get("source") or {}).get("url", SUPPLIER_URL)))
    manifest_sha = _manifest(catalog, pages, details, errors)
    verified_capture = inspect_supplier_capture(capture, require_details=require_details)
    summary = {
        "dry_run": dry_run, "database": str(Path(path).expanduser().absolute()),
        "capture_dir": str(capture), "snapshot_json": str(snapshot) if snapshot else None,
        "valid_page_checkpoints": len(pages), "unique_listing_products": len(items),
        "detail_records": len(details), "input_errors": len(errors), "manifest_sha256": manifest_sha,
        "creates_verified_claims": False,
        "independent_capture_validation": verified_capture,
    }
    if dry_run:
        summary["status"] = "preview"
        return summary
    initialize_supplier_db(path)
    now = _now()
    with supplier_connection(path) as conn:
        run_id = _id()
        conn.execute("BEGIN IMMEDIATE")
        try:
            supplier_id = _upsert_supplier(conn, catalog, source_url)
            conn.execute(
                """INSERT INTO supplier_catalog_runs(id,supplier_id,started_utc,source_url,mode,input_manifest_sha256,args_json)
                   VALUES(?,?,?,?,?,?,?)""",
                (run_id, supplier_id, now, source_url, "capture_sync", manifest_sha, _json({
                    "capture_dir": str(capture), "snapshot_json": str(snapshot) if snapshot else None,
                })),
            )
            conn.execute(
                """INSERT INTO supplier_catalog_run_events(run_id,created_utc,status,summary_json,note)
                   VALUES(?,?,?,?,?)""",
                (run_id, now, "started", _json(summary), "Importing timestamped supplier-page observations."),
            )
            for error in errors:
                _record_error(conn, run_id, error)
            for page_path, page_record in pages:
                try:
                    _insert_page(conn, run_id, source_url, page_path, page_record)
                except (ValueError, sqlite3.Error) as exc:
                    _record_error(conn, run_id, {
                        "stage": "listing_page", "item_ref": str(page_path),
                        "error_type": type(exc).__name__, "message": str(exc),
                    })
            inserted_observations = 0
            unchanged_observations = 0
            product_ids_by_url = {}
            for item in items:
                observed_at = str(_first(item, "captured_at", "observed_at", default=_first(catalog, "updated_at", default=now)))
                product_id = _upsert_product(conn, supplier_id, item, observed_at)
                product_ids_by_url[_item_url(item)] = product_id
                page_number = _as_int(_first(item, "page_number", "position", default=None))
                obs_id, inserted = _insert_observation(conn, product_id, run_id, item, source_url, page_number)
                inserted_observations += int(inserted)
                unchanged_observations += int(not inserted)
            detail_inserted = 0
            detail_missing_body = []
            for record in details:
                item_url = normalize_url(str(record.get("listing_url") or record.get("detail_url") or ""))
                product_id = product_ids_by_url.get(item_url)
                if not product_id:
                    item = next((x for x in items if _item_url(x) == item_url), None)
                    if not item:
                        errors.append({"stage": "detail_orphan", "item_ref": str(record.get("item_id", "")),
                                       "error_type": "OrphanDetail", "message": "详情记录对应的商品不在本次目录输入中"})
                        _record_error(conn, run_id, errors[-1])
                        continue
                    product_id = _upsert_product(conn, supplier_id, item, str(record.get("captured_at") or now))
                detail_dir = capture / "details"
                text_name = Path(str((record.get("detail_page") or {}).get("body_text_file") or f"{record.get('item_id')}.txt")).name
                if not (detail_dir / text_name).is_file():
                    detail_missing_body.append(str(record.get("item_id", "")))
                detail_inserted += int(_insert_detail(conn, run_id, product_id, next((x for x in items if _item_url(x) == item_url), {}),
                                                      record, detail_dir))
            detail_requested = verified_capture["detail_requested"]
            detail_audit_status = verified_capture["detail_status"]
            status = "complete" if (
                verified_capture["status"] == "complete"
                and not errors and not detail_missing_body
            ) else "partial"
            summary.update({
                "run_id": run_id, "supplier_id": supplier_id, "status": status,
                "products_seen": len(items), "observations_inserted": inserted_observations,
                "observations_unchanged": unchanged_observations, "details_inserted": detail_inserted,
                "listing_audit_status": verified_capture["listing_status"],
                "independent_validation_failures": verified_capture["failures"],
                "detail_audit_status": detail_audit_status,
                "detail_collection_requested": detail_requested,
                "detail_missing_body_count": len(detail_missing_body),
                "errors": len(errors), "created_utc": now,
            })
            conn.execute(
                """INSERT INTO supplier_catalog_run_events(run_id,created_utc,status,summary_json,note)
                   VALUES(?,?,?,?,?)""",
                (run_id, _now(), status, _json(summary),
                 "Complete means the captured source audits were complete; seller claims remain unverified."),
            )
            conn.commit()
        except BaseException as exc:
            if conn.in_transaction:
                conn.rollback()
            supplier_id = _upsert_supplier(conn, catalog, source_url)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO supplier_catalog_runs(id,supplier_id,started_utc,source_url,mode,input_manifest_sha256,args_json)
                   VALUES(?,?,?,?,?,?,?)""",
                (run_id, supplier_id, now, source_url, "capture_sync", manifest_sha, _json({"failed": True})),
            )
            conn.execute(
                """INSERT INTO supplier_catalog_run_events(run_id,created_utc,status,summary_json,note)
                   VALUES(?,?,?,?,?)""",
                (run_id, _now(), "failed", _json({"error_type": type(exc).__name__}), str(exc)[:2000]),
            )
            conn.commit()
            raise
    summary["database_audit"] = audit_supplier_db(path)
    return summary
