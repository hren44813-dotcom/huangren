"""Reusable parsing and export helpers for visible Alibaba catalog captures."""
from __future__ import annotations
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
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
LISTING_JS = r"""
() => {
  const clean = value => (value || "").replace(/\s+/g, " ").trim();
  const visible = el => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  };
  return Array.from(document.querySelectorAll('a[href*="/product-detail/"]'))
    .filter(visible).map(a => {
      const title = clean(a.innerText || a.getAttribute("title") || a.getAttribute("aria-label"));
      let node = a, card = null;
      for (let i = 0; i < 9 && node; i++, node = node.parentElement) {
        const text = clean(node.innerText);
        if (text.length >= 20 && text.length <= 1800 &&
            /(?:CN¥|CNY|RMB|¥|US\s*\$|Min\.?\s*order|Min\.?\s*Order)/i.test(text)) {
          card = node; break;
        }
      }
      const image = (card || a).querySelector("img");
      return {title, url:a.href,
        image_url:image ? (image.currentSrc || image.src || image.getAttribute("data-src") || "") : "",
        card_text:clean(card ? card.innerText : a.innerText)};
    }).filter(item => item.url && item.title);
}
"""
META_JS = r"""
() => {
  const clean = value => (value || "").replace(/\s+/g, " ").trim();
  const links = Array.from(document.querySelectorAll("a[href]")).map(a => ({
    label: clean(a.innerText), url: a.href
  })).filter(a => a.label && /productgrouplist|productlist|company_profile|feedback/i.test(a.url));
  return {page_title:document.title, page_url:location.href,
    category_links:links, page_text:document.body ? document.body.innerText : ""};
}
"""
DETAIL_JS = r"""
() => {
  const clean = value => (value || "").replace(/\s+/g, " ").trim();
  const rows = Array.from(document.querySelectorAll("tr")).map(row =>
    Array.from(row.querySelectorAll("th,td")).map(cell => clean(cell.innerText))
  ).filter(row => row.length && row.some(Boolean));
  const definitions = Array.from(document.querySelectorAll("dt")).map(dt => {
    const dd = dt.nextElementSibling;
    return [clean(dt.innerText), clean(dd && dd.innerText)];
  }).filter(row => row[0] || row[1]);
  const images = Array.from(document.querySelectorAll("img"))
    .map(img => img.currentSrc || img.src || img.getAttribute("data-src") || "")
    .filter(src => /^https?:\/\//i.test(src));
  const canonical = document.querySelector('link[rel="canonical"]');
  const ogImage = document.querySelector('meta[property="og:image"]');
  return {title:document.title || "", canonical_url:canonical ? canonical.href : location.href,
    og_image:ogImage ? ogImage.content : "", image_urls:Array.from(new Set(images)),
    table_rows:rows, definition_rows:definitions,
    body_text:document.body ? document.body.innerText : ""};
}
"""


def now_iso() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_url(url: str) -> str:
    """Strip tracking query strings and fragments from a public product URL."""
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
    return {
        "page_number": page_number,
        "page_url": page.url,
        "source_url": source_url,
        "captured_at": now_iso(),
        "visible_item_count": len(deduped),
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


def save_listing_outputs(output: Path) -> dict:
    """Merge page checkpoints and write deduplicated local JSON and CSV exports."""
    pages_dir = output / "pages"
    items_by_url: dict[str, dict] = {}
    page_files = sorted(pages_dir.glob("page_*.json"))
    for path in page_files:
        with path.open(encoding="utf-8") as stream:
            page_data = json.load(stream)
        for item in page_data.get("items", []):
            if item.get("product_url"):
                items_by_url[item["product_url"]] = item
    items = sorted(items_by_url.values(), key=lambda row: (row.get("page_number", 0), row.get("title", "")))
    catalog = {
        "schema_version": "1.0",
        "supplier": "Dongguan Dele Hardware Technology Co., Ltd.",
        "source_url": DEFAULT_URL,
        "updated_at": now_iso(),
        "captured_page_count": len(page_files),
        "unique_product_count": len(items),
        "items": items,
        "limitations": [
            "Only pages actually saved by the visible browser session are included.",
            "Prices and MOQ are listing observations and can vary by options or time.",
            "Seller title claims are not independently verified technical specifications.",
            "A sales count not displayed on a card is null, not zero.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = [
        "page_number", "title", "model_hints", "price_text", "price_min", "price_max",
        "price_currency", "moq_quantity", "moq_unit", "sales_count_displayed",
        "sales_status", "delivery_text", "product_url", "image_url", "verification_status", "captured_at",
    ]
    with (output / "catalog.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            row = dict(item)
            row["model_hints"] = "; ".join(row.get("model_hints", []))
            writer.writerow(row)
    return {"captured_page_count": len(page_files), "unique_product_count": len(items)}
