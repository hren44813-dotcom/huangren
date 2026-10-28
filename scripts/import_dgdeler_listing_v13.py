"""Import each observed DGDeler listing card as an unverified, source-linked V13 document."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.catalog_v12 import initialize_catalog  # noqa: E402
from ecom_images.database_v9 import DEFAULT_DB  # noqa: E402
from ecom_images.knowledge_ingest_v13 import import_document, initialize_ingestion  # noqa: E402
from ecom_images.knowledge_schema_v13 import initialize_knowledge  # noqa: E402

DEFAULT_SNAPSHOT = ROOT / "docs" / "supplier-research" / "dgdeler_product_list_page1_2026-10-28.json"
MISSING = "未在当前商品列表快照中显示；需打开商品详情或 SKU 选项核实"


def _safe_https_url(value: Any, *, product: bool = False) -> str:
    """Accept only HTTPS Alibaba URLs, and product-detail paths for product links."""
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("来源 URL 无效")
    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "alibaba.com" or host.endswith(".alibaba.com")):
        raise ValueError("来源必须是 HTTPS Alibaba 页面")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("来源 URL 包含不允许的凭据或端口")
    if product and not parsed.path.startswith("/product-detail/"):
        raise ValueError("商品链接不是 Alibaba product-detail 页面")
    return value.strip()


def _clean(value: Any) -> str:
    """Normalize a single field for readable evidence markdown."""
    if value is None or value == "":
        return MISSING
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def render_item_markdown(item: dict[str, Any], snapshot: dict[str, Any]) -> str:
    """Render one listing card while keeping unobserved detail fields explicitly missing."""
    source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
    product_url = _safe_https_url(item.get("product_url"), product=True)
    listing_url = _safe_https_url(source.get("url") or source.get("canonical_url"))
    title = _clean(item.get("title"))
    models = item.get("models") if isinstance(item.get("models"), list) else []
    lines = [
        f"# Alibaba 商品列表观察：{title}",
        "",
        f"- 商品详情链接：{product_url}",
        f"- 列表来源页面：{listing_url}",
        f"- 采集日期：{_clean(item.get('captured_at') or snapshot.get('captured_at'))}",
        f"- 商品位置：第 { _clean(item.get('position')) } 个可见卡片",
        "- 证据等级：unverified（供应商页面观察，未独立核验）",
        "- 记录范围：当前列表卡片；并非商品详情页或 SKU 级规格表",
        "",
        "## 列表卡片原文证据",
        "",
        f"- 商品标题原文：{title}",
        f"- 标题中的型号线索：{', '.join(str(x) for x in models) if models else MISSING}",
        f"- 页面显示价格原文：{_clean(item.get('price_text'))}",
        f"- 币种：{_clean(item.get('price_currency') or source.get('displayed_currency'))}",
        f"- 页面显示 MOQ 原文：{_clean(item.get('moq_quantity'))} {_clean(item.get('moq_unit')) if item.get('moq_unit') else ''}".rstrip(),
        f"- 页面显示销量：{_clean(item.get('sales_count_displayed'))}",
        f"- 页面显示交期：{_clean(item.get('delivery_text'))}",
        f"- 列表商品图文件标签：{_clean(item.get('image_asset_label'))}",
        "",
        "## SKU 与技术规格",
        "",
        f"- SKU/变体选项：{MISSING}",
        f"- 材质：{MISSING}",
        f"- 尺寸/孔距/外形：{MISSING}",
        f"- 扭矩/负载/寿命：{MISSING}",
        f"- 表面处理：{MISSING}",
        f"- 包装/单位：{MISSING}",
        f"- 详情页 MOQ 与阶梯数量：{MISSING}",
        "",
        "## 证据边界",
        "",
        "本记录只转录当前列表快照明确展示的文字。标题中的材质、尺寸、功能或型号描述仍是卖家标题声明，不能直接当作已验证规格。列表卡片未显示某字段，不代表商品本身没有该属性。需要访问商品详情、选择具体 SKU/变体并保存对应原文后才能补齐。",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse snapshot path, target V13 database and dry-run option."""
    parser = argparse.ArgumentParser(description="将 DGDeler 商品列表卡片逐个作为未验证来源导入 V13。")
    parser.add_argument("--snapshot-json", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 N 个商品；0 表示全部。")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Import listing-card evidence documents; never create parameter claims."""
    args = parse_args(argv)
    try:
        if args.limit < 0:
            raise ValueError("--limit 不能小于 0")
        snapshot = json.loads(args.snapshot_json.read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("items"), list):
            raise ValueError("快照必须包含 items 数组")
        source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
        listing_url = _safe_https_url(source.get("url") or source.get("canonical_url"))
        items = [item for item in snapshot["items"] if isinstance(item, dict)]
        if args.limit:
            items = items[:args.limit]
        rows = []
        seen = set()
        for item in items:
            product_url = _safe_https_url(item.get("product_url"), product=True)
            if product_url in seen:
                continue
            seen.add(product_url)
            rows.append((item, product_url))
        if not rows:
            raise ValueError("快照中没有有效的唯一商品详情链接")
        if args.dry_run:
            print(json.dumps({
                "dry_run": True, "source_listing_url": listing_url, "snapshot": str(args.snapshot_json),
                "unique_products": len(rows), "authority_level": "unverified",
                "creates_claims": False, "creates_sku_mappings": False,
                "missing_fields": ["SKU/变体", "材质", "尺寸", "扭矩/负载", "表面处理", "详情页 MOQ"],
                "items": [{"title": _clean(item.get("title")), "product_url": url,
                           "model_hints": item.get("models", []), "listing_moq": item.get("moq_quantity"),
                           "listing_moq_unit": item.get("moq_unit")} for item, url in rows],
            }, ensure_ascii=False, indent=2))
            return 0
        initialize_catalog(args.database)
        initialize_knowledge(args.database)
        initialize_ingestion(args.database)
        results = []
        with tempfile.TemporaryDirectory(prefix="dgdeler-v13-listing-") as temp:
            temp_root = Path(temp)
            for index, (item, product_url) in enumerate(rows, start=1):
                item_id = re.sub(r"[^A-Za-z0-9._-]", "_", str(item.get("models", [""])[0] if item.get("models") else "unmodeled"))
                filename = f"{index:03d}_{item_id[:60]}.md"
                file_path = temp_root / filename
                file_path.write_text(render_item_markdown(item, snapshot), encoding="utf-8")
                metadata = {
                    "page_kind": "product_listing_card",
                    "source_url": product_url,
                    "listing_url": listing_url,
                    "captured_at": str(item.get("captured_at") or snapshot.get("captured_at") or ""),
                    "capture_method": str(source.get("capture_method") or "previously_captured_browser_visible_text"),
                    "raw_html_saved": str(bool(source.get("raw_html_saved", False))).lower(),
                    "evidence_status": "seller_listing_observation_unverified",
                    "model_hints": ", ".join(str(x) for x in item.get("models", []) if x)[:1000],
                }
                result = import_document(
                    args.database, file_path=file_path, source_kind="supplier_document",
                    authority_level="unverified", document_family="DGDeler Alibaba product listing card",
                    document_number=product_url, source_metadata=metadata,
                )
                results.append({
                    "title": _clean(item.get("title")), "product_url": product_url,
                    "source_id": result.get("source_id"), "sha256": result.get("sha256"),
                    "segment_count": result.get("segment_count"),
                    "already_indexed": result.get("already_indexed", False),
                })
                print(f"[{index}/{len(rows)}] {item.get('title', product_url)}")
        print(json.dumps({
            "ok": True, "unique_products": len(results),
            "newly_indexed": sum(not row["already_indexed"] for row in results),
            "authority_level": "unverified", "creates_claims": False,
            "creates_sku_mappings": False, "results": results,
        }, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"DGDeler 列表导入 V13 失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
