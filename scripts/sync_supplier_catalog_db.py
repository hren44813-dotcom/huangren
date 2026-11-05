"""Sync captured Alibaba supplier pages into a normalized SQLite database."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.supplier_catalog_db import (  # noqa: E402
    DEFAULT_CAPTURE_DIR, DEFAULT_DB, DEFAULT_SNAPSHOT, audit_supplier_db,
    export_supplier_db, list_supplier_products, sync_supplier_catalog,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="把供应商列表、价格历史、详情属性与 SKU 选项写入独立的 SQLite 观察数据库。"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="导入当前采集目录和已提交的第 1 页快照。")
    sync.add_argument("--capture-dir", type=Path, default=DEFAULT_CAPTURE_DIR)
    sync.add_argument("--snapshot-json", type=Path, default=DEFAULT_SNAPSHOT)
    sync.add_argument("--no-snapshot", action="store_true", help="不合并仓库中的第 1 页快照。")
    sync.add_argument("--database", type=Path, default=DEFAULT_DB)
    sync.add_argument("--dry-run", action="store_true", help="只预览输入数量，不修改数据库。")
    sync.add_argument("--require-complete", action="store_true", help="若采集审计不是 complete，则返回退出码 2。")
    sync.add_argument("--require-details", action="store_true", help="所有目录商品均必须有详情和非空正文。")
    sync.add_argument("--export-dir", type=Path, default=None, help="CSV/审计导出目录，默认在采集目录下 exports/。")

    audit = sub.add_parser("audit", help="检查 SQLite 完整性、外键和数据覆盖。")
    audit.add_argument("--database", type=Path, default=DEFAULT_DB)
    audit.add_argument("--require-complete", action="store_true", help="最新采集批次也必须为 complete。")
    audit.add_argument("--require-details", action="store_true", help="最新批次必须实际执行且完成详情采集。")

    export = sub.add_parser("export", help="导出最新商品表、价格历史、型号提及和规格属性。")
    export.add_argument("--database", type=Path, default=DEFAULT_DB)
    export.add_argument("--output-dir", type=Path, default=DEFAULT_CAPTURE_DIR / "exports")

    search = sub.add_parser("search", help="按商品标题、链接或型号字符串检索。")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--database", type=Path, default=DEFAULT_DB)
    search.add_argument("--limit", type=int, default=100)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "sync":
            summary = sync_supplier_catalog(
                args.database,
                capture_dir=args.capture_dir,
                snapshot_json=None if args.no_snapshot else args.snapshot_json,
                dry_run=args.dry_run,
                require_details=args.require_details,
            )
            if not args.dry_run:
                export_dir = args.export_dir or (args.capture_dir / "exports")
                exports = export_supplier_db(args.database, export_dir)
                summary["exports"] = exports["files"]
                summary["export_dir"] = exports["output_dir"]
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            if args.require_complete and summary.get("status") != "complete":
                return 2
            if not args.dry_run and not summary.get("database_audit", {}).get("ok", False):
                return 3
            return 0
        if args.command == "audit":
            report = audit_supplier_db(args.database)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if not report["ok"]:
                return 3
            latest = report.get("latest_run")
            if args.require_complete and (not latest or latest["status"] != "complete"):
                return 2
            if args.require_details and (
                not latest or latest["status"] != "complete"
                or latest.get("summary", {}).get("detail_audit_status") != "complete"
            ):
                return 2
            return 0
        if args.command == "export":
            result = export_supplier_db(args.database, args.output_dir)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["audit"]["ok"] else 3
        results = list_supplier_products(args.database, query=args.query, limit=args.limit)
        print(json.dumps({"count": len(results), "items": results}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"供应商数据库操作失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
