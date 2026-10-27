"""Local SQLite V10 metadata inspection and bounded, read-only operational reports.

Never creates or modifies a database. No customer photos or API keys are read.
This module is a convenience reporting layer, not authentication/authorization.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

SUPPORTED_VERSIONS = {1, 2}
JOB_COLUMNS = ("id", "created_utc", "updated_utc", "platform", "template", "generated", "failed_generation", "stage", "revision")
REQUIRED_TABLES = {"jobs", "job_files", "review_events", "templates", "imported_files"}
IDENTIFIER = re.compile(r"^[a-f0-9]{32}$")
DIGEST = re.compile(r"^[a-f0-9]{64}$")
MAX_PAGE = 100


def _safe_path(path: str | Path) -> Path:
    target = Path(path).expanduser().absolute()
    if target.is_symlink() or any(p.is_symlink() for p in target.parents):
        raise ValueError("数据库路径不能包含符号链接")
    if not target.is_file():
        raise ValueError("数据库不存在或不是普通文件；查询不会创建数据库")
    return target


@contextmanager
def _readonly(path: str | Path) -> Iterator[sqlite3.Connection]:
    target = _safe_path(path)
    try:
        connection = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        raise ValueError("无法以只读方式打开数据库") from exc
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in SUPPORTED_VERSIONS:
            raise ValueError(f"不支持的数据库结构版本：{version}；不会修改源文件")
        tables = {r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if not REQUIRED_TABLES.issubset(tables):
            raise ValueError("缺少必要业务表，拒绝查询不兼容的数据库")
        # Reject a forged table layout rather than discovering schema errors
        # after partially generating a report.
        expected = {
            "jobs": {*JOB_COLUMNS, "input_sha256", "record_json"},
            "job_files": {"job_id", "name", "sha256"},
            "review_events": {"event_id", "job_id", "created_utc", "reviewer", "report_sha256", "review_json"},
            "templates": {"name", "name_key", "layout_json", "layout_sha256"},
            "imported_files": {"origin", "kind", "sha256"},
        }
        for table, needed in expected.items():
            fields = {r[1] for r in connection.execute(f"PRAGMA table_info({table})")}
            if not needed.issubset(fields):
                raise ValueError(f"数据库表结构不兼容：{table}")
        yield connection
    except sqlite3.DatabaseError as exc:
        raise ValueError("数据库查询失败，请先运行数据库完整性检查") from exc
    finally:
        connection.close()


def _positive_int(value: int, maximum: int, label: str, *, allow_zero: bool = False) -> int:
    if type(value) is not int or not (0 if allow_zero else 1) <= value <= maximum:
        raise ValueError(f"{label}必须为合法整数，最大 {maximum}")
    return value


def _date(value: str | None, label: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{label}需要 YYYY-MM-DD 格式")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{label}不是有效日期") from exc
    return value


def _job_filters(*, stage: str | None, platform: str | None, since: str | None,
                 until: str | None, keyword: str | None) -> tuple[str, list[str]]:
    conditions = []
    params: list[str] = []
    for field, value, label in (("stage", stage, "阶段"), ("platform", platform, "平台")):
        if value is not None:
            if not isinstance(value, str) or not value.strip() or len(value) > 100:
                raise ValueError(f"{label}筛选值不合法")
            conditions.append(f"{field}=?")
            params.append(value.strip())
    lo, hi = _date(since, "开始日期"), _date(until, "结束日期")
    if lo and hi and lo > hi:
        raise ValueError("开始日期不能晚于结束日期")
    if lo:
        conditions.append("created_utc >= ?")
        params.append(lo)
    if hi:
        conditions.append("created_utc < ?")
        # Date-only comparison: lexical ISO timestamps are later than YYYY-MM-DD.
        # Using the next day allows all hours of the requested end day.
        from datetime import date, timedelta
        from datetime import datetime as dt
        try:
            tomorrow = date.fromisoformat(hi) + timedelta(days=1)
        except OverflowError as exc:
            raise ValueError("结束日期超出支持范围") from exc
        conditions[-1] = "created_utc < ?"
        params.append(tomorrow.isoformat())
    if keyword is not None:
        if not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 100:
            raise ValueError("关键词最多 100 字")
        # Literal substring match: '%' and '_' must not act as wildcards.
        escaped = keyword.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append("(id LIKE ? ESCAPE '\\' OR template LIKE ? ESCAPE '\\')")
        params.extend([f"%{escaped}%", f"%{escaped}%"])
    return (" WHERE " + " AND ".join(conditions)) if conditions else "", params


def list_job_page(path: str | Path, *, page: int = 1, page_size: int = 25,
                  stage: str | None = None, platform: str | None = None,
                  since: str | None = None, until: str | None = None,
                  keyword: str | None = None) -> dict[str, Any]:
    """Stable page of historical jobs; explicitly bounded to prevent memory-heavy dumps."""
    _positive_int(page, 1_000_000, "页码")
    _positive_int(page_size, MAX_PAGE, "每页数量")
    where, params = _job_filters(stage=stage, platform=platform, since=since,
                                 until=until, keyword=keyword)
    with _readonly(path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM jobs" + where, params).fetchone()[0]
        query = f"SELECT {', '.join(JOB_COLUMNS)} FROM jobs{where} ORDER BY created_utc DESC,id DESC LIMIT ? OFFSET ?"
        rows = conn.execute(query, [*params, page_size, (page - 1) * page_size]).fetchall()
    return {"total": total, "page": page, "page_size": page_size,
            "rows": [dict(r) for r in rows]}


def database_summary(path: str | Path) -> dict[str, Any]:
    """Operational inventory, not an integrity audit or approval of any product."""
    with _readonly(path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        totals = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in sorted(REQUIRED_TABLES)}
        by_stage = [dict(r) for r in conn.execute(
            "SELECT stage,COUNT(*) AS count FROM jobs GROUP BY stage ORDER BY count DESC,stage"
        ).fetchall()]
        by_platform = [dict(r) for r in conn.execute(
            "SELECT platform,COUNT(*) AS count FROM jobs GROUP BY platform ORDER BY count DESC,platform"
        ).fetchall()]
        last = conn.execute("SELECT MAX(updated_utc) FROM jobs").fetchone()[0]
        orphan_images = conn.execute("""SELECT count(*) FROM job_files AS f
            LEFT JOIN jobs AS j ON j.id=f.job_id WHERE j.id IS NULL""").fetchone()[0]
        orphan_reviews = conn.execute("""SELECT count(*) FROM review_events AS e
            LEFT JOIN jobs AS j ON j.id=e.job_id WHERE j.id IS NULL""").fetchone()[0]
        return {"schema_version": version, "totals": totals, "by_stage": by_stage,
                "by_platform": by_platform, "last_job_update_utc": last,
                "orphan_job_files": orphan_images, "orphan_review_events": orphan_reviews,
                "note": "数量统计不等于完整性或商品真实性验收，请另运行 db_admin.py check"}


def job_review_timeline(path: str | Path, job_id: str, *, limit: int = 100) -> dict[str, Any]:
    """Verify returned review digests; return only metadata, never private review text."""
    if not isinstance(job_id, str) or not IDENTIFIER.fullmatch(job_id):
        raise ValueError("请填写完整 32 位任务编号")
    _positive_int(limit, MAX_PAGE, "历史条数")
    with _readonly(path) as conn:
        job = conn.execute("SELECT id,stage,revision,generated FROM jobs WHERE id=?", (job_id,)).fetchone()
        if job is None:
            raise ValueError("找不到该任务编号")
        events = conn.execute("""SELECT event_id,created_utc,reviewer,report_sha256,review_json
            FROM review_events WHERE job_id=? ORDER BY event_id DESC LIMIT ?""", (job_id, limit)).fetchall()
        timeline = []
        for row in events:
            digest = hashlib.sha256(row["review_json"].encode("utf-8")).hexdigest()
            timeline.append({"event_id": row["event_id"], "reviewed_utc": row["created_utc"],
                             "reviewer": row["reviewer"], "sha256": row["report_sha256"],
                             "checksum_ok": digest == row["report_sha256"] and bool(DIGEST.fullmatch(digest))})
    return {"job": dict(job), "events": timeline}


def jobs_csv(report: dict[str, Any]) -> str:
    """UTF-8 BOM CSV compatible with Excel, including formula injection protection."""
    rows = report.get("rows")
    if not isinstance(rows, list) or len(rows) > MAX_PAGE:
        raise ValueError("一次最多导出 100 行；请逐页导出")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=JOB_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("报告行格式无效")
        def safe(value: Any) -> str:
            cell = str(value) if value is not None else ""
            if cell.lstrip().startswith(("=", "+", "-", "@")):
                return "'" + cell
            return cell
        writer.writerow({name: safe(row.get(name)) for name in JOB_COLUMNS})
    return "\ufeff" + stream.getvalue()