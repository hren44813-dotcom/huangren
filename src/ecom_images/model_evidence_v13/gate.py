"""Fail-closed gate for verified product facts used in image/content production."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from ..database_v9 import DEFAULT_DB
from .reconcile import reconcile_model_evidence

_TRUSTED_MAPPING_AUTHORITIES = {
    "manufacturer_controlled", "independent_test", "user_supplied", "system_export",
}

def evaluate_content_gate(
    path: str | Path = DEFAULT_DB, *, model_code: str, required_attributes: list[str],
    manufacturer_name: str = "", sku_id: str = "",
) -> dict[str, Any]:
    """Fail closed unless every requested parameter has accepted, traceable, non-conflicting evidence."""
    if not isinstance(required_attributes, list) or not required_attributes or len(required_attributes) > 20:
        raise ValueError("required_attributes 必须是1到20项的参数名称列表")
    attributes = []
    attribute_labels: dict[str, str] = {}
    for item in required_attributes:
        if not isinstance(item, str) or not item.strip() or len(item) > 150:
            raise ValueError("参数名称无效")
        key = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", item)).strip().casefold()
        if key not in attributes:
            attributes.append(key)
            attribute_labels[key] = item.strip()
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
        elif not matching[0]["source_bytes_verified"]:
            reasons.append("SKU/型号映射来源原始文件缺失或 SHA-256/文件大小与登记值不一致")
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
            reasons.append(f"参数“{attribute_labels.get(attribute_key, attribute_key)}”存在跨来源/跨 SKU 数值冲突，必须先解决")
            continue
        eligible = [claim for claim in attr_claims if claim["can_use_for_content"]]
        if not eligible:
            reasons.append(f"参数“{attribute_labels.get(attribute_key, attribute_key)}”没有满足来源、定位、独立复核和无冲突条件的 accepted 主张")
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
        "blocked_attributes": [a for a in required_attributes if re.sub(
            r"\s+", " ", unicodedata.normalize("NFKC", a)).strip().casefold()
            not in {re.sub(r"\s+", " ", unicodedata.normalize("NFKC", c["attribute"])).strip().casefold()
                    for c in approved_claims}], "reasons": reasons,
        "note": "门禁只批准报告中的具体参数与来源；不要把未列入 approved_claims 的规格或功效补写到商品图文。",
    }
