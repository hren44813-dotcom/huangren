"""Seed a resumable local capture from the committed, explicitly scoped page-1 snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.supplier_catalog_capture import DEFAULT_URL, parse_listing_item  # noqa: E402

DEFAULT_SNAPSHOT = ROOT / "docs" / "supplier-research" / "dgdeler_product_list_page1_2026-10-28.json"
DEFAULT_OUTPUT = ROOT / "data" / "supplier_captures" / "dgdeler"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从仓库中已记录的第 1 页快照建立可恢复的采集检查点。")
    parser.add_argument("--snapshot-json", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true", help="允许替换 page_001.json 与 catalog.json，不删除其他分页。")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        snapshot = json.loads(args.snapshot_json.read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("items"), list):
            raise ValueError("快照必须包含 items 数组")
        source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
        source_url = str(source.get("url") or source.get("canonical_url") or DEFAULT_URL)
        page_number = 1
        items = []
        for original in snapshot["items"]:
            if not isinstance(original, dict) or not original.get("product_url"):
                continue
            price = str(original.get("price_text") or "")
            moq = original.get("moq_quantity")
            unit = str(original.get("moq_unit") or "")
            parts = [price]
            if moq is not None:
                parts.append(f"Min. order: {moq} {unit}".strip())
            if original.get("sales_count_displayed") is not None:
                parts.append(f"{original['sales_count_displayed']} sold")
            if original.get("delivery_text"):
                parts.append(str(original["delivery_text"]))
            parsed = parse_listing_item({
                "title": original.get("title", ""),
                "url": original["product_url"],
                "card_text": " ".join(parts),
                "image_url": "",
            }, page_number, source_url)
            parsed["captured_at"] = str(original.get("captured_at") or snapshot.get("captured_at") or "2026-10-28")
            parsed["model_hints"] = original.get("models") or parsed.get("model_hints", [])
            parsed["category_guess"] = original.get("category_guess", "")
            parsed["image_asset_label"] = original.get("image_asset_label", "")
            parsed["verification_status"] = "seller_listing_observation_unverified"
            items.append(parsed)
        if not items:
            raise ValueError("快照没有可用的商品链接")
        output = args.output.expanduser().absolute()
        pages_dir = output / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        page_path = pages_dir / "page_001.json"
        catalog_path = output / "catalog.json"
        if not args.force and (page_path.exists() or catalog_path.exists()):
            raise FileExistsError("已有采集数据；如确需重新建立第 1 页检查点，请使用 --force")
        pagination = str(source.get("displayed_pagination") or "1/139")
        page_record = {
            "page_number": 1,
            "page_url": source_url,
            "source_url": source_url,
            "captured_at": str(snapshot.get("captured_at") or "2026-10-28"),
            "visible_item_count": len(items),
            "pagination_text": pagination,
            "page_title": "All products - Dongguan Dele Hardware Technology Co., Ltd.",
            "category_links": [],
            "items": items,
            "page_text": "",
            "seeded_from_committed_snapshot": True,
            "raw_html_saved": False,
        }
        page_path.write_text(json.dumps(page_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        catalog = {
            "schema_version": "1.0",
            "supplier": str(source.get("supplier") or "Dongguan Dele Hardware Technology Co., Ltd."),
            "source_url": source_url,
            "updated_at": str(snapshot.get("captured_at") or "2026-10-28"),
            "captured_page_count": 1,
            "unique_product_count": len(items),
            "items": items,
            "limitations": [
                "This seed contains only the previously captured first-page snapshot.",
                "It is a resume checkpoint, not a claim that the supplier catalog is complete.",
                "All seller listing prices and title claims remain unverified observations.",
            ],
        }
        catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "seeded_items": len(items),
            "page_checkpoint": str(page_path),
            "catalog_path": str(catalog_path),
            "displayed_pagination": pagination,
            "complete_catalog": False,
        }, ensure_ascii=False, indent=2))
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"无法建立采集检查点：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
