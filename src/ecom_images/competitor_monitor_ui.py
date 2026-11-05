"""Streamlit desk for assistants monitoring each competitor listing's many SKUs."""
from __future__ import annotations

import hashlib
import sqlite3

from datetime import date

from .competitor_monitor import (
    DEFAULT_DB, available_dates, daily_report, import_csv, report_csv, template_csv,
)
from .competitor_tasks import (
    daily_blank_csv, daily_checklist, import_watchlist, list_watchlist, watch_template,
)


def render(st) -> None:
    st.subheader("竞品 SKU 每日监测")
    st.caption("操作顺序：下载模板 → 每日填写/上传 → 预检 → 确认保存 → 下载价格变化报表。"
               "一个竞品链接有多个 SKU 时，每个 SKU 填一行，同日期链接级数据保持一致。")
    st.info("这里记录运营助理人工核实的页面观察，不自动登录或抓取淘宝/天猫；"
            "截图文件名只用于索引，图片本身不会上传至数据库。"
            "未显示的销量请留空，不等于 0。")
    st.markdown("### 一、固定竞品清单和每日任务")
    st.caption("首次先登记需要监测的竞品链接及各 SKU。后续只需选择日期即可下载当天任务表。"
               "要停用某个 SKU，请在清单里将其监测状态改为「停用」并再次导入；不会删除历史观察。")
    st.download_button(
        "下载竞品链接与 SKU 固定清单模板",
        data=watch_template(), file_name="竞品固定监测清单_模板.csv",
        mime="text/csv", key="competitor_watch_template",
    )
    watch_upload = st.file_uploader(
        "上传固定竞品清单（一个链接可以登记多个 SKU）",
        type=["csv"], key="competitor_watch_upload",
    )
    watch_data = watch_upload.getvalue() if watch_upload else b""
    watch_digest = hashlib.sha256(watch_data).hexdigest() if watch_data else ""
    if st.button("预检固定清单", disabled=not bool(watch_data), key="competitor_watch_preview"):
        st.session_state.pop("competitor_watch_preview_result", None)
        try:
            preview = import_watchlist(DEFAULT_DB, watch_data, dry_run=True)
            st.session_state["competitor_watch_preview_result"] = (watch_digest, preview)
            st.success("清单预检通过。")
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
            st.error(f"清单预检失败：{exc}")
    watched = st.session_state.get("competitor_watch_preview_result")
    if watched and watched[0] == watch_digest and watch_digest:
        details = watched[1]
        st.write(f"待处理 {details['rows']} 个 SKU：新增 {details['new']} 个，"
                 f"更新/停用 {details['updated']} 个，不变 {details['unchanged']} 个。")
        confirmed = st.checkbox(
            "我已确认固定清单及启用/停用状态；修改会保留操作历史。",
            key="competitor_watch_confirm",
        )
        if st.button("确认保存固定清单", disabled=not confirmed, key="competitor_watch_save"):
            try:
                saved = import_watchlist(DEFAULT_DB, watch_data, dry_run=False)
                st.success(f"清单已保存：新增 {saved['new']}，更新 {saved['updated']}。")
                st.session_state.pop("competitor_watch_preview_result", None)
            except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
                st.error(f"清单写入失败，整批未修改：{exc}")
    elif watched and watch_digest != watched[0]:
        st.warning("固定清单已更换，请重新预检。")
    try:
        watch_rows = list_watchlist(DEFAULT_DB)
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        st.error(f"无法读取固定监测清单：{exc}")
        watch_rows = []
    if watch_rows:
        active_count = sum(row["active"] for row in watch_rows)
        st.caption(f"当前固定清单：启用 {active_count} 个 SKU，停用 {len(watch_rows) - active_count} 个。")
        with st.expander("查看固定监测清单", expanded=False):
            st.dataframe([
                {"竞店": row["shop"], "竞品链接": row["url"],
                 "SKU": row["sku"], "币种": row["currency"],
                 "状态": "启用" if row["active"] else "停用"}
                for row in watch_rows
            ], use_container_width=True, hide_index=True)

        chosen_day = st.date_input("生成哪一天的监测任务", value=date.today(),
                                   key="competitor_task_day").isoformat()
        alert_threshold = st.slider("价格异常变动提醒阈值", 5, 100, 20, step=5,
                                    format="%d%%", key="competitor_alert_threshold")
        try:
            checklist = daily_checklist(DEFAULT_DB, chosen_day, alert_percent=alert_threshold)
            first, second, third = st.columns(3)
            first.metric("应监测 SKU", checklist["total"])
            second.metric("已完成价格记录", checklist["completed"])
            third.metric("未完成/待补价格", checklist["pending"])
            percent = checklist["completed"] / checklist["total"] if checklist["total"] else 0
            st.progress(percent, text=f"当天有效价格记录完成率 {percent:.1%}")
            st.download_button(
                "下载当天 SKU 监测任务表（价格等观察字段留空）",
                data=daily_blank_csv(DEFAULT_DB, chosen_day),
                file_name=f"竞品待监测清单_{chosen_day}.csv",
                mime="text/csv", key="competitor_task_download",
            )
            st.caption("任务表会预填日期、链接、SKU 与币种；"
                       "价格、销量、评价、优惠券和活动须以当天实际看到的信息填写。")
            with st.expander("查看当天未完成任务及完成状态", expanded=bool(checklist["pending"])):
                st.dataframe(checklist["rows"], use_container_width=True, hide_index=True)
            if checklist["alerts"]:
                st.warning(f"当天有 {len(checklist['alerts'])} 项需复核的变化或数据缺口。")
                st.dataframe(checklist["alerts"], use_container_width=True, hide_index=True)
            else:
                st.caption("当前没有可确认的异常提醒。未记录数据不会被视为价格持平。")
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
            st.error(f"每日任务读取失败：{exc}")
    else:
        st.info("请先登记固定竞品链接与 SKU。已有历史价格记录仍保留，不会自动成为固定任务。")

    st.divider()
    st.markdown("### 二、上传当天实际监测结果")
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
    st.markdown("### 三、查看每日 SKU 价格变化")
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
