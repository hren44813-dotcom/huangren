"""Normalized, append-only SQLite catalog for supplier product observations.

This database is deliberately separate from the V13 evidence ledger. It stores what a
supplier page displayed at a point in time; it does not promote those observations to
verified manufacturer specifications or accepted knowledge claims.
"""
from __future__ import annotations

import csv
import hashlib
from contextlib import contextmanager
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    with supplier_connection(path) as conn:
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


@contextmanager
def supplier_connection(path: str | Path = DEFAULT_DB):
    """Close SQLite connections reliably and commit or roll back ordinary transactions."""
    conn = open_supplier_db(path)
    try:
        yield conn
        if conn.in_transaction:
            conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
