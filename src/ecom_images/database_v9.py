"""V9 local SQLite metadata store (no product pixels or API credentials).

JSON V5/V6 files are *not* deleted; they can be imported explicitly and safely.
The schema uses transactional SQLite storage with file hashes and append-only
review history, not an identity/permission system or tamper-proof audit log.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .sku_layout_v4 import layout_from_json, layout_json
from .template_library_v5 import MAX_TEMPLATES, template_name

DB_VERSION = 1
MAX_RECORD_BYTES = 256_000
HASH = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[0-9a-f]{32}$")
DEFAULT_DB = Path(__file__).resolve().parents[2] / ".local" / "huangren.sqlite3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_path(path: str | Path) -> Path:
    target = Path(path).expanduser().absolute()
    # Check every existing ancestor, not only the immediate parent; a nested
    # symlink could otherwise redirect the database outside the intended folder.
    if target.is_symlink() or any(parent.is_symlink() for parent in (target.parent, *target.parent.parents)):
        raise ValueError("数据库文件路径及其父目录不能包含符号链接")
    return target


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


@contextmanager
def open_database(path: str | Path = DEFAULT_DB) -> Iterator[sqlite3.Connection]:
    """Open, migrate schema and close connection; each data write is a transaction."""
    target = _check_path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(str(target), timeout=12, isolation_level=None)
    try:
        if os.name == "posix":
            os.chmod(target, 0o600)
        conn.execute("PRAGMA busy_timeout=12000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > DB_VERSION:
            raise RuntimeError(f"数据库版本 {version} 高于程序支持的 {DB_VERSION}，拒绝写入")
        if version == 0:
            try:
                conn.executescript("""BEGIN IMMEDIATE;

                    CREATE TABLE IF NOT EXISTS jobs (
                      id TEXT PRIMARY KEY, created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL,
                      platform TEXT NOT NULL, template TEXT NOT NULL, input_sha256 TEXT NOT NULL,
                      generated INTEGER NOT NULL, failed_generation INTEGER NOT NULL,
                      stage TEXT NOT NULL, record_json TEXT NOT NULL,
                      revision INTEGER NOT NULL DEFAULT 1
                    );
                    CREATE TABLE IF NOT EXISTS job_files (
                      job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
                      name TEXT NOT NULL, sha256 TEXT NOT NULL,
                      PRIMARY KEY(job_id, name)
                    );
                    CREATE TABLE IF NOT EXISTS review_events (
                      event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
                      created_utc TEXT NOT NULL, reviewer TEXT NOT NULL,
                      report_sha256 TEXT NOT NULL, review_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_review_job ON review_events(job_id,event_id);
                    CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_utc DESC,id);
                    CREATE TABLE IF NOT EXISTS templates (
                      name_key TEXT PRIMARY KEY, name TEXT NOT NULL,
                      layout_json TEXT NOT NULL, layout_sha256 TEXT NOT NULL,
                      updated_utc TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS imported_files (
                      origin TEXT PRIMARY KEY, kind TEXT NOT NULL,
                      sha256 TEXT NOT NULL, imported_utc TEXT NOT NULL
                    );
                    PRAGMA user_version=1;
                    COMMIT;
                """)
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        # Fail closed on pre-existing non-DB files or incompatible schemas.
        conn.execute("SELECT id FROM jobs LIMIT 0")
        yield conn
    finally:
        conn.close()


def _validate_job(record: dict[str, Any]) -> tuple[str, list[tuple[str, str]]]:
    if not isinstance(record, dict):
        raise ValueError("任务记录必须是对象")
    identifier = record.get("id")
    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        raise ValueError("任务编号无效")
    if not isinstance(record.get("input_sha256"), str) or not HASH.fullmatch(record["input_sha256"]):
        raise ValueError("输入指纹无效")
    allowed_fields = {"version", "id", "created_utc", "updated_utc", "platform", "template",
                      "input_sha256", "generated", "failed_generation", "stage", "files", "review"}
    if set(record) - allowed_fields:
        raise ValueError("任务包含未知字段，为防泄露禁止入库")
    if record.get("version") != 1:
        raise ValueError("任务格式版本无效")
    files = record.get("files")
    if not isinstance(files, list) or len(files) > 120:
        raise ValueError("任务文件清单无效")
    pairs: list[tuple[str, str]] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("图片摘要格式无效")
        name, digest = entry.get("name"), entry.get("sha256")
        if not isinstance(name, str) or not name or len(name) > 255 or name != Path(name).name or "\\" in name or "/" in name:
            raise ValueError("输出图片文件名不安全")
        if not isinstance(digest, str) or not HASH.fullmatch(digest):
            raise ValueError("图片校验值无效")
        pairs.append((name, digest))
    if len(pairs) != len(set(name for name, _ in pairs)):
        raise ValueError("任务图片文件名重复")
    if type(record.get("generated")) is not int or record["generated"] != len(pairs):
        raise ValueError("生成数量与文件列表不一致")
    if type(record.get("failed_generation")) is not int or not 0 <= record["failed_generation"] <= 100000:
        raise ValueError("失败数量无效")
    for key, n in (("platform", 60), ("template", 100), ("stage", 80), ("created_utc", 60), ("updated_utc", 60)):
        if not isinstance(record.get(key), str) or len(record[key]) > n or not record[key]:
            raise ValueError(f"任务字段 {key} 无效")
    review = record.get("review")
    if review is not None:
        if not isinstance(review, dict) or not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
            raise ValueError("人工审核信息无效")
        if set(review) - {"reviewed_utc", "reviewer", "counts", "image_sha256", "ready_to_publish", "rows"}:
            raise ValueError("审核摘要包含未知字段")
        checks = review.get("image_sha256")
        if not isinstance(checks, dict) or checks != dict(pairs):
            raise ValueError("审核图片摘要与任务不一致")
        rows = review.get("rows")
        if (not isinstance(rows, list) or len(rows) != len(pairs)
            or not all(isinstance(r, dict) for r in rows)
            or {r.get("file") for r in rows} != {name for name, _ in pairs}
            or any(set(r) - {"file", "status", "note"} for r in rows)):
            raise ValueError("审核文件列表不匹配")
        if type(review.get("ready_to_publish")) is not bool:
            raise ValueError("审核发布标记无效")
    raw = _json(record).encode("utf-8")
    if len(raw) > MAX_RECORD_BYTES:
        raise ValueError("任务元数据超过最大限制")
    return identifier, pairs


def save_job(path: str | Path, record: dict[str, Any], *, expected_revision: int | None = None) -> int:
    """Atomic insertion/CAS update; immutable job and file identities are verified.

    Updates require the previous revision, preventing stale browser tabs from
    overwriting another review. Successful updates append immutable review rows.
    """
    identifier, pairs = _validate_job(record)
    raw = _json(record)
    with open_database(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            previous = conn.execute("SELECT record_json,revision FROM jobs WHERE id=?", (identifier,)).fetchone()
            if previous is None:
                if expected_revision is not None:
                    raise ValueError("任务未创建，版本不匹配")
                conn.execute("""INSERT INTO jobs(id,created_utc,updated_utc,platform,template,input_sha256,generated,
                    failed_generation,stage,record_json,revision) VALUES(?,?,?,?,?,?,?,?,?,?,1)""",
                    (identifier, record["created_utc"], record["updated_utc"], record["platform"], record["template"],
                     record["input_sha256"], record["generated"], record["failed_generation"], record["stage"], raw))
                conn.executemany("INSERT INTO job_files(job_id,name,sha256) VALUES(?,?,?)",
                                 ((identifier, name, digest) for name, digest in pairs))
                revision = 1
            else:
                old, revision = json.loads(previous[0]), previous[1]
                if expected_revision is None or expected_revision != revision:
                    raise ValueError("任务已被其他窗口更新，请刷新后重新审核")
                frozen = ("id", "created_utc", "platform", "template", "input_sha256", "generated", "failed_generation", "files")
                if any(old.get(k) != record.get(k) for k in frozen):
                    raise ValueError("任务核心数据不可修改，请创建新批次")
                if old.get("review") is not None and record.get("review") is None:
                    raise ValueError("不允许清除已有人工审核")
                if old == record:
                    conn.execute("COMMIT")
                    return revision
                revision += 1
                conn.execute("UPDATE jobs SET updated_utc=?,stage=?,record_json=?,revision=? WHERE id=?",
                             (record["updated_utc"], record["stage"], raw, revision, identifier))
            review = record.get("review")
            if review is not None and (previous is None or json.loads(previous[0]).get("review") != review):
                review_raw = _json(review)
                conn.execute("INSERT INTO review_events(job_id,created_utc,reviewer,report_sha256,review_json) VALUES(?,?,?,?,?)",
                             (identifier, _now(), review["reviewer"].strip(), _sha(review_raw.encode("utf-8")), review_raw))
            conn.execute("COMMIT")
            return revision
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


def read_job(path: str | Path, identifier: str) -> tuple[dict[str, Any], int] | None:
    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        raise ValueError("任务编号无效")
    with open_database(path) as conn:
        row = conn.execute("SELECT record_json,revision FROM jobs WHERE id=?", (identifier,)).fetchone()
    return (json.loads(row[0]), row[1]) if row else None


def list_jobs(path: str | Path, limit: int = 20, *, stage: str | None = None) -> list[dict[str, Any]]:
    limit = max(0, min(100, int(limit)))
    sql = "SELECT id,created_utc,platform,template,generated,failed_generation,stage,revision FROM jobs"
    args: list[Any] = []
    if stage:
        sql += " WHERE stage=?"
        args.append(stage)
    sql += " ORDER BY created_utc DESC,id DESC LIMIT ?"
    args.append(limit)
    with open_database(path) as conn:
        rows = conn.execute(sql, args).fetchall()
    return [{"任务编号": r[0][:10], "创建时间UTC": r[1], "平台": r[2], "模板": r[3],
             "完成图片": r[4], "失败": r[5], "阶段": r[6], "版本": r[7]} for r in rows]


def review_history(path: str | Path, identifier: str) -> list[dict[str, Any]]:
    if not IDENTIFIER.fullmatch(identifier):
        raise ValueError("任务编号无效")
    with open_database(path) as conn:
        rows = conn.execute("SELECT event_id,created_utc,reviewer,report_sha256 FROM review_events WHERE job_id=? ORDER BY event_id",
                            (identifier,)).fetchall()
    return [{"event_id": r[0], "reviewed_utc": r[1], "reviewer": r[2], "sha256": r[3]} for r in rows]


def list_templates(path: str | Path) -> list[str]:
    with open_database(path) as conn:
        return [r[0] for r in conn.execute("SELECT name FROM templates ORDER BY name_key").fetchall()]


def save_template(path: str | Path, name: str, layout: dict, *, overwrite: bool = False) -> str:
    label = template_name(name)
    raw = layout_json(layout)
    with open_database(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute("SELECT name FROM templates WHERE name_key=?", (label.casefold(),)).fetchone()
            if existing and not overwrite:
                raise ValueError("模板名称已存在，请确认覆盖")
            if not existing and conn.execute("SELECT count(*) FROM templates").fetchone()[0] >= MAX_TEMPLATES:
                raise ValueError(f"最多保存 {MAX_TEMPLATES} 套模板")
            if existing:
                # Preserve original spelling when replacing an existing template.
                conn.execute("UPDATE templates SET layout_json=?,layout_sha256=?,updated_utc=? WHERE name_key=?",
                             (raw.decode("utf-8"), _sha(raw), _now(), label.casefold()))
                label = existing[0]
            else:
                conn.execute("INSERT INTO templates(name_key,name,layout_json,layout_sha256,updated_utc) VALUES(?,?,?,?,?)",
                             (label.casefold(), label, raw.decode("utf-8"), _sha(raw), _now()))
            conn.execute("COMMIT")
            return label
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


def load_template(path: str | Path, name: str) -> dict:
    label = template_name(name)
    with open_database(path) as conn:
        row = conn.execute("SELECT layout_json,layout_sha256 FROM templates WHERE name_key=?", (label.casefold(),)).fetchone()
    if row is None:
        raise ValueError("模板不存在")
    if _sha(row[0].encode("utf-8")) != row[1]:
        raise RuntimeError("模板校验值不匹配，可能存在损坏")
    return layout_from_json(row[0].encode("utf-8"))


def delete_template(path: str | Path, name: str) -> None:
    label = template_name(name)
    with open_database(path) as conn:
        count = conn.execute("DELETE FROM templates WHERE name_key=?", (label.casefold(),)).rowcount
        if count == 0:
            raise ValueError("模板不存在")


def migrate_legacy(path: str | Path, *, job_directory: str | Path, template_directory: str | Path,
                   dry_run: bool = False) -> dict[str, Any]:
    """Import legacy JSON with per-file atomic transactions; never delete source files.

    A changed imported JSON is a conflict, not an automatic overwrite. This is
    an explicit one-time migration, not a background reader of untrusted files.
    A dry-run against a missing database uses a temporary scratch DB and never
    creates the target database or modifies source files.
    """
    target = _check_path(path)
    if dry_run and not target.exists():
        with tempfile.TemporaryDirectory(prefix="huangren-db-dryrun-") as tempdir:
            scratch = Path(tempdir) / "dryrun.sqlite3"
            with open_database(scratch):
                pass
            return migrate_legacy(scratch, job_directory=job_directory,
                                  template_directory=template_directory, dry_run=True)
    report: dict[str, Any] = {"jobs_imported": 0, "templates_imported": 0, "unchanged": 0,
                              "would_import": 0, "dry_run": dry_run, "errors": []}
    for kind, folder in (("job", Path(job_directory)), ("template", Path(template_directory))):
        if not folder.is_dir() or folder.is_symlink():
            continue
        for file in sorted(folder.glob("*.json")):
            if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_RECORD_BYTES:
                report["errors"].append(f"{file.name}: 文件类型不允许或过大")
                continue
            try:
                raw = file.read_bytes()
                digest = _sha(raw)
                if kind == "job":
                    obj = json.loads(raw)
                    identifier, pairs = _validate_job(obj)
                    if identifier != file.stem:
                        raise ValueError("任务文件名和编号不一致")
                    job_raw = _json(obj)
                else:
                    layout = layout_from_json(raw)
                    label = template_name(file.stem)
                    layout_raw = layout_json(layout)
                with open_database(path) as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        old = conn.execute("SELECT sha256 FROM imported_files WHERE origin=?", (str(file.resolve()),)).fetchone()
                        if old:
                            if old[0] != digest:
                                raise ValueError("旧文件自导入后已改变；不会覆盖数据库")
                            report["unchanged"] += 1
                        elif kind == "job":
                            if conn.execute("SELECT 1 FROM jobs WHERE id=?", (identifier,)).fetchone():
                                raise ValueError("数据库已有同编号任务，请人工核对")
                            if not dry_run:
                                conn.execute("""INSERT INTO jobs(id,created_utc,updated_utc,platform,template,input_sha256,generated,
                                    failed_generation,stage,record_json,revision) VALUES(?,?,?,?,?,?,?,?,?,?,1)""",
                                    (identifier, obj["created_utc"], obj["updated_utc"], obj["platform"], obj["template"],
                                     obj["input_sha256"], obj["generated"], obj["failed_generation"], obj["stage"], job_raw))
                                conn.executemany("INSERT INTO job_files(job_id,name,sha256) VALUES(?,?,?)",
                                                 [(identifier,n,h) for n,h in pairs])
                                if obj.get("review") is not None:
                                    v = _json(obj["review"])
                                    conn.execute("INSERT INTO review_events(job_id,created_utc,reviewer,report_sha256,review_json) VALUES(?,?,?,?,?)",
                                                 (identifier, _now(), obj["review"]["reviewer"], _sha(v.encode()), v))
                        else:
                            if conn.execute("SELECT 1 FROM templates WHERE name_key=?", (label.casefold(),)).fetchone():
                                raise ValueError("数据库已有同名模板，请人工核对")
                            if conn.execute("SELECT count(*) FROM templates").fetchone()[0] >= MAX_TEMPLATES:
                                raise ValueError(f"数据库最多保存 {MAX_TEMPLATES} 套模板，无法继续迁移")
                            if not dry_run:
                                conn.execute("INSERT INTO templates(name_key,name,layout_json,layout_sha256,updated_utc) VALUES(?,?,?,?,?)",
                                             (label.casefold(), label, layout_raw.decode(), _sha(layout_raw), _now()))
                        if not old:
                            if not dry_run:
                                conn.execute("INSERT INTO imported_files(origin,kind,sha256,imported_utc) VALUES(?,?,?,?)",
                                             (str(file.resolve()), kind, digest, _now()))
                            report["would_import" if dry_run else
                                   ("jobs_imported" if kind == "job" else "templates_imported")] += 1
                        conn.execute("COMMIT")
                    except BaseException:
                        if conn.in_transaction:
                            conn.execute("ROLLBACK")
                        raise
            except (OSError, RuntimeError, ValueError, sqlite3.Error, TypeError, KeyError) as exc:
                report["errors"].append(f"{file.name}: {exc}")
    return report


def integrity_report(path: str | Path) -> dict[str, Any]:
    # A check must be read-only: never create a blank database merely because
    # an operator selected the wrong path in the UI or CLI.
    target = _check_path(path)
    if not target.is_file():
        return {"ok": False, "sqlite_integrity": ["database file does not exist"],
                "foreign_key_errors": 0, "logical_errors": ["数据库文件不存在；未创建新文件"],
                "schema_version": None,
                "counts": {name: 0 for name in ("jobs", "job_files", "review_events", "templates", "imported_files")}}
    with open_database(target) as conn:
        checks = [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()]
        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        rows = conn.execute("SELECT id,record_json,revision,generated FROM jobs").fetchall()
        audit_entries = conn.execute("SELECT event_id,job_id,reviewer,review_json,report_sha256 FROM review_events ORDER BY event_id").fetchall()
        templates = conn.execute("SELECT name,layout_json,layout_sha256 FROM templates").fetchall()
        review_events = conn.execute("SELECT event_id,job_id,reviewer,report_sha256,review_json FROM review_events ORDER BY job_id,event_id").fetchall()
        problems = []
        for ident, raw, revision, generated in rows:
            try:
                obj = json.loads(raw)
                _id, files = _validate_job(obj)
                stored = conn.execute("SELECT name,sha256 FROM job_files WHERE job_id=? ORDER BY name", (ident,)).fetchall()
                if _id != ident or sorted(files) != stored or len(files) != generated or revision < 1:
                    problems.append(f"任务 {ident}: 文件或元数据不一致")
            except (ValueError, TypeError, KeyError):
                problems.append(f"任务 {ident}: JSON 内容异常")
        for event_id, job_id, reviewer, raw, digest in audit_entries:
            try:
                event = json.loads(raw)
                if (_sha(raw.encode("utf-8")) != digest or event.get("reviewer") != reviewer
                    or not conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone()):
                    problems.append(f"审核事件 {event_id}: 摘要或关联信息不一致")
            except (ValueError, TypeError, AttributeError):
                problems.append(f"审核事件 {event_id}: 数据损坏")
        for ident, raw, _, _ in rows:
            try:
                review = json.loads(raw).get("review")
                latest = conn.execute("SELECT review_json FROM review_events WHERE job_id=? ORDER BY event_id DESC LIMIT 1", (ident,)).fetchone()
                if (review is None) != (latest is None) or (review is not None and _json(review) != latest[0]):
                    problems.append(f"任务 {ident}: 最新审核历史与任务摘要不一致")
            except (ValueError, TypeError, AttributeError):
                problems.append(f"任务 {ident}: 审核摘要不可解析")
        for name, raw, digest in templates:
            try:
                if _sha(raw.encode("utf-8")) != digest:
                    raise ValueError("sha mismatch")
                layout_from_json(raw.encode("utf-8"))
            except (ValueError, TypeError):
                problems.append(f"模板 {name}: 规则或摘要无效")
        counts = {name: conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                  for name in ("jobs", "job_files", "review_events", "templates", "imported_files")}
        schema = conn.execute("PRAGMA user_version").fetchone()[0]
    return {"ok": checks == ["ok"] and not fk_errors and not problems and schema == DB_VERSION,
            "sqlite_integrity": checks, "foreign_key_errors": len(fk_errors), "logical_errors": problems,
            "schema_version": schema, "counts": counts}


def _snapshot(source: Path, destination: Path, *, overwrite: bool) -> Path:
    source = _check_path(source)
    destination = _check_path(destination)
    if not source.is_file():
        raise ValueError("源数据库不存在")
    if source == destination or destination.exists() and not overwrite:
        raise ValueError("备份目标已存在或与源文件相同")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tempname = tempfile.mkstemp(prefix=".db-snapshot-", suffix=".sqlite3", dir=destination.parent)
    os.close(fd)
    temp = Path(tempname)
    try:
        with closing(sqlite3.connect(str(source))) as origin:
            if origin.execute("PRAGMA user_version").fetchone()[0] != DB_VERSION:
                raise ValueError("源数据库版本不受支持")
            if origin.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("源数据库完整性检查失败")
            with closing(sqlite3.connect(str(temp))) as fresh:
                origin.backup(fresh)
        with closing(sqlite3.connect(str(temp))) as check:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("备份数据库完整性检查失败")
        if not integrity_report(temp)["ok"]:
            raise ValueError("备份业务摘要校验失败，拒绝覆盖目标数据库")
        os.replace(temp, destination)
        return destination
    finally:
        if temp.exists():
            temp.unlink()


def backup_database(path: str | Path, destination: str | Path, *, overwrite: bool = False) -> Path:
    if not Path(path).expanduser().is_file():
        raise ValueError("源数据库不存在，拒绝创建空白备份")
    if not integrity_report(path)["ok"]:
        raise ValueError("数据库业务完整性检查未通过，拒绝备份")
    return _snapshot(Path(path), Path(destination), overwrite=overwrite)


def restore_database(backup: str | Path, destination: str | Path, *, overwrite: bool = False) -> Path:
    """Run only when app/other DB connections are stopped; refuse live WAL sidecars."""
    target = _check_path(destination)
    if any(Path(str(target) + suffix).exists() for suffix in ("-wal", "-shm")):
        raise ValueError("数据库 WAL/SHM 文件存在，请先完全停止应用再恢复")
    if target.exists() and not overwrite:
        raise ValueError("已有数据库，恢复需明确 --overwrite")
    output = _snapshot(Path(backup), target, overwrite=overwrite)
    report = integrity_report(output)
    if not report["ok"]:
        raise ValueError("恢复完成但业务校验不通过，需人工检查")
    return output
