"""JSON-LD details and provenance-preserving Markdown."""
from __future__ import annotations
import json
import re
from typing import Any
from .listing import PRICE_RE, SOLD_RE

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
