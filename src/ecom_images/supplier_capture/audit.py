"""Source checkpoint, listing and product detail audits."""
from __future__ import annotations
import csv
import hashlib
import json
import re
from pathlib import Path
from .listing import now_iso
from .detail import enrich_detail_payload, render_detail_markdown
from .batch import read_batch, belongs_to_batch

def build_listing_audit(output: Path) -> dict:
    """Check captured page coverage, pagination consistency, duplicate URLs and invalid checkpoints."""
    pages_dir = output / "pages"
    page_paths = sorted(pages_dir.glob("page_*.json")) if pages_dir.exists() else []
    page_records = []
    invalid_files = []
    batch = read_batch(output)
    stale_page_count = 0
    for path in page_paths:
        match = re.fullmatch(r"page_(\d+)\.json", path.name)
        file_number = int(match.group(1)) if match else None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("page record must be an object")
            if not belongs_to_batch(data, batch):
                stale_page_count += 1
                continue
            data["_file_page_number"] = file_number
            page_records.append(data)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            invalid_files.append({"file": path.name, "error": str(exc)})
    captured_numbers = sorted({
        int(record.get("_file_page_number"))
        for record in page_records if isinstance(record.get("_file_page_number"), int)
    })
    totals = []
    page_mismatches = []
    empty_pages = []
    all_urls = []
    for record in page_records:
        file_number = record.get("_file_page_number")
        page_number = record.get("page_number")
        if not isinstance(file_number, int) or not isinstance(page_number, int) or file_number != page_number:
            page_mismatches.append({"file_page": file_number, "record_page": page_number})
        pagination = str(record.get("pagination_text") or "")
        match = re.search(r"(\d+)\s*/\s*(\d+)", pagination)
        if match:
            totals.append(int(match.group(2)))
            if isinstance(file_number, int) and int(match.group(1)) != file_number:
                page_mismatches.append({
                    "file_page": file_number, "pagination_page": int(match.group(1)),
                    "pagination_text": pagination,
                })
        items = record.get("items", [])
        if not items:
            empty_pages.append(file_number)
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and item.get("product_url"):
                all_urls.append(item["product_url"])
    # Never infer the catalog's total page count from existing checkpoints.
    # A saved page 1 alone is not evidence that the supplier has only one page.
    pagination_total_known = bool(page_records) and len(totals) == len(page_records) and len(set(totals)) == 1
    expected_pages = totals[0] if pagination_total_known else None
    captured_set = set(captured_numbers)
    missing_pages = (
        [number for number in range(1, expected_pages + 1) if number not in captured_set]
        if expected_pages else []
    )
    duplicate_occurrences = len(all_urls) - len(set(all_urls))
    complete = bool(pagination_total_known and expected_pages and not missing_pages
                    and not invalid_files and not page_mismatches and not empty_pages)
    audit = {
        "checked_at": now_iso(),
        "expected_page_count": expected_pages,
        "capture_batch_id": batch["batch_id"] if batch else None,
        "stale_page_count": stale_page_count,
        "pagination_total_known": pagination_total_known,
        "pagination_total_conflicting": len(set(totals)) > 1,
        "captured_page_count": len(captured_numbers),
        "captured_page_numbers": captured_numbers,
        "missing_page_numbers": missing_pages,
        "invalid_page_files": invalid_files,
        "pagination_mismatches": page_mismatches,
        "pages_with_no_visible_products": empty_pages,
        "listing_item_occurrences": len(all_urls),
        "unique_product_count": len(set(all_urls)),
        "duplicate_product_occurrences": duplicate_occurrences,
        "is_complete": complete,
        "status": "complete" if complete else ("partial" if page_records else "not_started"),
        "limitations": [
            "Completeness is measured against the pagination total visible in captured pages.",
            "A captured page with zero visible product cards requires manual review.",
            "Listing fields remain timestamped seller-page observations, not verified specifications.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "catalog_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit


def write_detail_exports(output: Path) -> dict:
    """Export detail index/attribute CSVs, V13-ready Markdown, and an honest coverage audit."""
    output = output.resolve()
    catalog_path = output / "catalog.json"
    if not catalog_path.exists():
        raise FileNotFoundError(f"未找到商品目录：{catalog_path}；请先运行 listing 子命令。")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    items = catalog.get("items", [])
    batch = read_batch(output)
    details_dir = output / "details"
    markdown_dir = output / "details_markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)
    detail_files = sorted(
        path for path in details_dir.glob("*.json") if path.name != "capture_errors.json"
    ) if details_dir.exists() else []
    records_by_id = {}
    invalid_files = []
    capture_errors = []
    capture_error_path = details_dir / "capture_errors.json"
    if capture_error_path.is_file():
        try:
            value = json.loads(capture_error_path.read_text(encoding="utf-8"))
            if isinstance(value, list):
                capture_errors = [row for row in value if isinstance(row, dict)
                                  and (batch is None or row.get("capture_batch_id") == batch["batch_id"])]
            else:
                invalid_files.append({"file": capture_error_path.name, "error": "capture error log must be a JSON array"})
        except (OSError, json.JSONDecodeError) as exc:
            invalid_files.append({"file": capture_error_path.name, "error": str(exc)})
    for path in detail_files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or not record.get("item_id"):
                raise ValueError("detail record missing item_id")
            if not belongs_to_batch(record, batch):
                continue
            records_by_id[str(record["item_id"])] = (path, record)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            invalid_files.append({"file": path.name, "error": str(exc)})
    index_rows = []
    attribute_rows = []
    catalog_ids = set()
    for item in items:
        item_id = str(item.get("item_id") or hashlib.sha256(str(item.get("product_url", "")).encode()).hexdigest()[:16])
        catalog_ids.add(item_id)
        entry = records_by_id.get(item_id)
        if not entry:
            continue
        detail_path, record = entry
        detail_page = record.get("detail_page") if isinstance(record.get("detail_page"), dict) else {}
        text_name = Path(str(detail_page.get("body_text_file") or f"{item_id}.txt")).name
        text_path = details_dir / text_name
        try:
            body_text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
        except OSError:
            body_text = ""
        enriched = enrich_detail_payload(detail_page, body_text)
        enriched["body_text_file"] = text_name
        record["detail_page"] = enriched
        detail_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path = markdown_dir / f"{item_id}.md"
        md_path.write_text(render_detail_markdown(record, body_text), encoding="utf-8")
        product = enriched.get("structured_product", {})
        prices = enriched.get("visible_price_candidates", [])
        options = enriched.get("option_groups", [])
        index_rows.append({
            "item_id": item_id,
            "listing_title": item.get("title"),
            "product_url": item.get("product_url"),
            "detail_title": enriched.get("title"),
            "canonical_url": enriched.get("canonical_url"),
            "schema_name": product.get("name"),
            "schema_sku": product.get("sku"),
            "schema_mpn": product.get("mpn"),
            "schema_brand": product.get("brand"),
            "schema_category": product.get("category"),
            "schema_price": product.get("price"),
            "schema_price_high": product.get("price_high"),
            "schema_currency": product.get("price_currency"),
            "schema_availability": product.get("availability"),
            "visible_price_candidates": json.dumps(prices, ensure_ascii=False),
            "visible_moq": json.dumps(enriched.get("visible_moq"), ensure_ascii=False),
            "visible_sales_count": enriched.get("visible_sales_count"),
            "image_count": len(enriched.get("image_urls", [])),
            "attribute_count": len(enriched.get("attribute_pairs", [])),
            "option_group_count": len(options),
            "body_text_chars": len(body_text),
            "verification_status": record.get("verification_status", "visible_detail_page_observation_unverified"),
            "captured_at": record.get("captured_at"),
            "detail_file": str(detail_path.relative_to(output)),
            "markdown_file": str(md_path.relative_to(output)),
            "text_file": str(text_path.relative_to(output)) if text_path.exists() else "",
        })
        for pair in enriched.get("attribute_pairs", []):
            attribute_rows.append({
                "item_id": item_id,
                "listing_title": item.get("title"),
                "product_url": item.get("product_url"),
                "attribute": pair.get("key"),
                "value": pair.get("value"),
                "source_locator": pair.get("source_locator"),
                "verification_status": "seller_page_observation_unverified",
            })
    index_columns = [
        "item_id", "listing_title", "product_url", "detail_title", "canonical_url",
        "schema_name", "schema_sku", "schema_mpn", "schema_brand", "schema_category",
        "schema_price", "schema_price_high", "schema_currency", "schema_availability",
        "visible_price_candidates", "visible_moq", "visible_sales_count", "image_count",
        "attribute_count", "option_group_count", "body_text_chars", "verification_status",
        "captured_at", "detail_file", "markdown_file", "text_file",
    ]
    with (output / "details_index.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=index_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(index_rows)
    attribute_columns = [
        "item_id", "listing_title", "product_url", "attribute", "value",
        "source_locator", "verification_status",
    ]
    with (output / "detail_attributes.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=attribute_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(attribute_rows)
    missing_ids = sorted(catalog_ids - set(records_by_id))
    orphan_ids = sorted(set(records_by_id) - catalog_ids)
    text_missing = [
        row["item_id"] for row in index_rows
        if not row["text_file"] or not row["body_text_chars"]
    ]
    audit = {
        "checked_at": now_iso(),
        "expected_product_count": len(items),
        "valid_detail_count": len(index_rows),
        "missing_detail_count": len(missing_ids),
        "missing_item_ids": missing_ids,
        "orphan_detail_item_ids": orphan_ids,
        "invalid_detail_files": invalid_files,
        "capture_error_count": len(capture_errors),
        "capture_errors": capture_errors,
        "missing_body_text_item_ids": text_missing,
        "markdown_documents_written": len(index_rows),
        "attribute_rows_written": len(attribute_rows),
        "is_complete": bool(items) and not missing_ids and not orphan_ids and not invalid_files and not text_missing and not capture_errors,
        "status": "complete" if items and not missing_ids and not orphan_ids and not invalid_files and not text_missing and not capture_errors else (
            "partial" if index_rows or items else "not_started"
        ),
        "limitations": [
            "Detail extraction records page-visible content and structured metadata only.",
            "Price options, hidden tabs, login-gated data, and dynamic fields may be absent.",
            "All supplier-page technical claims remain unverified until reviewed against authoritative evidence.",
        ],
    }
    (output / "details_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit
