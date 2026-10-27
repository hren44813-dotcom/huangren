"""V5 SKU 逐张审核：明确区分机器校验与人工验收，不会自动批准。"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any

FIELDS = ("产品结构", "原尺寸及标注", "卖点真实性", "平台与清晰度")
STATUSES = ("待审核", "通过", "返工")


def review_rows(images: list[tuple[str, bytes, dict]]) -> list[dict[str, Any]]:
    return [
        {"文件名": name, **{field: False for field in FIELDS}, "审核结论": "待审核", "备注": ""}
        for name, _, _ in images
    ]


def audit_reviews(
    images: list[tuple[str, bytes, dict]],
    edited_rows: list[dict[str, Any]],
    *, failed_generation: int = 0,
) -> dict[str, Any]:
    """只有明确勾选全部真实性检查且标记通过才会进入可发布集合。"""
    if failed_generation < 0:
        raise ValueError("失败数量不能为负数")
    expected = {name: data for name, data, _ in images}
    if len(expected) != len(images) or len(edited_rows) != len(images):
        raise ValueError("审核行数或生成文件名不匹配")
    observed: set[str] = set()
    reviewed: list[dict[str, Any]] = []
    counts = {state: 0 for state in STATUSES}
    for entry in edited_rows:
        if not isinstance(entry, dict):
            raise ValueError("审核记录必须为对象")
        name = entry.get("文件名")
        if not isinstance(name, str) or name not in expected or name in observed:
            raise ValueError("审核记录对应的图片不存在或重复")
        observed.add(name)
        state = entry.get("审核结论")
        if state not in STATUSES:
            raise ValueError(f"{name}：审核结论无效")
        fields = {}
        for field in FIELDS:
            value = entry.get(field)
            if type(value) is not bool:
                raise ValueError(f"{name}：{field} 必须是明确勾选值")
            fields[field] = value
        if state == "通过" and not all(fields.values()):
            raise ValueError(f"{name}：标记通过前必须核对并勾选全部4项")
        note = entry.get("备注", "")
        if not isinstance(note, str) or len(note) > 500:
            raise ValueError(f"{name}：备注必须是500字以内的文本")
        if state == "返工" and not note.strip():
            raise ValueError(f"{name}：返工项目必须填写问题及修改建议")
        counts[state] += 1
        reviewed.append({"file": name, "image_sha256": hashlib.sha256(expected[name]).hexdigest(),
                         "status": state, "checks": fields, "note": note.strip()})
    ready = bool(images) and counts["通过"] == len(images) and failed_generation == 0
    return {"schema_version": 1, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "automatic_checks_are_not_manual_approval": True,
            "ready_to_publish": ready, "failed_generation": failed_generation,
            "counts": counts, "rows": reviewed}


def review_csv(report: dict[str, Any]) -> bytes:
    out = io.StringIO(newline="")
    cols = ["文件名", "审核结论", *FIELDS, "备注", "图片SHA256"]
    writer = csv.DictWriter(out, fieldnames=cols)
    writer.writeheader()

    def cell(value: str) -> str:
        # 防止 CSV 在 Excel 中被解释为公式。
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value

    for row in report["rows"]:
        writer.writerow({"文件名": cell(row["file"]), "审核结论": row["status"],
                         **{field: "是" if row["checks"][field] else "否" for field in FIELDS},
                         "备注": cell(row["note"]), "图片SHA256": row["image_sha256"]})
    return ("\ufeff" + out.getvalue()).encode("utf-8")


def verify_review_report(images: list[tuple[str, bytes, dict]], report: dict[str, Any]) -> None:
    """防止图片被替换、旧审核报告回放或修改状态后仍被导出。"""
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise ValueError("审核报告格式无效")
    rows = report.get("rows")
    if not isinstance(rows, list):
        raise ValueError("审核报告缺少逐张记录")
    edited = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("checks"), dict):
            raise ValueError("审核报告数据异常")
        edited.append({"文件名": row.get("file"), "审核结论": row.get("status"),
                       "备注": row.get("note"),
                       **{field: row["checks"].get(field) for field in FIELDS}})
    failures = report.get("failed_generation")
    if type(failures) is not int:
        raise ValueError("失败数量无效")
    checked = audit_reviews(images, edited, failed_generation=failures)
    if (checked["counts"] != report.get("counts") or
        checked["ready_to_publish"] != report.get("ready_to_publish") or
        [(r["file"], r["image_sha256"], r["status"], r["checks"], r["note"]) for r in checked["rows"]] !=
        [(r.get("file"), r.get("image_sha256"), r.get("status"), r.get("checks"), r.get("note")) for r in rows]):
        raise ValueError("图片内容、审核状态或校验值与审核报告不一致，必须重新审核")


def review_signature(report: dict[str, Any]) -> str:
    """编辑审核表任意一项后签名变化；无须把生成时间算入。"""
    return hashlib.sha256(json.dumps({"rows": report["rows"],
                                      "failed_generation": report["failed_generation"]},
                                     ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def review_zip(images: list[tuple[str, bytes, dict]], report: dict[str, Any]) -> bytes:
    verify_review_report(images, report)
    approved = {r["file"] for r in report["rows"] if r["status"] == "通过"}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("review_report.json", json.dumps(report, ensure_ascii=False, indent=2))
        z.writestr("review_report.csv", review_csv(report))
        for name, data, _ in images:
            if name in approved:
                if name != name.replace("\\", "/").split("/")[-1] or name.startswith("."):
                    raise ValueError("审核通过的文件名不安全")
                z.writestr("approved/" + name, data)
    return out.getvalue()
