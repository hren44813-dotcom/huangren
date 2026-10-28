"""Read-only V13 source, SKU mapping, claim and parameter-conflict reconciliation."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from ..catalog_v12 import _validate_catalog
from ..database_v9 import DEFAULT_DB
from ..knowledge_ingest_v13 import validate_ingestion
from ..knowledge_schema_v13 import open_knowledge_readonly
from ..knowledge_review_v13 import _checked_source_path
from .normalize import (
    _ACTIVE_STATES, _contains_exact_model, _object, _value_key,
    _evidence_ready, normalize_model_code,
)

_MAX_SOURCE_SCAN = 5000

def _verify_source_file(database_path: str | Path, storage_ref: str, expected_sha: str, expected_size: int) -> tuple[bool, str]:
    try:
        _checked_source_path(database_path, storage_ref, expected_sha, expected_size)
        return True, ""
    except (OSError, ValueError, RuntimeError) as exc:
        return False, str(exc)


def _read_source_mentions(conn, model_code: str, limit: int, database_path: str | Path) -> tuple[list[dict[str, Any]], int, int, bool]:
    code = normalize_model_code(model_code)
    compact_code = re.sub(r"[^A-Z0-9]", "", code)
    if not compact_code:
        sql = """SELECT d.id,d.source_id,d.segment_type,d.pdf_page,d.printed_page,d.sheet_name,
            d.cell_range,d.line_start,d.line_end,d.heading_path,d.text,d.text_sha256,d.region_json,
            s.original_filename,s.source_kind,s.authority_level,s.sha256,s.storage_ref,s.document_family,s.size_bytes
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
            s.original_filename,s.source_kind,s.authority_level,s.sha256,s.storage_ref,s.document_family,s.size_bytes
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
        source_verified, source_error = _verify_source_file(database_path, row[17], row[16], row[19])
        results.append({
            "segment_id": row[0], "source_id": row[1], "segment_type": row[2],
            "pdf_page": row[3], "printed_page": row[4] or None, "sheet_name": row[5] or None,
            "cell_range": row[6] or None, "line_start": row[7], "line_end": row[8],
            "heading_path": row[9] or None, "excerpt": row[10][:600],
            "text_sha256": row[11], "region": region, "filename": row[13],
            "source_kind": row[14], "authority_level": row[15], "source_sha256": row[16],
            "storage_ref": row[17], "document_family": row[18], "source_size_bytes": row[19],
            "source_bytes_verified": source_verified,
            "source_verification_error": source_error,
        })
    return results, len(exact), len(source_ids), truncated


def _load_claims(conn, model_id: str, database_path: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    links = conn.execute("""SELECT l.id,l.sku_id,s.code,s.model,p.name,p.category,st.name,
        e.state,e.actor,e.note,e.source_id,src.original_filename,src.authority_level,src.sha256,src.storage_ref,src.size_bytes,
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
    mappings = []
    for r in links:
        verified, verification_error = _verify_source_file(database_path, r[14] or "", r[13] or "", r[15] or 0)
        mappings.append({
            "link_id": r[0], "sku_id": r[1], "sku_code": r[2], "sku_model_text": r[3],
            "product_name": r[4], "category": r[5], "store_name": r[6], "state": r[7] or "unknown",
            "actor": r[8], "note": r[9], "source_id": r[10], "source_filename": r[11],
            "source_authority_level": r[12], "source_sha256": r[13], "source_storage_ref": r[14],
            "source_size_bytes": r[15], "source_bytes_verified": verified,
            "source_verification_error": verification_error, "confirmed_model_count": r[16],
        })
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
        s.original_filename,s.source_kind,s.authority_level,s.sha256,s.storage_ref,s.document_family,s.size_bytes
        FROM knowledge_claim_evidence e JOIN knowledge_sources s ON s.id=e.source_id
        WHERE e.claim_id IN ({placeholders}) ORDER BY e.created_utc,e.id""", ids).fetchall()
    for r in evidence_rows:
        region = _object(r[6])
        source_verified, source_error = _verify_source_file(database_path, r[14], r[13], r[16])
        segment_verified = None
        segment_id = region.get("segment_id")
        if segment_id:
            segment = conn.execute(
                "SELECT source_id,text,text_sha256 FROM knowledge_document_segments WHERE id=?",
                (segment_id,),
            ).fetchone()
            segment_verified = bool(
                segment and segment[0] == r[2]
                and hashlib.sha256(segment[1].encode("utf-8")).hexdigest() == segment[2]
                and r[7] == segment[1][:1000]
                and region.get("source_sha256") == r[13]
            )
        by_id[r[0]]["evidence"].append({
            "evidence_id": r[1], "source_id": r[2], "role": r[3], "pdf_page": r[4],
            "printed_page": r[5] or None, "region": region, "literal_excerpt": r[7],
            "extraction_method": r[8], "confidence_note": r[9], "filename": r[10],
            "source_kind": r[11], "authority_level": r[12], "source_sha256": r[13],
            "storage_ref": r[14], "document_family": r[15], "source_size_bytes": r[16],
            "source_bytes_verified": source_verified, "source_verification_error": source_error,
            "segment_hash_verified": segment_verified,
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
            FROM catalog_models ORDER BY manufacturer_name,model_code""").fetchall()
        matches = [r for r in all_models if normalize_model_code(r[2]) == code
                   and (not manufacturer or unicodedata.normalize("NFKC", r[1]).strip().casefold() == manufacturer)]
        source_mentions, source_mention_count, source_count, truncated = _read_source_mentions(conn, model_code, limit, path)
        sku_rows = conn.execute("""SELECT s.id,s.code,s.model,s.specs_json,s.active,p.code,p.name,p.category,
            st.code,st.name FROM catalog_skus s JOIN catalog_products p ON p.id=s.product_id
            JOIN catalog_stores st ON st.id=s.store_id ORDER BY st.code,p.code,s.code""").fetchall()
        sku_candidates = [{
            "sku_id": r[0], "sku_code": r[1], "sku_model_text": r[2], "specs": _object(r[3]),
            "active": bool(r[4]), "product_code": r[5], "product_name": r[6],
            "category": r[7], "store_code": r[8], "store_name": r[9],
        } for r in sku_rows if r[2].strip() and normalize_model_code(r[2]) == code]
        model_reports = []
        for row in matches:
            mappings, claims = _load_claims(conn, row[0], path)
            conflicts = _annotate_conflicts(claims)
            confirmed_ids = {m["sku_id"] for m in mappings if m["state"] == "confirmed"}
            for sku in sku_candidates:
                sku.setdefault("confirmed_for_model_ids", [])
                if sku["sku_id"] in confirmed_ids:
                    sku["confirmed_for_model_ids"].append(row[0])
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
            elif matched_ids.intersection(sku.get("confirmed_for_model_ids", [])):
                sku["mapping_review_status"] = "confirmed"
            else:
                sku["mapping_review_status"] = "candidate_unconfirmed"
        return {
            "schema_version": "1.0", "model_query": model_code,
            "manufacturer_filter": manufacturer_name.strip(), "model_found": bool(model_reports),
            "model_identity_count": len(model_reports), "ambiguous_model_identity": len(model_reports) > 1,
            "models": model_reports, "source_mentions": source_mentions,
            "source_mention_count": source_mention_count, "source_count": source_count,
            "source_search_truncated": truncated, "sku_candidates": sku_candidates,
            "all_claims_can_use_for_content": bool(model_reports)
                and any(claim["state"] == "accepted" for item in model_reports for claim in item["claims"])
                and not any(conflict for item in model_reports for conflict in item["conflicts"])
                and all(claim["can_use_for_content"] for item in model_reports for claim in item["claims"]
                        if claim["state"] == "accepted"),
            "note": "只读核对报告；来源命中不等于参数已验证，SKU 文本匹配不会自动创建型号关联。",
        }
