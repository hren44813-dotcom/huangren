"""Append-only claims, evidence, reviews and conflict workflows."""
from __future__ import annotations
import json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from .catalog_v12 import _validate_catalog
from .database_v9 import DEFAULT_DB,open_database
from .knowledge_schema_v13 import validate_knowledge
from .knowledge_v13 import _id,_text


def _now() -> str:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_claim(path: str|Path=DEFAULT_DB,*,subject_type: str,subject_id: str,attribute: str,literal_value: str,
    claim_kind: str,created_by: str,unit: str="",normalized_value: Any=None,supersedes_claim_id: str|None=None) -> str:
    """Create an immutable claim and its initial proposed event."""
    if subject_type not in {"model","product","sku","asset"}: raise ValueError("主张对象类型无效")
    if claim_kind not in {"catalog_transcription","supplier_assertion","physical_measurement","independent_test","manual_observation","system_inference"}:
        raise ValueError("主张来源类型无效")
    attribute=_text(attribute,"参数名称",150); literal_value=_text(literal_value,"原始值",1000)
    created_by=_text(created_by,"录入人",100); unit=_text(unit,"单位",50,empty=True)
    try: normalized=json.dumps(normalized_value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
    except (TypeError,ValueError) as exc: raise ValueError("标准化值不是有效JSON") from exc
    with open_database(path) as conn:
        _validate_catalog(conn); validate_knowledge(conn)
        if supersedes_claim_id and not conn.execute("SELECT 1 FROM knowledge_claims WHERE id=?",(supersedes_claim_id,)).fetchone():
            raise ValueError("被替代的参数主张不存在")
        ident=_id(); conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("""INSERT INTO knowledge_claims(id,subject_type,subject_id,attribute,literal_value,normalized_value_json,
            unit,claim_kind,created_by,supersedes_claim_id,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (ident,subject_type,subject_id,attribute,literal_value,normalized,unit,claim_kind,created_by,supersedes_claim_id,_now()))
            conn.execute("INSERT INTO knowledge_claim_events(claim_id,state,actor,note,created_utc) VALUES(?,?,?,?,?)",
                         (ident,"proposed",created_by,"新建主张，等待证据与复核",_now()))
            conn.execute("COMMIT"); return ident
        except sqlite3.IntegrityError as exc:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise ValueError(f"无法创建参数主张：{exc}") from exc
        except BaseException:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise


def _reopen_if_contradicted(conn: sqlite3.Connection,claim_id: str,actor: str,note: str) -> None:
    """Reopen an accepted claim when new contradictory evidence or review arrives."""
    latest=conn.execute("SELECT state FROM knowledge_claim_events WHERE claim_id=? ORDER BY event_id DESC LIMIT 1",(claim_id,)).fetchone()
    if latest and latest[0]=="accepted":
        conn.execute("INSERT INTO knowledge_claim_events(claim_id,state,actor,note,created_utc) VALUES(?,?,?,?,?)",
                     (claim_id,"reopened",actor,note,_now()))


def add_claim_evidence(path: str|Path=DEFAULT_DB,*,claim_id: str,source_id: str,evidence_role: str,
    extraction_method: str,created_by: str,pdf_page: int|None=None,printed_page: str="",
    region: dict[str,Any]|None=None,literal_excerpt: str="",confidence_note: str="") -> str:
    """Attach a source locator and reopen accepted claims if evidence contradicts them."""
    if evidence_role not in {"supports","contradicts","context"}: raise ValueError("证据角色无效")
    if extraction_method not in {"manual","pdf_text","ocr","measurement","manufacturer_confirmation","system_export","other"}:
        raise ValueError("证据提取方式无效")
    if pdf_page is not None and (type(pdf_page) is not int or pdf_page<=0): raise ValueError("PDF页码必须是正整数")
    created_by=_text(created_by,"录入人",100); printed_page=_text(printed_page,"印刷页码",50,empty=True)
    literal_excerpt=_text(literal_excerpt,"原文摘录",1000,empty=True); confidence_note=_text(confidence_note,"置信说明",500,empty=True)
    if region is not None and not isinstance(region,dict): raise ValueError("来源区域必须是JSON对象")
    try: region_json=json.dumps(region or {},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
    except (TypeError,ValueError) as exc: raise ValueError("来源区域不是有效JSON") from exc
    with open_database(path) as conn:
        _validate_catalog(conn); validate_knowledge(conn)
        if not conn.execute("SELECT 1 FROM knowledge_claims WHERE id=?",(claim_id,)).fetchone(): raise ValueError("参数主张不存在")
        if not conn.execute("SELECT 1 FROM knowledge_sources WHERE id=?",(source_id,)).fetchone(): raise ValueError("原始资料不存在")
        ident=_id(); conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("""INSERT INTO knowledge_claim_evidence(id,claim_id,source_id,evidence_role,pdf_page,printed_page,
            region_json,literal_excerpt,extraction_method,confidence_note,created_by,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ident,claim_id,source_id,evidence_role,pdf_page,printed_page,region_json,literal_excerpt,extraction_method,confidence_note,created_by,_now()))
            if evidence_role=="contradicts": _reopen_if_contradicted(conn,claim_id,created_by,"新增反对性证据，重新审查")
            conn.execute("COMMIT"); return ident
        except BaseException:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise


def add_claim_review(path: str|Path=DEFAULT_DB,*,claim_id: str,verdict: str,reviewer_role: str,
    reviewer_name: str,method: str,notes: str) -> str:
    """Append a review and reopen accepted claims if the review contradicts them."""
    if verdict not in {"supports","contradicts","inconclusive"}: raise ValueError("复核结论无效")
    if reviewer_role not in {"author","second_reviewer","manufacturer","independent_lab","warehouse","other"}:
        raise ValueError("复核人员类型无效")
    reviewer_name=_text(reviewer_name,"审核人",100); method=_text(method,"复核方法",300); notes=_text(notes,"复核说明",1000)
    with open_database(path) as conn:
        _validate_catalog(conn); validate_knowledge(conn)
        if not conn.execute("SELECT 1 FROM knowledge_claims WHERE id=?",(claim_id,)).fetchone(): raise ValueError("参数主张不存在")
        conn.execute("BEGIN IMMEDIATE"); ident=_id()
        try:
            conn.execute("INSERT INTO knowledge_claim_reviews(id,claim_id,verdict,reviewer_role,reviewer_name,method,notes,created_utc) VALUES(?,?,?,?,?,?,?,?)",
                         (ident,claim_id,verdict,reviewer_role,reviewer_name,method,notes,_now()))
            if verdict=="contradicts": _reopen_if_contradicted(conn,claim_id,reviewer_name,"新增反对性复核，重新审查")
            conn.execute("COMMIT"); return ident
        except BaseException:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise


def transition_claim(path: str|Path=DEFAULT_DB,*,claim_id: str,state: str,actor: str,note: str="") -> None:
    """Append a claim state; acceptance requires evidence and independent support."""
    if state not in {"proposed","accepted","rejected","superseded","reopened"}: raise ValueError("参数主张状态无效")
    actor=_text(actor,"操作人",100); note=_text(note,"状态说明",500,empty=state in {"proposed","accepted"})
    with open_database(path) as conn:
        _validate_catalog(conn); validate_knowledge(conn)
        if not conn.execute("SELECT 1 FROM knowledge_claims WHERE id=?",(claim_id,)).fetchone(): raise ValueError("参数主张不存在")
        row=conn.execute("SELECT state FROM knowledge_claim_events WHERE claim_id=? ORDER BY event_id DESC LIMIT 1",(claim_id,)).fetchone()
        current=row[0] if row else ""
        allowed={"proposed":{"accepted","rejected","superseded"},"accepted":{"rejected","superseded","reopened"},
                 "rejected":{"reopened","superseded"},"reopened":{"accepted","rejected","superseded"},"superseded":set()}
        if state not in allowed.get(current,set()): raise ValueError(f"不允许主张状态从{current or '未知'}变更为{state}")
        try: conn.execute("INSERT INTO knowledge_claim_events(claim_id,state,actor,note,created_utc) VALUES(?,?,?,?,?)",
                          (claim_id,state,actor,note,_now()))
        except sqlite3.IntegrityError as exc: raise ValueError(f"主张状态校验未通过：{exc}") from exc


def create_conflict(path: str|Path=DEFAULT_DB,*,claim_a_id: str,claim_b_id: str,created_by: str,description: str) -> str:
    """Open a conflict only for claims about the same subject and attribute."""
    if claim_a_id==claim_b_id: raise ValueError("冲突必须关联两个不同的主张")
    created_by=_text(created_by,"登记人",100); description=_text(description,"冲突描述",1000)
    first,second=sorted((claim_a_id,claim_b_id))
    with open_database(path) as conn:
        _validate_catalog(conn); validate_knowledge(conn)
        a=conn.execute("SELECT subject_type,subject_id,attribute FROM knowledge_claims WHERE id=?",(first,)).fetchone()
        b=conn.execute("SELECT subject_type,subject_id,attribute FROM knowledge_claims WHERE id=?",(second,)).fetchone()
        if not a or not b: raise ValueError("冲突中的参数主张不存在")
        if tuple(a)!=tuple(b): raise ValueError("只有同一对象、同一参数的主张才能登记冲突")
        old=conn.execute("SELECT id FROM knowledge_conflicts WHERE claim_a_id=? AND claim_b_id=?",(first,second)).fetchone()
        if old: return old[0]
        ident=_id(); conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("INSERT INTO knowledge_conflicts VALUES(?,?,?,?,?,?)",(ident,first,second,created_by,description,_now()))
            conn.execute("INSERT INTO knowledge_conflict_events(conflict_id,state,actor,resolution_note,source_id,created_utc) VALUES(?,?,?,?,?,?)",
                         (ident,"open",created_by,description,None,_now()))
            conn.execute("COMMIT"); return ident
        except BaseException:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise


def transition_conflict(path: str|Path=DEFAULT_DB,*,conflict_id: str,state: str,actor: str,
    resolution_note: str="",source_id: str|None=None) -> None:
    """Append a conflict resolution; resolving needs a source and written rationale."""
    if state not in {"resolved","reopened"}: raise ValueError("冲突状态只能为resolved或reopened")
    actor=_text(actor,"操作人",100); resolution_note=_text(resolution_note,"处理说明",1000,empty=state=="reopened")
    with open_database(path) as conn:
        _validate_catalog(conn); validate_knowledge(conn)
        if not conn.execute("SELECT 1 FROM knowledge_conflicts WHERE id=?",(conflict_id,)).fetchone(): raise ValueError("冲突记录不存在")
        row=conn.execute("SELECT state FROM knowledge_conflict_events WHERE conflict_id=? ORDER BY event_id DESC LIMIT 1",(conflict_id,)).fetchone()
        current=row[0] if row else ""
        if state=="resolved" and current not in {"open","reopened"}: raise ValueError("只有打开状态的冲突可以标记为解决")
        if state=="reopened" and current!="resolved": raise ValueError("只有已解决的冲突可以重新打开")
        if state=="resolved" and (not source_id or not resolution_note): raise ValueError("解决冲突必须提供来源证据和处理说明")
        if source_id and not conn.execute("SELECT 1 FROM knowledge_sources WHERE id=?",(source_id,)).fetchone(): raise ValueError("冲突处理证据来源不存在")
        conn.execute("INSERT INTO knowledge_conflict_events(conflict_id,state,actor,resolution_note,source_id,created_utc) VALUES(?,?,?,?,?,?)",
                     (conflict_id,state,actor,resolution_note,source_id,_now()))
