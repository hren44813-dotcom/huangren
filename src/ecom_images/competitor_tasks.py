"""Fixed competitor SKU watchlist, daily assignment coverage and evidence-based alerts."""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .competitor_monitor import (
    DEFAULT_DB, FIELDS, MAX_BYTES, MAX_ROWS, _cell, _connect, _day, _money, _url,
)

WATCH_FIELDS = ("竞店", "竞品链接", "SKU", "币种", "监测状态")
STATUS = {"启用": 1, "停用": 0}


def _encode_csv(fields, rows) -> bytes:
    """Preserve numeric values while neutralizing formula-like text in Excel."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        safe = {}
        for key, value in row.items():
            text = "" if value is None else str(value)
            prefix = text.lstrip()
            safe[key] = "'" + text if prefix and prefix[0] in "=+-@" else text
        writer.writerow(safe)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def watch_template() -> bytes:
    return _encode_csv(WATCH_FIELDS, [])


def parse_watchlist(data: bytes) -> list[dict]:
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
        raise ValueError("竞品清单 CSV 为空或超过 2 MB")
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
        if reader.fieldnames != list(WATCH_FIELDS):
            raise ValueError("请使用竞品清单模板的完整表头")
        records, seen, link_shops = [], set(), {}
        for line_no, row in enumerate(reader, 2):
            if len(records) >= MAX_ROWS:
                raise ValueError("竞品清单最多 5000 行")
            if None in row:
                raise ValueError(f"第 {line_no} 行有多余列")
            try:
                shop = _cell(row["竞店"], "竞店", 120, required=True)
                url = _url(row["竞品链接"])
                sku = _cell(row["SKU"], "SKU", 160, required=True)
                currency = _cell(row["币种"], "币种", 3, required=True).upper()
                state = _cell(row["监测状态"], "监测状态", 8, required=True)
                if not re.fullmatch(r"[A-Z]{3}", currency):
                    raise ValueError("币种应为 CNY、USD 等三个字母")
                if state not in STATUS:
                    raise ValueError("监测状态只能是 启用 或 停用")
                if (url, sku) in seen:
                    raise ValueError("同一竞品链接下 SKU 重复")
                if url in link_shops and link_shops[url] != shop:
                    raise ValueError("同一竞品链接的竞店不一致")
                link_shops[url] = shop
                seen.add((url, sku))
                records.append({"shop": shop, "url": url, "sku": sku,
                                "currency": currency, "active": STATUS[state]})
            except (KeyError, ValueError) as exc:
                raise ValueError(f"清单第 {line_no} 行：{exc}") from exc
        if not records:
            raise ValueError("清单没有任何 SKU")
        return records
    except (UnicodeError, csv.Error) as exc:
        raise ValueError(f"清单编码或格式错误：{exc}") from exc


def _has_registry(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='competitor_watchlist'"
    ).fetchone() is not None


def _create_registry(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS competitor_watchlist (
        url TEXT NOT NULL, sku TEXT NOT NULL, shop TEXT NOT NULL,
        currency TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)),
        created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL,
        PRIMARY KEY(url,sku))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS competitor_watchlist_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_utc TEXT NOT NULL, url TEXT NOT NULL, sku TEXT NOT NULL,
        old_json TEXT NOT NULL, new_json TEXT NOT NULL)""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS competitor_watchlist_events_no_update
                    BEFORE UPDATE ON competitor_watchlist_events BEGIN
                    SELECT RAISE(ABORT,'watchlist history is append-only'); END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS competitor_watchlist_events_no_delete
                    BEFORE DELETE ON competitor_watchlist_events BEGIN
                    SELECT RAISE(ABORT,'watchlist history is append-only'); END""")


def import_watchlist(path: str | Path = DEFAULT_DB, data: bytes = b"",
                     *, dry_run: bool = True) -> dict:
    """Add/modify/deactivate explicitly listed SKUs, with a permanent audit event."""
    rows = parse_watchlist(data)
    result = {"rows": len(rows), "new": 0, "updated": 0, "unchanged": 0,
              "enabled": sum(row["active"] for row in rows), "dry_run": dry_run}
    db = Path(path)
    if dry_run and not db.exists():
        result["new"] = len(rows)
        return result
    with _connect(db, writable=not dry_run) as conn:
        if not dry_run:
            conn.execute("BEGIN IMMEDIATE")
            _create_registry(conn)
        has_registry = _has_registry(conn)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            for row in rows:
                previous = (conn.execute(
                    "SELECT shop,url,sku,currency,active FROM competitor_watchlist WHERE url=? AND sku=?",
                    (row["url"], row["sku"]),
                ).fetchone() if has_registry else None)
                old = dict(previous) if previous is not None else None
                if old == row:
                    result["unchanged"] += 1
                    continue
                result["new" if old is None else "updated"] += 1
                if dry_run:
                    continue
                if old is None:
                    conn.execute("""INSERT INTO competitor_watchlist
                        (shop,url,sku,currency,active,created_utc,updated_utc)
                        VALUES (?,?,?,?,?,?,?)""", tuple(row.values()) + (now, now))
                else:
                    conn.execute("""UPDATE competitor_watchlist SET
                        shop=?,currency=?,active=?,updated_utc=? WHERE url=? AND sku=?""",
                        (row["shop"], row["currency"], row["active"], now, row["url"], row["sku"]))
                conn.execute("""INSERT INTO competitor_watchlist_events
                    (event_utc,url,sku,old_json,new_json) VALUES (?,?,?,?,?)""",
                    (now, row["url"], row["sku"], json.dumps(old, ensure_ascii=False),
                     json.dumps(row, ensure_ascii=False)))
            if not dry_run:
                conn.commit()
        except BaseException:
            if not dry_run and conn.in_transaction:
                conn.rollback()
            raise
    return result


def list_watchlist(path: str | Path = DEFAULT_DB, *, active_only: bool = False) -> list[dict]:
    db = Path(path)
    if not db.exists():
        return []
    with _connect(db, writable=False) as conn:
        if not _has_registry(conn):
            return []
        query = ("SELECT shop,url,sku,currency,active FROM competitor_watchlist"
                 + (" WHERE active=1" if active_only else "") + " ORDER BY shop,url,sku")
        return [dict(row) for row in conn.execute(query)]


def daily_checklist(path: str | Path, day: str, *, alert_percent: int = 20) -> dict:
    """Read-only status for every active SKU; missing rows are not delisting evidence."""
    day = _day(day)
    if type(alert_percent) is not int or not 1 <= alert_percent <= 100:
        raise ValueError("异常价格阈值应为 1%～100%")
    db = Path(path)
    if not db.is_file():
        return {"date": day, "total": 0, "completed": 0, "pending": 0,
                "missing_price": 0, "rows": [], "alerts": []}
    with _connect(db, writable=False) as conn:
        watchlist = list_watchlist(path, active_only=True)
        rows, alerts = [], []
        seen_links = set()
        completed = missing_price = 0
        for task in watchlist:
            today = conn.execute("""SELECT * FROM competitor_observations
                 WHERE url=? AND sku=? AND day=?""",
                 (task["url"], task["sku"], day)).fetchone()
            prior = conn.execute("""SELECT * FROM competitor_observations
                 WHERE url=? AND sku=? AND day<? ORDER BY day DESC LIMIT 1""",
                 (task["url"], task["sku"], day)).fetchone()
            if today is None:
                status = "待监测"
            elif today["price_cents"] is None:
                status = "已记录待补价格"
                missing_price += 1
            else:
                status = "完成"
                completed += 1
            rows.append({
                "日期": day, "竞店": task["shop"], "竞品链接": task["url"],
                "SKU": task["sku"], "币种": task["currency"], "状态": status,
                "本次价格": _money(today["price_cents"]) if today else "",
                "前次日期": prior["day"] if prior else "",
                "前次价格": _money(prior["price_cents"]) if prior else "",
            })
            if today is None:
                continue
            if today["price_cents"] is None:
                alerts.append({"竞品链接": task["url"], "SKU": task["sku"],
                               "类型": "缺少价格", "说明": "已经记录，但本次 SKU 价格未填写"})
            elif today["currency"] != task["currency"]:
                alerts.append({"竞品链接": task["url"], "SKU": task["sku"],
                               "类型": "币种不一致", "说明": "实际记录币种与任务清单不同，请核对"})
            elif (prior is not None and prior["currency"] == today["currency"]
                  and prior["price_cents"] is not None and prior["price_cents"] > 0):
                delta = Decimal(today["price_cents"] - prior["price_cents"]) / prior["price_cents"] * 100
                if abs(delta) >= alert_percent:
                    alerts.append({"竞品链接": task["url"], "SKU": task["sku"],
                                   "类型": "价格异常变动",
                                   "说明": f"相较 {prior['day']} 变化 {delta:+.1f}%；需人工核实"})
            if task["url"] not in seen_links:
                seen_links.add(task["url"])
                old_link = conn.execute("""SELECT day,coupon,campaign FROM competitor_observations
                    WHERE url=? AND day<? ORDER BY day DESC,id DESC LIMIT 1""",
                    (task["url"], day)).fetchone()
                if old_link is not None:
                    for field, kind in (("coupon", "优惠券变化"), ("campaign", "活动变化")):
                        old = old_link[field]
                        new = today[field]
                        if old in ("有", "无") and new in ("有", "无") and old != new:
                            alerts.append({"竞品链接": task["url"], "SKU": "链接级",
                                           "类型": kind, "说明": f"{old_link['day']}：{old} → {day}：{new}"})
        total = len(rows)
        return {"date": day, "total": total, "completed": completed,
                "pending": total - completed, "missing_price": missing_price,
                "rows": rows, "alerts": alerts}


def daily_blank_csv(path: str | Path, day: str) -> bytes:
    """Task handout: blank price and page facts, never copied from past observations."""
    day = _day(day)
    rows = [{
        "日期": day, "竞店": row["shop"], "竞品链接": row["url"],
        "SKU": row["sku"], "SKU价格": "", "币种": row["currency"],
        "链接销量": "", "评价带图": "", "优惠券": "", "活动": "",
        "截图文件名": "", "备注": "",
    } for row in list_watchlist(path, active_only=True)]
    return _encode_csv(FIELDS, rows)
