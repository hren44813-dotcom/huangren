"""V11 read-only Streamlit report; uses separate connections from production writes."""
from __future__ import annotations
import json
import sqlite3

from .database_v9 import DEFAULT_DB
from .db_reporting_v11 import database_summary, list_job_page, job_review_timeline, jobs_csv


def render(st) -> None:
    st.subheader("任务数据库 · 只读查询 V11")
    st.caption("仅查询本机业务元数据，不编辑任务和审核内容；数据库不会上传到 GitHub。")
    if not DEFAULT_DB.is_file():
        st.info("当前没有本机数据库。请先通过 Excel SKU 页面生成任务，或执行 db_admin.py init。")
        return
    try:
        summary = database_summary(DEFAULT_DB)
        a, b, c = st.columns(3)
        a.metric("制图任务", summary["totals"]["jobs"])
        b.metric("模板数量", summary["totals"]["templates"])
        c.metric("审核事件", summary["totals"]["review_events"])
        st.caption("这里显示数量，不代表商品已经通过人工审核。数据库完整性请使用 db_admin.py check。")
        with st.expander("任务阶段与平台分布", expanded=False):
            st.write("**阶段统计**")
            st.dataframe(summary["by_stage"], hide_index=True)
            st.write("**平台统计**")
            st.dataframe(summary["by_platform"], hide_index=True)
        filters = st.columns([1,1,1,1])
        with filters[0]:
            stage = st.selectbox("审核阶段", ["全部"] + [item["stage"] for item in summary["by_stage"]], key="v11_stage")
        with filters[1]:
            platform = st.selectbox("平台", ["全部"] + [item["platform"] for item in summary["by_platform"]], key="v11_platform")
        with filters[2]:
            since = st.text_input("开始日期 UTC", placeholder="YYYY-MM-DD", key="v11_since")
        with filters[3]:
            until = st.text_input("结束日期 UTC", placeholder="YYYY-MM-DD", key="v11_until")
        keyword = st.text_input("任务编号或模板名称包含", key="v11_keyword")
        page = st.number_input("页码", min_value=1, max_value=1000000, value=1, step=1, key="v11_page")
        result = list_job_page(
            DEFAULT_DB, page=int(page), page_size=25,
            stage=None if stage=="全部" else stage,
            platform=None if platform=="全部" else platform,
            since=since or None, until=until or None,
            keyword=keyword or None)
        st.caption(f"匹配任务 {result['total']} 条；当前第 {result['page']} 页（每页最多 25 条）")
        st.dataframe(result["rows"], hide_index=True, use_container_width=True)
        st.download_button("下载当前页 CSV（仅元数据）", jobs_csv(result).encode("utf-8"),
                           file_name=f"job_history_page_{page}.csv", mime="text/csv", key="v11_csv")
        with st.expander("按完整任务编号查看审核轨迹", expanded=False):
            job_id = st.text_input("32位完整任务编号", key="v11_job_id")
            if st.button("查询该任务审核历史", key="v11_reviews"):
                timeline = job_review_timeline(DEFAULT_DB, job_id)
                st.dataframe(timeline["events"], hide_index=True)
                if any(not e["checksum_ok"] for e in timeline["events"]):
                    st.error("存在审核摘要校验异常；请停止发布并执行完整性检查")
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        st.error(f"数据库查询失败：{exc}")