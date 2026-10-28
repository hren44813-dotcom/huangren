"""Independent, fail-closed verification of supplier capture checkpoints.

Does not trust generated audit JSON files. The listing files, catalog and detail
files themselves are re-opened before a run may be marked complete.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .supplier_catalog_capture import normalize_url
from .supplier_capture.batch import read_batch, belongs_to_batch

_PAGE_RE = re.compile(r"^page_(\d+)\.json$")
_PAGINATION_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")
MAX_JSON_BYTES = 30 * 1024 * 1024


def _read_json(path: Path) -> dict[str, Any]:
    """Read a bounded JSON object without trusting an earlier audit export."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("文件不存在或为不允许的符号链接")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("JSON 文件超过 30 MiB 上限")
    with path.open(encoding="utf-8") as stream:
        obj = json.load(stream)
    if not isinstance(obj, dict):
        raise ValueError("JSON 顶层必须是对象")
    return obj



def validate_alibaba_url(value: str, *, require_product: bool = False) -> str:
    """Reject local, non-HTTPS and non-Alibaba destinations before browser navigation."""
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("页面链接格式无效")
    parts = urlsplit(value.strip())
    host = (parts.hostname or "").lower()
    if (parts.scheme != "https" or not host
            or not (host == "alibaba.com" or host.endswith(".alibaba.com"))
            or parts.username is not None or parts.password is not None
            or parts.port not in (None, 443)):
        raise ValueError("仅允许 HTTPS 阿里巴巴页面")
    if require_product and not parts.path.startswith("/product-detail/"):
        raise ValueError("商品详情链接必须是阿里巴巴 product-detail 页面")
    return value.strip()

def _canonical_item(item: Any) -> str:
    """Canonicalize a captured product URL, returning empty for invalid rows."""
    if not isinstance(item, dict):
        return ""
    value = item.get("product_url") or item.get("url") or item.get("listing_url")
    if not isinstance(value, str):
        return ""
    try:
        return normalize_url(validate_alibaba_url(value, require_product=True))
    except ValueError:
        return ""


def _item_id(item: dict) -> str:
    """Read the extractor's stable ID or derive it from its canonical URL."""
    return str(item.get("item_id") or hashlib.sha256(_canonical_item(item).encode()).hexdigest()[:16])


def inspect_supplier_capture(capture_dir: str | Path, *, require_details: bool = False) -> dict[str, Any]:
    """Independently check actual pages, product coverage, details and optional full-detail gate."""
    root = Path(capture_dir).expanduser().absolute()
    failures: list[str] = []
    try:
        batch = read_batch(root)
    except ValueError:
        failures.append("invalid_capture_batch_manifest")
        batch = {"batch_id": "__invalid__"}
    stale_page_count = 0
    invalid_pages: list[dict] = []
    page_numbers: set[int] = set()
    page_urls: set[str] = set()
    expected_totals: set[int] = set()
    expected_pages: int | None = None
    catalog_items: list[dict] = []
    catalog_path = root / "catalog.json"
    try:
        catalog = _read_json(catalog_path)
        if batch is not None and catalog.get("capture_batch_id") != batch["batch_id"]:
            failures.append("catalog_capture_batch_mismatch")
        items = catalog.get("items")
        if not isinstance(items, list):
            raise ValueError("catalog.items 不是数组")
        catalog_items = [item for item in items if isinstance(item, dict)]
        if len(catalog_items) != len(items):
            failures.append("catalog_has_invalid_items")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        failures.append("missing_or_invalid_catalog")
        invalid_pages.append({"file": catalog_path.name, "error": str(exc)})

    catalog_urls: set[str] = set()
    catalog_ids: dict[str, str] = {}
    for item in catalog_items:
        url = _canonical_item(item)
        if not url:
            failures.append("catalog_has_invalid_product_url")
            continue
        if url in catalog_urls:
            failures.append("duplicate_catalog_product_url")
        catalog_urls.add(url)
        catalog_ids[_item_id(item)] = url

    page_files = sorted((root / "pages").glob("page_*.json"))
    if not page_files:
        failures.append("no_page_checkpoints")
    for path in page_files:
        match = _PAGE_RE.fullmatch(path.name)
        if not match:
            invalid_pages.append({"file": path.name, "error": "无效分页文件名"})
            continue
        filename_number = int(match.group(1))
        try:
            data = _read_json(path)
            if not belongs_to_batch(data, batch):
                stale_page_count += 1
                continue
            if data.get("page_number") != filename_number:
                raise ValueError("文件名和 page_number 不一致")
            items = data.get("items")
            if not isinstance(items, list) or not items:
                raise ValueError("页面商品列表缺失或为空")
            urls = [_canonical_item(item) for item in items]
            if not all(urls):
                raise ValueError("页面包含无效商品 URL")
            pagination = _PAGINATION_RE.search(str(data.get("pagination_text") or ""))
            if not pagination:
                raise ValueError("缺少明确的当前页/总页数标识")
            actual_page, total_pages = map(int, pagination.groups())
            if actual_page != filename_number or total_pages < actual_page:
                raise ValueError("分页标识与记录页码不一致")
            if filename_number in page_numbers:
                raise ValueError("重复页码")
            page_numbers.add(filename_number)
            page_urls.update(urls)
            expected_totals.add(total_pages)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            invalid_pages.append({"file": path.name, "error": str(exc)})
    if invalid_pages:
        failures.append("invalid_page_checkpoint")
    if len(expected_totals) == 1:
        expected_pages = next(iter(expected_totals))
    elif len(expected_totals) > 1:
        failures.append("conflicting_pagination_totals")
    else:
        failures.append("unknown_pagination_total")

    missing_pages = (
        [n for n in range(1, expected_pages + 1) if n not in page_numbers]
        if expected_pages is not None else []
    )
    if missing_pages:
        failures.append("missing_listing_pages")
    not_in_pages = sorted(catalog_urls - page_urls)
    not_in_catalog = sorted(page_urls - catalog_urls)
    if not_in_pages or not_in_catalog:
        failures.append("catalog_page_product_mismatch")
    if not catalog_urls:
        failures.append("no_valid_catalog_products")

    details_dir = root / "details"
    detail_files = sorted(path for path in details_dir.glob("*.json")
                          if path.name != "capture_errors.json")
    valid_detail_ids: set[str] = set()
    invalid_details: list[dict] = []
    unmatched_detail_ids: list[str] = []
    for path in detail_files:
        try:
            record = _read_json(path)
            if not belongs_to_batch(record, batch):
                continue
            item_id = str(record.get("item_id") or "")
            if not item_id or item_id not in catalog_ids:
                unmatched_detail_ids.append(item_id or path.name)
                continue
            if path.stem != item_id:
                raise ValueError("详情文件名与 item_id 不匹配")
            detail = record.get("detail_page")
            if not isinstance(detail, dict):
                raise ValueError("详情缺少 detail_page 对象")
            body_file = str(detail.get("body_text_file") or f"{item_id}.txt")
            if Path(body_file).name != body_file:
                raise ValueError("详情正文文件名包含非法路径")
            text_path = details_dir / body_file
            if text_path.is_symlink() or not text_path.is_file() or text_path.stat().st_size == 0:
                raise ValueError("详情正文文件缺失、为空或为符号链接")
            listing_url = normalize_url(str(record.get("listing_url") or ""))
            if listing_url != catalog_ids[item_id]:
                raise ValueError("详情来源 URL 与目录商品不匹配")
            # The requested listing URL is not proof of the actual loaded page:
            # a redirect to an Alibaba login wall can contain nonempty body text.
            actual_url = record.get("detail_url")
            if actual_url is not None:
                if not isinstance(actual_url, str):
                    raise ValueError("详情最终 URL 不是文本")
                validate_alibaba_url(actual_url, require_product=True)
            valid_detail_ids.add(item_id)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            invalid_details.append({"file": path.name, "error": str(exc)})
    if invalid_details or unmatched_detail_ids:
        failures.append("invalid_or_orphan_detail")
    missing_detail_ids = sorted(set(catalog_ids) - valid_detail_ids)
    if missing_detail_ids:
        failures.append("missing_product_details")

    capture_error_path = details_dir / "capture_errors.json"
    unresolved_errors = 0
    if capture_error_path.exists():
        try:
            if capture_error_path.is_symlink() or capture_error_path.stat().st_size > MAX_JSON_BYTES:
                raise ValueError("错误记录文件不安全")
            error_rows = json.loads(capture_error_path.read_text(encoding="utf-8"))
            if not isinstance(error_rows, list):
                raise ValueError("错误记录必须是数组")
            unresolved_errors = len([row for row in error_rows
                                     if batch is None or (isinstance(row, dict)
                                     and row.get("capture_batch_id") == batch["batch_id"])])
        except (ValueError, OSError, json.JSONDecodeError):
            unresolved_errors = 1
        if unresolved_errors:
            failures.append("unresolved_detail_capture_errors")
    listing_blockers = {
        "missing_or_invalid_catalog", "catalog_has_invalid_items",
        "catalog_has_invalid_product_url", "duplicate_catalog_product_url",
        "no_page_checkpoints", "invalid_page_checkpoint", "conflicting_pagination_totals",
        "unknown_pagination_total", "missing_listing_pages",
        "catalog_page_product_mismatch", "no_valid_catalog_products",
        "invalid_capture_batch_manifest", "catalog_capture_batch_mismatch",
    }
    detail_blockers = {
        "invalid_or_orphan_detail", "missing_product_details",
        "unresolved_detail_capture_errors",
    }
    listing_complete = not any(x in listing_blockers for x in failures)
    marker = root / "details_collection_requested.json"
    marker_requested = False
    if marker.is_file():
        try:
            marker_data = _read_json(marker)
            marker_requested = batch is None or marker_data.get("capture_batch_id") == batch["batch_id"]
        except (ValueError, OSError, json.JSONDecodeError):
            marker_requested = True
    detail_requested = require_details or marker_requested or (
        bool(detail_files) and batch is None) or bool(valid_detail_ids)
    # No product inventory means detail coverage is unknown, not "complete".
    detail_complete = bool(catalog_ids) and not any(x in detail_blockers for x in failures)
    status = "complete" if listing_complete and (not detail_requested or detail_complete) else "partial"
    return {
        "status": status,
        "listing_status": "complete" if listing_complete else "partial",
        "detail_status": ("complete" if detail_complete else "partial") if detail_requested else "not_requested",
        "detail_requested": detail_requested,
        "require_details": require_details,
        "capture_batch_id": batch["batch_id"] if batch else None,
        "stale_page_checkpoints": stale_page_count,
        "expected_listing_pages": expected_pages,
        "captured_listing_pages": len(page_numbers),
        "missing_listing_pages": missing_pages,
        "catalog_products": len(catalog_urls),
        "page_product_urls": len(page_urls),
        "missing_from_pages": not_in_pages,
        "missing_from_catalog": not_in_catalog,
        "valid_detail_products": len(valid_detail_ids),
        "missing_detail_ids": missing_detail_ids,
        "unmatched_detail_ids": unmatched_detail_ids,
        "invalid_pages": invalid_pages,
        "invalid_details": invalid_details,
        "unresolved_detail_capture_errors": unresolved_errors,
        "failures": sorted(set(failures)),
    }
