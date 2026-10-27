"""Excel 批量 SKU 规格图的中文 Streamlit 页面。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .session_guard import input_fingerprint
from .sku_batch import build_sku_batch, read_sku_rows, unpack_image_zip
from .sku_template_v3 import THEMES
from .sku_layout_ui import configure as configure_v4
from .workflow import UploadedPicture
from .sku_review_ui import render as render_sku_review
from .sku_preflight_v6 import inspect_batch
from .production_ledger_v6 import new_record
from .database_v9 import DEFAULT_DB, list_jobs, save_job, integrity_report, backup_database

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "assets" / "templates" / "sku_import_template.xlsx"
TEMPLATE_V3_PATH = Path(__file__).resolve().parents[2] / "assets" / "templates" / "sku_import_template_v3.xlsx"
HISTORY = Path(__file__).resolve().parents[2] / ".local" / "production_runs"


def render(st, platform: str) -> None:
    st.subheader("Excel 批量 SKU · V6 四步工作流（兼容 V2–V5）")
    st.caption("流程：①资料预检查 → ②批量制图 → ③人工审核 → ④审核留档/导出。每步绑定本次输入，不跨批复用审核。")
    template_choice = st.selectbox("选择模板版式", ["V2 经典 SKU 版式", *THEMES, "V5 自定义布局与模板库（兼容V4）"], key="sku_template_style")
    using_v4 = template_choice == "V5 自定义布局与模板库（兼容V4）"
    selected_style = None if template_choice == "V2 经典 SKU 版式" or using_v4 else template_choice
    custom_layout, clean_template, layout_payload = (configure_v4(st) if using_v4 else (None, None, b""))
    st.caption("V3 有三套工业风预设；V5 在 V4 版式基础上增加位置微调、可保存模板及审核表，不能自动清除旧模板上的旧商品。")
    st.caption("仅将已核实的尺寸与材质绘制到原产品照片上；不改变孔位、产品比例和机械结构。适用于拉手、锁具、铰链、阻尼转轴等产品。")
    chosen_template = TEMPLATE_V3_PATH if (selected_style or using_v4) else TEMPLATE_PATH
    st.download_button("📥 下载 Excel SKU 填写模板", chosen_template.read_bytes(),
                       file_name="工业五金批量SKU导入模板_V3.xlsx" if (selected_style or using_v4) else "工业五金批量SKU导入模板.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
    st.info("Excel 中一行对应一个 SKU：填写 SKU编码、商品名称、图片文件名；V3/V4/V5/V6 可选填写『尺寸图文件名』并上传对应原尺寸图。所有图片按完整文件名精确匹配，缺图不替换；空值不推断。")
    excel_file = st.file_uploader("① 上传已填写的 SKU Excel（.xlsx）", type=["xlsx"], key="excel_sku_file")
    source_method = st.radio("② 上传产品原图的方式", ["图片 ZIP 压缩包", "直接上传多张图片"], horizontal=True, key="sku_source")
    image_zip = None
    images = None
    if source_method == "图片 ZIP 压缩包":
        image_zip = st.file_uploader("上传产品图片 ZIP（文件名需对应 Excel，≤70MB）", type=["zip"], key="sku_photo_zip")
    else:
        images = st.file_uploader("选择多张 PNG / JPG / WEBP（每张≤12MB）", type=["png", "jpg", "jpeg", "webp"],
                                  accept_multiple_files=True, key="sku_photo_multiselect")
    excel_bytes = excel_file.getvalue() if excel_file is not None else b""
    uploaded_pictures = [UploadedPicture(f.name, f.getvalue()) for f in (images or [])]
    zip_bytes = image_zip.getvalue() if image_zip is not None else b""
    if excel_bytes:
        try:
            preview = read_sku_rows(excel_bytes)
            st.caption(f"Excel 已读取 {len(preview)} 行 SKU（每批最多 80 行）。下方仅预览前 20 行。");
            st.dataframe([{"行号": r.row_number, **r.data} for r in preview[:20]], hide_index=True, use_container_width=True)
        except ValueError as exc:
            st.warning(f"Excel 预检查：{exc}")
    fingerprint = input_fingerprint(
        [UploadedPicture("sku_excel.xlsx", excel_bytes),
         *([UploadedPicture("sku_images.zip", zip_bytes)] if source_method == "图片 ZIP 压缩包" else uploaded_pictures)],
        {"platform": platform, "workflow": "sku_excel", "source": source_method, "template_style": template_choice,
         "v4_layout": layout_payload.decode("utf-8") if layout_payload else ""},
        clean_template)
    # 第一关：只有当前输入快照通过预检查后才能运行制图；有错误的行须显式选择部分制图。
    if st.button("① 预检查 SKU 清单和图片匹配", key="sku_v6_check", use_container_width=True):
        st.session_state.pop("sku_preflight_v6", None)
        if using_v4 and custom_layout is None:
            st.error("请先修复模板布局越界或重叠问题。")
        elif not excel_bytes or (not zip_bytes and not uploaded_pictures):
            st.warning("先上传 Excel 和产品图片，再开始预检查。")
        else:
            try:
                pictures = unpack_image_zip(zip_bytes) if zip_bytes else uploaded_pictures
                preview_result = inspect_batch(excel_bytes, pictures, template_style=selected_style,
                                               custom_layout=custom_layout)
                st.session_state["sku_preflight_v6"] = (fingerprint, preview_result)
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
                st.error(f"预检查失败：{exc}")
    preflight = st.session_state.get("sku_preflight_v6")
    current_preflight = preflight[1] if preflight and preflight[0] == fingerprint else None
    if preflight and current_preflight is None:
        st.warning("模板、Excel、图片或平台已变化；必须重新预检查。")
    if current_preflight is not None:
        st.info(f"预检查完成：{current_preflight.ready} 行可生成，{current_preflight.blocked} 行需要修正。")
        st.dataframe(current_preflight.rows, hide_index=True, use_container_width=True)
    allow_partial = st.checkbox("发现缺失/错误行时，仍仅对可生成的行继续制图", key="sku_v6_partial",
                                disabled=not current_preflight or not current_preflight.blocked)
    enabled = bool(current_preflight and current_preflight.ready and
                   (not current_preflight.blocked or allow_partial))
    if st.button("② 开始批量制图（尚未审核）", type="primary", use_container_width=True,
                 disabled=not enabled, key="build_sku_excel"):
        st.session_state.pop("sku_excel_result", None)
        if using_v4 and custom_layout is None:
            st.error("V4 布局坐标无效，请先调整无重叠的区域")
        elif not excel_bytes or (not zip_bytes and not uploaded_pictures):
            st.error("请先上传 Excel 和产品图片")
        else:
            try:
                with st.spinner("正在逐行生成 SKU 图及检查导出尺寸..."):
                    pictures = unpack_image_zip(zip_bytes) if zip_bytes else uploaded_pictures
                    # 防止“只处理合格行”勾选被绕过；名单严格来自当前输入的预检查快照。
                    allowed = frozenset(int(row["Excel行号"]) for row in current_preflight.rows
                                        if row["状态"] == "可生成")
                    result = build_sku_batch(excel_bytes, pictures, template_style=selected_style,
                                             custom_layout=custom_layout, clean_template=clean_template,
                                             allowed_row_numbers=allowed)
                job = new_record(result.images, fingerprint=fingerprint, platform=platform,
                                 template=template_choice, failed_generation=result.failures)
                job_revision = None
                try:
                    job_revision = save_job(DEFAULT_DB, job)
                except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
                    st.error(f"本机数据库保存失败：{exc}。当前只允许下载内部制作包，不能进行审核留档。")
                st.session_state["sku_excel_result"] = (fingerprint, result, job, job_revision)
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(f"批量制作失败：{exc}")
    saved = st.session_state.get("sku_excel_result")
    if saved and saved[0] != fingerprint:
        st.warning("Excel、产品图或平台已变化，旧结果已经隐藏；请重新生成，避免下载错 SKU 图。")
    if saved and saved[0] == fingerprint:
        result = saved[1]
        job_record = saved[2] if len(saved) > 2 else None
        st.success(f"本次完成：{result.successes} 个 SKU 成功，{result.failures} 行未成功") if result.successes else st.warning("本次没有生成成功的图片，请查看每行失败原因")
        st.dataframe(result.rows, hide_index=True, use_container_width=True)
        st.caption("机器通过仅代表像素、格式等检查通过。图片孔位、材质、标注数字真实性及平台实时审核规则仍需人工检查。")
        if any(meta.get("dimension_source") for _, _, meta in result.images):
            st.warning("尺寸图清晰度提醒：小字号数字经等比缩放可能难以阅读。请在手机预览中逐一检查原尺寸标注；当前自动质检无法判断文字是否易读。")
        st.download_button("📦 下载内部制图包（未经人工审核，不可直接发布）", result.zip_bytes(),
                           file_name="sku_excel_批量图片及校验报告.zip", mime="application/zip", use_container_width=True)
        if result.images:
            st.write("**前 12 张图片预览**")
            for start in range(0, min(12, len(result.images)), 3):
                cols = st.columns(3)
                for col, (name, data, _) in zip(cols, result.images[start:start + 3]):
                    with col:
                        st.image(data, caption=name, use_container_width=True)

        if job_record and len(saved) > 3 and saved[3] is not None:
            render_sku_review(st, result, job_record, saved[3])
    with st.expander("V9 SQLite 数据库 · 任务流水、完整性与备份", expanded=False):
        try:
            history = list_jobs(DEFAULT_DB, limit=40)
            if history:
                st.dataframe(history, hide_index=True, use_container_width=True)
            else:
                st.caption("数据库暂无任务记录。旧版 JSON 可通过 scripts/db_admin.py import-legacy 迁移。")
            if st.button("检查数据库完整性", key="db_v9_check"):
                check = integrity_report(DEFAULT_DB)
                st.success("数据库与业务摘要校验通过") if check["ok"] else st.error("校验存在问题，请查看输出")
                st.json(check)
            if st.button("创建当前数据库备份", key="db_v9_backup"):
                import tempfile
                with tempfile.TemporaryDirectory() as folder:
                    snapshot = backup_database(DEFAULT_DB, Path(folder) / "huangren_backup.sqlite3")
                    st.session_state["db_v9_backup_bytes"] = snapshot.read_bytes()
            if st.session_state.get("db_v9_backup_bytes"):
                st.download_button("下载 SQLite 数据库备份", st.session_state["db_v9_backup_bytes"],
                                   file_name="huangren_backup.sqlite3", mime="application/octet-stream")
            st.caption("数据库仅保存在当前设备 .local/，不会自动同步。备份只包含业务元数据；发布审核仍需真人复核。")
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            st.error(f"本机数据库不可用：{exc}")
