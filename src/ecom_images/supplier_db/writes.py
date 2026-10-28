"""Transactional supplier observation write helpers."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from ..supplier_catalog_capture import enrich_detail_payload, normalize_url
from .schema import _now, _id, _json, _sha
from .helpers import _supplier_info, _first, _item_url, _models, _as_int, _as_float, _price_currency

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
    verification = str(_first(item, "verification_status", default="seller_listing_observation_unverified") or "seller_listing_observation_unverified")
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
