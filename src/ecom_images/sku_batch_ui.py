"""Excel 批量 SKU 规格图的中文 Streamlit 页面。"""
from __future__ import annotations

from pathlib import Path

from .session_guard import input_fingerprint
from .sku_batch import build_sku_batch, read_sku_rows, unpack_image_zip
from .workflow import UploadedPicture

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "assets" / "templates" / "sku_import_template.xlsx"


def render(st, platform: str) -> None:
    st.subheader("Excel 一键批量生成 SKU 规格图")
    st.caption("仅将已核实的尺寸与材质绘制到原产品照片上；不改变孔位、产品比例和机械结构。适用于拉手、锁具、铰链、阻尼转轴等产品。")
    st.download_button("📥 下载 Excel SKU 填写模板", TEMPLATE_PATH.read_bytes(),
                       file_name="工业五金批量SKU导入模板.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
    st.info("Excel 中一行对应一个 SKU：填写 SKU编码、商品名称、图片文件名等；多张产品图片文件名必须与 Excel 完全对应（大小写可不同）。已确认尺寸才填写，空值不推断。")
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
        {"platform": platform, "workflow": "sku_excel", "source": source_method})
    if st.button("③ 按 Excel 批量制作 SKU 图", type="primary", use_container_width=True, key="build_sku_excel"):
        st.session_state.pop("sku_excel_result", None)
        if not excel_bytes or (not zip_bytes and not uploaded_pictures):
            st.error("请先上传 Excel 和产品图片")
        else:
            try:
                with st.spinner("正在逐行生成 SKU 图及检查导出尺寸..."):
                    pictures = unpack_image_zip(zip_bytes) if zip_bytes else uploaded_pictures
                    result = build_sku_batch(excel_bytes, pictures)
                st.session_state["sku_excel_result"] = (fingerprint, result)
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(f"批量制作失败：{exc}")
    saved = st.session_state.get("sku_excel_result")
    if saved and saved[0] != fingerprint:
        st.warning("Excel、产品图或平台已变化，旧结果已经隐藏；请重新生成，避免下载错 SKU 图。")
    if saved and saved[0] == fingerprint:
        result = saved[1]
        st.success(f"本次完成：{result.successes} 个 SKU 成功，{result.failures} 行未成功") if result.successes else st.warning("本次没有生成成功的图片，请查看每行失败原因")
        st.dataframe(result.rows, hide_index=True, use_container_width=True)
        st.caption("机器通过仅代表像素、格式等检查通过。图片孔位、材质、标注数字真实性及平台实时审核规则仍需人工检查。")
        st.download_button("📦 下载 SKU 图片 ZIP + 逐行 CSV/JSON 报告 + 质量报告", result.zip_bytes(),
                           file_name="sku_excel_批量图片及校验报告.zip", mime="application/zip", use_container_width=True)
        if result.images:
            st.write("**前 12 张图片预览**")
            for start in range(0, min(12, len(result.images)), 3):
                cols = st.columns(3)
                for col, (name, data, _) in zip(cols, result.images[start:start + 3]):
                    with col:
                        st.image(data, caption=name, use_container_width=True)
