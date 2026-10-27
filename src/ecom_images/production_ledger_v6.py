"""V6 本机任务台账：只保存流程元数据与校验值，不保存商品照片或API密钥。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ID_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_RUNS = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_record(images: list[tuple[str, bytes, dict]], *, fingerprint: str,
               platform: str, template: str, failed_generation: int = 0,
               batch_id: str | None = None) -> dict[str, Any]:
    """记录输出文件的 SHA256 及流程状态，来源图只记录输入指纹。"""
    if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise ValueError("输入指纹无效")
    if failed_generation < 0:
        raise ValueError("失败数量不能小于0")
    identifier = batch_id or uuid.uuid4().hex
    if not ID_RE.fullmatch(identifier):
        raise ValueError("无效批次编号")
    names = [name for name, _, _ in images]
    if len(set(names)) != len(names):
        raise ValueError("输出文件名重复")
    return {"version": 1, "id": identifier, "created_utc": _now(),
            "updated_utc": _now(), "platform": platform[:60], "template": template[:100],
            "input_sha256": fingerprint, "generated": len(images),
            "failed_generation": failed_generation, "stage": "待人工审核",
            "files": [{"name": name, "sha256": hashlib.sha256(data).hexdigest()}
                      for name, data, _ in images], "review": None}


def record_review(record: dict[str, Any], images: list[tuple[str, bytes, dict]],
                  report: dict[str, Any], *, reviewer: str) -> dict[str, Any]:
    """核对现有图片与当初记录的校验值，再保存审核决定。"""
    from .sku_review_v5 import verify_review_report
    if not reviewer.strip() or len(reviewer) > 80:
        raise ValueError("请填写80字以内的审核人标识")
    current = [{"name": name, "sha256": hashlib.sha256(data).hexdigest()}
               for name, data, _ in images]
    if current != record.get("files"):
        raise ValueError("当前图片内容不同于原批次，不能复用旧审核")
    verify_review_report(images, report)
    if report.get("failed_generation") != record.get("failed_generation"):
        raise ValueError("审核报告和本批次的失败数量不一致")
    summary = {
        "schema_version": 2,
        "reviewed_utc": _now(), "reviewer": reviewer.strip(),
        "counts": report["counts"], "image_sha256": {r["file"]: r["image_sha256"] for r in report["rows"]},
        "ready_to_publish": bool(report["ready_to_publish"]),
        "rows": [{"file": r["file"], "status": r["status"], "note": r["note"],
                  "checks": dict(r["checks"])} for r in report["rows"]],
    }
    result = {**record, "review": summary, "updated_utc": _now()}
    if report["counts"]["返工"] or record["failed_generation"]:
        result["stage"] = "返工中"
    elif report["counts"]["待审核"]:
        result["stage"] = "部分待审核"
    elif report["ready_to_publish"]:
        result["stage"] = "全部审核通过"
    else:
        result["stage"] = "无可发布图片"
    return result


def save_record(folder: Path, record: dict[str, Any]) -> Path:
    """原子保存 JSON，防止写到一半损坏。"""
    identifier = record.get("id")
    if not isinstance(identifier, str) or not ID_RE.fullmatch(identifier):
        raise ValueError("任务编号无效")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{identifier}.json"
    raw = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")
    if len(raw) > 256_000:
        raise ValueError("任务记录过大")
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=folder, prefix=".draft_", suffix=".tmp", delete=False) as out:
            temp = Path(out.name)
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()
    return path


def list_records(folder: Path, limit: int = 20) -> list[dict[str, Any]]:
    if not folder.exists():
        return []
    items = []
    for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:min(MAX_RUNS, max(0, limit))]:
        if not ID_RE.fullmatch(path.stem) or path.stat().st_size > 256_000:
            continue
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(entry, dict) and entry.get("id") == path.stem:
            items.append({"任务编号": entry["id"][:10], "创建时间UTC": entry.get("created_utc", ""),
                          "平台": entry.get("platform", ""), "模板": entry.get("template", ""),
                          "完成图片": entry.get("generated", 0), "失败": entry.get("failed_generation", 0),
                          "阶段": entry.get("stage", "")})
    return items
