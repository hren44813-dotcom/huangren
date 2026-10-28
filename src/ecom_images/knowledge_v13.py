"""V13 APIs for model identities, SKU mappings and source provenance."""
from __future__ import annotations
import hashlib,json,re,sqlite3,uuid
from datetime import date,datetime,timezone
from pathlib import Path
from typing import Any
from .catalog_v12 import _validate_catalog
from .database_v9 import DEFAULT_DB,open_database
from .knowledge_schema_v13 import open_knowledge_readonly,validate_knowledge
SHA256=re.compile(r"^[0-9a-f]{64}$")
SOURCE_KINDS={"manufacturer_document","supplier_document","purchase_record","physical_photo","lab_report","platform_export","internal_note","other"}
AUTHORITY_LEVELS={"unverified","user_supplied","manufacturer_controlled","independent_test","system_export"}


def _now() -> str:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id() -> str:
    """Return a random stable identifier for a new record."""
    return uuid.uuid4().hex


def _text(value: str,label: str,limit: int=500,*,empty: bool=False) -> str:
    """Validate bounded text and reject control characters."""
    if not isinstance(value,str): raise ValueError(f"{label}必须是文本")
    cleaned=value.strip()
    if (not empty and not cleaned) or len(cleaned)>limit or any(ord(c)<32 for c in cleaned):
        raise ValueError(f"{label}为空、包含控制字符或超过{limit}字")
    return cleaned


def _json_object(value: dict[str,Any],label: str) -> str:
    """Serialize a deterministic JSON object."""
    if not isinstance(value,dict): raise ValueError(f"{label}必须是JSON对象")
    try: return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
    except (TypeError,ValueError) as exc: raise ValueError(f"{label}包含无法序列化的值") from exc


def register_source(path: str|Path=DEFAULT_DB,*,filename: str,source_kind: str,authority_level: str,
    sha256: str,size_bytes: int,media_type: str="",page_count: int|None=None,document_family: str="",
    document_number: str="",revision_label: str="",issue_date: str="",storage_ref: str="",
    metadata: dict[str,Any]|None=None,supersedes_source_id: str|None=None) -> str:
    """Register source metadata and a precomputed digest; source bytes stay outside SQLite."""
    filename=_text(filename,"文件名",255)
    if filename in {".",".."} or "/" in filename or "\\" in filename: raise ValueError("文件名必须是纯文件名，不能包含路径")
    if source_kind not in SOURCE_KINDS or authority_level not in AUTHORITY_LEVELS: raise ValueError("资料类型或权威级别无效")
    if not SHA256.fullmatch(sha256): raise ValueError("SHA-256必须是64位小写十六进制")
    if type(size_bytes) is not int or size_bytes<=0: raise ValueError("文件大小必须为正整数")
    if page_count is not None and (type(page_count) is not int or page_count<=0): raise ValueError("页数必须为正整数")
    storage_ref=_text(storage_ref,"相对存储引用",500,empty=True)
    if storage_ref and (storage_ref.startswith(("/","\\")) or ".." in Path(storage_ref).parts or "\\" in storage_ref):
        raise ValueError("存储引用必须是安全的相对路径")
    fields=(document_family,media_type,document_number,revision_label,issue_date); limits=(200,150,200,100,40)
    clean=[_text(v,k,n,empty=True) for v,k,n in zip(fields,("文档系列","MIME类型","文件编号","修订版","发布日期"),limits)]
    if clean[4]:
        try: date.fromisoformat(clean[4])
        except ValueError as exc: raise ValueError("发布日期必须使用YYYY-MM-DD格式") from exc
    metadata_json=_json_object(metadata or {},"元数据")
    with open_database(path) as conn:
        _validate_catalog(conn); validate_knowledge(conn)
        old=conn.execute("""SELECT id,original_filename,source_kind,authority_level,size_bytes,document_family,media_type,
        page_count,document_number,revision_label,issue_date,metadata_json FROM knowledge_sources WHERE sha256=?""",(sha256,)).fetchone()
        identity=(filename,source_kind,authority_level,size_bytes,clean[0],clean[1],page_count,clean[2],clean[3],clean[4],metadata_json)
        if old:
            if tuple(old[1:])!=identity: raise ValueError("同一SHA-256已存在但元数据不一致；不得静默升级来源可信度")
            return old[0]
        if supersedes_source_id and not conn.execute("SELECT 1 FROM knowledge_sources WHERE id=?",(supersedes_source_id,)).fetchone():
            raise ValueError("被替代的原始资料不存在")
        ident=_id(); conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("""INSERT INTO knowledge_sources(id,document_family,original_filename,source_kind,authority_level,
            sha256,size_bytes,media_type,page_count,document_number,revision_label,issue_date,storage_ref,metadata_json,
            supersedes_source_id,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ident,clean[0],filename,source_kind,authority_level,sha256,size_bytes,clean[1],page_count,clean[2],clean[3],
             clean[4],storage_ref,metadata_json,supersedes_source_id,_now()))
            conn.execute("COMMIT"); return ident
        except BaseException:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise


def register_source_file(path: str|Path=DEFAULT_DB,*,file_path: str|Path,source_kind: str,
    authority_level: str,storage_ref: str="",**metadata: Any) -> str:
    """Hash an existing local file and register metadata only, never the file bytes."""
    source=Path(file_path).expanduser()
    if source.is_symlink() or any(p.is_symlink() for p in source.absolute().parents): raise ValueError("原始资料路径不能包含符号链接")
    if not source.is_file(): raise ValueError("原始资料文件不存在")
    digest=hashlib.sha256(); size=0
    with source.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""): digest.update(chunk); size+=len(chunk)
    return register_source(path,filename=source.name,source_kind=source_kind,authority_level=authority_level,
        sha256=digest.hexdigest(),size_bytes=size,storage_ref=storage_ref,**metadata)


def add_model(path: str|Path=DEFAULT_DB,*,model_code: str,category: str,manufacturer_name: str="",series: str="") -> str:
    """Create a manufacturer model identity without inferring any store SKU."""
    model_code=_text(model_code,"制造商型号",100); manufacturer_name=_text(manufacturer_name,"制造商",200,empty=True)
    category=_text(category,"商品类别",100); series=_text(series,"产品系列",100,empty=True)
    with open_database(path) as conn:
        _validate_catalog(conn); validate_knowledge(conn)
        row=conn.execute("SELECT id,category,series FROM catalog_models WHERE manufacturer_name=? AND model_code=?",
                         (manufacturer_name,model_code)).fetchone()
        if row:
            if row[1:]!=(category,series): raise ValueError("制造商型号已存在但类别或系列不一致；拒绝覆盖")
            return row[0]
        ident=_id()
        try: conn.execute("INSERT INTO catalog_models VALUES(?,?,?,?,?,?)",(ident,manufacturer_name,model_code,category,series,_now()))
        except sqlite3.IntegrityError as exc: raise ValueError("制造商型号编码冲突") from exc
        return ident


def link_sku_model(path: str|Path=DEFAULT_DB,*,sku_id: str,model_id: str,actor: str,note: str="",source_id: str|None=None) -> str:
    """Create a proposed SKU-to-model mapping; never silently confirm it."""
    actor=_text(actor,"操作人",100); note=_text(note,"映射说明",500,empty=True)
    with open_database(path) as conn:
        _validate_catalog(conn); validate_knowledge(conn)
        if not conn.execute("SELECT 1 FROM catalog_skus WHERE id=?",(sku_id,)).fetchone(): raise ValueError("SKU档案不存在")
        if not conn.execute("SELECT 1 FROM catalog_models WHERE id=?",(model_id,)).fetchone(): raise ValueError("制造商型号不存在")
        if source_id and not conn.execute("SELECT 1 FROM knowledge_sources WHERE id=?",(source_id,)).fetchone(): raise ValueError("映射证据来源不存在")
        old=conn.execute("SELECT id FROM catalog_sku_model_links WHERE sku_id=? AND model_id=?",(sku_id,model_id)).fetchone()
        if old: return old[0]
        ident=_id(); conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("INSERT INTO catalog_sku_model_links VALUES(?,?,?,?,?,?)",(ident,sku_id,model_id,actor,note,_now()))
            conn.execute("INSERT INTO catalog_sku_model_events(link_id,state,actor,note,source_id,created_utc) VALUES(?,?,?,?,?,?)",
                         (ident,"proposed",actor,note,source_id,_now()))
            conn.execute("COMMIT"); return ident
        except BaseException:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise


def set_sku_model_link_state(path: str|Path=DEFAULT_DB,*,link_id: str,state: str,actor: str,note: str="",source_id: str|None=None) -> None:
    """Append a mapping decision and retain its previous states."""
    if state not in {"proposed","confirmed","rejected","withdrawn"}: raise ValueError("SKU/型号映射状态无效")
    actor=_text(actor,"操作人",100); note=_text(note,"说明",500,empty=state!="confirmed")
    with open_database(path) as conn:
        _validate_catalog(conn); validate_knowledge(conn)
        if not conn.execute("SELECT 1 FROM catalog_sku_model_links WHERE id=?",(link_id,)).fetchone(): raise ValueError("映射记录不存在")
        if source_id and not conn.execute("SELECT 1 FROM knowledge_sources WHERE id=?",(source_id,)).fetchone(): raise ValueError("映射证据来源不存在")
        row=conn.execute("SELECT state FROM catalog_sku_model_events WHERE link_id=? ORDER BY event_id DESC LIMIT 1",(link_id,)).fetchone()
        current=row[0] if row else ""
        allowed={"proposed":{"confirmed","rejected","withdrawn"},"confirmed":{"withdrawn","proposed"},
                 "rejected":{"proposed","withdrawn"},"withdrawn":{"proposed"}}
        if state not in allowed.get(current,set()): raise ValueError(f"不允许从{current or '未知'}变更为{state}")
        if state=="confirmed" and (not source_id or not note): raise ValueError("确认映射必须提供证据来源和说明")
        conn.execute("INSERT INTO catalog_sku_model_events(link_id,state,actor,note,source_id,created_utc) VALUES(?,?,?,?,?,?)",
                     (link_id,state,actor,note,source_id,_now()))


def list_models(path: str|Path=DEFAULT_DB,*,search: str="",limit: int=100) -> list[dict[str,Any]]:
    """List model identities and latest mapping events without inferring relationships."""
    if not 1<=limit<=500 or len(search)>100: raise ValueError("查询条件或条数无效")
    with open_knowledge_readonly(path) as conn:
        rows=conn.execute("""SELECT m.id,m.manufacturer_name,m.model_code,m.category,m.series,
        (SELECT COUNT(*) FROM catalog_sku_model_links l WHERE l.model_id=m.id),
        (SELECT e.state FROM catalog_sku_model_events e JOIN catalog_sku_model_links l ON l.id=e.link_id
         WHERE l.model_id=m.id ORDER BY e.event_id DESC LIMIT 1)
        FROM catalog_models m WHERE INSTR(m.model_code,?)>0 OR INSTR(m.manufacturer_name,?)>0
        ORDER BY m.manufacturer_name,m.model_code LIMIT ?""",(search,search,limit)).fetchall()
    return [{"model_id":r[0],"manufacturer":r[1],"model_code":r[2],"category":r[3],
             "series":r[4],"sku_mapping_count":r[5],"latest_mapping_event":r[6]} for r in rows]
