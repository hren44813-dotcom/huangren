"""V5 发布前人工审核面板：不把自动检测结果视为真实商品审核通过。"""
from __future__ import annotations

import hashlib

from .sku_review_v5 import FIELDS, audit_reviews, review_rows, review_zip


def render(st, result, batch_id: str) -> None:
    st.markdown("#### V5：逐张人工审核与仅导出通过图片")
    st.caption("必须人工确认产品孔位/结构、尺寸标注、卖点真实性、平台规格。机器校验成功≠审核通过。")
    if not result.images:
        st.info("本批没有可审核图片。")
        return
    key = f"v5_review_table_{batch_id}"
    cols = {field: st.column_config.CheckboxColumn(field, default=False) for field in FIELDS}
    cols["审核结论"] = st.column_config.SelectboxColumn("审核结论", options=["待审核", "通过", "返工"], required=True)
    cols["备注"] = st.column_config.TextColumn("备注（说明缺陷、修改意见）", max_chars=500)
    table = st.data_editor(
        review_rows(result.images), key=key, hide_index=True, use_container_width=True,
        disabled=["文件名"], column_config=cols, num_rows="fixed",
    )
    try:
        edited = table.to_dict("records") if hasattr(table, "to_dict") else list(table)
        report = audit_reviews(result.images, edited, failed_generation=result.failures)
    except ValueError as exc:
        st.warning(f"审核记录不能导出：{exc}")
        return
    counts = report["counts"]
    st.caption(f"审核进度：通过 {counts['通过']}，返工 {counts['返工']}，待审核 {counts['待审核']}；生成失败 {result.failures}。")
    if report["ready_to_publish"]:
        st.success("整批图片均已逐张人工核验且没有生成失败项。仍需按平台最新要求复核。")
    else:
        st.warning("本批尚未整体验收完成。允许导出已明确审核通过的图片，未审核和返工图片不会进入通过目录。")
    bundle = review_zip(result.images, report)
    st.download_button("📦 下载审核报告 + 已通过图片 ZIP", data=bundle,
                       file_name="sku_人工审核结果.zip", mime="application/zip", key=f"v5_review_download_{batch_id}",
                       use_container_width=True)
