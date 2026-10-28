"""Reusable parsing and export helpers for visible Alibaba catalog captures."""
from __future__ import annotations
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

DEFAULT_URL = "https://dgdeler.en.alibaba.com/productlist.html"
PRICE_RE = re.compile(
    r"(?:CN¥|CNY|RMB|¥|US\s*\$|\$)\s*([0-9][0-9,]*(?:\.\d+)?)"
    r"\s*(?:[-–~]\s*(?:CN¥|CNY|RMB|¥|US\s*\$|\$)?\s*([0-9][0-9,]*(?:\.\d+)?))?",
    re.IGNORECASE,
)
MOQ_RE = re.compile(
    r"Min\.?\s*order\s*:?\s*([0-9][0-9,]*)\s*"
    r"(pieces?|pcs?|sets?|pairs?|units?|boxes?|lots?)?",
    re.IGNORECASE,
)
SOLD_RE = re.compile(r"\b([0-9][0-9,]*)\s+sold\b", re.IGNORECASE)
DELIVERY_RE = re.compile(r"\bDelivery\s+by\s+([^\n\r]+)", re.IGNORECASE)
MODEL_RE = re.compile(
    r"\b(?:MS|CL|GL\d?|HC|XAH|XAG|XAE|XAC|LS|CK|HFX|TX)"
    r"\s*-?\s*[A-Z0-9]+(?:-[A-Z0-9]+)*\b",
    re.IGNORECASE,
)
from .browser_js import LISTING_JS, META_JS


def now_iso() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_url(url: str) -> str:
    """Strip tracking query strings and fragments from a public product URL."""
    if not url.strip():
        return ""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, "", ""))


def parse_listing_item(raw: dict, page_number: int, source_url: str) -> dict:
    """Parse visible card text while keeping seller claims explicitly unverified."""
    title = re.sub(r"\s+", " ", str(raw.get("title", "")).strip())
    card_text = re.sub(r"\s+", " ", str(raw.get("card_text", "")).strip())
    url = normalize_url(str(raw.get("url", "")))
    match = PRICE_RE.search(card_text)
    price_min = float(match.group(1).replace(",", "")) if match else None
    price_max = float(match.group(2).replace(",", "")) if match and match.group(2) else price_min
    currency = None
    if match:
        prefix = card_text[match.start():match.start(1)].strip().upper()
        currency = "USD" if "$" in prefix else "CNY" if any(
            token in prefix for token in ("CN¥", "CNY", "RMB", "¥")
        ) else None
    moq = MOQ_RE.search(card_text)
    sold = SOLD_RE.search(card_text)
    delivery = DELIVERY_RE.search(card_text)
    models = sorted({re.sub(r"\s+", "", value.upper()) for value in MODEL_RE.findall(title)})
    return {
        "item_id": hashlib.sha256(url.encode("utf-8")).hexdigest()[:16],
        "page_number": page_number,
        "title": title,
        "product_url": url,
        "image_url": raw.get("image_url") or None,
        "card_text": card_text,
        "model_hints": models,
        "price_text": match.group(0) if match else None,
        "price_min": price_min,
        "price_max": price_max,
        "price_currency": currency,
        "moq_quantity": int(moq.group(1).replace(",", "")) if moq else None,
        "moq_unit": (moq.group(2) or "").lower() if moq else None,
        "sales_count_displayed": int(sold.group(1).replace(",", "")) if sold else None,
        "sales_status": "displayed" if sold else "not_displayed_not_zero",
        "delivery_text": delivery.group(0).strip() if delivery else None,
        "listing_source_url": source_url,
        "captured_at": now_iso(),
        "verification_status": "seller_listing_observation_unverified",
    }


def is_challenge(text: str, url: str = "") -> bool:
    """Detect visible CAPTCHA or unusual-traffic pages for manual verification."""
    probe = f"{url}\n{text}".lower()
    return any(phrase in probe for phrase in (
        "please slide to verify", "unusual traffic from your network",
        "verify you are human", "security verification", "captcha",
    ))


def scrape_listing_page(page, page_number: int, source_url: str) -> dict:
    """Capture product cards and public category/navigation metadata from the current page."""
    raw_items = page.evaluate(LISTING_JS)
    deduped: dict[str, dict] = {}
    for raw in raw_items:
        item = parse_listing_item(raw, page_number, source_url)
        if not item["product_url"]:
            continue
        previous = deduped.get(item["product_url"])
        if previous is None or len(item["card_text"]) > len(previous["card_text"]):
            deduped[item["product_url"]] = item
    metadata = page.evaluate(META_JS)
    page_text = metadata.get("page_text", "")
    pagination_text = next(
        (line.strip() for line in page_text.splitlines() if re.search(r"\b\d+\s*/\s*\d+\b", line)),
        None,
    )
    return {
        "page_number": page_number,
        "page_url": page.url,
        "source_url": source_url,
        "captured_at": now_iso(),
        "visible_item_count": len(deduped),
        "pagination_text": pagination_text,
        "page_title": metadata.get("page_title"),
        "category_links": metadata.get("category_links", []),
        "items": list(deduped.values()),
        "page_text": metadata.get("page_text", ""),
    }


def product_fingerprint(page) -> str:
    """Return a fingerprint of the first 30 visible product links."""
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('a[href*=\"/product-detail/\"]'))"
        ".map(a=>a.href).filter(Boolean).slice(0,30).join('|')"
    )
