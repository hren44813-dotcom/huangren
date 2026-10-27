"""Industrial-hardware commerce catalog, additive to the V10/V11 SQLite store.

No product image bytes, customer files, credentials or invented product parameters.
Existing jobs/templates/reviews remain owned by database_v9; catalog tables use
an independent catalog_schema marker so SQLite user_version remains unchanged.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .database_v9 import DEFAULT_DB, open_database

CATALOG_VERSION = 1
MAX_CSV_BYTES = 3 * 1024 * 1024
MAX_ROWS = 500
HEX_SHA = re.compile(r"[0-9a-f]{64}\Z")
CODE = re.compile(r"[\w.\-]{1,64}\Z", re.UNICODE)
ASSET_KINDS = {"产品原图", "原尺寸图", "安装场景图", "SKU成品图", "其他"}
PLATFORMS = {"淘宝", "天猫", "阿里国际站", "其他"}
COLUMNS = (
    "店铺编码", "店铺名称", "平台", "商品编码", "商品名称", "商品类别",
    "SKU编码", "产品型号", "材质", "表面处理", "孔距(mm)", "总长(mm)", "备注",
)
_REQUIRED = COLUMNS[:7]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _identifier() -> str:
    return uuid.uuid4().hex


def _clean_code(value: str, label: str) -> str:
    val = value.strip()
    if not CODE.fullmatch(val):
        raise ValueError(f"{label}须为1-64位字母、数字、下划线、点或短横线（亦支持中文编码）")
    return val


def _clean_text(value: str, label: str, *, max_len: int = 150, required: bool = True) -> str:
    val = value.strip()
    if (required and not val) or len(val) > max_len or any(ord(c) < 32 for c in val):
        raise ValueError(f"{label}不能为空、包含控制字符或超过{max_len}字")
    return val


def _size(value: str, name: str) -> str:
    if not value.strip():
        return ""
    raw = value.strip()
    if not re.fullmatch(r"\d{1,6}(?:\.\d{1,3})?", raw) or not 0 < float(raw) <= 100000:
        raise ValueError(f"{name}只能填写已确认的正数毫米值，不含单位")
    return raw


def _parse_csv(raw: bytes) -> list[dict[str, str]]:
    if not raw or len(raw) > MAX_CSV_BYTES:
        raise ValueError("CSV为空或超过3MB")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("CSV文件必须使用UTF-8编码") from exc
    try:
        reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("CSV表头为空或有重复列")
        missing = set(_REQUIRED) - set(reader.fieldnames)
        if missing:
            raise ValueError("CSV缺少必填表头：" + "、".join(sorted(missing)))
        unknown = set(reader.fieldnames) - set(COLUMNS)
        if unknown:
            raise ValueError("CSV包含未知列：" + "、".join(sorted(unknown)))
        rows = []
        for lineno, row in enumerate(reader, start=2):
            if lineno > MAX_ROWS + 1:
                raise ValueError(f"单次最多导入{MAX_ROWS}行")
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"第{lineno}行列数不匹配")
            try:
                data = {k: (row.get(k) or "").strip() for k in COLUMNS}
                for key in ("店铺编码", "商品编码", "SKU编码"):
                    data[key] = _clean_code(data[key], key)
                for key in ("店铺名称", "商品名称", "商品类别"):
                    data[key] = _clean_text(data[key], key)
                for key in ("产品型号", "材质", "表面处理", "备注"):
                    data[key] = _clean_text(data[key], key, max_len=300 if key == "备注" else 100, required=False)
                if data["平台"] not in PLATFORMS:
                    raise ValueError("平台必须为淘宝、天猫、阿里国际站或其他")
                for key in ("孔距(mm)", "总长(mm)"):
                    data[key] = _size(data[key], key)
                # Prevent spreadsheet formula interpretation in downstream exports.
                if any(v.lstrip().startswith(("=", "+", "-", "@")) for v in data.values()):
                    raise ValueError("不接受以=、+、-、@开头的文本")
                rows.append(data)
            except ValueError as exc:
                raise ValueError(f"第{lineno}行：{exc}") from exc
    except csv.Error as exc:
        raise ValueError("CSV格式错误") from exc
    if not rows:
        raise ValueError("CSV没有数据行")
    return rows


_DDL = (
    """CREATE TABLE IF NOT EXISTS catalog_meta (
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS catalog_stores (
        id TEXT PRIMARY KEY, code TEXT NOT NULL COLLATE NOCASE UNIQUE,
        name TEXT NOT NULL, platform TEXT NOT NULL
          CHECK(platform IN ('淘宝','天猫','阿里国际站','其他')),
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
        created_utc TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS catalog_products (
        id TEXT PRIMARY KEY, store_id TEXT NOT NULL REFERENCES catalog_stores(id) ON DELETE RESTRICT,
        code TEXT NOT NULL COLLATE NOCASE, name TEXT NOT NULL, category TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_utc TEXT NOT NULL,
        UNIQUE(store_id,code), UNIQUE(id,store_id))""",
    """CREATE TABLE IF NOT EXISTS catalog_skus (
        id TEXT PRIMARY KEY, store_id TEXT NOT NULL, product_id TEXT NOT NULL,
        code TEXT NOT NULL COLLATE NOCASE, model TEXT NOT NULL DEFAULT '',
        specs_json TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_utc TEXT NOT NULL,
        UNIQUE(store_id,code),
        FOREIGN KEY(product_id,store_id) REFERENCES catalog_products(id,store_id) ON DELETE RESTRICT)""",
    """CREATE TABLE IF NOT EXISTS catalog_assets (
        id TEXT PRIMARY KEY, sku_id TEXT NOT NULL REFERENCES catalog_skus(id) ON DELETE RESTRICT,
        kind TEXT NOT NULL CHECK(kind IN ('产品原图','原尺寸图','安装场景图','SKU成品图','其他')),
        filename TEXT NOT NULL, sha256 TEXT NOT NULL CHECK(length(sha256)=64),
        width INTEGER CHECK(width IS NULL OR width>0),
        height INTEGER CHECK(height IS NULL OR height>0),
        created_utc TEXT NOT NULL, UNIQUE(sku_id,kind,sha256))""",
    """CREATE TABLE IF NOT EXISTS catalog_job_skus (
        job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
        sku_id TEXT NOT NULL REFERENCES catalog_skus(id) ON DELETE RESTRICT,
        linked_utc TEXT NOT NULL, PRIMARY KEY(job_id,sku_id))""",
    """CREATE TABLE IF NOT EXISTS catalog_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_type TEXT NOT NULL CHECK(entity_type IN ('store','product','sku','asset','job_link')),
        entity_id TEXT NOT NULL, action TEXT NOT NULL,
        details_json TEXT NOT NULL, created_utc TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_catalog_product_store ON catalog_products(store_id,code)",
    "CREATE INDEX IF NOT EXISTS idx_catalog_sku_product ON catalog_skus(product_id,code)",
    "CREATE INDEX IF NOT EXISTS idx_catalog_asset_sku ON catalog_assets(sku_id,kind)",
    "CREATE INDEX IF NOT EXISTS idx_catalog_job_sku ON catalog_job_skus(sku_id,job_id)",
    "CREATE INDEX IF NOT EXISTS idx_catalog_event_entity ON catalog_events(entity_type,entity_id,event_id)",
    """CREATE TRIGGER IF NOT EXISTS catalog_events_no_update
        BEFORE UPDATE ON catalog_events
        BEGIN SELECT RAISE(ABORT,'catalog events append only'); END""",
    """CREATE TRIGGER IF NOT EXISTS catalog_events_no_delete
        BEFORE DELETE ON catalog_events
        BEGIN SELECT RAISE(ABORT,'catalog events append only'); END""",
)
_TABLES = {"catalog_meta", "catalog_stores", "catalog_products", "catalog_skus",
           "catalog_assets", "catalog_job_skus", "catalog_events"}


def _validate_catalog(conn: sqlite3.Connection) -> None:
    if not _TABLES.issubset({r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}):
        raise RuntimeError("商品档案数据库表缺失，停止操作")
    version = conn.execute("SELECT value FROM catalog_meta WHERE key='schema_version'").fetchone()
    if not version or version[0] != str(CATALOG_VERSION):
        raise RuntimeError("商品档案数据库版本缺失或高于程序支持范围")
    required = {
        "catalog_stores": {"id","code","name","platform","active"},
        "catalog_products": {"id","store_id","code","name","category"},
        "catalog_skus": {"id","store_id","product_id","code","specs_json"},
        "catalog_assets": {"id","sku_id","kind","filename","sha256"},
        "catalog_job_skus": {"job_id","sku_id"},
        "catalog_events": {"event_id","entity_type","entity_id","details_json"},
    }
    for table, cols in required.items():
        present = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not cols.issubset(present):
            raise RuntimeError(f"商品档案表 {table} 结构不兼容")
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    if not {"catalog_events_no_update", "catalog_events_no_delete"}.issubset(triggers):
        raise RuntimeError("商品档案事件保护触发器缺失")


def initialize_catalog(path: str | Path = DEFAULT_DB) -> None:
    """Transactional additive DDL; never drops or overwrites V10/V11 tables."""
    with open_database(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Validate existing catalog versions before any writes.
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='catalog_meta'").fetchone():
                version = conn.execute("SELECT value FROM catalog_meta WHERE key='schema_version'").fetchone()
                if version is None or version[0] != str(CATALOG_VERSION):
                    raise RuntimeError("检测到未知商品档案数据库版本，拒绝覆盖")
            elif any(r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'catalog_%' AND type IN ('table','trigger')")):
                raise RuntimeError("发现未标记版本的商品档案对象，拒绝自动接管")
            for sql in _DDL:
                conn.execute(sql)
            conn.execute("INSERT OR IGNORE INTO catalog_meta(key,value) VALUES('schema_version',?)", (str(CATALOG_VERSION),))
            _validate_catalog(conn)
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


def _event(conn: sqlite3.Connection, kind: str, ident: str, action: str, details: dict) -> None:
    conn.execute("INSERT INTO catalog_events(entity_type,entity_id,action,details_json,created_utc) VALUES(?,?,?,?,?)",
                 (kind,ident,action,json.dumps(details,ensure_ascii=False,sort_keys=True),_now()))


def _apply_rows(conn: sqlite3.Connection, rows: list[dict[str,str]]) -> dict[str, int]:
    count = {"stores": 0, "products": 0, "skus": 0, "unchanged": 0}
    for lineno, row in enumerate(rows,start=2):
        try:
            store = conn.execute("SELECT id,name,platform FROM catalog_stores WHERE code=?",(row["店铺编码"],)).fetchone()
            if store is None:
                store_id = _identifier()
                conn.execute("INSERT INTO catalog_stores(id,code,name,platform,created_utc) VALUES(?,?,?,?,?)",
                             (store_id,row["店铺编码"],row["店铺名称"],row["平台"],_now()))
                _event(conn,"store",store_id,"create",{"code":row["店铺编码"]})
                count["stores"]+=1
            else:
                store_id=store[0]
                if store[1:]!=(row["店铺名称"],row["平台"]):
                    raise ValueError("店铺编码已存在，但名称或平台不一致，拒绝覆盖")
            product=conn.execute("SELECT id,name,category FROM catalog_products WHERE store_id=? AND code=?",
                                 (store_id,row["商品编码"])).fetchone()
            if product is None:
                product_id=_identifier()
                conn.execute("INSERT INTO catalog_products(id,store_id,code,name,category,created_utc) VALUES(?,?,?,?,?,?)",
                             (product_id,store_id,row["商品编码"],row["商品名称"],row["商品类别"],_now()))
                _event(conn,"product",product_id,"create",{"code":row["商品编码"],"store_id":store_id})
                count["products"]+=1
            else:
                product_id=product[0]
                if product[1:]!=(row["商品名称"],row["商品类别"]):
                    raise ValueError("商品编码已存在，但名称或类别不一致")
            spec={"material":row["材质"],"surface":row["表面处理"],
                  "hole_spacing_mm":row["孔距(mm)"],"total_length_mm":row["总长(mm)"],"note":row["备注"]}
            spec_raw=json.dumps(spec,ensure_ascii=False,sort_keys=True,separators=(",",":"))
            sku=conn.execute("SELECT id,product_id,model,specs_json FROM catalog_skus WHERE store_id=? AND code=?",
                             (store_id,row["SKU编码"])).fetchone()
            if sku is None:
                sku_id=_identifier()
                conn.execute("INSERT INTO catalog_skus(id,store_id,product_id,code,model,specs_json,created_utc) VALUES(?,?,?,?,?,?,?)",
                             (sku_id,store_id,product_id,row["SKU编码"],row["产品型号"],spec_raw,_now()))
                _event(conn,"sku",sku_id,"create",{"code":row["SKU编码"],"product_id":product_id})
                count["skus"]+=1
            elif sku[1:]!=(product_id,row["产品型号"],spec_raw):
                raise ValueError("SKU编码已存在，但所属商品或参数不同；请先人工确认，不自动覆盖")
            else:
                count["unchanged"]+=1
        except (ValueError,sqlite3.IntegrityError) as exc:
            raise ValueError(f"第{lineno}行：{exc}") from exc
    return count


def import_catalog_csv(path: str | Path, data: bytes, *, dry_run: bool=True) -> dict[str,int]:
    """All-or-nothing import; dry run against consistent scratch copy of DB."""
    rows=_parse_csv(data)
    if dry_run:
        with tempfile.TemporaryDirectory(prefix="huangren-catalog-preview-") as td:
            tmp=Path(td)/"preview.sqlite3"
            original=Path(path).expanduser().absolute()
            if original.exists():
                if original.is_symlink() or any(parent.is_symlink() for parent in original.parents):
                    raise ValueError("拒绝读取符号链接数据库或符号链接父目录")
                with closing(sqlite3.connect(original.as_uri()+"?mode=ro",uri=True)) as src:
                    with closing(sqlite3.connect(tmp)) as dst:
                        src.backup(dst)
            return import_catalog_csv(tmp,data,dry_run=False)
    initialize_catalog(path)
    with open_database(path) as conn:
        _validate_catalog(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            report=_apply_rows(conn,rows)
            conn.execute("COMMIT")
            return report
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


def _validate_filename(name: str) -> None:
    if (not isinstance(name,str) or not name or len(name)>255 or name in (".","..")
        or name != Path(name).name or "\\" in name or any(ord(c)<32 for c in name)):
        raise ValueError("素材文件名不安全")


def attach_asset(path: str | Path, *, sku_id: str, kind: str, filename: str,
                 sha256: str, width: int | None=None, height: int | None=None) -> str:
    """Save only asset metadata and digest (not image bytes)."""
    if kind not in ASSET_KINDS:
        raise ValueError("素材类型无效")
    _validate_filename(filename)
    if not HEX_SHA.fullmatch(sha256):
        raise ValueError("素材SHA256无效")
    if any(x is not None and (type(x) is not int or x <= 0 or x>100000) for x in (width,height)):
        raise ValueError("素材宽高无效")
    with open_database(path) as conn:
        _validate_catalog(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            if not conn.execute("SELECT 1 FROM catalog_skus WHERE id=?",(sku_id,)).fetchone():
                raise ValueError("SKU档案不存在")
            row=conn.execute("SELECT id FROM catalog_assets WHERE sku_id=? AND kind=? AND sha256=?",
                             (sku_id,kind,sha256)).fetchone()
            if row:
                conn.execute("COMMIT")
                return row[0]
            ident=_identifier()
            conn.execute("INSERT INTO catalog_assets(id,sku_id,kind,filename,sha256,width,height,created_utc) VALUES(?,?,?,?,?,?,?,?)",
                         (ident,sku_id,kind,filename,sha256,width,height,_now()))
            _event(conn,"asset",ident,"create",{"sku_id":sku_id,"kind":kind,"sha256":sha256})
            conn.execute("COMMIT")
            return ident
        except BaseException:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise


def link_job_sku(path: str | Path, *, job_id: str, sku_id: str) -> None:
    """Connect an existing production job to a catalog SKU without rewriting job history."""
    with open_database(path) as conn:
        _validate_catalog(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            if not conn.execute("SELECT 1 FROM jobs WHERE id=?",(job_id,)).fetchone():
                raise ValueError("制图任务不存在")
            if not conn.execute("SELECT 1 FROM catalog_skus WHERE id=?",(sku_id,)).fetchone():
                raise ValueError("SKU档案不存在")
            exists=conn.execute("SELECT 1 FROM catalog_job_skus WHERE job_id=? AND sku_id=?",(job_id,sku_id)).fetchone()
            if not exists:
                conn.execute("INSERT INTO catalog_job_skus(job_id,sku_id,linked_utc) VALUES(?,?,?)",(job_id,sku_id,_now()))
                _event(conn,"job_link",job_id,"link",{"sku_id":sku_id})
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise


def _open_readonly(path: str | Path) -> sqlite3.Connection:
    # Do not initialize or migrate merely because a user opened the listing page.
    target=Path(path).expanduser().absolute()
    if target.is_symlink() or any(p.is_symlink() for p in target.parents) or not target.is_file():
        raise ValueError("数据库不存在或路径不安全；请先执行初始化")
    conn=sqlite3.connect(target.as_uri()+"?mode=ro",uri=True,timeout=5)
    conn.execute("PRAGMA query_only=ON")
    return conn


def catalog_summary(path: str | Path) -> dict[str,Any]:
    with closing(_open_readonly(path)) as conn:
        _validate_catalog(conn)
        counts={key:conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for key,table in (
            ("stores","catalog_stores"),("products","catalog_products"),("skus","catalog_skus"),
            ("assets","catalog_assets"),("job_links","catalog_job_skus"),("events","catalog_events"))}
        fk_issues=conn.execute("PRAGMA foreign_key_check").fetchall()
        integrity=conn.execute("PRAGMA quick_check").fetchone()[0]
        return {"catalog_schema_version":CATALOG_VERSION,"counts":counts,
                "sqlite_quick_check":integrity,"foreign_key_errors":len(fk_issues),
                "ok":integrity=="ok" and not fk_issues}


def catalog_audit(path: str | Path) -> dict[str, Any]:
    """Read-only logical audit; does not repair, initialize or silently migrate."""
    findings=[]
    with closing(_open_readonly(path)) as conn:
        _validate_catalog(conn)
        physical=conn.execute("PRAGMA quick_check").fetchone()[0]
        if physical!="ok": findings.append("SQLite 物理检查失败")
        bad_fks=conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad_fks: findings.append(f"数据库存在{len(bad_fks)}个外键异常")
        for ident,raw in conn.execute("SELECT id,specs_json FROM catalog_skus"):
            try:
                specs=json.loads(raw)
                expected={"material","surface","hole_spacing_mm","total_length_mm","note"}
                if not isinstance(specs,dict) or set(specs)!=expected or not all(isinstance(x,str) for x in specs.values()):
                    raise ValueError("字段不匹配")
                for key in ("hole_spacing_mm","total_length_mm"):
                    if specs[key]: _size(specs[key],key)
            except (ValueError,TypeError):
                findings.append(f"SKU {ident[:10]} 的参数JSON无效")
        for ident,digest in conn.execute("SELECT id,sha256 FROM catalog_assets"):
            if not isinstance(digest,str) or not HEX_SHA.fullmatch(digest):
                findings.append(f"素材 {ident[:10]} 的SHA256无效")
        for ident,detail in conn.execute("SELECT event_id,details_json FROM catalog_events"):
            try:
                obj=json.loads(detail)
                if not isinstance(obj,dict):raise ValueError("not object")
            except (ValueError,TypeError):
                findings.append(f"变更事件 {ident} 数据无效")
        old_jobs=conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        linked_jobs=conn.execute("SELECT COUNT(DISTINCT job_id) FROM catalog_job_skus").fetchone()[0]
    return {"ok":not findings,"findings":findings[:100],"additional_findings":max(0,len(findings)-100),
            "unlinked_legacy_jobs":max(0,old_jobs-linked_jobs),
            "note":"未关联的旧任务可以逐个绑定SKU，不代表文件损坏；本工具不会推断归属"}


def list_skus(path: str | Path, *, store_code: str="", search: str="", limit: int=100) -> list[dict[str,Any]]:
    if not 1<=limit<=500 or len(search)>100 or len(store_code)>64:
        raise ValueError("查询条件或条数无效")
    with closing(_open_readonly(path)) as conn:
        _validate_catalog(conn)
        sql="""SELECT s.code,p.code,p.name,k.code,k.model,k.specs_json,k.id
                 FROM catalog_skus k JOIN catalog_products p ON k.product_id=p.id
                 JOIN catalog_stores s ON s.id=k.store_id WHERE 1=1"""
        args=[]
        if store_code.strip(): sql+=" AND s.code=?";args.append(store_code.strip())
        if search.strip():
            # Use INSTR rather than LIKE so user-supplied % and _ are literal.
            sql+=" AND (INSTR(k.code,?)>0 OR INSTR(p.name,?)>0 OR INSTR(k.model,?)>0)"
            args.extend([search.strip()]*3)
        sql+=" ORDER BY s.code,p.code,k.code LIMIT ?";args.append(limit)
        return [{"店铺编码":a,"商品编码":b,"商品名称":c,"SKU编码":d,"型号":e,
                 "参数":json.loads(f),"sku_id":g} for a,b,c,d,e,f,g in conn.execute(sql,args).fetchall()]


def csv_template() -> bytes:
    stream=io.StringIO(newline="")
    writer=csv.writer(stream)
    writer.writerow(COLUMNS)
    return ("\ufeff"+stream.getvalue()).encode("utf-8")
