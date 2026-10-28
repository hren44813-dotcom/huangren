"""Offline, append-only daily SKU observations for competitors; never scraped or inferred."""
from __future__ import annotations

import csv
import io
import ipaddress
import re
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_DB = Path(__file__).resolve().parents[2] / ".local" / "competitor_monitor.sqlite3"
FIELDS = (
    "日期", "竞店", "竞品链接", "SKU", "SKU价格", "币种", "链接销量",
    "评价带图", "优惠券", "活动", "截图文件名", "备注",
)
FLAGS = {"有", "无", "未显示"}
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000


def template_csv() -> bytes:
    """One SKU per link and date; link-level facts repeat across rows."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(FIELDS)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def _cell(value: str, label: str, limit: int = 400, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label}必须是文本")
    text = value.strip()
    if required and not text:
        raise ValueError(f"{label}不能为空")
    if len(text) > limit or any(ord(c) < 32 and c not in "\n\r\t" for c in text):
        raise ValueError(f"{label}过长或包含控制字符")
    # Spreadsheet formulas and tab/newline prefixes must not become executable CSV.
    if text[:1] in ("=", "+", "-", "@"):
        raise ValueError(f"{label}不能以公式符号开头")
    return text


def _url(raw: str) -> str:
    text = _cell(raw, "竞品链接", 2000, required=True)
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").lower().rstrip(".")
        if (parts.scheme != "https" or not host or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443)
                or host == "localhost" or host.endswith(".localhost")
                or not re.fullmatch(r"[a-z0-9.-]+", host) or "." not in host):
            raise ValueError("竞品链接必须是公开 HTTPS 网站地址")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("不允许 IP 地址形式的竞品链接")
    except (ValueError, UnicodeError) as exc:
        raise ValueError("竞品链接必须是公开 HTTPS 网站地址") from exc
    return text.split("#", 1)[0]


def _day(raw: str) -> str:
    value = _cell(raw, "日期", 10, required=True)
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError as exc:
        raise ValueError("日期必须为 YYYY-MM-DD") from exc
    return value


def _price(raw: str) -> int | None:
    value = _cell(raw, "SKU价格", 24)
    if not value:
        return None
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", value):
        raise ValueError("SKU价格必须是非负数，最多两位小数；不可填区间")
    try:
        cents = int(Decimal(value) * 100)
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError("SKU价格不是有效数字") from exc
    if cents > 999999999:
        raise ValueError("SKU价格超出限制")
    return cents


def _sales(raw: str) -> int | None:
    value = _cell(raw, "链接销量", 20)
    if not value:
        return None  # Not displayed is unknown, not zero.
    if not re.fullmatch(r"\d+", value) or len(value) > 12:
        raise ValueError("链接销量必须是非负整数，未显示时留空")
    return int(value)


def _parse(raw: dict[str, str], number: int) -> dict:
    try:
        day = _day(raw["日期"])
        shop = _cell(raw["竞店"], "竞店", 120, required=True)
        url = _url(raw["竞品链接"])
        sku = _cell(raw["SKU"], "SKU", 160, required=True)
        price = _price(raw["SKU价格"])
        currency = _cell(raw["币种"], "币种", 3, required=True).upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("币种必须使用三位字母，例如 CNY、USD")
        sales = _sales(raw["链接销量"])
        flags = {}
        for name, key in (("评价带图", "photo_reviews"), ("优惠券", "coupon"), ("活动", "campaign")):
            value = _cell(raw[name], name, 10, required=True)
            if value not in FLAGS:
                raise ValueError(f"{name}请选择 有/无/未显示")
            flags[key] = value
        screenshot = _cell(raw["截图文件名"], "截图文件名", 180)
        if screenshot and ("/" in screenshot or "\\" in screenshot or screenshot in (".", "..")
                           or not screenshot.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))):
            raise ValueError("截图文件名只允许图片文件名，不能包含路径")
        note = _cell(raw["备注"], "备注", 600)
        return {"day": day, "shop": shop, "url": url, "sku": sku,
                "price_cents": price, "currency": currency, "sales": sales,
                **flags, "screenshot": screenshot, "note": note}
    except (KeyError, ValueError) as exc:
        raise ValueError(f"CSV 第 {number} 行：{exc}") from exc


def parse_csv(data: bytes) -> list[dict]:
    """Validate entire CSV and link-level consistency before any database write."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
        raise ValueError("CSV 文件为空或超过 2 MB")
    try:
        decoded = data.decode("utf-8-sig")
        stream = io.StringIO(decoded, newline="")
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames != list(FIELDS):
            raise ValueError("CSV 表头必须与下载模板完全一致")
        rows = []
        seen = {}
        link_facts = {}
        for i, raw in enumerate(reader, 2):
            if len(rows) >= MAX_ROWS:
                raise ValueError("每次最多导入 5000 行")
            if None in raw:
                raise ValueError(f"CSV 第 {i} 行有多余列")
            row = _parse(raw, i)
            key = row["day"], row["url"], row["sku"]
            if key in seen:
                raise ValueError(f"CSV 第 {i} 行重复了同日期、同链接的 SKU：{row['sku']}")
            seen[key] = True
            link_key = row["day"], row["url"]
            facts = row["shop"], row["sales"], row["photo_reviews"], row["coupon"], row["campaign"]
            if link_key in link_facts and link_facts[link_key] != facts:
                raise ValueError(f"CSV 第 {i} 行同一竞品链接的销量/评价/优惠券/活动不一致")
            link_facts[link_key] = facts
            rows.append(row)
        if not rows:
            raise ValueError("CSV 没有可导入的数据行")
        return rows
    except (UnicodeError, csv.Error) as exc:
        raise ValueError(f"CSV 编码或格式错误：{exc}") from exc


def _connect(path: Path, *, writable: bool) -> sqlite3.Connection:
    path = Path(path).expanduser().absolute()
    if path.is_symlink():
        raise ValueError("不允许通过符号链接访问监测数据库")
    if not writable and not path.is_file():
        raise ValueError("尚未导入竞品监测记录")
    if writable:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    if writable:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("""CREATE TABLE IF NOT EXISTS competitor_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day TEXT NOT NULL, shop TEXT NOT NULL, url TEXT NOT NULL, sku TEXT NOT NULL,
            price_cents INTEGER, currency TEXT NOT NULL, sales INTEGER,
            photo_reviews TEXT NOT NULL, coupon TEXT NOT NULL, campaign TEXT NOT NULL,
            screenshot TEXT NOT NULL, note TEXT NOT NULL, imported_utc TEXT NOT NULL,
            UNIQUE(day,url,sku))""")
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_competitor_history
                        ON competitor_observations(url,sku,day)""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS competitor_no_update
                        BEFORE UPDATE ON competitor_observations BEGIN
                        SELECT RAISE(ABORT,'observations are append-only'); END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS competitor_no_delete
                        BEFORE DELETE ON competitor_observations BEGIN
                        SELECT RAISE(ABORT,'observations are append-only'); END""")
        conn.commit()
    else:
        exists = conn.execute("""SELECT 1 FROM sqlite_master WHERE type='table'
                                 AND name='competitor_observations'""").fetchone()
        if not exists:
            conn.close()
            raise ValueError("监测数据库尚未初始化")
    return conn


def import_csv(path: str | Path, data: bytes, *, dry_run: bool = True) -> dict:
    """All-or-nothing import, idempotent for identical rows and fail-closed for edits."""
    rows = parse_csv(data)
    counts = {"rows": len(rows), "new": 0, "unchanged": 0,
              "dates": sorted({row["day"] for row in rows}),
              "links": len({row["url"] for row in rows}), "dry_run": dry_run}
    db = Path(path)
    # Preview never creates an empty database or mutates an existing one.
    if dry_run and not db.exists():
        counts["new"] = len(rows)
        return counts
    with _connect(db, writable=not dry_run) as conn:
        if not dry_run:
            conn.execute("BEGIN IMMEDIATE")
        try:
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for row in rows:
                old = conn.execute("""SELECT * FROM competitor_observations
                                      WHERE day=? AND url=? AND sku=?""",
                                   (row["day"], row["url"], row["sku"])).fetchone()
                if old is not None:
                    if any(old[key] != val for key, val in row.items()):
                        raise ValueError(f"已存在不同数据：{row['day']} · {row['sku']}。不会静默覆盖，请核实原始记录")
                    counts["unchanged"] += 1
                else:
                    counts["new"] += 1
                    if not dry_run:
                        conn.execute("""INSERT INTO competitor_observations
                            (day,shop,url,sku,price_cents,currency,sales,photo_reviews,
                             coupon,campaign,screenshot,note,imported_utc)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            tuple(row.values()) + (stamp,))
            if not dry_run:
                conn.commit()
        except BaseException:
            if not dry_run and conn.in_transaction:
                conn.rollback()
            raise
    return counts


def available_dates(path: str | Path) -> list[str]:
    """Read-only; never initialize on view."""
    db = Path(path)
    if not db.is_file():
        return []
    with _connect(db, writable=False) as conn:
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT day FROM competitor_observations ORDER BY day DESC LIMIT 365")]


def daily_report(path: str | Path, day: str) -> dict:
    """Compare each SKU with its previous observation; never infer a sale or delisting."""
    day = _day(day)
    with _connect(Path(path), writable=False) as conn:
        current = conn.execute("""SELECT * FROM competitor_observations
                                 WHERE day=? ORDER BY shop,url,sku""", (day,)).fetchall()
        rows = []
        for item in current:
            before = conn.execute("""SELECT day,price_cents,currency,sales
                FROM competitor_observations WHERE url=? AND sku=? AND day<?
                ORDER BY day DESC LIMIT 1""", (item["url"], item["sku"], day)).fetchone()
            old_price = before["price_cents"] if before is not None else None
            old_currency = before["currency"] if before is not None else None
            new_price = item["price_cents"]
            if before is None:
                state = "首次记录"
            elif old_price is None or new_price is None or old_currency != item["currency"]:
                state = "无法比较"
            elif new_price > old_price:
                state = "涨价"
            elif new_price < old_price:
                state = "降价"
            else:
                state = "持平"
            change = new_price - old_price if state in ("涨价", "降价", "持平") else None
            rows.append({
                "日期": item["day"], "竞店": item["shop"], "竞品链接": item["url"],
                "SKU": item["sku"], "本次价格": _money(new_price),
                "币种": item["currency"], "前次日期": before["day"] if before else "",
                "前次价格": _money(old_price) if before else "", "价格变化": state,
                "变动金额": _money(change), "链接销量": item["sales"],
                "评价带图": item["photo_reviews"], "优惠券": item["coupon"],
                "活动": item["campaign"], "截图文件名": item["screenshot"],
                "备注": item["note"],
            })
        # If a SKU is absent from today's manual record, mark it "unrecorded",
        # not "delisted"; we have no live marketplace availability signal.
        missing = []
        for link in {r["url"] for r in current}:
            previous = conn.execute("""SELECT MAX(day) FROM competitor_observations
                                       WHERE url=? AND day<?""", (link, day)).fetchone()[0]
            if not previous:
                continue
            former = {r[0] for r in conn.execute(
                "SELECT sku FROM competitor_observations WHERE day=? AND url=?", (previous, link))}
            today = {r["sku"] for r in current if r["url"] == link}
            for sku in sorted(former - today):
                missing.append({"竞品链接": link, "SKU": sku, "前次日期": previous,
                                "状态": "本次未记录（不能认定下架）"})
    return {"date": day, "rows": rows, "missing": missing,
            "total": len(rows),
            "price_up": sum(r["价格变化"] == "涨价" for r in rows),
            "price_down": sum(r["价格变化"] == "降价" for r in rows),
            "new_skus": sum(r["价格变化"] == "首次记录" for r in rows)}


def _money(cents: int | None) -> str:
    return "" if cents is None else f"{Decimal(cents) / 100:.2f}"


def report_csv(report: dict) -> bytes:
    """Escape spreadsheet formula prefixes even in URLs and all free text."""
    fields = ("日期", "竞店", "竞品链接", "SKU", "本次价格", "币种", "前次日期",
              "前次价格", "价格变化", "变动金额", "链接销量",
              "评价带图", "优惠券", "活动", "截图文件名", "备注")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in report["rows"]:
        safe = {}
        numeric_fields = {"本次价格", "前次价格", "变动金额", "链接销量"}
        for field in fields:
            text = "" if row[field] is None else str(row[field])
            # Preserve legitimate negative numeric deltas while neutralizing untrusted text.
            if field in numeric_fields and re.fullmatch(r"-?\d+(?:\.\d+)?", text):
                safe[field] = text
            else:
                safe[field] = "'" + text if text.lstrip()[:1] in ("=", "+", "-", "@") else text
        writer.writerow(safe)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")
