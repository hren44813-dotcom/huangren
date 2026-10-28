"""Transactional review workflow APIs layered on the append-only V13 knowledge schema."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog_v12 import _validate_catalog
from .database_v9 import DEFAULT_DB, open_database
from .knowledge_schema_v13 import open_knowledge_readonly, validate_knowledge
from .knowledge_v13 import _id, _text
from .knowledge_ingest_v13 import (
    PARSER_VERSION,
    _sha256_file,
    _stored_path,
    validate_ingestion,
)

CLAIM_KINDS = {
    "catalog_transcription", "supplier_assertion", "physical_measurement",
    "independent_test", "manual_observation", "system_inference",
}
EVIDENCE_ROLES = {"supports", "contradicts", "context"}
REVIEW_VERDICTS = {"supports", "contradicts", "inconclusive"}
REVIEWER_ROLES = {"author", "second_reviewer", "manufacturer", "independent_lab", "warehouse", "other"}
CLAIM_STATES = {"proposed", "accepted", "rejected", "superseded", "reopened"}
_ALLOWED_TRANSITIONS = {
    "proposed": {"accepted", "rejected", "superseded"},
    "accepted": {"rejected", "superseded", "reopened"},
    "rejected": {"reopened", "superseded"},
    "reopened": {"accepted", "rejected", "superseded"},
    "superseded": set(),
}

_CLAIM_SELECT = """SELECT
    c.id,c.subject_type,c.subject_id,c.attribute,c.literal_value,c.unit,c.claim_kind,
    c.normalized_value_json,c.created_by,c.created_utc,c.supersedes_claim_id,
    COALESCE((SELECT e.state FROM knowledge_claim_events e WHERE e.claim_id=c.id ORDER BY e.event_id DESC LIMIT 1),'unknown'),
    COALESCE(m.model_code,
      (SELECT cm.model_code FROM catalog_sku_model_links l JOIN catalog_models cm ON cm.id=l.model_id
       WHERE c.subject_type='sku' AND l.sku_id=c.subject_id
       AND (SELECT ev.state FROM catalog_sku_model_events ev WHERE ev.link_id=l.id ORDER BY ev.event_id DESC LIMIT 1)='confirmed'
       ORDER BY l.created_utc LIMIT 1),s.model,''),
    COALESCE(s.code,''),COALESCE(p.name,''),COALESCE(p.category,''),COALESCE(st.name,''),
    (SELECT COUNT(*) FROM knowledge_claim_evidence ev WHERE ev.claim_id=c.id),
    (SELECT COUNT(*) FROM knowledge_claim_reviews rv WHERE rv.claim_id=c.id),
    (SELECT rv.verdict FROM knowledge_claim_reviews rv WHERE rv.claim_id=c.id ORDER BY rv.created_utc DESC,rv.id DESC LIMIT 1),
    (SELECT rv.reviewer_name FROM knowledge_claim_reviews rv WHERE rv.claim_id=c.id ORDER BY rv.created_utc DESC,rv.id DESC LIMIT 1),
    (SELECT rv.created_utc FROM knowledge_claim_reviews rv WHERE rv.claim_id=c.id ORDER BY rv.created_utc DESC,rv.id DESC LIMIT 1)
    FROM knowledge_claims c
    LEFT JOIN catalog_models m ON c.subject_type='model' AND m.id=c.subject_id
    LEFT JOIN catalog_skus s ON c.subject_type='sku' AND s.id=c.subject_id
    LEFT JOIN catalog_products p ON s.product_id=p.id
    LEFT JOIN catalog_stores st ON s.store_id=st.id
    WHERE 1=1"""

_CLAIM_KEYS = (
    "claim_id", "subject_type", "subject_id", "attribute", "literal_value", "unit", "claim_kind",
    "normalized_value_json", "created_by", "created_utc", "supersedes_claim_id", "state", "model_code",
    "sku_code", "product_name", "category", "store_name", "evidence_count", "review_count",
    "latest_review_verdict", "latest_reviewer", "latest_reviewed_utc",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _object(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    except (TypeError, ValueError):
        return {}


def _latest_state(conn: sqlite3.Connection, table: str, key: str, ident: str, default: str = "unknown") -> str:
    row = conn.execute(
        f"SELECT state FROM {table} WHERE {key}=? ORDER BY event_id DESC LIMIT 1", (ident,)
    ).fetchone()
    return row[0] if row else default


def _validate_limit(limit: int, maximum: int = 200) -> None:
    if type(limit) is not int or not 1 <= limit <= maximum:
        raise ValueError(f"limit 必须在 1 到 {maximum} 之间")


def list_review_claims(
    path: str | Path = DEFAULT_DB, *, model_code: str = "", attribute: str = "",
    state: str = "", limit: int = 100,
) -> list[dict[str, Any]]:
    """List claims for the review queue, optionally filtered by exact model and attribute text."""
    _validate_limit(limit)
    for value, label, maximum in ((model_code, "型号", 100), (attribute, "参数", 150), (state, "状态", 20)):
        if not isinstance(value, str) or len(value) > maximum:
            raise ValueError(f"{label}筛选条件无效")
    if state and state not in CLAIM_STATES | {"unknown"}:
        raise ValueError("主张状态筛选无效")
    with open_knowledge_readonly(path) as conn:
        sql = _CLAIM_SELECT
        args: list[Any] = []
        if model_code.strip():
            code = model_code.strip()
            sql += """ AND (m.model_code=? COLLATE NOCASE OR
                (c.subject_type='sku' AND (s.model=? COLLATE NOCASE OR EXISTS(
                  SELECT 1 FROM catalog_sku_model_links l JOIN catalog_models cm ON cm.id=l.model_id
                  WHERE l.sku_id=c.subject_id AND cm.model_code=? COLLATE NOCASE
                  AND (SELECT ev.state FROM catalog_sku_model_events ev WHERE ev.link_id=l.id
                       ORDER BY ev.event_id DESC LIMIT 1)='confirmed'))))"""
            args.extend((code, code, code))
        if attribute.strip():
            sql += " AND INSTR(UPPER(c.attribute),UPPER(?))>0"
            args.append(attribute.strip())
        if state:
            sql += " AND COALESCE((SELECT e.state FROM knowledge_claim_events e WHERE e.claim_id=c.id ORDER BY e.event_id DESC LIMIT 1),'unknown')=?"
            args.append(state)
        sql += " ORDER BY c.created_utc DESC,c.id LIMIT ?"
        args.append(limit)
        rows = conn.execute(sql, args).fetchall()
    return [dict(zip(_CLAIM_KEYS, row)) for row in rows]


def get_claim_review_detail(path: str | Path = DEFAULT_DB, *, claim_id: str) -> dict[str, Any]:
    """Return a claim plus append-only evidence, review and state histories."""
    if not isinstance(claim_id, str) or not claim_id.strip() or len(claim_id) > 100:
        raise ValueError("参数主张 ID 无效")
    with open_knowledge_readonly(path) as conn:
        row = conn.execute(_CLAIM_SELECT + " AND c.id=?", (claim_id.strip(),)).fetchone()
        if not row:
            raise ValueError("参数主张不存在")
        claim = dict(zip(_CLAIM_KEYS, row))
        evidence_rows = conn.execute("""SELECT e.id,e.source_id,s.original_filename,s.source_kind,s.authority_level,
            s.sha256,s.storage_ref,e.evidence_role,e.pdf_page,e.printed_page,e.region_json,e.literal_excerpt,
            e.extraction_method,e.confidence_note,e.created_by,e.created_utc
            FROM knowledge_claim_evidence e JOIN knowledge_sources s ON s.id=e.source_id
            WHERE e.claim_id=? ORDER BY e.created_utc,e.id""", (claim_id,)).fetchall()
        reviews = conn.execute("""SELECT id,verdict,reviewer_role,reviewer_name,method,notes,created_utc
            FROM knowledge_claim_reviews WHERE claim_id=? ORDER BY created_utc,id""", (claim_id,)).fetchall()
        events = conn.execute("""SELECT event_id,state,actor,note,created_utc FROM knowledge_claim_events
            WHERE claim_id=? ORDER BY event_id""", (claim_id,)).fetchall()
    evidence = [{
        "evidence_id": r[0], "source_id": r[1], "filename": r[2], "source_kind": r[3],
        "authority_level": r[4], "source_sha256": r[5], "storage_ref": r[6], "role": r[7],
        "pdf_page": r[8], "printed_page": r[9] or None, "region": _object(r[10]),
        "literal_excerpt": r[11], "extraction_method": r[12], "confidence_note": r[13],
        "created_by": r[14], "created_utc": r[15],
    } for r in evidence_rows]
    review_items = [{
        "review_id": r[0], "verdict": r[1], "reviewer_role": r[2], "reviewer_name": r[3],
        "method": r[4], "notes": r[5], "created_utc": r[6],
    } for r in reviews]
    event_items = [{"event_id": r[0], "state": r[1], "actor": r[2], "note": r[3], "created_utc": r[4]} for r in events]
    return {"claim": claim, "evidence": evidence, "reviews": review_items, "events": event_items}


def list_review_sources(path: str | Path = DEFAULT_DB, *, limit: int = 200) -> list[dict[str, Any]]:
    """List registered source metadata for evidence and conflict resolution forms."""
    _validate_limit(limit)
    with open_knowledge_readonly(path) as conn:
        rows = conn.execute("""SELECT id,original_filename,source_kind,authority_level,sha256,size_bytes,
            media_type,page_count,document_family,document_number,revision_label,issue_date,storage_ref,created_utc
            FROM knowledge_sources ORDER BY created_utc DESC,original_filename LIMIT ?""", (limit,)).fetchall()
    keys = ("source_id", "filename", "source_kind", "authority_level", "sha256", "size_bytes",
            "media_type", "page_count", "document_family", "document_number", "revision_label",
            "issue_date", "storage_ref", "created_utc")
    return [dict(zip(keys, row)) for row in rows]


def list_open_conflicts(
    path: str | Path = DEFAULT_DB, *, model_code: str = "", attribute: str = "", limit: int = 100,
) -> list[dict[str, Any]]:
    """Return open/reopened conflicts and both literal claim values."""
    _validate_limit(limit)
    if not isinstance(model_code, str) or len(model_code) > 100:
        raise ValueError("型号筛选条件无效")
    if not isinstance(attribute, str) or len(attribute) > 150:
        raise ValueError("参数筛选条件无效")
    sql = """SELECT cf.id,cf.created_by,cf.description,cf.created_utc,
        COALESCE((SELECT e.state FROM knowledge_conflict_events e WHERE e.conflict_id=cf.id ORDER BY e.event_id DESC LIMIT 1),'unknown'),
        (SELECT e.actor FROM knowledge_conflict_events e WHERE e.conflict_id=cf.id ORDER BY e.event_id DESC LIMIT 1),
        (SELECT e.resolution_note FROM knowledge_conflict_events e WHERE e.conflict_id=cf.id ORDER BY e.event_id DESC LIMIT 1),
        (SELECT e.source_id FROM knowledge_conflict_events e WHERE e.conflict_id=cf.id ORDER BY e.event_id DESC LIMIT 1),
        a.id,a.subject_type,a.subject_id,a.attribute,a.literal_value,a.unit,a.claim_kind,
        COALESCE((SELECT e.state FROM knowledge_claim_events e WHERE e.claim_id=a.id ORDER BY e.event_id DESC LIMIT 1),'unknown'),
        COALESCE(am.model_code,(SELECT cm.model_code FROM catalog_sku_model_links l JOIN catalog_models cm ON cm.id=l.model_id
          WHERE a.subject_type='sku' AND l.sku_id=a.subject_id
          AND (SELECT ev.state FROM catalog_sku_model_events ev WHERE ev.link_id=l.id ORDER BY ev.event_id DESC LIMIT 1)='confirmed'
          ORDER BY l.created_utc LIMIT 1),sa.model,''),
        b.id,b.subject_type,b.subject_id,b.attribute,b.literal_value,b.unit,b.claim_kind,
        COALESCE((SELECT e.state FROM knowledge_claim_events e WHERE e.claim_id=b.id ORDER BY e.event_id DESC LIMIT 1),'unknown'),
        COALESCE(bm.model_code,(SELECT cm.model_code FROM catalog_sku_model_links l JOIN catalog_models cm ON cm.id=l.model_id
          WHERE b.subject_type='sku' AND l.sku_id=b.subject_id
          AND (SELECT ev.state FROM catalog_sku_model_events ev WHERE ev.link_id=l.id ORDER BY ev.event_id DESC LIMIT 1)='confirmed'
          ORDER BY l.created_utc LIMIT 1),sb.model,'')
        FROM knowledge_conflicts cf
        JOIN knowledge_claims a ON a.id=cf.claim_a_id
        JOIN knowledge_claims b ON b.id=cf.claim_b_id
        LEFT JOIN catalog_models am ON a.subject_type='model' AND am.id=a.subject_id
        LEFT JOIN catalog_skus sa ON a.subject_type='sku' AND sa.id=a.subject_id
        LEFT JOIN catalog_models bm ON b.subject_type='model' AND bm.id=b.subject_id
        LEFT JOIN catalog_skus sb ON b.subject_type='sku' AND sb.id=b.subject_id
        WHERE COALESCE((SELECT e.state FROM knowledge_conflict_events e WHERE e.conflict_id=cf.id ORDER BY e.event_id DESC LIMIT 1),'unknown') IN ('open','reopened')"""
    args: list[Any] = []
    if model_code.strip():
        sql += """ AND (am.model_code=? COLLATE NOCASE OR bm.model_code=? COLLATE NOCASE OR
            (a.subject_type='sku' AND sa.model=? COLLATE NOCASE) OR
            (b.subject_type='sku' AND sb.model=? COLLATE NOCASE) OR
            EXISTS(SELECT 1 FROM catalog_sku_model_links l JOIN catalog_models cm ON cm.id=l.model_id
              WHERE a.subject_type='sku' AND l.sku_id=a.subject_id AND cm.model_code=? COLLATE NOCASE
              AND (SELECT ev.state FROM catalog_sku_model_events ev WHERE ev.link_id=l.id ORDER BY ev.event_id DESC LIMIT 1)='confirmed') OR
            EXISTS(SELECT 1 FROM catalog_sku_model_links l JOIN catalog_models cm ON cm.id=l.model_id
              WHERE b.subject_type='sku' AND l.sku_id=b.subject_id AND cm.model_code=? COLLATE NOCASE
              AND (SELECT ev.state FROM catalog_sku_model_events ev WHERE ev.link_id=l.id ORDER BY ev.event_id DESC LIMIT 1)='confirmed'))"""
        args.extend([model_code.strip()] * 6)
    if attribute.strip():
        sql += " AND INSTR(UPPER(a.attribute),UPPER(?))>0"
        args.append(attribute.strip())
    sql += " ORDER BY cf.created_utc DESC,cf.id LIMIT ?"
    args.append(limit)
    with open_knowledge_readonly(path) as conn:
        rows = conn.execute(sql, args).fetchall()
    output = []
    for r in rows:
        output.append({
            "conflict_id": r[0], "created_by": r[1], "description": r[2], "created_utc": r[3],
            "state": r[4], "latest_actor": r[5], "resolution_note": r[6], "resolution_source_id": r[7],
            "claim_a": {"claim_id": r[8], "subject_type": r[9], "subject_id": r[10], "attribute": r[11],
                "literal_value": r[12], "unit": r[13], "claim_kind": r[14], "state": r[15], "model_code": r[16]},
            "claim_b": {"claim_id": r[17], "subject_type": r[18], "subject_id": r[19], "attribute": r[20],
                "literal_value": r[21], "unit": r[22], "claim_kind": r[23], "state": r[24], "model_code": r[25]},
        })
    return output


def _checked_source_path(path: str | Path, storage_ref: str, expected_sha: str, expected_size: int) -> Path:
    if not storage_ref:
        raise ValueError("原始资料没有可验证的存储引用，不能用于预览或创建证据")
    stored = _stored_path(path, storage_ref)
    if not stored.is_file():
        raise ValueError("已登记的原始资料文件不存在，不能用于预览或创建证据")
    actual_sha, actual_size = _sha256_file(stored)
    if actual_sha != expected_sha or actual_size != expected_size:
        raise ValueError("原始资料 SHA-256 或文件大小与登记值不一致，已阻止操作")
    return stored


def _segment_row(conn: sqlite3.Connection, segment_id: str) -> tuple[Any, ...]:
    row = conn.execute("""SELECT d.id,d.source_id,d.parser_version,d.segment_type,d.pdf_page,d.printed_page,
        d.sheet_name,d.cell_range,d.line_start,d.line_end,d.heading_path,d.text,d.text_sha256,d.region_json,
        s.original_filename,s.source_kind,s.authority_level,s.sha256,s.size_bytes,s.storage_ref
        FROM knowledge_document_segments d JOIN knowledge_sources s ON s.id=d.source_id
        WHERE d.id=? AND d.parser_version=?""", (segment_id, PARSER_VERSION)).fetchone()
    if not row:
        raise ValueError("文档索引片段不存在或解析器版本已变更")
    return row


def create_claim_from_segment(
    path: str | Path = DEFAULT_DB, *, segment_id: str, model_id: str, attribute: str,
    literal_value: str, unit: str = "", claim_kind: str = "catalog_transcription",
    created_by: str, evidence_role: str = "supports",
) -> dict[str, Any]:
    """Atomically create a proposed model claim and its source evidence from one indexed segment."""
    if not isinstance(segment_id, str) or not segment_id.strip() or len(segment_id) > 100:
        raise ValueError("索引片段 ID 无效")
    if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 100:
        raise ValueError("制造商型号 ID 无效")
    if claim_kind not in CLAIM_KINDS:
        raise ValueError("参数主张来源类型无效")
    if evidence_role not in EVIDENCE_ROLES:
        raise ValueError("证据角色无效")
    attribute = _text(attribute, "参数名称", 150)
    literal_value = _text(literal_value, "原始值", 1000)
    unit = _text(unit, "单位", 50, empty=True)
    created_by = _text(created_by, "录入人", 100)

    with open_database(path) as conn:
        _validate_catalog(conn)
        validate_knowledge(conn)
        validate_ingestion(conn)
        row = _segment_row(conn, segment_id.strip())
        if not conn.execute("SELECT 1 FROM catalog_models WHERE id=?", (model_id.strip(),)).fetchone():
            raise ValueError("制造商型号不存在；请先显式登记型号，不能从 SKU 自由文本自动推断")
        stored = _checked_source_path(path, row[19], row[17], row[18])
        if hashlib.sha256(row[11].encode("utf-8")).hexdigest() != row[12]:
            raise ValueError("索引片段文本指纹不一致，已阻止创建证据")
        region = _object(row[13])
        if not isinstance(region, dict):
            raise ValueError("索引片段区域定位数据无效")
        region.update({
            "segment_id": row[0], "segment_type": row[3], "source_filename": row[14],
            "source_sha256": row[17], "sheet_name": row[6] or None, "cell_range": row[7] or None,
            "line_start": row[8], "line_end": row[9], "heading_path": row[10] or None,
        })
        try:
            region_json = json.dumps(region, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("来源区域不是有效 JSON") from exc
        claim_id, evidence_id = _id(), _id()
        extraction_method = "pdf_text" if stored.suffix.lower() == ".pdf" else "other"
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = _segment_row(conn, segment_id.strip())
            if current[1] != row[1] or current[12] != row[12] or current[17] != row[17]:
                raise ValueError("原始资料或索引片段在操作期间发生变化，请重新检索")
            if not conn.execute("SELECT 1 FROM catalog_models WHERE id=?", (model_id.strip(),)).fetchone():
                raise ValueError("制造商型号不存在")
            conn.execute("""INSERT INTO knowledge_claims(id,subject_type,subject_id,attribute,literal_value,
                normalized_value_json,unit,claim_kind,created_by,supersedes_claim_id,created_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (claim_id, "model", model_id.strip(), attribute, literal_value, "null", unit, claim_kind,
                 created_by, None, _now()))
            conn.execute("""INSERT INTO knowledge_claim_events(claim_id,state,actor,note,created_utc)
                VALUES(?,?,?,?,?)""", (claim_id, "proposed", created_by, "从已核验指纹的原始片段创建候选主张，等待复核", _now()))
            conn.execute("""INSERT INTO knowledge_claim_evidence(id,claim_id,source_id,evidence_role,pdf_page,
                printed_page,region_json,literal_excerpt,extraction_method,confidence_note,created_by,created_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (evidence_id, claim_id, row[1], evidence_role, row[4], row[5] or "", region_json,
                 row[11][:1000], extraction_method, "原始文件 SHA-256 与登记值一致；片段仍需人工判读",
                 created_by, _now()))
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise ValueError(f"无法创建候选主张和证据：{exc}") from exc
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return {
        "claim_id": claim_id, "evidence_id": evidence_id, "source_id": row[1],
        "filename": row[14], "source_sha256": row[17], "pdf_page": row[4],
        "segment_id": row[0], "location": region, "state": "proposed",
        "note": "已原子创建候选主张和来源证据；尚未接受或验证参数",
    }


def render_segment_preview(
    path: str | Path = DEFAULT_DB, *, segment_id: str, scale: float = 1.25,
) -> dict[str, Any]:
    """Render a PDF physical page with the indexed bbox highlighted after verifying source bytes."""
    if not isinstance(segment_id, str) or not segment_id.strip() or len(segment_id) > 100:
        raise ValueError("索引片段 ID 无效")
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or not 0.5 <= scale <= 2.0:
        raise ValueError("预览缩放比例必须在 0.5 到 2.0 之间")
    with open_knowledge_readonly(path) as conn:
        validate_ingestion(conn)
        row = _segment_row(conn, segment_id.strip())
        if row[4] is None or row[3] not in {"pdf_page", "pdf_line"}:
            return {"available": False, "reason": "此结果不是 PDF 页片段；请查看原文和结构化位置", "segment_id": row[0]}
        stored = _checked_source_path(path, row[19], row[17], row[18])
        region = _object(row[13])
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("PDF 预览需要 PyMuPDF") from exc
        try:
            document = fitz.open(str(stored))
        except Exception as exc:
            raise ValueError(f"原始 PDF 无法打开：{exc}") from exc
        try:
            if not document.is_pdf or document.needs_pass:
                raise ValueError("原始 PDF 格式无效或已加密")
            page_index = int(row[4]) - 1
            if page_index < 0 or page_index >= len(document):
                raise ValueError("索引中的 PDF 页码超出原始文件范围")
            page = document[page_index]
            rect = page.rect
            bbox = region.get("bbox")
            highlighted = False
            normalized_bbox = None
            if isinstance(bbox, list) and len(bbox) == 4:
                try:
                    coords = [float(v) for v in bbox]
                except (TypeError, ValueError, OverflowError):
                    coords = []
                if len(coords) == 4 and all(math.isfinite(v) for v in coords):
                    target = fitz.Rect(coords) & rect
                    if target.is_valid and not target.is_empty and target.width > 0 and target.height > 0:
                        page.draw_rect(target, color=(1, 0, 0), width=2, overlay=True)
                        highlighted = True
                        normalized_bbox = [round(target.x0 / max(rect.width, 1), 6),
                            round(target.y0 / max(rect.height, 1), 6),
                            round(target.x1 / max(rect.width, 1), 6),
                            round(target.y1 / max(rect.height, 1), 6)]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(float(scale), float(scale)), alpha=False)
            png = pixmap.tobytes("png")
            return {
                "available": True, "png": png, "filename": row[14], "pdf_page": row[4],
                "source_sha256": row[17], "storage_relpath": row[19], "highlighted": highlighted,
                "bbox": bbox, "normalized_bbox": normalized_bbox,
                "page_size": [round(float(rect.width), 2), round(float(rect.height), 2)],
                "segment_id": row[0],
            }
        finally:
            document.close()


def record_claim_review(
    path: str | Path = DEFAULT_DB, *, claim_id: str, verdict: str, reviewer_role: str,
    reviewer_name: str, method: str, notes: str, decision_state: str = "",
    actor: str = "", decision_note: str = "",
) -> dict[str, Any]:
    """Atomically append a review and optional state transition; failed acceptance rolls back both."""
    if verdict not in REVIEW_VERDICTS:
        raise ValueError("复核结论无效")
    if reviewer_role not in REVIEWER_ROLES:
        raise ValueError("复核人员类型无效")
    if decision_state and decision_state not in CLAIM_STATES:
        raise ValueError("参数主张状态无效")
    reviewer_name = _text(reviewer_name, "审核人", 100)
    method = _text(method, "复核方法", 300)
    notes = _text(notes, "复核说明", 1000)
    if decision_state:
        actor = _text(actor, "状态操作人", 100)
        decision_note = _text(decision_note, "状态说明", 500, empty=decision_state == "accepted")
    with open_database(path) as conn:
        _validate_catalog(conn)
        validate_knowledge(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            if not conn.execute("SELECT 1 FROM knowledge_claims WHERE id=?", (claim_id,)).fetchone():
                raise ValueError("参数主张不存在")
            current = _latest_state(conn, "knowledge_claim_events", "claim_id", claim_id, "")
            review_id = _id()
            conn.execute("""INSERT INTO knowledge_claim_reviews(id,claim_id,verdict,reviewer_role,
                reviewer_name,method,notes,created_utc) VALUES(?,?,?,?,?,?,?,?)""",
                (review_id, claim_id, verdict, reviewer_role, reviewer_name, method, notes, _now()))
            if verdict == "contradicts" and current == "accepted":
                conn.execute("""INSERT INTO knowledge_claim_events(claim_id,state,actor,note,created_utc)
                    VALUES(?,?,?,?,?)""", (claim_id, "reopened", reviewer_name, "新增反对性复核，重新审查", _now()))
                current = "reopened"
            if decision_state:
                if decision_state not in _ALLOWED_TRANSITIONS.get(current, set()):
                    raise ValueError(f"不允许主张状态从{current or '未知'}变更为{decision_state}")
                conn.execute("""INSERT INTO knowledge_claim_events(claim_id,state,actor,note,created_utc)
                    VALUES(?,?,?,?,?)""", (claim_id, decision_state, actor, decision_note, _now()))
            final_state = _latest_state(conn, "knowledge_claim_events", "claim_id", claim_id, "unknown")
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise ValueError(f"主张状态校验未通过：{exc}") from exc
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return {"review_id": review_id, "claim_id": claim_id, "state": final_state,
            "decision_applied": bool(decision_state), "verdict": verdict}
