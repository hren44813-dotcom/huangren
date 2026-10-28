"""Normalization and source-quality predicates shared by V13 model evidence tools."""
from __future__ import annotations

import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

_TRUSTED_AUTHORITIES = {"manufacturer_controlled", "independent_test"}
_TRUSTED_REVIEWERS = {"second_reviewer", "manufacturer", "independent_lab"}
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
        and item.get("source_bytes_verified") is True
        and item.get("segment_hash_verified") is not False
    ]
    independent_support = [
        item for item in reviews
        if item["verdict"] == "supports" and item["reviewer_role"] in _TRUSTED_REVIEWERS
    ]
    if claim.get("state") != "accepted":
        reasons.append("参数主张尚未处于 accepted 状态")
    if not trusted_support:
        reasons.append("缺少带原文定位、原件指纹有效的制造商受控资料或独立测试支持证据")
    if any(item["role"] == "supports" and item.get("source_bytes_verified") is not True for item in evidence):
        reasons.append("支持证据原始文件缺失或 SHA-256/文件大小与登记值不一致")
    if any(item["role"] == "supports" and item.get("segment_hash_verified") is False for item in evidence):
        reasons.append("支持证据引用的索引片段不存在或文本指纹不一致")
    if not independent_support:
        reasons.append("缺少第二复核人、制造商或独立实验室的支持性复核")
    if any(item["role"] == "contradicts" for item in evidence):
        reasons.append("存在反对性来源证据")
    if any(item["verdict"] == "contradicts" for item in reviews):
        reasons.append("存在反对性复核记录")
    if claim.get("claim_kind") == "system_inference":
        reasons.append("系统推断不能直接作为商品参数宣传")
    return not reasons, reasons
