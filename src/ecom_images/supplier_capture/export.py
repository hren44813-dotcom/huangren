"""Deduplicated supplier catalog listing exports."""
from __future__ import annotations
import csv
import json
from pathlib import Path
from .listing import DEFAULT_URL, now_iso
from .audit import build_listing_audit
from .batch import read_batch, belongs_to_batch

def save_listing_outputs(output: Path) -> dict:
    """Merge page checkpoints and write deduplicated local JSON and CSV exports."""
    pages_dir = output / "pages"
    items_by_url: dict[str, dict] = {}
    page_files = sorted(pages_dir.glob("page_*.json"))
    batch = read_batch(output)
    source_url = DEFAULT_URL
    valid_page_count = 0
    for path in page_files:
        try:
            with path.open(encoding="utf-8") as stream:
                page_data = json.load(stream)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(page_data, dict) or not belongs_to_batch(page_data, batch):
            continue
        valid_page_count += 1
        source_url = page_data.get("source_url") or source_url
        for item in page_data.get("items", []):
            if isinstance(item, dict) and item.get("product_url"):
                items_by_url[item["product_url"]] = item
    items = sorted(items_by_url.values(), key=lambda row: (row.get("page_number", 0), row.get("title", "")))
    catalog = {
        "schema_version": "1.0",
        **({"capture_batch_id": batch["batch_id"], "batch_started_at": batch["started_at"]} if batch else {}),
        "supplier": "Dongguan Dele Hardware Technology Co., Ltd.",
        "source_url": source_url,
        "updated_at": now_iso(),
        "captured_page_count": valid_page_count,
        "unique_product_count": len(items),
        "items": items,
        "limitations": [
            "Only pages actually saved by the visible browser session are included.",
            "Prices and MOQ are listing observations and can vary by options or time.",
            "Seller title claims are not independently verified technical specifications.",
            "A sales count not displayed on a card is null, not zero.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = [
        "page_number", "title", "model_hints", "price_text", "price_min", "price_max",
        "price_currency", "moq_quantity", "moq_unit", "sales_count_displayed",
        "sales_status", "delivery_text", "product_url", "image_url", "verification_status", "captured_at",
    ]
    with (output / "catalog.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            row = dict(item)
            row["model_hints"] = "; ".join(row.get("model_hints", []))
            writer.writerow(row)
    audit = build_listing_audit(output)
    return {
        "captured_page_count": valid_page_count,
        "unique_product_count": len(items),
        "audit_status": audit["status"],
        "missing_page_count": len(audit["missing_page_numbers"]),
        "capture_batch_id": batch["batch_id"] if batch else None,
        "stale_page_count": audit["stale_page_count"],
    }
