"""Manage the local SQLite database: migrate, inspect, backup and restore."""
from __future__ import annotations

import argparse
import json
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.database_v9 import (  # noqa: E402
    DEFAULT_DB, backup_database, integrity_report, migrate_legacy, restore_database, open_database,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="huangren SQLite 数据库管理（仅本地元数据）")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB, help="数据库文件位置")
    action = parser.add_subparsers(dest="action", required=True)
    action.add_parser("init", help="显式初始化空数据库（不会导入旧记录）")
    action.add_parser("check", help="只读检查数据库完整性（不存在时返回错误，不自动创建）")
    migration = action.add_parser("import-legacy", help="迁移 V5/V6 JSON（不删除原始文件）")
    migration.add_argument("--jobs", type=Path, default=ROOT / ".local/production_runs")
    migration.add_argument("--templates", type=Path, default=ROOT / ".local/sku_templates")
    migration.add_argument("--dry-run", action="store_true")
    snapshot = action.add_parser("backup", help="一致性备份（不会保存商品原图）")
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.add_argument("--overwrite", action="store_true")
    restore = action.add_parser("restore", help="仅在应用关闭后恢复数据库")
    restore.add_argument("--source", type=Path, required=True)
    restore.add_argument("--overwrite", action="store_true")
    restore.add_argument("--app-stopped", action="store_true", help="确认已关闭所有使用该数据库的应用")
    args = parser.parse_args(argv)
    try:
        if args.action == "init":
            with open_database(args.database):
                pass
            print(f"数据库初始化完成：{args.database}")
            return 0
        if args.action == "check":
            data = integrity_report(args.database)
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0 if data["ok"] else 1
        if args.action == "import-legacy":
            data = migrate_legacy(args.database, job_directory=args.jobs,
                                  template_directory=args.templates, dry_run=args.dry_run)
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0 if not data["errors"] else 2
        if args.action == "backup":
            print(f"备份成功：{backup_database(args.database, args.output, overwrite=args.overwrite)}")
        elif args.action == "restore":
            if not args.app_stopped:
                parser.error("恢复数据库前必须停止应用，并明确传入 --app-stopped")
            print(f"恢复成功：{restore_database(args.source, args.database, overwrite=args.overwrite)}")
        return 0
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"数据库操作失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
