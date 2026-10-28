"""Read-only model reconciliation and fail-closed content evidence gate for V13."""
from __future__ import annotations

import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .catalog_v12 import _validate_catalog
from .database_v9 import DEFAULT_DB
from .knowledge_ingest_v13 import validate_ingestion
from .knowledge_schema_v13 import open_knowledge_readonly

_MAX_SOURCE_SCAN = 10000
_TRUSTED_AUTHORITIES = {"manufacturer_controlled", "independent_test"}
_TRUSTED_REVIEWERS = {"second_reviewer", "manufacturer", "independent_lab"}
_TRUSTED_MAPPING_AUTHORITIES = {
    "manufacturer_controlled", "independent_test", "user_supplied", "system_export",
}
_ACTIVE_STATES = {"proposed", "accepted", "reopened", "unknown"}
_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-"})


def normalize_model_code(value: str) -> str:
    """Normalize spacing, Unicode compatibility forms and dash variants, not model suffixes."""
    if not isinstance(value, str):
        raise ValueError("型号必须是文本")
    text = unicodedata.normalize("NFKC", value).translate(_DASHES).upper()
    text = re.sub(r"\s*([./_\-])\s*", r"\1", text)
    text = re.sub(r"\s+", "", text)
    if not text or len(text) > 100 or any(ord(char) < 32 for char in text):
        raise ValueError("型号为空、包含控制字符或超过100字")
    return text


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).translate(_DASHES).upper()
    text = re.sub(r"\s*([./_\-])\s*", r"\1", text)
    return re.sub(r"\s+", " ", text)


def _contains_exact_model(text: str, model_code: str) -> bool:
    """Require token boundaries so GL1-336 does not match GL1-336A or GL1-336-Z."""
    code = normalize_model_code(model_code)
    pattern = r"(?<![A-Z0-9_.\-])" + re.escape(code) + r"(?![A-Z0-9_.\-])"
    return re.search(pattern, _normalize_text(text)) is not None


def _object(value: Any) -> dict[str, Any]:
    try:
        result = json.loads(value) if isinstance(value, str) else value
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def _unit_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = text.replace("·", ".").replace("⋅", ".")
    return re.sub(r"\s+", "", text)


def _value_key(claim: dict[str, Any]) -> str:
    try:
        value = json.loads(claim["normalized_value_json"])
    except (TypeError, ValueError, KeyError):
        value = None
    if value is None:
        value = claim.get("literal_value", "")
    if isinstance(value, bool):
        rendered = "bool:" + str(value).lower()
    elif isinstance(value, (int, float, Decimal)):
        try:
            rendered = "number:" + str(Decimal(str(value)).normalize())
        except InvalidOperation:
            rendered = "raw:" + str(value).strip().casefold()
    elif isinstance(value, str):
        candidate = value.strip()
        try:
            number = Decimal(candidate.replace(",", ""))
            rendered = "number:" + str(number.normalize())
        except InvalidOperation:
            rendered = "text:" + re.sub(r"\s+", " ", unicodedata.normalize("NFKC", candidate)).casefold()
    else:
        rendered = "json:" + json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return rendered + "|unit:" + _unit_key(claim.get("unit", ""))


def _has_locator(evidence: dict[str, Any]) -> bool:
    region = evidence.get("region") or {}
    return bool(
        evidence.get("pdf_page")
        or evidence.get("printed_page")
        or region.get("segment_id")
        or region.get("line_start")
        or region.get("cell_range")
        or region.get("sheet_name")
        or region.get("bbox")
    )


def _evidence_ready(claim: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    evidence = claim.get("evidence", [])
    reviews = claim.get("reviews", [])
    trusted_support = [
        item for item in evidence
        if item["role"] == "supports"
        and item["authority_level"] in _TRUSTED_AUTHORITIES
        and item["literal_excerpt"].strip()
        and _has_locator(item)
    ]
    independent_support = [
        item for item in reviews
        if item["verdict"] == "supports" and item["reviewer_role"] in _TRUSTED_REVIEWERS
    ]
    if claim.get("state") != "accepted":
        reasons.append("参数主张尚未处于 accepted 状态")
    if not trusted_support:
        reasons.append("缺少带原文定位的制造商受控资料或独立测试支持证据")
    if not independent_support:
        reasons.append("缺少第二复核人、制造商或独立实验室的支持性复核")
    if any(item["role"] == "contradicts" for item in evidence):
        reasons.append("存在反对性来源证据")
    if any(item["verdict"] == "contradicts" for item in reviews):
        reasons.append("存在反对性复核记录")
    if claim.get("claim_kind") == "system_inference":
        reasons.append("系统推断不能直接作为商品参数宣传")
    return not reasons, reasons


def _read_source_mentions(conn, model_code: str, limit: int) -> tuple[list[dict[str, Any]], int, int, bool]:
    code = normalize_model_code(model_code)
    compact_code = re.sub(r"[^A-Z0-9]", "", code)
    if not compact_code:
        sql = """SELECT d.id,d.source_id,d.segment_type,d.pdf_page,d.printed_page,d.sheet_name,
            d.cell_range,d.line_start,d.line_end,d.heading_path,d.text,d.text_sha256,d.region_json,
            s.original_filename,s.source_kind,s.authority_level,s.sha256,s.storage_ref,s.document_family
            FROM knowledge_document_segments d JOIN knowledge_sources s ON s.id=d.source_id
            WHERE INSTR(UPPER(d.text),UPPER(?))>0 ORDER BY s.created_utc DESC,d.ordinal LIMIT ?"""
        rows = conn.execute(sql, (model_code, _MAX_SOURCE_SCAN + 1)).fetchall()
    else:
        compact_text = (
            "UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("
            "REPLACE(REPLACE(REPLACE(REPLACE(UPPER(d.text),' ',''),char(9),''),char(10),''),"
            "char(13),''),'-',''),'–',''),'—',''),'−',''),'.',''),'_',''),'/',''),':',''))"
        )
        sql = f"""SELECT d.id,d.source_id,d.segment_type,d.pdf_page,d.printed_page,d.sheet_name,
            d.cell_range,d.line_start,d.line_end,d.heading_path,d.text,d.text_sha256,d.region_json,
            s.original_filename,s.source_kind,s.authority_level,s.sha256,s.storage_ref,s.document_family
            FROM knowledge_document_segments d JOIN knowledge_sources s ON s.id=d.source_id
            WHERE INSTR(UPPER(d.text),UPPER(?))>0 OR INSTR({compact_text},?)>0
            ORDER BY s.created_utc DESC,d.ordinal LIMIT ?"""
        rows = conn.execute(sql, (model_code, compact_code, _MAX_SOURCE_SCAN + 1)).fetchall()
    truncated = len(rows) > _MAX_SOURCE_SCAN
    rows = rows[:_MAX_SOURCE_SCAN]
    exact = [row for row in rows if _contains_exact_model(row[10], model_code)]
    source_ids = {row[1] for row in exact}
    results = []
    for row in exact[:limit]:
        region = _object(row[12])
        results.append({
            "segment_id": row[0], "source_id": row[1], "segment_type": row[2],
            "pdf_page": row[3], "printed_page": row[4] or None, "sheet_name": row[5] or None,
            "cell_range": row[6] or None, "line_start": row[7], "line_end": row[8],
            "heading_path": row[9] or None, "excerpt": row[10][:600],
            "text_sha256": row[11], "region": region, "filename": row[13],
            "source_kind": row[14], "authority_level": row[15], "source_sha256": row[16],
            "storage_ref": row[17], "document_family": row[18],
        })
    return results, len(exact), len(source_ids), truncated


def _load_claims(conn, model_id: str) -> list[dict[str, Any]]:
    links = conn.execute("""SELECT l.id,l.sku_id,s.code,s.model,p.name,p.category,st.name,
        e.state,e.actor,e.note,e.source_id,src.original_filename,src.authority_level,src.sha256,
        (SELECT COUNT(DISTINCT l2.model_id) FROM catalog_sku_model_links l2
         WHERE l2.sku_id=l.sku_id AND
         (SELECT ev2.state FROM catalog_sku_model_events ev2 WHERE ev2.link_id=l2.id
          ORDER BY ev2.event_id DESC LIMIT 1)='confirmed')
        FROM catalog_sku_model_links l
        JOIN catalog_skus s ON s.id=l.sku_id
        JOIN catalog_products p ON p.id=s.product_id
        JOIN catalog_stores st ON st.id=s.store_id
        LEFT JOIN catalog_sku_model_events e ON e.event_id=(
          SELECT ev.event_id FROM catalog_sku_model_events ev WHERE ev.link_id=l.id
          ORDER BY ev.event_id DESC LIMIT 1)
        LEFT JOIN knowledge_sources src ON src.id=e.source_id
        WHERE l.model_id=? ORDER BY l.created_utc,l.id""", (model_id,)).fetchall()
    mappings = [{
        "link_id": r[0], "sku_id": r[1], "sku_code": r[2], "sku_model_text": r[3],
        "product_name": r[4], "category": r[5], "store_name": r[6], "state": r[7] or "unknown",
        "actor": r[8], "note": r[9], "source_id": r[10], "source_filename": r[11],
        "source_authority_level": r[12], "source_sha256": r[13], "confirmed_model_count": r[14],
    } for r in links]
    confirmed_skus = sorted({item["sku_id"] for item in mappings if item["state"] == "confirmed"})
    params: list[Any] = [model_id]
    subject_sql = "c.subject_type='model' AND c.subject_id=?"
    if confirmed_skus:
        subject_sql += " OR (c.subject_type='sku' AND c.subject_id IN (" + ",".join("?" for _ in confirmed_skus) + "))"
        params.extend(confirmed_skus)
    rows = conn.execute(f"""SELECT c.id,c.subject_type,c.subject_id,c.attribute,c.literal_value,
        c.normalized_value_json,c.unit,c.claim_kind,c.created_by,c.created_utc,c.supersedes_claim_id,
        COALESCE((SELECT e.state FROM knowledge_claim_events e WHERE e.claim_id=c.id
          ORDER BY e.event_id DESC LIMIT 1),'unknown')
        FROM knowledge_claims c WHERE ({subject_sql}) ORDER BY c.created_utc,c.id""", params).fetchall()
    claims = [{
        "claim_id": r[0], "subject_type": r[1], "subject_id": r[2], "attribute": r[3],
        "literal_value": r[4], "normalized_value_json": r[5], "unit": r[6], "claim_kind": r[7],
        "created_by": r[8], "created_utc": r[9], "supersedes_claim_id": r[10], "state": r[11],
        "evidence": [], "reviews": [],
    } for r in rows]
    by_id = {item["claim_id"]: item for item in claims}
    if not by_id:
        return mappings, claims
    ids = list(by_id)
    placeholders = ",".join("?" for _ in ids)
    evidence_rows = conn.execute(f"""SELECT e.claim_id,e.id,e.source_id,e.evidence_role,e.pdf_page,
        e.printed_page,e.region_json,e.literal_excerpt,e.extraction_method,e.confidence_note,
        s.original_filename,s.source_kind,s.authority_level,s.sha256,s.storage_ref,s.document_family
        FROM knowledge_claim_evidence e JOIN knowledge_sources s ON s.id=e.source_id
        WHERE e.claim_id IN ({placeholders}) ORDER BY e.created_utc,e.id""", ids).fetchall()
    for r in evidence_rows:
        by_id[r[0]]["evidence"].append({
            "evidence_id": r[1], "source_id": r[2], "role": r[3], "pdf_page": r[4],
            "printed_page": r[5] or None, "region": _object(r[6]), "literal_excerpt": r[7],
            "extraction_method": r[8], "confidence_note": r[9], "filename": r[10],
            "source_kind": r[11], "authority_level": r[12], "source_sha256": r[13],
            "storage_ref": r[14], "document_family": r[15],
        })
    review_rows = conn.execute(f"""SELECT claim_id,id,verdict,reviewer_role,reviewer_name,
        method,notes,created_utc FROM knowledge_claim_reviews
        WHERE claim_id IN ({placeholders}) ORDER BY created_utc,id""", ids).fetchall()
    for r in review_rows:
        by_id[r[0]]["reviews"].append({
            "review_id": r[1], "verdict": r[2], "reviewer_role": r[3],
            "reviewer_name": r[4], "method": r[5], "notes": r[6], "created_utc": r[7],
        })
    return mappings, claims


def _annotate_conflicts(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        if claim["state"] in _ACTIVE_STATES:
            key = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", claim["attribute"])).strip().casefold()
            groups.setdefault(key, []).append(claim)
    conflicts = []
    conflicted_attributes = set()
    for key, group in groups.items():
        values: dict[str, list[dict[str, Any]]] = {}
        for claim in group:
            values.setdefault(_value_key(claim), []).append(claim)
        if len(values) > 1:
            conflicted_attributes.add(key)
            conflicts.append({
                "attribute": group[0]["attribute"], "normalized_attribute": key,
                "distinct_value_count": len(values),
                "claims": [{
                    "claim_id": c["claim_id"], "subject_type": c["subject_type"],
                    "subject_id": c["subject_id"], "literal_value": c["literal_value"],
                    "unit": c["unit"], "state": c["state"],
                    "sources": [{
                        "source_id": e["source_id"], "filename": e["filename"],
                        "authority_level": e["authority_level"], "role": e["role"],
                        "pdf_page": e["pdf_page"], "printed_page": e["printed_page"],
                        "excerpt": e["literal_excerpt"][:300],
                    } for e in c["evidence"]],
                } for c in group],
                "resolution_required": True,
                "note": "检测到不同原始值；不自动换算单位、不自动选择来源，需人工复核。",
            })
    for claim in claims:
        key = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", claim["attribute"])).strip().casefold()
        ready, reasons = _evidence_ready(claim)
        claim["evidence_ready"] = ready
        claim["evidence_gate_reasons"] = reasons
        claim["attribute_conflict"] = key in conflicted_attributes
        claim["can_use_for_content"] = ready and key not in conflicted_attributes
    return conflicts


def reconcile_model_evidence(
    path: str | Path = DEFAULT_DB, *, model_code: str, manufacturer_name: str = "", limit: int = 100,
) -> dict[str, Any]:
    """Read-only report of exact model mentions, SKU mappings, claims, sources and conflicts."""
    code = normalize_model_code(model_code)
    if not isinstance(manufacturer_name, str) or len(manufacturer_name) > 200:
        raise ValueError("制造商筛选条件无效")
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("limit 必须在 1 到 500 之间")
    manufacturer = unicodedata.normalize("NFKC", manufacturer_name).strip().casefold()
    with open_knowledge_readonly(path) as conn:
        _validate_catalog(conn)
        validate_ingestion(conn)
        all_models = conn.execute("""SELECT id,manufacturer_name,model_code,category,series,created_utc
            FROM catalog_models ORDER BY manufacturer_name,model_code LIMIT 5000""").fetchall()
        matches = [r for r in all_models if normalize_model_code(r[2]) == code
                   and (not manufacturer or unicodedata.normalize("NFKC", r[1]).strip().casefold() == manufacturer)]
        source_mentions, source_mention_count, source_count, truncated = _read_source_mentions(conn, model_code, limit)
        sku_rows = conn.execute("""SELECT s.id,s.code,s.model,s.specs_json,s.active,p.code,p.name,p.category,
            st.code,st.name FROM catalog_skus s JOIN catalog_products p ON p.id=s.product_id
            JOIN catalog_stores st ON st.id=s.store_id ORDER BY st.code,p.code,s.code LIMIT 5000""").fetchall()
        sku_candidates = [{
            "sku_id": r[0], "sku_code": r[1], "sku_model_text": r[2], "specs": _object(r[3]),
            "active": bool(r[4]), "product_code": r[5], "product_name": r[6],
            "category": r[7], "store_code": r[8], "store_name": r[9],
        } for r in sku_rows if normalize_model_code(r[2]) == code]
        model_reports = []
        for row in matches:
            mappings, claims = _load_claims(conn, row[0])
            conflicts = _annotate_conflicts(claims)
            confirmed_ids = {m["sku_id"] for m in mappings if m["state"] == "confirmed"}
            for sku in sku_candidates:
                if sku["sku_id"] not in confirmed_ids:
                    sku["confirmed_for_this_model"] = False
            model_reports.append({
                "model_id": row[0], "manufacturer_name": row[1], "model_code": row[2],
                "category": row[3], "series": row[4], "created_utc": row[5],
                "mappings": mappings, "confirmed_sku_count": len(confirmed_ids),
                "claims": claims, "conflicts": conflicts,
            })
        matched_ids = {row["model_id"] for row in model_reports}
        for sku in sku_candidates:
            if not matched_ids:
                sku["mapping_review_status"] = "no_registered_model_identity"
            elif len(matched_ids) > 1:
                sku["mapping_review_status"] = "ambiguous_model_identity"
            elif not sku.get("confirmed_for_this_model", False):
                sku["mapping_review_status"] = "candidate_unconfirmed"
            else:
                sku["mapping_review_status"] = "confirmed"
        return {
            "schema_version": "1.0", "model_query": model_code,
            "manufacturer_filter": manufacturer_name.strip(), "model_found": bool(model_reports),
            "model_identity_count": len(model_reports), "ambiguous_model_identity": len(model_reports) > 1,
            "models": model_reports, "source_mentions": source_mentions,
            "source_mention_count": source_mention_count, "source_count": source_count,
            "source_search_truncated": truncated, "sku_candidates": sku_candidates,
            "all_claims_can_use_for_content": bool(model_reports) and not any(
                conflict for item in model_reports for conflict in item["conflicts"]
            ) and all(claim["can_use_for_content"] for item in model_reports for claim in item["claims"]
                      if claim["state"] == "accepted"),
            "note": "只读核对报告；来源命中不等于参数已验证，SKU 文本匹配不会自动创建型号关联。",
        }


def evaluate_content_gate(
    path: str | Path = DEFAULT_DB, *, model_code: str, required_attributes: list[str],
    manufacturer_name: str = "", sku_id: str = "",
) -> dict[str, Any]:
    """Fail closed unless every requested parameter has accepted, traceable, non-conflicting evidence."""
    if not isinstance(required_attributes, list) or not required_attributes or len(required_attributes) > 20:
        raise ValueError("required_attributes 必须是1到20项的参数名称列表")
    attributes = []
    for item in required_attributes:
        if not isinstance(item, str) or not item.strip() or len(item) > 150:
            raise ValueError("参数名称无效")
        key = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", item)).strip().casefold()
        if key not in attributes:
            attributes.append(key)
    report = reconcile_model_evidence(
        path, model_code=model_code, manufacturer_name=manufacturer_name, limit=500,
    )
    reasons: list[str] = []
    approved_claims: list[dict[str, Any]] = []
    if report["model_identity_count"] != 1:
        reasons.append("型号未登记或制造商身份不唯一，阻止商品参数内容生成")
        return {
            "allowed": False, "status": "blocked", "model_code": report["model_query"],
            "sku_id": sku_id or None, "approved_claims": [], "blocked_attributes": required_attributes,
            "reasons": reasons, "reconciliation": report,
        }
    model = report["models"][0]
    if sku_id:
        matching = [m for m in model["mappings"] if m["sku_id"] == sku_id and m["state"] == "confirmed"]
        if not matching:
            reasons.append("SKU 与制造商型号没有经过来源证据确认的显式映射")
        elif any(m["confirmed_model_count"] != 1 for m in matching):
            reasons.append("该 SKU 被确认映射到多个制造商型号，身份冲突未解决")
        elif matching[0]["source_authority_level"] not in _TRUSTED_MAPPING_AUTHORITIES:
            reasons.append("SKU/型号映射来源仍未验证或权威级别不足")
    for attribute_key in attributes:
        attr_claims = [
            claim for claim in model["claims"]
            if re.sub(r"\s+", " ", unicodedata.normalize("NFKC", claim["attribute"])).strip().casefold() == attribute_key
            and claim["state"] == "accepted"
            and (claim["subject_type"] == "model" or (sku_id and claim["subject_type"] == "sku" and claim["subject_id"] == sku_id))
        ]
        conflict = next((c for c in model["conflicts"] if c["normalized_attribute"] == attribute_key), None)
        if conflict:
            reasons.append(f"参数“{attribute_key}”存在跨来源/跨 SKU 数值冲突，必须先解决")
            continue
        eligible = [claim for claim in attr_claims if claim["can_use_for_content"]]
        if not eligible:
            reasons.append(f"参数“{attribute_key}”没有满足来源、定位、独立复核和无冲突条件的 accepted 主张")
            continue
        eligible.sort(key=lambda item: (len(item["evidence"]), item["created_utc"]), reverse=True)
        claim = eligible[0]
        approved_claims.append({
            "claim_id": claim["claim_id"], "subject_type": claim["subject_type"],
            "subject_id": claim["subject_id"], "attribute": claim["attribute"],
            "literal_value": claim["literal_value"], "unit": claim["unit"],
            "source_evidence": [{
                "source_id": e["source_id"], "filename": e["filename"],
                "source_sha256": e["source_sha256"], "authority_level": e["authority_level"],
                "pdf_page": e["pdf_page"], "printed_page": e["printed_page"],
                "region": e["region"], "literal_excerpt": e["literal_excerpt"],
            } for e in claim["evidence"] if e["role"] == "supports"],
        })
    allowed = not reasons and len(approved_claims) == len(attributes)
    return {
        "allowed": allowed, "status": "approved" if allowed else "blocked",
        "model_id": model["model_id"], "manufacturer_name": model["manufacturer_name"],
        "model_code": model["model_code"], "sku_id": sku_id or None,
        "required_attributes": required_attributes, "approved_claims": approved_claims,
        "blocked_attributes": [a for a in required_attributes if not any(
            c["attribute"].casefold() == a.casefold() for c in approved_claims
        )], "reasons": reasons,
        "note": "门禁只批准报告中的具体参数与来源；不要把未列入 approved_claims 的规格或功效补写到商品图文。",
    }
