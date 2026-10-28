"""Normalized, append-only SQLite catalog for supplier product observations.

This database is deliberately separate from the V13 evidence ledger. It stores what a
supplier page displayed at a point in time; it does not promote those observations to
verified manufacturer specifications or accepted knowledge claims.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .supplier_catalog_capture import enrich_detail_payload, normalize_url

SCHEMA_VERSION = 1
SUPPLIER_NAME = "Dongguan Dele Hardware Technology Co., Ltd."
SUPPLIER_URL = "https://dgdeler.en.alibaba.com/productlist.html"
DEFAULT_DB = Path(__file__).resolve().parents[2] / ".local" / "supplier_catalog.sqlite3"
DEFAULT_CAPTURE_DIR = Path(__file__).resolve().parents[2] / "data" / "supplier_captures" / "dgdeler"
DEFAULT_SNAPSHOT = Path(__file__).resolve().parents[2] / "docs" / "supplier-research" / "dgdeler_product_list_page1_2026-10-28.json"

_DDL = (
    """CREATE TABLE supplier_catalog_meta (
        key TEXT PRIMARY KEY, value TEXT NOT NULL
    )""",
    """CREATE TABLE supplier_catalog_suppliers (
        id TEXT PRIMARY KEY, platform TEXT NOT NULL, name TEXT NOT NULL,
        storefront_url TEXT NOT NULL, created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL,
        UNIQUE(platform, name, storefront_url)
    )""",
    """CREATE TABLE supplier_catalog_products (
        id TEXT PRIMARY KEY, supplier_id TEXT NOT NULL REFERENCES supplier_catalog_suppliers(id) ON DELETE RESTRICT,
        product_url TEXT NOT NULL UNIQUE, title TEXT NOT NULL DEFAULT '',
        model_hints_json TEXT NOT NULL DEFAULT '[]', category_guess TEXT NOT NULL DEFAULT '',
        image_url TEXT NOT NULL DEFAULT '', image_label TEXT NOT NULL DEFAULT '',
        first_seen_utc TEXT NOT NULL, last_seen_utc TEXT NOT NULL
    )""",
    """CREATE TABLE supplier_catalog_runs (
        id TEXT PRIMARY KEY, supplier_id TEXT NOT NULL REFERENCES supplier_catalog_suppliers(id) ON DELETE RESTRICT,
        started_utc TEXT NOT NULL, source_url TEXT NOT NULL, mode TEXT NOT NULL,
        input_manifest_sha256 TEXT NOT NULL CHECK(length(input_manifest_sha256)=64),
        args_json TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE supplier_catalog_run_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES supplier_catalog_runs(id) ON DELETE RESTRICT,
        created_utc TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('started','complete','partial','failed')),
        summary_json TEXT NOT NULL DEFAULT '{}', note TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE supplier_catalog_pages (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES supplier_catalog_runs(id) ON DELETE RESTRICT,
        page_number INTEGER NOT NULL CHECK(page_number>0), source_url TEXT NOT NULL, page_url TEXT NOT NULL DEFAULT '',
        captured_utc TEXT NOT NULL, pagination_text TEXT NOT NULL DEFAULT '', item_count INTEGER NOT NULL CHECK(item_count>=0),
        content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64), checkpoint_file TEXT NOT NULL DEFAULT '',
        raw_json TEXT NOT NULL, UNIQUE(run_id, page_number)
    )""",
    """CREATE TABLE supplier_catalog_observations (
        id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES supplier_catalog_products(id) ON DELETE RESTRICT,
        run_id TEXT NOT NULL REFERENCES supplier_catalog_runs(id) ON DELETE RESTRICT,
        observed_at TEXT NOT NULL, page_number INTEGER, title TEXT NOT NULL DEFAULT '',
        price_text TEXT NOT NULL DEFAULT '', price_min REAL, price_max REAL, price_currency TEXT NOT NULL DEFAULT '',
        moq_quantity INTEGER, moq_unit TEXT NOT NULL DEFAULT '', sales_count_displayed INTEGER,
        sales_status TEXT NOT NULL DEFAULT 'not_displayed_not_zero', delivery_text TEXT NOT NULL DEFAULT '',
        source_url TEXT NOT NULL DEFAULT '', image_url TEXT NOT NULL DEFAULT '',
        verification_status TEXT NOT NULL DEFAULT 'seller_listing_observation_unverified',
        observation_sha256 TEXT NOT NULL CHECK(length(observation_sha256)=64), raw_json TEXT NOT NULL,
        UNIQUE(product_id, observation_sha256)
    )""",
    """CREATE TABLE supplier_catalog_model_mentions (
        id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES supplier_catalog_products(id) ON DELETE RESTRICT,
        observation_id TEXT NOT NULL REFERENCES supplier_catalog_observations(id) ON DELETE RESTRICT,
        model_code TEXT NOT NULL COLLATE NOCASE, evidence_text TEXT NOT NULL DEFAULT '',
        extraction_method TEXT NOT NULL DEFAULT 'listing_title_regex',
        verification_status TEXT NOT NULL DEFAULT 'seller_title_model_mention_unverified',
        UNIQUE(observation_id, model_code)
    )""",
    """CREATE TABLE supplier_catalog_detail_observations (
        id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES supplier_catalog_products(id) ON DELETE RESTRICT,
        run_id TEXT NOT NULL REFERENCES supplier_catalog_runs(id) ON DELETE RESTRICT,
        observed_at TEXT NOT NULL, detail_url TEXT NOT NULL DEFAULT '', canonical_url TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '', body_text_sha256 TEXT NOT NULL CHECK(length(body_text_sha256)=64),
        body_text_chars INTEGER NOT NULL DEFAULT 0 CHECK(body_text_chars>=0),
        verification_status TEXT NOT NULL DEFAULT 'visible_detail_page_observation_unverified',
        detail_sha256 TEXT NOT NULL CHECK(length(detail_sha256)=64), structured_json TEXT NOT NULL DEFAULT '{}',
        raw_json TEXT NOT NULL, UNIQUE(product_id, detail_sha256)
    )""",
    """CREATE TABLE supplier_catalog_attributes (
        id TEXT PRIMARY KEY, detail_observation_id TEXT NOT NULL REFERENCES supplier_catalog_detail_observations(id) ON DELETE RESTRICT,
        product_id TEXT NOT NULL REFERENCES supplier_catalog_products(id) ON DELETE RESTRICT,
        attribute TEXT NOT NULL, value TEXT NOT NULL, source_locator TEXT NOT NULL DEFAULT '',
        verification_status TEXT NOT NULL DEFAULT 'seller_page_observation_unverified',
        attribute_sha256 TEXT NOT NULL CHECK(length(attribute_sha256)=64),
        UNIQUE(detail_observation_id, attribute_sha256)
    )""",
    """CREATE TABLE supplier_catalog_options (
        id TEXT PRIMARY KEY, detail_observation_id TEXT NOT NULL REFERENCES supplier_catalog_detail_observations(id) ON DELETE RESTRICT,
        product_id TEXT NOT NULL REFERENCES supplier_catalog_products(id) ON DELETE RESTRICT,
        group_name TEXT NOT NULL DEFAULT '', option_label TEXT NOT NULL DEFAULT '', option_value TEXT NOT NULL DEFAULT '',
        is_selected INTEGER NOT NULL DEFAULT 0 CHECK(is_selected IN (0,1)),
        is_disabled INTEGER NOT NULL DEFAULT 0 CHECK(is_disabled IN (0,1)),
        option_sha256 TEXT NOT NULL CHECK(length(option_sha256)=64),
        UNIQUE(detail_observation_id, option_sha256)
    )""",
    """CREATE TABLE supplier_catalog_errors (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES supplier_catalog_runs(id) ON DELETE RESTRICT,
        occurred_utc TEXT NOT NULL, stage TEXT NOT NULL, item_ref TEXT NOT NULL DEFAULT '',
        error_type TEXT NOT NULL, message TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}'
    )""",
    "CREATE INDEX idx_supplier_products_supplier ON supplier_catalog_products(supplier_id, title)",
    "CREATE INDEX idx_supplier_observations_product_time ON supplier_catalog_observations(product_id, observed_at DESC)",
    "CREATE INDEX idx_supplier_observations_run ON supplier_catalog_observations(run_id)",
    "CREATE INDEX idx_supplier_models_code ON supplier_catalog_model_mentions(model_code COLLATE NOCASE)",
    "CREATE INDEX idx_supplier_details_product_time ON supplier_catalog_detail_observations(product_id, observed_at DESC)",
    "CREATE INDEX idx_supplier_attributes_product ON supplier_catalog_attributes(product_id, attribute)",
    "CREATE INDEX idx_supplier_run_events_latest ON supplier_catalog_run_events(run_id, event_id DESC)",
    "CREATE INDEX idx_supplier_errors_run ON supplier_catalog_errors(run_id, occurred_utc)",
    """CREATE TRIGGER supplier_catalog_meta_no_update BEFORE UPDATE ON supplier_catalog_meta
       BEGIN SELECT RAISE(ABORT,'supplier catalog metadata is append-only'); END""",
    """CREATE TRIGGER supplier_catalog_meta_no_delete BEFORE DELETE ON supplier_catalog_meta
       BEGIN SELECT RAISE(ABORT,'supplier catalog metadata is append-only'); END""",
)
_APPEND_ONLY = (
    "supplier_catalog_run_events", "supplier_catalog_pages", "supplier_catalog_observations",
    "supplier_catalog_model_mentions", "supplier_catalog_detail_observations",
    "supplier_catalog_attributes", "supplier_catalog_options", "supplier_catalog_errors",
)
for _table in _APPEND_ONLY:
    _DDL += (
        f"""CREATE TRIGGER {_table}_no_update BEFORE UPDATE ON {_table}
            BEGIN SELECT RAISE(ABORT,'{_table} is append-only'); END""",
        f"""CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table}
            BEGIN SELECT RAISE(ABORT,'{_table} is append-only'); END""",
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id() -> str:
    return uuid.uuid4().hex


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _safe_db_path(path: str | Path) -> Path:
    target = Path(path).expanduser().absolute()
    if target.is_symlink() or any(parent.is_symlink() for parent in target.parents):
        raise ValueError("供应商数据库路径不能包含符号链接")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def open_supplier_db(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Open a validated local database connection with foreign keys enabled."""
    target = _safe_db_path(path)
    conn = sqlite3.connect(str(target), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def initialize_supplier_db(path: str | Path = DEFAULT_DB) -> None:
    """Create or validate the normalized supplier catalog schema without replacing data."""
    with open_supplier_db(path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if version == SCHEMA_VERSION:
            required = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            expected = {
                "supplier_catalog_meta", "supplier_catalog_suppliers", "supplier_catalog_products",
                "supplier_catalog_runs", "supplier_catalog_run_events", "supplier_catalog_pages",
                "supplier_catalog_observations", "supplier_catalog_model_mentions",
                "supplier_catalog_detail_observations", "supplier_catalog_attributes",
                "supplier_catalog_options", "supplier_catalog_errors",
            }
            if not expected.issubset(required):
                raise RuntimeError("供应商数据库缺少必需表；拒绝自动覆盖")
            meta = conn.execute("SELECT value FROM supplier_catalog_meta WHERE key='schema_version'").fetchone()
            if not meta or meta[0] != str(SCHEMA_VERSION):
                raise RuntimeError("供应商数据库 schema_version 不匹配")
            return
        if version != 0 or tables:
            raise RuntimeError(f"检测到不受支持的供应商数据库版本 {version}；拒绝自动覆盖")
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in _DDL:
                conn.execute(statement)
            conn.execute("INSERT INTO supplier_catalog_meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
            conn.execute("INSERT INTO supplier_catalog_meta(key,value) VALUES('created_utc',?)", (_now(),))
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


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
        if model and model not in found:
            found.append(model)
    if not found:
        title = str(_first(item, "title", "product_title", "listing_title", default=""))
        pattern = re.compile(r"\b(?:MS|CL|GL\d?|HC|XAH|XAG|XAE|XAC|LS|CK|HFX|TX)\s*-?\s*[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.I)
        found = list(dict.fromkeys(re.sub(r"\s+", "", match.group(0)).upper() for match in pattern.finditer(title)))
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
    errors: list[dict] = []
    page_records: list[tuple[Path, dict]] = []
    detail_records: list[dict] = []
    catalog_path = capture_dir / "catalog.json"
    snapshot = {}
    if snapshot_json and snapshot_json.is_file():
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
                detail_records.append(record)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                errors.append({"stage": "detail", "item_ref": str(path), "error_type": type(exc).__name__, "message": str(exc)})
        error_path = details_dir / "capture_errors.json"
        if error_path.is_file():
            try:
                detail_errors = json.loads(error_path.read_text(encoding="utf-8"))
                if isinstance(detail_errors, list):
                    for error in detail_errors:
                        if isinstance(error, dict):
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


def _upsert_supplier(conn: sqlite3.Connection, catalog: dict, source_url: str) -> str:
    platform, name, storefront = _supplier_info(catalog, source_url)
    supplier_id = _sha(f"{platform}|{name}|{storefront}")
    now = _now()
    conn.execute(
        """INSERT INTO supplier_catalog_suppliers(id,platform,name,storefront_url,created_utc,updated_utc)
           VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_utc=excluded.updated_utc""",
        (supplier_id, platform, name, storefront, now, now),
    )
    return supplier_id


def _record_error(conn: sqlite3.Connection, run_id: str, error: dict) -> None:
    conn.execute(
        """INSERT INTO supplier_catalog_errors(id,run_id,occurred_utc,stage,item_ref,error_type,message,metadata_json)
           VALUES(?,?,?,?,?,?,?,?)""",
        (_id(), run_id, _now(), str(error.get("stage", "unknown")), str(error.get("item_ref", "")),
         str(error.get("error_type", "Error")), str(error.get("message", ""))[:2000],
         _json({key: value for key, value in error.items() if key not in {"stage", "item_ref", "error_type", "message"}})),
    )


def _insert_page(conn: sqlite3.Connection, run_id: str, source_url: str, path: Path, record: dict) -> None:
    page_number = _as_int(_first(record, "page_number", default=re.search(r"page_(\d+)", path.name).group(1)
                                  if re.search(r"page_(\d+)", path.name) else None))
    if not page_number:
        raise ValueError(f"无法识别分页编号：{path.name}")
    raw = _json(record)
    conn.execute(
        """INSERT INTO supplier_catalog_pages(id,run_id,page_number,source_url,page_url,captured_utc,
           pagination_text,item_count,content_sha256,checkpoint_file,raw_json)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (_id(), run_id, page_number, str(record.get("source_url") or source_url),
         str(record.get("page_url") or ""), str(record.get("captured_at") or _now()),
         str(record.get("pagination_text") or ""), len(record.get("items", [])) if isinstance(record.get("items"), list) else 0,
         _sha(raw), path.name, raw),
    )


def _upsert_product(conn: sqlite3.Connection, supplier_id: str, item: dict, observed_at: str) -> str:
    url = _item_url(item)
    if not url:
        raise ValueError("商品缺少可用的 product_url")
    product_id = _sha(url)
    title = str(_first(item, "title", "product_title", "listing_title", default="")).strip()
    models = _models(item)
    category = str(_first(item, "category_guess", default="") or "")
    image_url = str(_first(item, "image_url", default="") or "")
    image_label = str(_first(item, "image_asset_label", default="") or "")
    conn.execute(
        """INSERT INTO supplier_catalog_products(id,supplier_id,product_url,title,model_hints_json,category_guess,
           image_url,image_label,first_seen_utc,last_seen_utc) VALUES(?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(product_url) DO UPDATE SET title=CASE WHEN excluded.title<>'' THEN excluded.title ELSE title END,
           model_hints_json=CASE WHEN excluded.model_hints_json<>'[]' THEN excluded.model_hints_json ELSE model_hints_json END,
           category_guess=CASE WHEN excluded.category_guess<>'' THEN excluded.category_guess ELSE category_guess END,
           image_url=CASE WHEN excluded.image_url<>'' THEN excluded.image_url ELSE image_url END,
           image_label=CASE WHEN excluded.image_label<>'' THEN excluded.image_label ELSE image_label END,
           last_seen_utc=excluded.last_seen_utc""",
        (product_id, supplier_id, url, title, _json(models), category, image_url, image_label, observed_at, observed_at),
    )
    row = conn.execute("SELECT id FROM supplier_catalog_products WHERE product_url=?", (url,)).fetchone()
    if not row:
        raise RuntimeError(f"商品写入后无法读取：{url}")
    return row["id"]


def _insert_observation(conn: sqlite3.Connection, product_id: str, run_id: str, item: dict,
                        source_url: str, page_number: int | None = None) -> tuple[str, bool]:
    observed_at = str(_first(item, "captured_at", "observed_at", default=_now()))
    title = str(_first(item, "title", "product_title", "listing_title", default="") or "")
    price_text = str(_first(item, "price_text", default="") or "")
    price_min = _as_float(_first(item, "price_min", "price_min_cny", default=None))
    price_max = _as_float(_first(item, "price_max", "price_max_cny", default=price_min))
    currency = _price_currency(item)
    moq_quantity = _as_int(_first(item, "moq_quantity", default=None))
    moq_unit = str(_first(item, "moq_unit", default="") or "")
    sales_count = _as_int(_first(item, "sales_count_displayed", default=None))
    sales_status = str(_first(item, "sales_status", default=("displayed" if sales_count is not None else "not_displayed_not_zero")))
    delivery = str(_first(item, "delivery_text", default="") or "")
    image_url = str(_first(item, "image_url", default="") or "")
    item_source = str(_first(item, "listing_source_url", "source_url", default=source_url) or source_url)
    verification = str(_first(item, "verification_status", "sales_status", default="seller_listing_observation_unverified") or "seller_listing_observation_unverified")
    raw = _json(item)
    hash_payload = {
        "observed_at": observed_at, "title": title, "price_text": price_text,
        "price_min": price_min, "price_max": price_max, "currency": currency,
        "moq_quantity": moq_quantity, "moq_unit": moq_unit, "sales_count_displayed": sales_count,
        "sales_status": sales_status, "delivery_text": delivery, "source_url": item_source,
        "raw_json": raw,
    }
    observation_hash = _sha(_json(hash_payload))
    existing = conn.execute(
        "SELECT id FROM supplier_catalog_observations WHERE product_id=? AND observation_sha256=?",
        (product_id, observation_hash),
    ).fetchone()
    if existing:
        return existing["id"], False
    observation_id = _id()
    conn.execute(
        """INSERT INTO supplier_catalog_observations(id,product_id,run_id,observed_at,page_number,title,
           price_text,price_min,price_max,price_currency,moq_quantity,moq_unit,sales_count_displayed,
           sales_status,delivery_text,source_url,image_url,verification_status,observation_sha256,raw_json)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (observation_id, product_id, run_id, observed_at, page_number, title, price_text, price_min, price_max,
         currency, moq_quantity, moq_unit, sales_count, sales_status, delivery, item_source, image_url,
         verification, observation_hash, raw),
    )
    for model in _models(item):
        mention_id = _id()
        conn.execute(
            """INSERT OR IGNORE INTO supplier_catalog_model_mentions(id,product_id,observation_id,model_code,
               evidence_text,extraction_method,verification_status) VALUES(?,?,?,?,?,?,?)""",
            (mention_id, product_id, observation_id, model, title, "listing_title_or_snapshot_model_field",
             "seller_title_model_mention_unverified"),
        )
    return observation_id, True


def _insert_detail(conn: sqlite3.Connection, run_id: str, product_id: str, item: dict,
                   record: dict, details_dir: Path) -> bool:
    detail = record.get("detail_page") if isinstance(record.get("detail_page"), dict) else {}
    text_name = Path(str(detail.get("body_text_file") or f"{record.get('item_id')}.txt")).name
    text_path = details_dir / text_name
    try:
        body_text = text_path.read_text(encoding="utf-8") if text_path.is_file() else ""
    except OSError:
        body_text = ""
    enriched = enrich_detail_payload(detail, body_text)
    observed_at = str(record.get("captured_at") or _now())
    detail_url = str(record.get("detail_url") or item.get("product_url") or "")
    canonical_url = str(enriched.get("canonical_url") or detail_url)
    title = str(enriched.get("title") or record.get("listing_title") or "")
    body_hash = _sha(body_text)
    structured = enriched.get("structured_product") if isinstance(enriched.get("structured_product"), dict) else {}
    detail_raw = _json({"record": record, "enriched_detail": enriched})
    detail_hash = _sha(_json({"observed_at": observed_at, "detail_url": detail_url,
                              "canonical_url": canonical_url, "body_hash": body_hash,
                              "detail_raw": detail_raw}))
    existing = conn.execute(
        "SELECT id FROM supplier_catalog_detail_observations WHERE product_id=? AND detail_sha256=?",
        (product_id, detail_hash),
    ).fetchone()
    if existing:
        return False
    detail_id = _id()
    conn.execute(
        """INSERT INTO supplier_catalog_detail_observations(id,product_id,run_id,observed_at,detail_url,
           canonical_url,title,body_text_sha256,body_text_chars,verification_status,detail_sha256,
           structured_json,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (detail_id, product_id, run_id, observed_at, detail_url, canonical_url, title, body_hash,
         len(body_text), str(record.get("verification_status") or "visible_detail_page_observation_unverified"),
         detail_hash, _json(structured), detail_raw),
    )
    for pair in enriched.get("attribute_pairs", []):
        if not isinstance(pair, dict):
            continue
        attribute = str(pair.get("key") or "").strip()
        value = str(pair.get("value") or "").strip()
        locator = str(pair.get("source_locator") or "")
        if not attribute or not value:
            continue
        attr_hash = _sha(_json({"attribute": attribute, "value": value, "locator": locator}))
        conn.execute(
            """INSERT OR IGNORE INTO supplier_catalog_attributes(id,detail_observation_id,product_id,
               attribute,value,source_locator,verification_status,attribute_sha256) VALUES(?,?,?,?,?,?,?,?)""",
            (_id(), detail_id, product_id, attribute, value, locator, "seller_page_observation_unverified", attr_hash),
        )
    for group in enriched.get("option_groups", []):
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("group") or group.get("kind") or "option")
        for option in group.get("options", []):
            if not isinstance(option, dict):
                continue
            label = str(option.get("label") or "")
            value = str(option.get("value") or "")
            if not label and not value:
                continue
            option_hash = _sha(_json({"group": group_name, "label": label, "value": value,
                                      "selected": bool(option.get("selected")), "disabled": bool(option.get("disabled"))}))
            conn.execute(
                """INSERT OR IGNORE INTO supplier_catalog_options(id,detail_observation_id,product_id,group_name,
                   option_label,option_value,is_selected,is_disabled,option_sha256) VALUES(?,?,?,?,?,?,?,?,?)""",
                (_id(), detail_id, product_id, group_name, label, value, int(bool(option.get("selected"))),
                 int(bool(option.get("disabled"))), option_hash),
            )
    return True


def sync_supplier_catalog(path: str | Path = DEFAULT_DB, *,
                          capture_dir: str | Path = DEFAULT_CAPTURE_DIR,
                          snapshot_json: str | Path | None = DEFAULT_SNAPSHOT,
                          dry_run: bool = False) -> dict:
    """Load capture checkpoints, listing observations and detail evidence into normalized SQLite."""
    capture = Path(capture_dir).expanduser().absolute()
    snapshot = Path(snapshot_json).expanduser().absolute() if snapshot_json else None
    catalog, pages, details, errors = _load_inputs(capture, snapshot)
    items = [item for item in catalog.get("items", []) if isinstance(item, dict) and _item_url(item)]
    unique_items = {_item_url(item): item for item in items}
    items = list(unique_items.values())
    source_url = str(_first(catalog, "source_url", default=(catalog.get("source") or {}).get("url", SUPPLIER_URL)))
    manifest_sha = _manifest(catalog, pages, details, errors)
    summary = {
        "dry_run": dry_run, "database": str(Path(path).expanduser().absolute()),
        "capture_dir": str(capture), "snapshot_json": str(snapshot) if snapshot else None,
        "valid_page_checkpoints": len(pages), "unique_listing_products": len(items),
        "detail_records": len(details), "input_errors": len(errors), "manifest_sha256": manifest_sha,
        "creates_verified_claims": False,
    }
    if dry_run:
        summary["status"] = "preview"
        return summary
    initialize_supplier_db(path)
    now = _now()
    with open_supplier_db(path) as conn:
        supplier_id = _upsert_supplier(conn, catalog, source_url)
        run_id = _id()
        conn.execute("BEGIN IMMEDIATE")
        try:
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
            audit_path = capture / "catalog_audit.json"
            detail_audit_path = capture / "details_audit.json"
            listing_audit = _load_json(audit_path) if audit_path.is_file() else {}
            detail_audit = _load_json(detail_audit_path) if detail_audit_path.is_file() else {}
            status = "complete" if (
                listing_audit.get("status") == "complete"
                and (not detail_audit or detail_audit.get("status") == "complete")
                and not errors and not detail_missing_body
            ) else "partial"
            summary.update({
                "run_id": run_id, "supplier_id": supplier_id, "status": status,
                "products_seen": len(items), "observations_inserted": inserted_observations,
                "observations_unchanged": unchanged_observations, "details_inserted": detail_inserted,
                "listing_audit_status": listing_audit.get("status", "not_available"),
                "detail_audit_status": detail_audit.get("status", "not_available"),
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
            with conn:
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
            raise
    summary["database_audit"] = audit_supplier_db(path)
    return summary


def audit_supplier_db(path: str | Path = DEFAULT_DB) -> dict:
    """Report SQLite integrity, foreign keys, observation coverage and current run status."""
    initialize_supplier_db(path)
    with open_supplier_db(path) as conn:
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
    with open_supplier_db(path) as conn:
        queries = {
            "supplier_products.csv": """SELECT p.id AS product_id,s.name AS supplier,p.title,p.product_url,
                p.model_hints_json,p.category_guess,p.image_url,p.first_seen_utc,p.last_seen_utc,
                (SELECT o.price_text FROM supplier_catalog_observations o WHERE o.product_id=p.id
                 ORDER BY o.rowid DESC LIMIT 1) AS latest_price_text,
                (SELECT o.price_min FROM supplier_catalog_observations o WHERE o.product_id=p.id
                 ORDER BY o.rowid DESC LIMIT 1) AS latest_price_min,
                (SELECT o.price_max FROM supplier_catalog_observations o WHERE o.product_id=p.id
                 ORDER BY o.rowid DESC LIMIT 1) AS latest_price_max,
                (SELECT o.price_currency FROM supplier_catalog_observations o WHERE o.product_id=p.id
                 ORDER BY o.rowid DESC LIMIT 1) AS latest_currency,
                (SELECT o.moq_quantity FROM supplier_catalog_observations o WHERE o.product_id=p.id
                 ORDER BY o.rowid DESC LIMIT 1) AS latest_moq,
                (SELECT o.sales_count_displayed FROM supplier_catalog_observations o WHERE o.product_id=p.id
                 ORDER BY o.rowid DESC LIMIT 1) AS latest_sales_displayed,
                (SELECT o.sales_status FROM supplier_catalog_observations o WHERE o.product_id=p.id
                 ORDER BY o.rowid DESC LIMIT 1) AS latest_sales_status
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
    with open_supplier_db(path) as conn:
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
