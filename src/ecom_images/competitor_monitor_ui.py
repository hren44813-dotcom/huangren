"""Streamlit desk for assistants monitoring each competitor listing's many SKUs."""
from __future__ import annotations

import hashlib
import sqlite3

from .competitor_monitor import (
    DEFAULT_DB, available_dates, daily_report, import_csv, report_csv, template_csv,
)


def render(st) -> None:
    st.subheader("竞品 SKU 每日监测")
    st.caption("操作顺序：下载模板 → 每日填写/上传 → 预检 → 确认保存 → 下载价格变化报表。"
               "一个竞品链接有多个 SKU 时，每个 SKU 填一行，同日期链接级数据保持一致。")
    st.info("这里记录运营助理人工核实的页面观察，不自动登录或抓取淘宝/天猫；"
            "截图文件名只用于索引，图片本身不会上传至数据库。"
            "未显示的销量请留空，不等于 0。")
    st.download_button(
        "① 下载空白 CSV 模板（Excel 可打开）",
        data=template_csv(), file_name="竞品SKU每日监测_空白模板.csv",
        mime="text/csv", key="competitor_template",
    )

    uploaded = st.file_uploader(
        "② 上传今日监测表 CSV（UTF-8，最多 2 MB / 5000 行）",
        type=["csv"], key="competitor_daily_csv",
    )
    content = uploaded.getvalue() if uploaded else b""
    digest = hashlib.sha256(content).hexdigest() if content else ""
    if st.button("③ 预检数据（不会修改数据库）", disabled=not bool(content),
                 key="competitor_preview"):
        st.session_state.pop("competitor_import_preview", None)
        try:
            result = import_csv(DEFAULT_DB, content, dry_run=True)
            st.session_state["competitor_import_preview"] = (digest, result)
            st.success("预检通过，可确认正式写入。")
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
            st.error(f"预检未通过：{exc}")

    preview = st.session_state.get("competitor_import_preview")
    if preview and digest and preview[0] == digest:
        result = preview[1]
        st.write(f"表格共 {result['rows']} 行，涉及 {result['links']} 个竞品链接，"
                 f"拟新增 {result['new']} 行，已存在且一致 {result['unchanged']} 行。")
        st.caption("日期：" + "、".join(result["dates"]))
        consent = st.checkbox(
            "我已核对 SKU 与价格、备份原始监测表，并确认本次记录应永久追加；"
            "同日期同链接同 SKU 的不同数据不会被覆盖。",
            key="competitor_confirm",
        )
        if st.button("④ 确认保存历史数据", disabled=not consent, key="competitor_save"):
            try:
                saved = import_csv(DEFAULT_DB, content, dry_run=False)
                st.success(f"保存成功：新增 {saved['new']} 行；重复一致 {saved['unchanged']} 行。")
                st.session_state.pop("competitor_import_preview", None)
            except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
                st.error(f"保存失败，整批已回滚：{exc}")
    elif preview and digest != preview[0]:
        st.warning("上传表格发生变化，旧预检已失效。请重新预检。")

    st.divider()
    st.markdown("**⑤ 查看每日 SKU 价格变化**")
    try:
        days = available_dates(DEFAULT_DB)
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        st.error(f"无法读取监测日期：{exc}")
        return
    if not days:
        st.info("目前没有已保存的监测数据。完成第一次正式导入后即可查看变化报表。")
        return
    chosen = st.selectbox("选择监测日期", days, key="competitor_report_date")
    try:
        report = daily_report(DEFAULT_DB, chosen)
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        st.error(f"报表读取失败：{exc}")
        return
    a, b, c, d = st.columns(4)
    a.metric("记录 SKU", report["total"])
    b.metric("涨价 SKU", report["price_up"])
    c.metric("降价 SKU", report["price_down"])
    d.metric("首次记录", report["new_skus"])
    st.caption("价格对比的是该 SKU 上一次已保存的监测日期，并不一定是昨天；"
               "币种不同或价格未显示时，不计算变动金额。")
    if report["rows"]:
        st.dataframe(report["rows"], use_container_width=True, hide_index=True)
        st.download_button(
            "下载该日变化报表 CSV",
            data=report_csv(report), file_name=f"竞品SKU价格变化_{chosen}.csv",
            mime="text/csv", key="competitor_report_download",
        )
    if report["missing"]:
        st.warning(f"前次记录中有 {len(report['missing'])} 个 SKU 本次未填写；"
                   "只能判定为未记录，不能据此认为已下架。")
        st.dataframe(report["missing"], use_container_width=True, hide_index=True)
