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
  const visible = el => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  };
  const rows = Array.from(document.querySelectorAll("table")).flatMap(table =>
    Array.from(table.querySelectorAll("tr")).map(row =>
      Array.from(row.querySelectorAll("th,td")).map(cell => clean(cell.innerText))
    )
  ).filter(row => row.length && row.some(Boolean));
  const definitions = Array.from(document.querySelectorAll("dt")).map(dt => {
    const dd = dt.nextElementSibling;
    return [clean(dt.innerText), clean(dd && dd.innerText)];
  }).filter(row => row[0] || row[1]);
  const imageDetails = Array.from(document.querySelectorAll("img"))
    .filter(visible).map(img => ({
      url: img.currentSrc || img.src || img.getAttribute("data-src") || "",
      alt: clean(img.getAttribute("alt") || ""),
      title: clean(img.getAttribute("title") || "")
    })).filter(img => /^https?:\/\//i.test(img.url));
  const metaTags = Array.from(document.querySelectorAll("meta[name],meta[property],meta[itemprop]"))
    .map(meta => ({
      key: meta.getAttribute("name") || meta.getAttribute("property") || meta.getAttribute("itemprop") || "",
      value: meta.getAttribute("content") || ""
    })).filter(meta => meta.key && meta.value);
  const jsonLd = [], jsonLdErrors = [];
  Array.from(document.querySelectorAll('script[type="application/ld+json"]')).forEach((script, index) => {
    try { jsonLd.push({script_index:index + 1, data:JSON.parse(script.textContent || "null")}); }
    catch (error) { jsonLdErrors.push({script_index:index + 1, error:String(error)}); }
  });
  const labelFor = el => {
    if (el.id) {
      const label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (label) return clean(label.innerText);
    }
    const parent = el.closest("label");
    if (parent) return clean(parent.innerText);
    return clean(el.getAttribute("aria-label") || el.getAttribute("title") || "");
  };
  const optionGroups = Array.from(document.querySelectorAll("select")).filter(visible).map((el, index) => ({
    kind:"select",
    group:labelFor(el) || clean(el.name || el.getAttribute("aria-label") || ("select_" + (index + 1))),
    options:Array.from(el.options).map(option => ({
      label:clean(option.textContent), value:option.value,
      selected:!!option.selected, disabled:!!option.disabled
    })).filter(option => option.label || option.value)
  }));
  const choiceElements = Array.from(document.querySelectorAll(
    'input[type="radio"],[role="radio"],[role="option"],[data-sku-id],[data-sku-value]'
  )).filter(visible);
  const grouped = new Map();
  choiceElements.forEach((el, index) => {
    const group = clean(el.name || el.closest('[role="radiogroup"]')?.getAttribute("aria-label") ||
      el.closest("[data-sku-property]")?.getAttribute("data-sku-property") ||
      el.closest("fieldset")?.querySelector("legend")?.innerText || "product_option");
    if (!grouped.has(group)) grouped.set(group, []);
    grouped.get(group).push({
      label:labelFor(el) || clean(el.getAttribute("data-value") || el.getAttribute("data-sku-value") ||
        el.getAttribute("aria-label") || el.getAttribute("title") || el.value || el.innerText || ("option_" + (index + 1))),
      value:el.getAttribute("data-sku-value") || el.getAttribute("data-value") || el.value || "",
      selected:el.checked === true || el.getAttribute("aria-checked") === "true" ||
        /\b(selected|active|checked)\b/i.test(String(el.className || "")),
      disabled:el.disabled === true || el.getAttribute("aria-disabled") === "true"
    });
  });
  for (const [group, options] of grouped.entries()) {
    optionGroups.push({kind:"choice", group, options});
  }
  const canonical = document.querySelector('link[rel="canonical"]');
  const ogImage = document.querySelector('meta[property="og:image"]');
  const links = Array.from(document.querySelectorAll("a[href]")).filter(visible).map(a => ({
    label:clean(a.innerText || a.getAttribute("aria-label") || ""),
    url:a.href
  })).filter(link => link.label && /^https?:\/\//i.test(link.url)).slice(0, 300);
  return {
    title:document.title || "",
    canonical_url:canonical ? canonical.href : location.href,
    og_image:ogImage ? ogImage.content : "",
    image_urls:Array.from(new Set(imageDetails.map(img => img.url))),
    image_details:imageDetails,
    table_rows:rows,
    definition_rows:definitions,
    meta_tags:metaTags,
    json_ld:jsonLd,
    json_ld_errors:jsonLdErrors,
    option_groups:optionGroups,
    links:links,
    body_text:document.body ? document.body.innerText : ""
  };
}
"""


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



DETAIL_MOQ_RE = re.compile(
    r"(?:MOQ|minimum order(?: quantity)?|min\.?\s*order)\s*[:：]?\s*"
    r"([0-9][0-9,]*)\s*(pieces?|pcs?|sets?|pairs?|units?|boxes?|lots?)?",
    re.IGNORECASE,
)


def _clean_text(value: Any) -> str:
    """Normalize a source value to compact plain text without inventing missing values."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return re.sub(r"\s+", " ", str(value)).strip()


def _walk_jsonld(value: Any):
    """Yield JSON-LD objects recursively so Product nodes work with arrays and @graph."""
    if isinstance(value, list):
        for child in value:
            yield from _walk_jsonld(child)
    elif isinstance(value, dict):
        yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from _walk_jsonld(child)


def _schema_type_names(node: dict) -> set[str]:
    """Return normalized Schema.org type names from a JSON-LD object."""
    value = node.get("@type", [])
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return set()
    return {str(item).rsplit("/", 1)[-1].lower() for item in value}


def _schema_product(node: dict) -> dict:
    """Extract common Schema.org product fields while preserving seller-claim status."""
    offers = node.get("offers", [])
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        offers = []
    offer = next((item for item in offers if isinstance(item, dict)), {})
    brand = node.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name") or brand.get("legalName")
    images = node.get("image", [])
    if isinstance(images, str):
        images = [images]
    if not isinstance(images, list):
        images = []
    additional = node.get("additionalProperty", [])
    if isinstance(additional, dict):
        additional = [additional]
    if not isinstance(additional, list):
        additional = []
    variants = node.get("hasVariant", [])
    if isinstance(variants, dict):
        variants = [variants]
    return {
        "name": _clean_text(node.get("name")),
        "sku": _clean_text(node.get("sku")),
        "mpn": _clean_text(node.get("mpn")),
        "brand": _clean_text(brand),
        "category": _clean_text(node.get("category")),
        "description": _clean_text(node.get("description")),
        "url": _clean_text(node.get("url")),
        "images": [_clean_text(item) for item in images if _clean_text(item)],
        "price": _clean_text(offer.get("price") or offer.get("lowPrice")),
        "price_high": _clean_text(offer.get("highPrice")),
        "price_currency": _clean_text(offer.get("priceCurrency")),
        "availability": _clean_text(offer.get("availability")),
        "seller": _clean_text(offer.get("seller")),
        "offers_count": len(offers),
        "variants_count": len(variants),
        "varies_by": node.get("variesBy", []) if isinstance(node.get("variesBy", []), list) else [],
        "additional_properties": [
            {
                "name": _clean_text(item.get("name")),
                "value": _clean_text(item.get("value") or item.get("valueReference")),
            }
            for item in additional if isinstance(item, dict) and
            (_clean_text(item.get("name")) or _clean_text(item.get("value")))
        ],
        "source_type": "seller_page_json_ld_unverified",
    }


def _extract_attribute_pairs(detail_page: dict) -> list[dict]:
    """Flatten visible table, definition-list and JSON-LD property pairs with locators."""
    pairs: list[dict] = []
    for row_no, raw_row in enumerate(detail_page.get("table_rows", []), start=1):
        cells = raw_row.get("cells", []) if isinstance(raw_row, dict) else raw_row
        if not isinstance(cells, list):
            continue
        cells = [_clean_text(cell) for cell in cells]
        cells = [cell for cell in cells if cell]
        if len(cells) < 2:
            continue
        candidates = list(zip(cells[0::2], cells[1::2])) if len(cells) >= 4 and len(cells) % 2 == 0 else [
            (cells[0], " | ".join(cells[1:]))
        ]
        for key, value in candidates:
            if key and value:
                pairs.append({"key": key, "value": value, "source_locator": f"table_row_{row_no}"})
    for row_no, row in enumerate(detail_page.get("definition_rows", []), start=1):
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            key, value = _clean_text(row[0]), _clean_text(row[1])
            if key and value:
                pairs.append({"key": key, "value": value, "source_locator": f"definition_row_{row_no}"})
    for product_no, product in enumerate(detail_page.get("structured_products", []), start=1):
        for prop_no, prop in enumerate(product.get("additional_properties", []), start=1):
            key, value = _clean_text(prop.get("name")), _clean_text(prop.get("value"))
            if key and value:
                pairs.append({
                    "key": key, "value": value,
                    "source_locator": f"json_ld_product_{product_no}_property_{prop_no}",
                })
    return pairs


def enrich_detail_payload(detail_page: dict, body_text: str) -> dict:
    """Add searchable product fields and quality flags without upgrading seller claims to facts."""
    detail = dict(detail_page)
    jsonld_nodes = []
    for entry in detail.get("json_ld", []):
        if isinstance(entry, dict) and "data" in entry:
            jsonld_nodes.extend(_walk_jsonld(entry.get("data")))
        else:
            jsonld_nodes.extend(_walk_jsonld(entry))
    product_nodes = []
    seen_products = set()
    for node in jsonld_nodes:
        types = _schema_type_names(node)
        if not types.intersection({"product", "productgroup", "individualproduct"}):
            continue
        product = _schema_product(node)
        identity = (product.get("url"), product.get("sku"), product.get("name"))
        if identity not in seen_products:
            seen_products.add(identity)
            product_nodes.append(product)
    detail["structured_products"] = product_nodes
    detail["structured_product"] = product_nodes[0] if product_nodes else {}
    detail["attribute_pairs"] = _extract_attribute_pairs(detail)

    price_candidates = []
    for match in PRICE_RE.finditer(body_text or ""):
        prefix = (body_text or "")[match.start():match.start(1)].strip().upper()
        currency = "USD" if "$" in prefix else (
            "CNY" if any(token in prefix for token in ("CN¥", "CNY", "RMB", "¥")) else None
        )
        price_candidates.append({
            "text": match.group(0),
            "price_min": float(match.group(1).replace(",", "")),
            "price_max": float(match.group(2).replace(",", "")) if match.group(2) else float(match.group(1).replace(",", "")),
            "currency": currency,
        })
    detail["visible_price_candidates"] = price_candidates[:100]
    moq_match = DETAIL_MOQ_RE.search(body_text or "")
    detail["visible_moq"] = ({
        "quantity": int(moq_match.group(1).replace(",", "")),
        "unit": (moq_match.group(2) or "").lower(),
        "text": moq_match.group(0),
    } if moq_match else None)
    sold_match = SOLD_RE.search(body_text or "")
    detail["visible_sales_count"] = int(sold_match.group(1).replace(",", "")) if sold_match else None
    detail["body_text_chars"] = len(body_text or "")
    detail["detail_quality"] = {
        "has_page_title": bool(detail.get("title")),
        "has_body_text": bool((body_text or "").strip()),
        "has_table_rows": bool(detail.get("table_rows")),
        "has_attribute_pairs": bool(detail.get("attribute_pairs")),
        "has_json_ld_product": bool(product_nodes),
        "has_option_groups": bool(detail.get("option_groups")),
        "has_product_images": bool(detail.get("image_urls")),
        "json_ld_parse_errors": len(detail.get("json_ld_errors", [])),
        "status": "captured_unverified",
    }
    return detail


def _md_escape(value: Any) -> str:
    """Escape source values for a generated Markdown table cell."""
    return _clean_text(value).replace("|", r"\|").replace("\n", " ")


def render_detail_markdown(record: dict, body_text: str) -> str:
    """Render a source-attributed, explicitly unverified Markdown document for V13 ingestion."""
    detail = record.get("detail_page", {})
    structured = detail.get("structured_product", {})
    title = _clean_text(record.get("listing_title") or detail.get("title") or "未命名商品")
    lines = [
        f"# 阿里巴巴商品详情：{title}",
        "",
        "> 来源页面采集记录。以下内容为供应商页面展示信息，未经独立验证；不会自动创建已接受的技术参数主张。",
        "",
        f"- 商品列表标题：{_clean_text(record.get('listing_title'))}",
        f"- 商品详情链接：{_clean_text(record.get('detail_url') or record.get('listing_url'))}",
        f"- 规范链接：{_clean_text(detail.get('canonical_url'))}",
        f"- 采集时间（UTC）：{_clean_text(record.get('captured_at'))}",
        f"- 记录 ID：{_clean_text(record.get('item_id'))}",
        f"- 数据状态：{_clean_text(record.get('verification_status') or 'visible_detail_page_observation_unverified')}",
        "",
        "## 页面结构化商品字段",
        "",
        "| 字段 | 页面值 |",
        "|---|---|",
    ]
    field_labels = [
        ("name", "商品名称"), ("sku", "SKU"), ("mpn", "MPN"),
        ("brand", "品牌"), ("category", "分类"), ("description", "描述"),
        ("price", "结构化价格"), ("price_high", "结构化最高价"),
        ("price_currency", "币种"), ("availability", "库存状态"),
        ("seller", "卖家字段"), ("url", "结构化链接"),
    ]
    for key, label in field_labels:
        value = structured.get(key)
        if value:
            lines.append(f"| {label} | {_md_escape(value)} |")
    lines.extend(["", "## 页面规格/属性", ""])
    attributes = detail.get("attribute_pairs", [])
    if attributes:
        lines.extend(["| 字段 | 页面值 | 定位 |", "|---|---|---|"])
        for pair in attributes:
            lines.append(
                f"| {_md_escape(pair.get('key'))} | {_md_escape(pair.get('value'))} | "
                f"{_md_escape(pair.get('source_locator'))} |"
            )
    else:
        lines.append("未从可见表格或结构化属性中提取到键值对；请查看下面的原始页面文本。")
    lines.extend(["", "## SKU/选项", ""])
    option_groups = detail.get("option_groups", [])
    if option_groups:
        for group in option_groups:
            lines.append(f"### {_clean_text(group.get('group') or group.get('kind') or '选项')}")
            for option in group.get("options", []):
                selected = "（当前选中）" if option.get("selected") else ""
                disabled = "（不可选）" if option.get("disabled") else ""
                lines.append(f"- {_clean_text(option.get('label') or option.get('value'))}{selected}{disabled}")
    else:
        lines.append("页面未检测到可见的 SKU 选项控件。")
    lines.extend(["", "## 页面可见原文", ""])
    fence = chr(96) * 4
    while fence in (body_text or ""):
        fence += chr(96)
    lines.extend([fence + "text", body_text or "（页面未返回可见正文）", fence, ""])
    return "\n".join(lines)


def build_listing_audit(output: Path) -> dict:
    """Check captured page coverage, pagination consistency, duplicate URLs and invalid checkpoints."""
    pages_dir = output / "pages"
    page_paths = sorted(pages_dir.glob("page_*.json")) if pages_dir.exists() else []
    page_records = []
    invalid_files = []
    for path in page_paths:
        match = re.fullmatch(r"page_(\d+)\.json", path.name)
        file_number = int(match.group(1)) if match else None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("page record must be an object")
            data["_file_page_number"] = file_number
            page_records.append(data)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            invalid_files.append({"file": path.name, "error": str(exc)})
    captured_numbers = sorted({
        int(record.get("_file_page_number"))
        for record in page_records if isinstance(record.get("_file_page_number"), int)
    })
    totals = []
    page_mismatches = []
    empty_pages = []
    all_urls = []
    for record in page_records:
        file_number = record.get("_file_page_number")
        page_number = record.get("page_number")
        if isinstance(file_number, int) and isinstance(page_number, int) and file_number != page_number:
            page_mismatches.append({"file_page": file_number, "record_page": page_number})
        pagination = str(record.get("pagination_text") or "")
        match = re.search(r"(\d+)\s*/\s*(\d+)", pagination)
        if match:
            totals.append(int(match.group(2)))
            if isinstance(file_number, int) and int(match.group(1)) != file_number:
                page_mismatches.append({
                    "file_page": file_number, "pagination_page": int(match.group(1)),
                    "pagination_text": pagination,
                })
        items = record.get("items", [])
        if not items:
            empty_pages.append(file_number)
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and item.get("product_url"):
                all_urls.append(item["product_url"])
    expected_pages = max(totals) if totals else (max(captured_numbers) if captured_numbers else None)
    captured_set = set(captured_numbers)
    missing_pages = (
        [number for number in range(1, expected_pages + 1) if number not in captured_set]
        if expected_pages else []
    )
    duplicate_occurrences = len(all_urls) - len(set(all_urls))
    complete = bool(expected_pages and not missing_pages and not invalid_files and not page_mismatches and not empty_pages)
    audit = {
        "checked_at": now_iso(),
        "expected_page_count": expected_pages,
        "captured_page_count": len(captured_numbers),
        "captured_page_numbers": captured_numbers,
        "missing_page_numbers": missing_pages,
        "invalid_page_files": invalid_files,
        "pagination_mismatches": page_mismatches,
        "pages_with_no_visible_products": empty_pages,
        "listing_item_occurrences": len(all_urls),
        "unique_product_count": len(set(all_urls)),
        "duplicate_product_occurrences": duplicate_occurrences,
        "is_complete": complete,
        "status": "complete" if complete else ("partial" if page_records else "not_started"),
        "limitations": [
            "Completeness is measured against the pagination total visible in captured pages.",
            "A captured page with zero visible product cards requires manual review.",
            "Listing fields remain timestamped seller-page observations, not verified specifications.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "catalog_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit


def write_detail_exports(output: Path) -> dict:
    """Export detail index/attribute CSVs, V13-ready Markdown, and an honest coverage audit."""
    output = output.resolve()
    catalog_path = output / "catalog.json"
    if not catalog_path.exists():
        raise FileNotFoundError(f"未找到商品目录：{catalog_path}；请先运行 listing 子命令。")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    items = catalog.get("items", [])
    details_dir = output / "details"
    markdown_dir = output / "details_markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)
    detail_files = sorted(details_dir.glob("*.json")) if details_dir.exists() else []
    records_by_id = {}
    invalid_files = []
    for path in detail_files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or not record.get("item_id"):
                raise ValueError("detail record missing item_id")
            records_by_id[str(record["item_id"])] = (path, record)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            invalid_files.append({"file": path.name, "error": str(exc)})
    index_rows = []
    attribute_rows = []
    catalog_ids = set()
    for item in items:
        item_id = str(item.get("item_id") or hashlib.sha256(str(item.get("product_url", "")).encode()).hexdigest()[:16])
        catalog_ids.add(item_id)
        entry = records_by_id.get(item_id)
        if not entry:
            continue
        detail_path, record = entry
        detail_page = record.get("detail_page") if isinstance(record.get("detail_page"), dict) else {}
        text_name = Path(str(detail_page.get("body_text_file") or f"{item_id}.txt")).name
        text_path = details_dir / text_name
        try:
            body_text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
        except OSError:
            body_text = ""
        enriched = enrich_detail_payload(detail_page, body_text)
        enriched["body_text_file"] = text_name
        record["detail_page"] = enriched
        detail_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path = markdown_dir / f"{item_id}.md"
        md_path.write_text(render_detail_markdown(record, body_text), encoding="utf-8")
        product = enriched.get("structured_product", {})
        prices = enriched.get("visible_price_candidates", [])
        options = enriched.get("option_groups", [])
        index_rows.append({
            "item_id": item_id,
            "listing_title": item.get("title"),
            "product_url": item.get("product_url"),
            "detail_title": enriched.get("title"),
            "canonical_url": enriched.get("canonical_url"),
            "schema_name": product.get("name"),
            "schema_sku": product.get("sku"),
            "schema_mpn": product.get("mpn"),
            "schema_brand": product.get("brand"),
            "schema_category": product.get("category"),
            "schema_price": product.get("price"),
            "schema_price_high": product.get("price_high"),
            "schema_currency": product.get("price_currency"),
            "schema_availability": product.get("availability"),
            "visible_price_candidates": json.dumps(prices, ensure_ascii=False),
            "visible_moq": json.dumps(enriched.get("visible_moq"), ensure_ascii=False),
            "visible_sales_count": enriched.get("visible_sales_count"),
            "image_count": len(enriched.get("image_urls", [])),
            "attribute_count": len(enriched.get("attribute_pairs", [])),
            "option_group_count": len(options),
            "body_text_chars": len(body_text),
            "verification_status": record.get("verification_status", "visible_detail_page_observation_unverified"),
            "captured_at": record.get("captured_at"),
            "detail_file": str(detail_path.relative_to(output)),
            "markdown_file": str(md_path.relative_to(output)),
            "text_file": str(text_path.relative_to(output)) if text_path.exists() else "",
        })
        for pair in enriched.get("attribute_pairs", []):
            attribute_rows.append({
                "item_id": item_id,
                "listing_title": item.get("title"),
                "product_url": item.get("product_url"),
                "attribute": pair.get("key"),
                "value": pair.get("value"),
                "source_locator": pair.get("source_locator"),
                "verification_status": "seller_page_observation_unverified",
            })
    index_columns = [
        "item_id", "listing_title", "product_url", "detail_title", "canonical_url",
        "schema_name", "schema_sku", "schema_mpn", "schema_brand", "schema_category",
        "schema_price", "schema_price_high", "schema_currency", "schema_availability",
        "visible_price_candidates", "visible_moq", "visible_sales_count", "image_count",
        "attribute_count", "option_group_count", "body_text_chars", "verification_status",
        "captured_at", "detail_file", "markdown_file", "text_file",
    ]
    with (output / "details_index.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=index_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(index_rows)
    attribute_columns = [
        "item_id", "listing_title", "product_url", "attribute", "value",
        "source_locator", "verification_status",
    ]
    with (output / "detail_attributes.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=attribute_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(attribute_rows)
    missing_ids = sorted(catalog_ids - set(records_by_id))
    orphan_ids = sorted(set(records_by_id) - catalog_ids)
    text_missing = [
        row["item_id"] for row in index_rows
        if not row["text_file"] or not row["body_text_chars"]
    ]
    audit = {
        "checked_at": now_iso(),
        "expected_product_count": len(items),
        "valid_detail_count": len(index_rows),
        "missing_detail_count": len(missing_ids),
        "missing_item_ids": missing_ids,
        "orphan_detail_item_ids": orphan_ids,
        "invalid_detail_files": invalid_files,
        "missing_body_text_item_ids": text_missing,
        "markdown_documents_written": len(index_rows),
        "attribute_rows_written": len(attribute_rows),
        "is_complete": bool(items) and not missing_ids and not orphan_ids and not invalid_files and not text_missing,
        "status": "complete" if items and not missing_ids and not orphan_ids and not invalid_files and not text_missing else (
            "partial" if index_rows or items else "not_started"
        ),
        "limitations": [
            "Detail extraction records page-visible content and structured metadata only.",
            "Price options, hidden tabs, login-gated data, and dynamic fields may be absent.",
            "All supplier-page technical claims remain unverified until reviewed against authoritative evidence.",
        ],
    }
    (output / "details_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit

def save_listing_outputs(output: Path) -> dict:
    """Merge page checkpoints and write deduplicated local JSON and CSV exports."""
    pages_dir = output / "pages"
    items_by_url: dict[str, dict] = {}
    page_files = sorted(pages_dir.glob("page_*.json"))
    source_url = DEFAULT_URL
    for path in page_files:
        with path.open(encoding="utf-8") as stream:
            page_data = json.load(stream)
        source_url = page_data.get("source_url") or source_url
        for item in page_data.get("items", []):
            if item.get("product_url"):
                items_by_url[item["product_url"]] = item
    items = sorted(items_by_url.values(), key=lambda row: (row.get("page_number", 0), row.get("title", "")))
    catalog = {
        "schema_version": "1.0",
        "supplier": "Dongguan Dele Hardware Technology Co., Ltd.",
        "source_url": source_url,
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
    audit = build_listing_audit(output)
    return {
        "captured_page_count": len(page_files),
        "unique_product_count": len(items),
        "audit_status": audit["status"],
        "missing_page_count": len(audit["missing_page_numbers"]),
    }
