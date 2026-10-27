"""V6 审核工作台：提交审核结果后才能导出已审核图片，修改审核表会使旧导出失效。"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from .sku_review_v5 import FIELDS, audit_reviews, review_rows, review_zip, review_signature
from .production_ledger_v6 import record_review
from .database_v9 import DEFAULT_DB, save_job

HISTORY = Path(__file__).resolve().parents[2] / ".local" / "production_runs"


def render(st, result, job_record: dict, revision: int = 1) -> None:
    st.markdown("#### ③ 逐张人工审核 → ④ 保存审核并导出")
    st.caption("机器通过不代表产品真实性审核。审核结果与本批输出图片 SHA256 绑定，修改图片或审核表后必须重新确认。")
    if not result.images:
        st.info("本批没有可审核图片；请根据失败报告修正后重新制图。")
        return
    batch_id = job_record["id"]
    key = f"v6_review_{batch_id}"
    columns = {field: st.column_config.CheckboxColumn(field, default=False) for field in FIELDS}
    columns["审核结论"] = st.column_config.SelectboxColumn("审核结论", options=["待审核", "通过", "返工"], required=True)
    columns["备注"] = st.column_config.TextColumn("问题或修改建议（返工必填）", max_chars=500)
    table = st.data_editor(review_rows(result.images), key=key, hide_index=True,
                           use_container_width=True, disabled=["文件名"],
                           column_config=columns, num_rows="fixed")
    try:
        edited = table.to_dict("records") if hasattr(table, "to_dict") else list(table)
        report = audit_reviews(result.images, edited, failed_generation=result.failures)
        signature = hashlib.sha256((review_signature(report) + "|" +
                                    st.session_state.get(f"v6_reviewer_{job_record['id']}", "")).encode("utf-8")).hexdigest()
    except (ValueError, TypeError) as exc:
        st.error(f"审核表校验未通过：{exc}")
        return
    counts = report["counts"]
    st.caption(f"待审核 {counts['待审核']} · 返工 {counts['返工']} · 通过 {counts['通过']} · 生成失败 {result.failures}")
    alias = st.text_input("审核人标识（用于本机留档）", key=f"v6_reviewer_{batch_id}",
                          placeholder="如：运营助理A")
    save_key = f"v6_saved_review_{batch_id}"
    if st.button("确认并保存当前审核记录", type="primary", key=f"v6_save_{batch_id}"):
        try:
            previous = st.session_state.get(save_key)
            baseline = previous[2] if previous else job_record
            expected = previous[3] if previous else revision
            saved_record = record_review(baseline, result.images, report, reviewer=alias)
            approved_bundle = review_zip(result.images, report)
            new_revision = save_job(DEFAULT_DB, saved_record, expected_revision=expected)
            st.session_state[save_key] = (signature, approved_bundle, saved_record, new_revision)
            st.success("审核结果已保存到 SQLite 数据库，图片校验值与审核历史已绑定。")
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
            st.error(f"无法保存审核结果：{exc}")
    current = st.session_state.get(save_key)
    if current and current[0] != signature:
        st.warning("审核表已修改，之前的审核下载已失效；请重新保存审核记录。")
    elif current and current[0] == signature:
        st.caption(f"当前审核阶段：{current[2]['stage']} · 校验指纹 {signature[:12]}")
        st.download_button("📦 下载已审核图片 + 审核报告 ZIP", current[1],
                           file_name=f"reviewed_sku_{batch_id[:10]}.zip", mime="application/zip",
                           key=f"v6_download_{batch_id}", use_container_width=True)
        if not counts["通过"]:
            st.info("尚无通过图片；下载包仅包含审核报告，不包含可发布图片。")
