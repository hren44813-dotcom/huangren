"""Audits, exports and read-only supplier search."""
from __future__ import annotations
import csv
import json
from pathlib import Path
from .schema import DEFAULT_DB, DEFAULT_CAPTURE_DIR, SCHEMA_VERSION, initialize_supplier_db, supplier_connection

def audit_supplier_db(path: str | Path = DEFAULT_DB) -> dict:
    """Report SQLite integrity, foreign keys, observation coverage and current run status."""
    initialize_supplier_db(path)
    with supplier_connection(path) as conn:
        integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
        fk_errors = [dict(row) for row in conn.execute("PRAGMA foreign_key_check")]
        counts = {}
        for table in (
            "supplier_catalog_suppliers", "supplier_catalog_products", "supplier_catalog_runs",
            "supplier_catalog_run_events", "supplier_catalog_pages", "supplier_catalog_observations",
            "supplier_catalog_model_mentions", "supplier_catalog_detail_observations",
            "supplier_catalog_attributes", "supplier_catalog_options", "supplier_catalog_errors",
        ):
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        latest = conn.execute(
            """SELECT e.run_id,e.status,e.created_utc,e.summary_json FROM supplier_catalog_run_events e
               JOIN (SELECT run_id,MAX(event_id) event_id FROM supplier_catalog_run_events GROUP BY run_id) last
               ON e.event_id=last.event_id ORDER BY e.event_id DESC LIMIT 1"""
        ).fetchone()
        missing = conn.execute(
            """SELECT COUNT(*) FROM supplier_catalog_products p
               WHERE NOT EXISTS(SELECT 1 FROM supplier_catalog_observations o WHERE o.product_id=p.id)"""
        ).fetchone()[0]
        price_missing = conn.execute(
            """SELECT COUNT(*) FROM supplier_catalog_observations
               WHERE price_min IS NULL OR price_currency=''"""
        ).fetchone()[0]
        sales_not_displayed = conn.execute(
            """SELECT COUNT(*) FROM supplier_catalog_observations
               WHERE sales_count_displayed IS NULL AND sales_status NOT IN ('not_displayed_not_zero','not_displayed_on_captured_listing','not_displayed')"""
        ).fetchone()[0]
        status = latest["status"] if latest else "not_started"
        return {
            "schema_version": SCHEMA_VERSION, "integrity_check": integrity,
            "foreign_key_errors": fk_errors, "counts": counts,
            "products_without_observations": missing, "observations_missing_price_or_currency": price_missing,
            "sales_status_inconsistent": sales_not_displayed,
            "latest_run": ({
                "run_id": latest["run_id"], "status": status, "created_utc": latest["created_utc"],
                "summary": json.loads(latest["summary_json"]),
            } if latest else None),
            "ok": integrity == ["ok"] and not fk_errors and missing == 0 and sales_not_displayed == 0,
        }


def export_supplier_db(path: str | Path = DEFAULT_DB, output_dir: str | Path = DEFAULT_CAPTURE_DIR / "exports") -> dict:
    """Write spreadsheet-friendly latest-product, price-history, attribute and audit exports."""
    initialize_supplier_db(path)
    out = Path(output_dir).expanduser().absolute()
    out.mkdir(parents=True, exist_ok=True)
    with supplier_connection(path) as conn:
        queries = {
            "supplier_products.csv": """SELECT p.id AS product_id,s.name AS supplier,p.title,p.product_url,
                p.model_hints_json,p.category_guess,p.image_url,p.first_seen_utc,p.last_seen_utc,
                (SELECT o.price_text FROM supplier_catalog_observations o WHERE o.product_id=p.id
                 ORDER BY o.observed_at DESC, o.rowid DESC LIMIT 1) AS latest_price_text,
                (SELECT o.price_min FROM supplier_catalog_observations o WHERE o.product_id=p.id
                 ORDER BY o.observed_at DESC, o.rowid DESC LIMIT 1) AS latest_price_min,
                (SELECT o.price_max FROM supplier_catalog_observations o WHERE o.product_id=p.id
                 ORDER BY o.observed_at DESC, o.rowid DESC LIMIT 1) AS latest_price_max,
                (SELECT o.price_currency FROM supplier_catalog_observations o WHERE o.product_id=p.id
                 ORDER BY o.observed_at DESC, o.rowid DESC LIMIT 1) AS latest_currency,
                (SELECT o.moq_quantity FROM supplier_catalog_observations o WHERE o.product_id=p.id
                 ORDER BY o.observed_at DESC, o.rowid DESC LIMIT 1) AS latest_moq,
                (SELECT o.sales_count_displayed FROM supplier_catalog_observations o WHERE o.product_id=p.id
                 ORDER BY o.observed_at DESC, o.rowid DESC LIMIT 1) AS latest_sales_displayed,
                (SELECT o.sales_status FROM supplier_catalog_observations o WHERE o.product_id=p.id
                 ORDER BY o.observed_at DESC, o.rowid DESC LIMIT 1) AS latest_sales_status
                FROM supplier_catalog_products p JOIN supplier_catalog_suppliers s ON s.id=p.supplier_id
                ORDER BY p.title""",
            "supplier_price_history.csv": """SELECT p.title,p.product_url,o.observed_at,o.page_number,o.price_text,
                o.price_min,o.price_max,o.price_currency,o.moq_quantity,o.moq_unit,o.sales_count_displayed,
                o.sales_status,o.delivery_text,o.source_url,o.verification_status,o.observation_sha256
                FROM supplier_catalog_observations o JOIN supplier_catalog_products p ON p.id=o.product_id
                ORDER BY p.title,o.observed_at,o.rowid""",
            "supplier_attributes.csv": """SELECT p.title,p.product_url,d.observed_at,a.attribute,a.value,a.source_locator,
                a.verification_status FROM supplier_catalog_attributes a
                JOIN supplier_catalog_products p ON p.id=a.product_id
                JOIN supplier_catalog_detail_observations d ON d.id=a.detail_observation_id
                ORDER BY p.title,a.attribute""",
            "supplier_model_mentions.csv": """SELECT p.title,p.product_url,m.model_code,m.evidence_text,m.extraction_method,
                m.verification_status FROM supplier_catalog_model_mentions m
                JOIN supplier_catalog_products p ON p.id=m.product_id ORDER BY m.model_code,p.title""",
        }
        for filename, query in queries.items():
            rows = conn.execute(query).fetchall()
            with (out / filename).open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                if rows:
                    writer.writerow(rows[0].keys())
                    writer.writerows([tuple(row) for row in rows])
                else:
                    writer.writerow(["no_records"])
        audit = audit_supplier_db(path)
        (out / "supplier_catalog_database_audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return {"output_dir": str(out), "files": list(queries) + ["supplier_catalog_database_audit.json"], "audit": audit}


def list_supplier_products(path: str | Path = DEFAULT_DB, *, query: str = "", limit: int = 100) -> list[dict]:
    """Search products by title, URL or observed model code."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit 必须在 1 到 1000 之间")
    initialize_supplier_db(path)
    needle = query.strip()
    with supplier_connection(path) as conn:
        if needle:
            rows = conn.execute(
                """SELECT DISTINCT p.id,p.title,p.product_url,p.model_hints_json,p.category_guess
                   FROM supplier_catalog_products p
                   LEFT JOIN supplier_catalog_model_mentions m ON m.product_id=p.id
                   WHERE p.title LIKE ? OR p.product_url LIKE ? OR m.model_code LIKE ?
                   ORDER BY p.title LIMIT ?""",
                (f"%{needle}%", f"%{needle}%", f"%{needle}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id,title,product_url,model_hints_json,category_guess FROM supplier_catalog_products ORDER BY title LIMIT ?",
                (limit,),
            ).fetchall()
    return [{
        "product_id": row["id"], "title": row["title"], "product_url": row["product_url"],
        "model_hints": json.loads(row["model_hints_json"]), "category_guess": row["category_guess"],
    } for row in rows]
