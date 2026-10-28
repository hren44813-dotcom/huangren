"""Import captured supplier product pages into the V13 knowledge base as unverified sources."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.database_v9 import DEFAULT_DB  # noqa: E402
from ecom_images.knowledge_ingest_v13 import import_document, initialize_ingestion  # noqa: E402
from ecom_images.knowledge_schema_v13 import initialize_knowledge  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the source directory, database path, dry-run and import limit."""
    parser = argparse.ArgumentParser(
        description="把供应商商品详情 Markdown 作为 unverified 来源导入 V13；不会自动创建已接受主张。"
    )
    parser.add_argument(
        "--capture-dir",
        type=Path,
        default=ROOT / "data" / "supplier_captures" / "dgdeler" / "details_markdown",
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=0, help="最多导入多少份；0 表示全部。")
    parser.add_argument("--dry-run", action="store_true", help="只列出待导入文件，不修改数据库。")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Import generated Markdown with supplier_document/unverified provenance."""
    args = parse_args(argv)
    try:
        if args.limit < 0:
            raise ValueError("--limit 不能小于 0")
        capture_dir = args.capture_dir.resolve()
        if not capture_dir.is_dir():
            raise FileNotFoundError(f"详情 Markdown 目录不存在：{capture_dir}")
        files = sorted(capture_dir.glob("*.md"))
        if args.limit:
            files = files[:args.limit]
        if not files:
            raise FileNotFoundError(f"目录中没有可导入的 Markdown 文件：{capture_dir}")
        if args.dry_run:
            print(json.dumps({
                "dry_run": True,
                "capture_dir": str(capture_dir),
                "database": str(args.database),
                "files_to_import": len(files),
                "filenames": [path.name for path in files],
                "source_kind": "supplier_document",
                "authority_level": "unverified",
                "creates_accepted_claims": False,
            }, ensure_ascii=False, indent=2))
            return 0
        initialize_knowledge(args.database)
        initialize_ingestion(args.database)
        results = []
        for index, path in enumerate(files, start=1):
            result = import_document(
                args.database,
                file_path=path,
                source_kind="supplier_document",
                authority_level="unverified",
                document_family="DGDeler Alibaba supplier catalog",
                document_number=path.stem,
            )
            results.append({
                "filename": path.name,
                "source_id": result.get("source_id"),
                "run_id": result.get("run_id"),
                "segment_count": result.get("segment_count"),
                "already_indexed": result.get("already_indexed", False),
                "warnings": result.get("warnings", []),
            })
            print(f"[{index}/{len(files)}] {path.name}: {result.get('segment_count', 0)} segments")
        print(json.dumps({
            "ok": True,
            "imported_file_count": len(results),
            "newly_indexed_count": sum(not row["already_indexed"] for row in results),
            "already_indexed_count": sum(row["already_indexed"] for row in results),
            "authority_level": "unverified",
            "creates_accepted_claims": False,
            "results": results,
        }, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"导入供应商资料失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
