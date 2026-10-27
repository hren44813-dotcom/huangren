"""Read-only operational reporting for the local huangren SQLite database."""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.db_reporting_v11 import database_summary, job_review_timeline, jobs_csv, list_job_page


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本机 huangren 数据库只读报表；不会修改数据库")
    parser.add_argument("--database", type=Path, default=ROOT / ".local/huangren.sqlite3")
    choices = parser.add_subparsers(dest="action", required=True)
    choices.add_parser("summary", help="汇总任务、模板及审核事件数量")
    jobs = choices.add_parser("jobs", help="分页查询任务，支持输出 CSV")
    jobs.add_argument("--page", type=int, default=1)
    jobs.add_argument("--page-size", type=int, default=25)
    jobs.add_argument("--stage")
    jobs.add_argument("--platform")
    jobs.add_argument("--since", help="YYYY-MM-DD（包含当日）")
    jobs.add_argument("--until", help="YYYY-MM-DD（包含当日）")
    jobs.add_argument("--keyword", help="任务编号或模板名称的一部分")
    jobs.add_argument("--format", choices=["json", "csv"], default="json")
    reviews = choices.add_parser("reviews", help="审核历史的摘要与校验结果")
    reviews.add_argument("job_id", help="完整的 32 位任务编号")
    reviews.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        if args.action == "summary":
            result = database_summary(args.database)
        elif args.action == "jobs":
            result = list_job_page(args.database, page=args.page, page_size=args.page_size,
                                   stage=args.stage, platform=args.platform, since=args.since,
                                   until=args.until, keyword=args.keyword)
            if args.format == "csv":
                sys.stdout.write(jobs_csv(result))
                return 0
        else:
            result = job_review_timeline(args.database, args.job_id, limit=args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, sqlite3.Error, OSError) as exc:
        print(f"只读数据库报表失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())