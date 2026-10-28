"""Capture-batch identity and conservative checkpoint reuse, without SQLite migrations."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_NAME = "listing_batch.json"
_ID = re.compile(r"[0-9a-f]{32}")


def read_batch(output: Path) -> dict | None:
    """Fail closed on a malformed manifest; never fall back to historical pages."""
    manifest = output / MANIFEST_NAME
    if not manifest.exists():
        return None
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("采集批次清单不是安全的普通文件")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("采集批次清单损坏") from exc
    if (not isinstance(data, dict) or not isinstance(data.get("batch_id"), str)
            or not _ID.fullmatch(data["batch_id"])
            or not isinstance(data.get("started_at"), str) or not data["started_at"]):
        raise ValueError("采集批次清单缺少有效批次 ID 或开始时间")
    return data


def start_batch(output: Path) -> dict:
    """Start a fresh observation, preserving old files but excluding them from reports."""
    output.mkdir(parents=True, exist_ok=True)
    batch = {
        "batch_id": uuid.uuid4().hex,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "refresh",
    }
    target = output / MANIFEST_NAME
    temporary = output / (MANIFEST_NAME + ".tmp")
    temporary.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return batch


def belongs_to_batch(record: dict, batch: dict | None) -> bool:
    """Unmarked checkpoints remain compatible only when no active batch exists."""
    return batch is None or record.get("capture_batch_id") == batch["batch_id"]


def reusable_page(record: dict, page_number: int, batch: dict | None) -> bool:
    if not isinstance(record, dict) or not belongs_to_batch(record, batch):
        return False
    if record.get("page_number") != page_number:
        return False
    items = record.get("items")
    if not isinstance(items, list) or not items:
        return False
    pagination = re.search(r"\b(\d+)\s*/\s*(\d+)\b", str(record.get("pagination_text") or ""))
    return bool(pagination and int(pagination.group(1)) == page_number
                and int(pagination.group(2)) >= page_number
                and all(isinstance(item, dict) and item.get("product_url") for item in items))


def reusable_detail(record: dict, *, item_id: str, listing_url: str,
                    text: str, batch: dict | None) -> bool:
    if not isinstance(record, dict) or not belongs_to_batch(record, batch):
        return False
    if str(record.get("item_id") or "") != item_id or not text.strip():
        return False
    detail = record.get("detail_page")
    if not isinstance(detail, dict) or detail.get("body_text_file", f"{item_id}.txt") != f"{item_id}.txt":
        return False
    from ..supplier_capture_validation import validate_alibaba_url
    from .listing import normalize_url
    try:
        if normalize_url(validate_alibaba_url(str(record.get("listing_url") or ""), require_product=True)) != normalize_url(listing_url):
            return False
        final_url = record.get("detail_url")
        if final_url is not None:
            validate_alibaba_url(str(final_url), require_product=True)
        return True
    except ValueError:
        return False
