"""Source input normalizers and manifests."""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any
from ..supplier_catalog_capture import normalize_url
from ..supplier_capture.listing import MODEL_RE
from ..supplier_capture.batch import read_batch, belongs_to_batch
from .schema import _json, _sha, SUPPLIER_NAME, SUPPLIER_URL

def _first(item: dict, *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return default


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(str(value).replace(",", "").strip())
        return number if number >= 0 else None
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).replace(",", "").strip())
        return number if number >= 0 else None
    except (TypeError, ValueError):
        return None


def _models(item: dict) -> list[str]:
    raw = _first(item, "model_hints", "models", default=[])
    if isinstance(raw, str):
        raw = re.split(r"[;,|]", raw)
    if not isinstance(raw, list):
        raw = []
    found = []
    for value in raw:
        model = re.sub(r"\s+", "", str(value)).strip().upper()
        if model and MODEL_RE.fullmatch(model) and model not in found:
            found.append(model)
    if not found:
        title = str(_first(item, "title", "product_title", "listing_title", default=""))
        found = list(dict.fromkeys(
            re.sub(r"\s+", "", match.group(0)).upper()
            for match in MODEL_RE.finditer(title)
        ))
    return found


def _item_url(item: dict) -> str:
    raw = _first(item, "product_url", "url", "listing_url", default="")
    return normalize_url(str(raw)) if raw else ""


def _price_currency(item: dict) -> str:
    value = str(_first(item, "price_currency", "currency", default="")).strip().upper()
    if value in {"CNY", "CN¥", "RMB", "¥"}:
        return "CNY"
    if value in {"USD", "US$", "$"}:
        return "USD"
    text = str(_first(item, "price_text", default="")).upper()
    if "$" in text and "¥" not in text:
        return "USD"
    if any(token in text for token in ("CN¥", "CNY", "RMB", "¥")):
        return "CNY"
    return value


def _supplier_info(catalog: dict, source_url: str) -> tuple[str, str, str]:
    source = catalog.get("source") if isinstance(catalog.get("source"), dict) else {}
    platform = str(_first(source, "platform", default="Alibaba.com"))
    name = str(_first(source, "supplier", default=_first(catalog, "supplier", default=SUPPLIER_NAME)))
    storefront = str(_first(source, "canonical_url", "url", default=_first(catalog, "source_url", default=source_url)))
    if not storefront:
        storefront = SUPPLIER_URL
    return platform, name, normalize_url(storefront) or SUPPLIER_URL


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def _load_inputs(capture_dir: Path, snapshot_json: Path | None) -> tuple[dict, list[tuple[Path, dict]], list[dict], list[dict]]:
    """Return merged catalog, valid page checkpoints, detail records and input errors."""
    batch = read_batch(capture_dir)
    errors: list[dict] = []
    page_records: list[tuple[Path, dict]] = []
    detail_records: list[dict] = []
    catalog_path = capture_dir / "catalog.json"
    snapshot = {}
    if batch is None and snapshot_json and snapshot_json.is_file():
        try:
            snapshot = _load_json(snapshot_json)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append({"stage": "snapshot", "item_ref": str(snapshot_json), "error_type": type(exc).__name__, "message": str(exc)})
    live = {}
    if catalog_path.is_file():
        try:
            live = _load_json(catalog_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append({"stage": "catalog", "item_ref": str(catalog_path), "error_type": type(exc).__name__, "message": str(exc)})
    catalog = dict(snapshot or live)
    if live:
        catalog = dict(live)
        live_items = live.get("items", []) if isinstance(live.get("items"), list) else []
        snapshot_items = snapshot.get("items", []) if isinstance(snapshot.get("items"), list) else []
        merged: dict[str, dict] = {}
        for item in snapshot_items + live_items:
            if not isinstance(item, dict):
                continue
            url = _item_url(item)
            if url:
                merged[url] = item
        catalog["items"] = list(merged.values())
        if not catalog.get("source_url"):
            catalog["source_url"] = (snapshot.get("source") or {}).get("url", SUPPLIER_URL)
    if not catalog:
        catalog = {"supplier": SUPPLIER_NAME, "source_url": SUPPLIER_URL, "items": []}
    pages_dir = capture_dir / "pages"
    if pages_dir.is_dir():
        for path in sorted(pages_dir.glob("page_*.json")):
            try:
                record = _load_json(path)
                if belongs_to_batch(record, batch):
                    page_records.append((path, record))
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                errors.append({"stage": "listing_page", "item_ref": str(path), "error_type": type(exc).__name__, "message": str(exc)})
    details_dir = capture_dir / "details"
    if details_dir.is_dir():
        for path in sorted(details_dir.glob("*.json")):
            if path.name == "capture_errors.json":
                continue
            try:
                record = _load_json(path)
                if not record.get("item_id"):
                    raise ValueError("detail JSON missing item_id")
                if belongs_to_batch(record, batch):
                    detail_records.append(record)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                errors.append({"stage": "detail", "item_ref": str(path), "error_type": type(exc).__name__, "message": str(exc)})
        error_path = details_dir / "capture_errors.json"
        if error_path.is_file():
            try:
                detail_errors = json.loads(error_path.read_text(encoding="utf-8"))
                if isinstance(detail_errors, list):
                    for error in detail_errors:
                        if isinstance(error, dict) and belongs_to_batch(error, batch):
                            errors.append({"stage": "detail_capture", **error})
            except (OSError, json.JSONDecodeError) as exc:
                errors.append({"stage": "detail_capture", "item_ref": str(error_path), "error_type": type(exc).__name__, "message": str(exc)})
    return catalog, page_records, detail_records, errors


def _manifest(catalog: dict, pages: list[tuple[Path, dict]], details: list[dict], errors: list[dict]) -> str:
    payload = {
        "source_url": catalog.get("source_url") or (catalog.get("source") or {}).get("url") or SUPPLIER_URL,
        "items": sorted(_item_url(item) for item in catalog.get("items", []) if isinstance(item, dict)),
        "pages": [(path.name, _sha(_json(record))) for path, record in pages],
        "details": sorted(str(item.get("item_id", "")) + ":" + _sha(_json(item)) for item in details),
        "errors": errors,
    }
    return _sha(_json(payload))
