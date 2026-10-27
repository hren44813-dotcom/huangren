"""历史商品结构参考层（V13）——与正式店铺SKU分离。

历史说明、推断结构片段、类别与颜色变体都是参考记录，未通过实物资料审核前
不能变为 catalog_skus / 广告卖点。默认不覆写、不删除历史记录。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database_v9 import DEFAULT_DB, open_database

VERSION = "1"
MAX_BYTES = 2 * 1024 * 1024
MODEL_ID = re.compile(r"H-[0-9a-f]{20}\Z")
DDL = (
 """CREATE TABLE IF NOT EXISTS history_ref_meta (
     key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
 """CREATE TABLE IF NOT EXISTS history_ref_items (
     id TEXT PRIMARY KEY, category TEXT NOT NULL, series TEXT NOT NULL,
     model TEXT NOT NULL, record_type TEXT NOT NULL,
     evidence_label TEXT NOT NULL, release_status TEXT NOT NULL,
     payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
     imported_utc TEXT NOT NULL,
     UNIQUE(category,series,model))""",
 """CREATE TABLE IF NOT EXISTS history_ref_options (
     item_id TEXT NOT NULL REFERENCES history_ref_items(id) ON DELETE RESTRICT,
     ordinal INTEGER NOT NULL CHECK(ordinal>=1),
     option_json TEXT NOT NULL, PRIMARY KEY(item_id,ordinal))""",
 """CREATE TABLE IF NOT EXISTS history_ref_links (
     item_id TEXT NOT NULL REFERENCES history_ref_items(id) ON DELETE RESTRICT,
     sku_id TEXT NOT NULL REFERENCES catalog_skus(id) ON DELETE RESTRICT,
     evidence_note TEXT NOT NULL, verified_by TEXT NOT NULL,
     created_utc TEXT NOT NULL, PRIMARY KEY(item_id,sku_id))""",
 "CREATE INDEX IF NOT EXISTS idx_history_ref_family ON history_ref_items(category,series,model)",
 "CREATE INDEX IF NOT EXISTS idx_history_ref_type ON history_ref_items(record_type)",
 "CREATE INDEX IF NOT EXISTS idx_history_ref_links_sku ON history_ref_links(sku_id)",
)

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def _digest(data: str) -> str:
    return hashlib.sha256(data.encode('utf-8')).hexdigest()

def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def _validate_ref_data(raw: bytes) -> list[dict[str, Any]]:
    if not raw or len(raw)>MAX_BYTES:
        raise ValueError('历史结构资料为空或超过2MB')
    try:
        data=json.loads(raw.decode('utf-8-sig'))
    except (UnicodeError, ValueError) as exc:
        raise ValueError('历史结构资料必须是有效 UTF-8 JSON') from exc
    if not isinstance(data,dict) or not isinstance(data.get('meta'),dict) or not isinstance(data.get('records'),list):
        raise ValueError('历史结构数据格式无效')
    if data['meta'].get('version')!='13.0':
        raise ValueError('只接受经检查的V13历史资料结构')
    rows=data['records']
    if len(rows)!=74 or data['meta'].get('record_count')!=74:
        raise ValueError('V13历史记录数量不符，拒绝部分覆盖')
    seen_ids=set();seen_names=set()
    required={'id','category','series','model','record_type','evidence_label','release_status',
              'components_from_description','historical_spec_text','variant_options','source',
              'sku_code','image_source','drawing_source','confirmed_by'}
    for i,row in enumerate(rows,1):
        if not isinstance(row,dict) or not required<=row.keys():
            raise ValueError(f'第{i}条缺少必要字段')
        if not isinstance(row['id'],str) or not MODEL_ID.fullmatch(row['id']):
            raise ValueError(f'第{i}条历史ID无效')
        if row['id'] in seen_ids:
            raise ValueError('历史ID重复')
        seen_ids.add(row['id'])
        for key in ('category','series','model','record_type','evidence_label'):
            val=row[key]
            if not isinstance(val,str) or not val.strip() or len(val)>180 or any(ord(x)<32 for x in val):
                raise ValueError(f'第{i}条{key}字段无效')
        name_key=(row['category'].casefold(),row['series'].casefold(),row['model'].casefold())
        if name_key in seen_names:
            raise ValueError('历史大类/系列/型号重复')
        seen_names.add(name_key)
        if row['release_status']!='历史记录·未完成原件核验' or any(row.get(k) is not None for k in
              ('sku_code','image_source','drawing_source','confirmed_by','confirmed_at')):
            raise ValueError('历史数据必须保持未核验状态，不能假冒正式店铺SKU')
        if not isinstance(row['variant_options'],list) or len(row['variant_options'])>30 or not all(isinstance(o,dict) and isinstance(o.get('option'),str) for o in row['variant_options']):
            raise ValueError(f'第{i}条变体结构不正确')
        if not isinstance(row['components_from_description'],list) or not all(isinstance(v,str) for v in row['components_from_description']):
            raise ValueError(f'第{i}条结构拆分字段不正确')
        if not isinstance(row['historical_spec_text'],str) or not isinstance(row['source'],dict):
            raise ValueError(f'第{i}条来源或参数错误')
    return rows

def initialize_history(path: str|Path = DEFAULT_DB) -> None:
    with open_database(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            existing=conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'history_ref_%'").fetchall()
            known={'history_ref_meta','history_ref_items','history_ref_options','history_ref_links'}
            if existing:
                names={v[0] for v in existing}
                if not known<=names:
                    raise RuntimeError('发现不完整的历史商品参考表，请先备份与人工检查')
                val=conn.execute("SELECT value FROM history_ref_meta WHERE key='schema_version'").fetchone()
                if not val or val[0]!=VERSION:
                    raise RuntimeError('历史商品参考库版本不兼容')
            for stmt in DDL:conn.execute(stmt)
            conn.execute("INSERT OR IGNORE INTO history_ref_meta(key,value) VALUES('schema_version',?)",(VERSION,))
            conn.execute('COMMIT')
        except BaseException:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise

def _check_initialized(conn: sqlite3.Connection) -> None:
    present={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'history_ref_%'")}
    if not {'history_ref_meta','history_ref_items','history_ref_options','history_ref_links'}<=present:
        raise RuntimeError('历史商品参考库未初始化，请先运行 init')
    val=conn.execute("SELECT value FROM history_ref_meta WHERE key='schema_version'").fetchone()
    if not val or val[0]!=VERSION:
        raise RuntimeError('历史商品参考库版本不支持')

def import_reference(path: str|Path, raw: bytes, *, dry_run: bool=False) -> dict[str,int|bool]:
    rows=_validate_ref_data(raw)
    target=Path(path).expanduser().absolute()
    if not target.exists():
        if dry_run:
            return {'inserted':0,'unchanged':0,'would_insert':len(rows),'dry_run':True}
        raise ValueError('数据库不存在；请先初始化主库和历史参考库')
    # Dry-run uses RO connection: no schema migration, no file modifications.
    if dry_run:
        with sqlite3.connect(target.as_uri()+'?mode=ro', uri=True) as conn:
            _check_initialized(conn)
            old={r[0]:r[1] for r in conn.execute('SELECT id,payload_sha256 FROM history_ref_items')}
            would=0;unchanged=0
            for rec in rows:
                digest=_digest(_canonical(rec))
                if rec['id'] not in old:would+=1
                elif old[rec['id']]==digest:unchanged+=1
                else:raise ValueError(f"历史编号 {rec['id']} 已存在且内容有冲突，拒绝自动覆盖")
            return {'inserted':0,'unchanged':unchanged,'would_insert':would,'dry_run':True}
    with open_database(path) as conn:
        _check_initialized(conn)
        conn.execute('BEGIN IMMEDIATE')
        try:
            inserted=unchanged=0
            for rec in rows:
                packed=_canonical(rec);digest=_digest(packed)
                existing=conn.execute('SELECT payload_sha256 FROM history_ref_items WHERE id=?',(rec['id'],)).fetchone()
                if existing:
                    if existing[0]!=digest:
                        raise ValueError(f"历史编号 {rec['id']} 已存在且内容有冲突，拒绝自动覆盖")
                    unchanged+=1;continue
                conn.execute('''INSERT INTO history_ref_items
                   (id,category,series,model,record_type,evidence_label,release_status,payload_json,payload_sha256,imported_utc)
                   VALUES(?,?,?,?,?,?,?,?,?,?)''',
                   (rec['id'],rec['category'],rec['series'],rec['model'],rec['record_type'],
                    rec['evidence_label'],rec['release_status'],packed,digest,_now()))
                for j,opt in enumerate(rec['variant_options'],1):
                    conn.execute('INSERT INTO history_ref_options(item_id,ordinal,option_json) VALUES(?,?,?)',
                                 (rec['id'],j,_canonical(opt)))
                inserted+=1
            conn.execute('COMMIT')
            return {'inserted':inserted,'unchanged':unchanged,'would_insert':0,'dry_run':False}
        except BaseException:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise

def list_reference(path: str|Path, *, text: str='', category: str='', limit: int=100,offset:int=0) -> list[dict[str,Any]]:
    if not 1<=limit<=500 or not 0<=offset<=100_000:
        raise ValueError('查询页大小或偏移量无效')
    target=Path(path).expanduser().absolute()
    if not target.exists():return []
    with sqlite3.connect(target.as_uri()+'?mode=ro', uri=True) as conn:
        _check_initialized(conn)
        where=[];args=[]
        if text:
            where.append("(model LIKE ? ESCAPE '\\' OR series LIKE ? ESCAPE '\\')")
            safe=text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            args.extend(['%'+safe+'%']*2)
        if category:
            where.append('category=?');args.append(category)
        sql='SELECT id,category,series,model,record_type,evidence_label FROM history_ref_items'
        if where:sql+=' WHERE '+' AND '.join(where)
        sql+=' ORDER BY category,series,model LIMIT ? OFFSET ?'
        args.extend([limit,offset])
        return [dict(zip(('id','category','series','model','record_type','evidence_label'),r)) for r in conn.execute(sql,args)]

def history_integrity(path: str|Path) -> dict[str,Any]:
    target=Path(path).expanduser().absolute()
    if not target.exists():return {'ok':False,'errors':['数据库不存在']}
    errors=[]
    with sqlite3.connect(target.as_uri()+'?mode=ro',uri=True) as conn:
        try:
            _check_initialized(conn)
            if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':errors.append('SQLite物理完整性错误')
            if conn.execute('PRAGMA foreign_key_check').fetchall():errors.append('历史关联外键错误')
            items=conn.execute('SELECT id,payload_json,payload_sha256 FROM history_ref_items').fetchall()
            for key,payload,digest in items:
                if _digest(payload)!=digest:
                    errors.append(f'{key}: 历史数据摘要已改变')
                    continue
                row=json.loads(payload)
                opts=conn.execute('SELECT ordinal,option_json FROM history_ref_options WHERE item_id=? ORDER BY ordinal',(key,)).fetchall()
                expected=[(i,_canonical(v)) for i,v in enumerate(row['variant_options'],1)]
                if opts!=expected:errors.append(f'{key}: 历史选项内容或顺序不一致')
            return {'ok':not errors,'records':len(items),'errors':errors}
        except (sqlite3.Error,RuntimeError,ValueError,TypeError,KeyError) as exc:
            return {'ok':False,'errors':[str(exc)]}

def link_verified_sku(path: str|Path,*,history_id:str,sku_id:str,verified_by:str,evidence_note:str) -> None:
    # Explicit human action; never infer SKU links from similar model strings.
    if not MODEL_ID.fullmatch(history_id):raise ValueError('历史商品编号无效')
    if not verified_by.strip() or len(verified_by)>80:raise ValueError('审核人无效')
    if len(evidence_note.strip())<10 or len(evidence_note)>500:
        raise ValueError('须填写至少10字的图纸或实物核验依据')
    with open_database(path) as conn:
        _check_initialized(conn)
        if not conn.execute('SELECT 1 FROM history_ref_items WHERE id=?',(history_id,)).fetchone():
            raise ValueError('历史商品不存在')
        if not conn.execute('SELECT 1 FROM catalog_skus WHERE id=?',(sku_id,)).fetchone():
            raise ValueError('正式SKU不存在；请先在商品档案中登记')
        conn.execute('INSERT INTO history_ref_links(item_id,sku_id,evidence_note,verified_by,created_utc) VALUES(?,?,?,?,?)',
                     (history_id,sku_id,evidence_note.strip(),verified_by.strip(),_now()))
