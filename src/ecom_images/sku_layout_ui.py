"""V4 SKU 参考模板校准控件：参考图只作位置辅助，不能自动抠除旧商品。"""
from __future__ import annotations

from .sku_layout_v4 import (
    LABELS, SLOT_NAMES, default_layout, layout_from_json, layout_json,
    preview_regions, validate_layout,
)
from .sku_template_v3 import THEMES
from .workflow import UploadedPicture


def configure(st) -> tuple[dict | None, UploadedPicture | None, bytes]:
    st.markdown("#### V4：校准参考模板区域")
    st.info("参考模板仅用于对照位置，不会自动去除旧产品、文字或参数。可上传**已清空旧内容的 1440×1440 净背景**用于最终制图。")
    left, right = st.columns(2)
    with left:
        ref = st.file_uploader("旧 SKU 模板（仅预览位置，不进入最终商品图）", type=["png", "jpg", "jpeg", "webp"], key="v4_reference")
    with right:
        background = st.file_uploader("可选：清理干净的 1440×1440 背景图（将用于最终输出）", type=["png", "jpg", "jpeg", "webp"], key="v4_clean_background")
    allow_clean = st.checkbox("我已确认净背景不含旧商品、旧规格、旧 Logo 或其他需删除的内容", key="v4_confirm_background")
    clean = UploadedPicture(background.name, background.getvalue()) if background and allow_clean else None
    if background and not allow_clean:
        st.warning("尚未确认净背景，当前只用自动生成的纯色底图。")
    choose = st.selectbox("版式配色", list(THEMES), key="v4_style")
    imported = st.file_uploader("可选：导入上次保存的 V4 JSON 布局", type=["json"], key="v4_layout_json")
    try:
        layout = layout_from_json(imported.getvalue()) if imported else default_layout(choose)
        # 导入 JSON 时保留原样式，防止校准的坐标被隐式重置。
        if imported:
            st.caption(f"已载入 JSON 配色：{layout['style']}。如需换配色，请下载备份后删除导入文件，再重新校准。")
    except ValueError as exc:
        st.error(f"布局无法载入：{exc}")
        return None, None, b""

    with st.expander("手动调整区域位置（单位 px）", expanded=False):
        st.caption("按现有模板手动输入 x、y、宽、高。四个区域不能重叠，且不能超出 1440 画布边缘。")
        for name in SLOT_NAMES:
            st.markdown(f"**{LABELS[name]}位置**")
            coords = st.columns(4)
            defaults = layout["slots"][name]
            values = []
            for j, (label, col) in enumerate(zip(("X", "Y", "宽", "高"), coords)):
                with col:
                    values.append(int(st.number_input(
                        f"{LABELS[name]} {label}", min_value=0, max_value=1440,
                        value=int(defaults[j]), step=10,
                        key=f"v4_{name}_{j}_{layout['style']}_{'json' if imported else 'preset'}"
                    )))
            layout["slots"][name] = values
        st.markdown("**标题/面板颜色**")
        palette = layout["colors"]
        c1, c2, c3 = st.columns(3)
        with c1:
            palette["title_fill"] = st.color_picker("标题块", palette["title_fill"], key="v4_title_fill")
            palette["title_color"] = st.color_picker("标题字", palette["title_color"], key="v4_title_color")
        with c2:
            palette["panel"] = st.color_picker("展示区域底色", palette["panel"], key="v4_panel")
            palette["body_text"] = st.color_picker("参数文字", palette["body_text"], key="v4_text")
        with c3:
            palette["background"] = st.color_picker("背景颜色", palette["background"], key="v4_bg")
            palette["accent"] = st.color_picker("参数标注色", palette["accent"], key="v4_accent")

    try:
        validate_layout(layout)
        payload = layout_json(layout)
        st.download_button("📐 保存布局 JSON，下次导入直接复用", payload,
                           file_name="sku_layout_v4.json", mime="application/json", key="v4_download_json")
        reference = UploadedPicture(ref.name, ref.getvalue()) if ref else None
        st.image(preview_regions(layout, reference), caption="预览定位：红=标题，蓝=产品，绿=尺寸图，黄=参数表（线框仅供定位，不加入最终图）", use_container_width=True)
    except (OSError, ValueError) as exc:
        st.error(f"区域设置有误：{exc}")
        return None, None, b""
    return layout, clean, payload
