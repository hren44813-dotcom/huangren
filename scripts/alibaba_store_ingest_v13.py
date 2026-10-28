"""CLI: crawl public Alibaba storefront pages and ingest source-grounded records into V13."""
from __future__ import annotations
import argparse,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
from ecom_images.alibaba_store_fetch_v13 import DEFAULT_DELAY_SECONDS,DEFAULT_MAX_PAGES,MAX_PAGE_BYTES,STORE_URL
from ecom_images.alibaba_store_v13 import crawl_store
from ecom_images.database_v9 import DEFAULT_DB


def main(argv:list[str]|None=None)->int:
    """Run a bounded storefront crawl and print a concise machine-readable summary."""
    parser=argparse.ArgumentParser(description="阿里国际站公开店铺采集：分类/分页/商品详情，保留来源证据并导入 V13")
    parser.add_argument("--url",default=STORE_URL,help="店铺首页 URL")
    parser.add_argument("--database",type=Path,default=DEFAULT_DB,help="已初始化的 V13 SQLite 数据库")
    parser.add_argument("--output-dir",type=Path,default=ROOT/"data/supplier_captures/alibaba_dgdeler",
                        help="本地原始 HTML 与采集报告目录（已加入 .gitignore）")
    parser.add_argument("--max-pages",type=int,default=DEFAULT_MAX_PAGES,help="最大访问页面数（1-5000）")
    parser.add_argument("--delay",type=float,default=DEFAULT_DELAY_SECONDS,help="请求间隔秒数，最低 0.5 秒")
    parser.add_argument("--timeout",type=float,default=20.0,help="单页请求超时秒数")
    parser.add_argument("--max-page-bytes",type=int,default=MAX_PAGE_BYTES,help="单页 HTML 最大字节数")
    parser.add_argument("--no-seed-known-categories",action="store_true",help="不使用已观察到的分类链接作为初始队列")
    parser.add_argument("--no-import",action="store_true",help="只抓取并生成报告，不写入 V13 数据库")
    args=parser.parse_args(argv)
    try:
        report=crawl_store(database=args.database,output_dir=args.output_dir,start_url=args.url,max_pages=args.max_pages,
            delay_seconds=args.delay,timeout=args.timeout,max_page_bytes=args.max_page_bytes,
            seed_known_categories=not args.no_seed_known_categories,import_to_v13=not args.no_import)
    except (ValueError,RuntimeError,OSError,sqlite3.Error) as exc:
        print(f"阿里国际站采集失败：{exc}",file=sys.stderr); return 1
    print(json.dumps({"ok":not bool(report["failed_pages"]),"attempted_pages":report["attempted_pages"],
        "successful_pages":report["successful_pages"],"blocked_pages":len(report["blocked_pages"]),
        "product_pages":report["product_pages"],"v13_imported_sources":report["v13_imported_sources"],
        "v13_imported_product_reports":report["v13_imported_product_reports"],
        "report_json":str(Path(args.output_dir).absolute()/"crawl_report.json"),
        "report_markdown":str(Path(args.output_dir).absolute()/"crawl_report.md"),
        "products_csv":str(Path(args.output_dir).absolute()/"products.csv")},
        ensure_ascii=False,indent=2))
    return 0 if report["successful_pages"] else 2


if __name__=="__main__": raise SystemExit(main())
