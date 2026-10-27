"""Chinese CLI for huangren's additive product/SKU catalog (V12)."""
from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.catalog_v12 import (  # noqa: E402
    catalog_audit, catalog_summary, csv_template, import_catalog_csv, initialize_catalog, list_skus,
)
from ecom_images.database_v9 import DEFAULT_DB  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="huangren 工业五金商品 / SKU 数据库管理 V12")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("init", help="在现有V10数据库上增建商品、SKU、素材关联表")
    actions.add_parser("check", help="只读检查商品档案表、外键和记录数量")
    template = actions.add_parser("template", help="输出 UTF-8 CSV 空白填写模板")
    template.add_argument("--output", type=Path, required=True)
    importer = actions.add_parser("import-csv", help="默认只预演；带--apply才正式写入（整批原子提交）")
    importer.add_argument("--input", type=Path, required=True)
    importer.add_argument("--apply", action="store_true")
    listing = actions.add_parser("list-skus", help="只读查看商品SKU")
    listing.add_argument("--store", default="")
    listing.add_argument("--search", default="")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--csv", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "init":
            initialize_catalog(args.database)
            print("商品SKU档案表已初始化；原V10/V11数据未删除")
        elif args.action == "check":
            report = {"summary":catalog_summary(args.database),"audit":catalog_audit(args.database)}
            print(json.dumps(report,ensure_ascii=False,indent=2))
            return 0 if report["summary"]["ok"] and report["audit"]["ok"] else 2
        elif args.action == "template":
            if args.output.exists():
                raise ValueError("模板文件已存在，拒绝覆盖")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(csv_template())
            print(f"空白模板已保存：{args.output}")
        elif args.action == "import-csv":
            data=import_catalog_csv(args.database,args.input.read_bytes(),dry_run=not args.apply)
            print(json.dumps({"mode":"写入" if args.apply else "只预演，未写入正式库",**data},ensure_ascii=False,indent=2))
        elif args.action == "list-skus":
            rows=list_skus(args.database,store_code=args.store,search=args.search,limit=args.limit)
            if args.csv:
                stream=io.StringIO()
                writer=csv.writer(stream)
                writer.writerow(["店铺编码","商品编码","商品名称","SKU编码","型号","参数JSON","sku_id"])
                for row in rows:
                    cells=[row[k] if k!="参数" else json.dumps(row[k],ensure_ascii=False)
                           for k in ("店铺编码","商品编码","商品名称","SKU编码","型号","参数","sku_id")]
                    writer.writerow(["'"+v if isinstance(v,str) and v.lstrip().startswith(("=","+","-","@")) else v for v in cells])
                sys.stdout.write("\ufeff"+stream.getvalue())
            else:
                print(json.dumps(rows,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,RuntimeError,OSError,sqlite3.Error) as exc:
        print(f"数据库操作失败：{exc}",file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
