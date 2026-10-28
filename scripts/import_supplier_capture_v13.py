"""Import captured supplier pages and reference snapshots into V13 as unverified sources."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.database_v9 import DEFAULT_DB  # noqa: E402
from ecom_images.catalog_v12 import initialize_catalog  # noqa: E402
from ecom_images.knowledge_ingest_v13 import import_document, initialize_ingestion  # noqa: E402
from ecom_images.knowledge_schema_v13 import initialize_knowledge  # noqa: E402

REFERENCE_SNAPSHOTS = (
    ROOT / "docs" / "supplier-research" / "dgdeler_product_list_page1_2026-10-28.md",
    ROOT / "docs" / "supplier-research" / "dgdeler_supplier_profile_2026-10-28.md",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse capture directory, database path, dry-run and reference snapshot options."""
    parser = argparse.ArgumentParser(
        description="将供应商商品详情和可用参考快照导入 V13；不会自动创建已接受主张。"
    )
    parser.add_argument(
        "--capture-dir", type=Path,
        default=ROOT / "data" / "supplier_captures" / "dgdeler" / "details_markdown",
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=0, help="最多导入多少份；0 表示全部。")
    parser.add_argument("--dry-run", action="store_true", help="只列出待导入文件，不修改数据库。")
    parser.add_argument(
        "--include-reference-snapshots", action="store_true",
        help="额外导入仓库内已提交的商品列表第 1 页和供应商主页摘要快照。",
    )
    return parser.parse_args(argv)


def _extract_source_url(text: str) -> str:
    """Read an explicitly printed source URL from the captured Markdown."""
    patterns = (
        r"(?im)^\s*-\s*商品详情链接：\s*(https?://\S+)",
        r"(?im)^\s*-\s*规范链接：\s*(https?://\S+)",
        r"(?im)^\s*-\s*来源页面：\s*(https?://\S+)",
        r"(?im)^\s*-\s*供应商主页：\s*(https?://\S+)",
        r"(?im)^\s*Source:\s*(https?://\S+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).rstrip(").,;")
    return ""


def _source_metadata(path: Path, text: str) -> tuple[str, str, dict[str, str]]:
    """Return source type, document family and URL-aware provenance metadata."""
    name = path.name.casefold()
    source_url = _extract_source_url(text)
    if "dgdeler_product_list_page1_" in name:
        source_kind = "other"
        family = "DGDeler Alibaba product-list reference snapshot"
        metadata = {
            "page_kind": "product_listing_snapshot",
            "capture_method": "connected_browser_rendered_page_text",
            "raw_html_saved": "false",
            "snapshot_id": "dgdeler_alibaba_product_list_page1_2026-10-28",
        }
    elif "dgdeler_supplier_profile_" in name:
        source_kind = "other"
        family = "DGDeler Alibaba supplier-profile reference snapshot"
        metadata = {
            "page_kind": "supplier_profile_snapshot",
            "capture_method": "browser_visible_page_text",
            "raw_html_saved": "false",
            "snapshot_id": "alibaba_dgdeler_company_overview_2026-10-28",
        }
    else:
        source_kind = "supplier_document"
        family = "DGDeler Alibaba supplier product details"
        metadata = {
            "page_kind": "product_detail_snapshot",
            "capture_method": "visible_browser_dom_and_jsonld",
            "raw_html_saved": "false",
        }
        canonical_match = re.search(r"(?im)^\s*-\s*规范链接：\s*(https?://\S+)", text)
        item_match = re.search(r"(?im)^\s*-\s*记录 ID：\s*(\S+)", text)
        captured_match = re.search(r"(?im)^\s*-\s*采集时间（UTC）：\s*(\S+)", text)
        if canonical_match:
            metadata["canonical_url"] = canonical_match.group(1).rstrip(").,;")
        if item_match:
            metadata["item_id"] = item_match.group(1)
        if captured_match:
            metadata["captured_at_utc"] = captured_match.group(1)
    if source_url:
        metadata["source_url"] = source_url
    return source_kind, family, metadata


def main(argv: list[str] | None = None) -> int:
    """Import generated Markdown with URL provenance and unverified status."""
    args = parse_args(argv)
    try:
        if args.limit < 0:
            raise ValueError("--limit 不能小于 0")
        capture_dir = args.capture_dir.resolve()
        if not capture_dir.is_dir():
            raise FileNotFoundError(f"详情 Markdown 目录不存在：{capture_dir}")
        files = sorted(capture_dir.glob("*.md"))
        if args.include_reference_snapshots:
            files.extend(path for path in REFERENCE_SNAPSHOTS if path.is_file())
        if args.limit:
            files = files[:args.limit]
        if not files:
            raise FileNotFoundError(
                f"没有可导入的 Markdown 文件：{capture_dir}；如需导入仓库现有快照，请加 --include-reference-snapshots"
            )
        plan = []
        for path in files:
            text = path.read_text(encoding="utf-8")
            source_kind, family, metadata = _source_metadata(path, text)
            plan.append({
                "path": path, "text": text, "source_kind": source_kind,
                "document_family": family, "source_metadata": metadata,
            })
        if args.dry_run:
            print(json.dumps({
                "dry_run": True, "capture_dir": str(capture_dir), "database": str(args.database),
                "files_to_import": len(plan),
                "files": [{
                    "filename": row["path"].name, "source_kind": row["source_kind"],
                    "authority_level": "unverified", "source_url": row["source_metadata"].get("source_url", ""),
                    "page_kind": row["source_metadata"].get("page_kind", ""),
                } for row in plan],
                "creates_accepted_claims": False,
            }, ensure_ascii=False, indent=2))
            return 0
        initialize_catalog(args.database)
        initialize_knowledge(args.database)
        initialize_ingestion(args.database)
        results = []
        for index, row in enumerate(plan, start=1):
            path = row["path"]
            result = import_document(
                args.database, file_path=path, source_kind=row["source_kind"],
                authority_level="unverified", document_family=row["document_family"],
                document_number=path.stem, source_metadata=row["source_metadata"],
            )
            results.append({
                "filename": path.name, "source_url": row["source_metadata"].get("source_url", ""),
                "source_id": result.get("source_id"), "run_id": result.get("run_id"),
                "segment_count": result.get("segment_count"),
                "already_indexed": result.get("already_indexed", False), "warnings": result.get("warnings", []),
            })
            print(f"[{index}/{len(plan)}] {path.name}: {result.get('segment_count', 0)} segments")
        print(json.dumps({
            "ok": True, "imported_file_count": len(results),
            "newly_indexed_count": sum(not row["already_indexed"] for row in results),
            "already_indexed_count": sum(row["already_indexed"] for row in results),
            "authority_level": "unverified", "creates_accepted_claims": False, "results": results,
        }, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"导入供应商资料失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
