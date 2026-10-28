"""Pre-render validation for image-job text explicitly bound to reviewed V13 claims."""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .database_v9 import DEFAULT_DB

_FIELD_INDEX = re.compile(r"^(selling_points|specs)\[(\d+)\](?:\.value)?$")
_SPEC_VALUE = re.compile(r"^specs\[(\d+)\]\.value$")
_SIMPLE_FIELDS = {"title", "subtitle", "label"}


def _norm_text(value: str, *, preserve_case: bool = False) -> str:
    text = unicodedata.normalize("NFKC", value).replace("·", ".").replace("⋅", ".")
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = re.sub(r"\s*([./_\-])\s*", r"\1", text)
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized if preserve_case else normalized.casefold()


def _contains_value(field_text: str, value: str, unit: str) -> bool:
    # SI prefixes are case-sensitive: MN.m and mN.m have different magnitudes.
    # Preserve case throughout paired value/unit matching; ordinary text fields
    # without units continue to use the previous case-insensitive behavior.
    has_unit = bool(unit.strip())
    haystack = _norm_text(field_text, preserve_case=has_unit)
    needle = _norm_text(value, preserve_case=has_unit)
    if not needle:
        return False
    numeric = False
    try:
        target = Decimal(value.strip().replace(",", ""))
        numeric = target.is_finite()
    except (InvalidOperation, ValueError):
        target = Decimal(0)
    if numeric:
        rendered = format(target.normalize(), "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        token = re.escape(rendered) + r"(?:\.0+)?"
    else:
        token = re.escape(needle)
    left = r"(?<![a-z0-9_.\-])"
    right = r"(?![a-z0-9_.\-])"
    unit_key = re.sub(r"\s+", "", _norm_text(unit, preserve_case=True))
    if not unit_key:
        return re.search(left + token + right, haystack) is not None
    # A reviewed value and unit must occur together, not as unrelated substrings:
    # "6 kN.m" and "6 pcs, 8 N.m" must never satisfy "6 N.m".
    return re.search(left + token + r"\s*" + re.escape(unit_key) + right, haystack) is not None


def _field_text(job: dict[str, Any], field: str) -> str:
    if field in _SIMPLE_FIELDS:
        value = job.get(field, "")
        return value if isinstance(value, str) else ""
    spec_match = _SPEC_VALUE.fullmatch(field)
    if spec_match:
        specs = job.get("specs")
        index = int(spec_match.group(1))
        if not isinstance(specs, list) or index >= len(specs) or not isinstance(specs[index], dict):
            return ""
        return str(specs[index].get("value", ""))
    match = _FIELD_INDEX.fullmatch(field)
    if match and match.group(1) == "selling_points" and ".value" not in field:
        values = job.get("selling_points")
        index = int(match.group(2))
        if isinstance(values, list) and index < len(values) and isinstance(values[index], str):
            return values[index]
    raise ValueError(f"不支持的证据绑定字段：{field}")


def verify_job_evidence_gate(job: dict[str, Any], base: Path) -> dict[str, Any] | None:
    """Verify explicit text-to-claim bindings before a deterministic image is written."""
    config = job.get("evidence_gate")
    from .model_evidence_reconciliation_v13 import evaluate_content_gate
    if config is None:
        return None
    if not isinstance(config, dict):
        raise ValueError("evidence_gate 必须是 JSON 对象")
    allowed_keys = {"database", "model_code", "manufacturer_name", "sku_id", "bindings"}
    if set(config) - allowed_keys:
        raise ValueError("evidence_gate 包含未知字段")
    model_code = config.get("model_code")
    if not isinstance(model_code, str) or not model_code.strip():
        raise ValueError("evidence_gate 必须填写 model_code")
    bindings = config.get("bindings")
    if not isinstance(bindings, list) or not 1 <= len(bindings) <= 20:
        raise ValueError("evidence_gate.bindings 必须包含1到20条文本绑定")
    clean_bindings = []
    seen_fields = set()
    attributes = []
    for item in bindings:
        if not isinstance(item, dict) or set(item) != {"field", "attribute"}:
            raise ValueError("每条证据绑定必须且只能包含 field 和 attribute")
        field, attribute = item["field"], item["attribute"]
        if not isinstance(field, str) or not isinstance(attribute, str) or not attribute.strip() or len(attribute) > 150:
            raise ValueError("证据绑定的字段路径或参数名称无效")
        if field in seen_fields:
            raise ValueError(f"同一文本字段不能重复绑定：{field}")
        seen_fields.add(field)
        field_text = _field_text(job, field)
        if not field_text.strip():
            raise ValueError(f"已绑定的文本字段为空：{field}")
        spec_match = _SPEC_VALUE.fullmatch(field)
        if spec_match:
            specs = job.get("specs")
            spec_label = specs[int(spec_match.group(1))].get("label", "")
            if _norm_text(str(spec_label)) != _norm_text(attribute):
                raise ValueError(f"{field} 的规格标签必须与证据参数名称一致")
        clean_bindings.append({"field": field, "attribute": attribute.strip(), "field_text": field_text})
        if attribute.strip().casefold() not in {a.casefold() for a in attributes}:
            attributes.append(attribute.strip())
    database = config.get("database")
    database_path = DEFAULT_DB if database is None else Path(str(database))
    if not database_path.is_absolute():
        database_path = (base / database_path).resolve()
    gate = evaluate_content_gate(
        database_path, model_code=model_code,
        manufacturer_name=str(config.get("manufacturer_name", "")),
        sku_id=str(config.get("sku_id", "")), required_attributes=attributes,
    )
    if not gate["allowed"]:
        reasons = "；".join(gate.get("reasons", [])) or "证据门禁未通过"
        raise ValueError(f"商品图片证据门禁已阻止生成：{reasons}")
    approved = {item["attribute"].strip().casefold(): item for item in gate["approved_claims"]}
    audit_bindings = []
    for binding in clean_bindings:
        claim = approved.get(binding["attribute"].casefold())
        if not claim:
            raise ValueError(f"参数“{binding['attribute']}”没有可用的已审核主张")
        if not _contains_value(binding["field_text"], claim["literal_value"], claim["unit"]):
            raise ValueError(
                f"文本字段 {binding['field']} 与已审核参数不一致；"
                f"该字段必须明确包含来源记录中的值“{claim['literal_value']} {claim['unit']}”."
            )
        audit_bindings.append({
            "field": binding["field"], "attribute": binding["attribute"],
            "claim_id": claim["claim_id"], "literal_value": claim["literal_value"],
            "unit": claim["unit"],
        })
    return {
        "status": "approved", "model_id": gate["model_id"], "model_code": gate["model_code"],
        "sku_id": gate.get("sku_id"), "bindings": audit_bindings,
        "note": "生成前门禁通过；只核验已声明绑定的字段，其他事实性文案仍需由调用方逐项绑定。",
    }
