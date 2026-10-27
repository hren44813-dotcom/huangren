"""中文电商图片制作界面：streamlit run app.py"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import streamlit as st
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ecom_images.ai_bridge import generate_xinghe  # noqa: E402
from ecom_images.session_guard import input_fingerprint  # noqa: E402
from ecom_images.main_direction_ui import render as render_main_directions  # noqa: E402
from ecom_images.sku_batch_ui import render as render_sku_batch  # noqa: E402
from ecom_images.workflow import (  # noqa: E402
    UploadedPicture, planned_count, produce_images,
)

st.set_page_config(page_title="工业五金电商图片工坊", page_icon="🛠️", layout="wide")
st.title("🛠️ 工业五金电商图片工坊")
st.caption("淘宝 / 天猫 / 阿里国际站 · 批量排版与可选 AI 详情页 · 保留产品原始结构")
st.info("标准制图在当前运行环境离线完成，不会将商品照片传给外部 AI。AI 生图需单独同意，并使用你自己的第三方密钥。")

platform = st.selectbox("目标平台", ["淘宝 / 天猫", "阿里国际站"])
st.caption("平台选择用于区分工作流程；预设尺寸是制图模板，不代表平台实时审核规则。发布前请核对各平台最新要求。")

direction_tab, standard, sku_tab, ai_tab = st.tabs(["① 主图方向策划", "② 标准主图 / SKU 批量制作", "③ Excel SKU / 工业模板 V5", "④ 星河 AI 详情页（可选）"])

with direction_tab:
    render_main_directions(st, platform)

with standard:
    uploaded = st.file_uploader("上传产品原图（可多选，建议透明 PNG）", type=["png", "jpg", "jpeg", "webp"],
                                accept_multiple_files=True, key="standard_upload")
    st.caption("每张最多 12 MB，每批最多 25 张。只做等比例排版，不自动抠图、不修复结构。")
    display_modes = {
        "主图 1440×1440": "main",
        "白底搜推 1440×1440 JPG": "search_white",
        "SKU 规格图 1440×1440": "sku",
        "3:4 竖图 1440×1920": "portrait",
        "详情模块 800×1600": "detail",
    }
    choices = st.multiselect("选择输出类型", list(display_modes),
                             default=["主图 1440×1440", "白底搜推 1440×1440 JPG"])
    a, b = st.columns([1, 1])
    with a:
        variants = st.slider("每类配色版本数（白底图固定 1 张）", 1, 4, 1)
        title = st.text_input("商品名称 / SKU 标题", placeholder="例如：MS705 转舌锁（仅填写已确认的商品信息）")
        subtitle = st.text_input("副标题（可选）", placeholder="填写真实卖点，不自动生成数据")
        brand = st.text_input("品牌名称（可选）", placeholder="例如 DG-DELER")
        label = st.text_input("竖图型号标注（可选）", placeholder="例如 MS705")
        uploaded_logo = st.file_uploader("Logo 文件（仅主图和详情模块使用）", type=["png", "jpg", "jpeg", "webp"], key="brand_logo")
    with b:
        accent = st.color_picker("标题色块颜色", "#0D7FF4")
        background = st.color_picker("图片背景颜色", "#F4F7FA")
        points_text = st.text_area("卖点（每行一条，最多 3 条）", height=112,
                                   placeholder="例如：仅填写已核实的材质、规格或使用场景")
        st.markdown("**SKU 参数（完全由你填写，不自动编造）**")
        spec_names = ["型号", "材质", "尺寸/孔距", "表面处理"]
        spec_values = [st.text_input(f"{name}（可留空）", key=f"spec_{i}") for i, name in enumerate(spec_names)]
    inputs = [UploadedPicture(f.name, f.getvalue()) for f in (uploaded or [])]
    logo_picture = UploadedPicture(uploaded_logo.name, uploaded_logo.getvalue()) if uploaded_logo else None
    chosen_modes = [display_modes[x] for x in choices]
    specs = [{"label": n, "value": v.strip()} for n, v in zip(spec_names, spec_values) if v.strip()]
    parameters = {"platform": platform, "modes": chosen_modes, "variants": variants,
                  "title": title, "subtitle": subtitle, "brand": brand, "label": label,
                  "selling_points": points_text.splitlines(), "specs": specs,
                  "accent": accent, "background": background}
    current_fingerprint = input_fingerprint(inputs, parameters, logo_picture)
    count = len(inputs)
    if choices and count:
        try:
            qty = planned_count(count, [display_modes[x] for x in choices], variants)
            st.caption(f"本批预计输出 {qty} 张图。不同配色版本不会虚构新的产品角度或功能。")
        except ValueError as exc:
            st.warning(str(exc))

    if st.button("开始批量生成图片", type="primary", key="make_offline", use_container_width=True):
        if not uploaded:
            st.error("请先上传至少一张产品图片")
        else:
            try:
                # 生成前清除旧结果，避免新一轮失败时旧图继续出现。
                st.session_state.pop("offline_result", None)
                with st.spinner("正在生成与验证图片…"):
                    result = produce_images(
                        inputs, chosen_modes, variants, title=title,
                        subtitle=subtitle, brand=brand, label=label,
                        selling_points=points_text.splitlines(), specs=specs,
                        accent=accent, background=background, logo=logo_picture,
                    )
                st.session_state["offline_result"] = (current_fingerprint, result)
            except (ValueError, OSError, RuntimeError) as exc:
                st.error(f"制作失败：{exc}")

    cached_result = st.session_state.get("offline_result")
    result = None
    if cached_result:
        if not isinstance(cached_result, tuple) or len(cached_result) != 2 or cached_result[0] != current_fingerprint:
            st.warning("输入图片、参数或平台已变化；旧批次结果已隐藏，请重新点击生成，防止下载错误 SKU。")
        else:
            result = cached_result[1]
    if result:
        st.subheader(f"生成结果：{len(result.images)} 张成功，{len(result.errors)} 项失败")
        if result.errors:
            with st.expander("查看未生成项目及原因", expanded=True):
                for err in result.errors:
                    st.error(err)
        if result.images:
            audits = result.quality_audits()
            auto_pass = sum(a["auto_pass"] for a in audits)
            st.caption(f"机器质检：{auto_pass}/{len(audits)} 张通过尺寸、格式等检查；产品结构、文案真实性及平台准入仍需人工复核。")
            if auto_pass < len(audits):
                with st.expander("查看自动质检未通过项目", expanded=True):
                    for audit in audits:
                        if not audit["auto_pass"]:
                            st.error(f"{audit['file']}：" + "；".join(c["item"] for c in audit["checks"] if not c["passed"]))
            with st.expander("发布前人工检查清单（所有图片均待验收）"):
                st.markdown("- [ ] 与产品原图逐一核对孔位、结构、配件、比例与表面细节")
                st.markdown("- [ ] 核对参数、功能、卖点与实际资料一致")
                st.markdown("- [ ] 核对手机端文字清晰度、遮挡和目标平台最新规则")
            st.download_button("📦 下载全部图片 ZIP（含质量报告）", data=result.zip_bytes(),
                               file_name="ecommerce_images.zip", mime="application/zip", use_container_width=True)
            for first in range(0, len(result.images), 3):
                cols = st.columns(3)
                for col, (name, data, meta) in zip(cols, result.images[first:first + 3]):
                    with col:
                        st.image(data, caption=f"{name}  ·  {meta['width']}×{meta['height']}", use_container_width=True)
                        st.download_button("下载这张", data=data, file_name=Path(name).name,
                                           mime="image/jpeg", key=f"download_{name}")

with sku_tab:
    render_sku_batch(st, platform)

with ai_tab:
    st.warning("该功能通过仓库内的星河技能脚本调用第三方 API，会上传你选择的产品图和提示词，可能产生费用；并非离线功能。AI 生成的产品结构、尺寸和文案必须人工复核。")
    ai_photo = st.file_uploader("AI 参考产品图（单张）", type=["png", "jpg", "jpeg", "webp"], key="ai_upload")
    ai_name = st.text_input("产品名称", key="ai_name", placeholder="例如 MS705 转舌锁")
    ai_platform = platform
    initial_prompt = (f"面向{ai_platform}的工业设备采购用户，设计单张电商详情页模块。"
                      f"商品：{ai_name or '（填写真实商品名称）'}。"
                      "严格参照所上传的真实参考图，锁体、钥匙、锁片、孔位、颜色、比例不改变。"
                      "画面使用简洁工业风，文字不要遮挡产品。禁止编造材质、盐雾、扭矩、尺寸、认证和功能。").strip()
    if st.button("填入安全提示词模板", key="fill_prompt"):
        st.session_state["ai_prompt"] = initial_prompt
    prompt = st.text_area("生成提示词（请逐屏填写真实信息）", key="ai_prompt", height=160,
                          placeholder="描述这一屏展示什么、用什么产品原图、哪些信息真实可信")
    x, y, z = st.columns(3)
    with x:
        ratio = st.selectbox("图片比例", ["3:4", "1:1", "16:9", "4:3", "9:16"])
    with y:
        resolution = st.selectbox("服务端请求分辨率", ["1k", "2k", "4k"], index=1)
    with z:
        ai_count = st.number_input("请求张数", min_value=1, max_value=4, value=1)
    ai_key = st.text_input("星河 API Key（仅用于本次调用，不写入仓库）", type="password")
    ai_model = st.text_input("服务商模型名称", value="gpt-image-2")
    agreed = st.checkbox("我确认拥有该图片的使用权，同意将它与提示词发送给第三方星河接口，并自行承担接口费用")
    if st.button("调用星河 AI 生成（可能收费）", type="secondary", use_container_width=True, key="make_ai"):
        if not ai_photo:
            st.error("请先上传 AI 参考图")
        else:
            try:
                with st.spinner("正在调用第三方服务…"):
                    zip_data = generate_xinghe(
                        UploadedPicture(ai_photo.name, ai_photo.getvalue()), api_key=ai_key,
                        model=ai_model, prompt=prompt, ratio=ratio, resolution=resolution,
                        quantity=int(ai_count), consent=agreed,
                    )
                st.session_state["ai_zip"] = zip_data
                st.success("服务商已返回图片，请下载并逐张核对。")
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(f"AI 制作失败：{exc}")
    if st.session_state.get("ai_zip"):
        data = st.session_state["ai_zip"]
        st.download_button("下载 AI 图片 ZIP", data=data, file_name="xinghe_detail_images.zip", mime="application/zip")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for item in zf.namelist():
                content = zf.read(item)
                st.image(content, caption=f"{item}（需人工核对结构与参数）", width=420)

st.divider()
st.caption("本工具不连接淘宝/天猫/阿里国际站后台，不会自动上架；公开 GitHub 仓库不要存放真实 API 密钥或客户保密图纸。")
