"""V5 SKU 布局控制台：本地模板库、区域微调和实时线框预览。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

from .sku_layout_v4 import (
    LABELS, SLOT_NAMES, default_layout, layout_from_json, layout_json,
    preview_regions, validate_layout,
)
from .sku_template_v3 import THEMES
from .template_library_v5 import delete_template, list_templates, load_template, save_template
from .workflow import UploadedPicture

LIBRARY = Path(__file__).resolve().parents[2] / ".local" / "sku_templates"


def configure(st) -> tuple[dict | None, UploadedPicture | None, bytes]:
    st.markdown("#### V5：SKU 模板校准与本机模板库")
    st.info("旧成品图仅供位置参考，不会自动擦除旧文字。最终可选用清理干净的1440×1440底图；本机模板库只保存版式JSON，不上传照片。")
    left, right = st.columns(2)
    with left:
        ref = st.file_uploader("参考旧 SKU 图（只用于位置预览）", type=["png", "jpg", "jpeg", "webp"], key="v4_reference")
    with right:
        background = st.file_uploader("可选：干净的1440×1440背景图", type=["png", "jpg", "jpeg", "webp"], key="v4_clean_background")
    allow_clean = st.checkbox("我确认净背景不含旧商品、旧规格或旧Logo", key="v4_confirm_background")
    clean = UploadedPicture(background.name, background.getvalue()) if background and allow_clean else None
    if background and not allow_clean:
        st.warning("未确认净背景清洁，生成时将改用纯色背景。")

    style = st.selectbox("工业版式配色", list(THEMES), key="v4_style")
    library_names = list_templates(LIBRARY)
    selected = st.selectbox("从本机模板库载入版式（可选）", ["使用默认版式", *library_names], key="v5_library_select")
    imported = st.file_uploader("或上传已有 JSON 布局", type=["json"], key="v4_layout_json")
    try:
        if imported:
            layout = layout_from_json(imported.getvalue())
            st.caption("优先使用上传的 JSON；不自动切换文件中保存的版式颜色。")
        elif selected != "使用默认版式":
            layout = load_template(LIBRARY, selected)
        else:
            layout = default_layout(style)
        source_key = hashlib.sha256(layout_json(layout)).hexdigest()[:12]
    except (ValueError, OSError) as exc:
        st.error(f"模板加载失败：{exc}")
        return None, None, b""

    with st.expander("调整布局：箭头微调、坐标及配色（调整后下方实时预览）", expanded=True):
        st.caption("本版支持按钮微调和数值定位（非鼠标拖拽）。调整时会检查越界和区域重叠。")
        selected_slot = st.selectbox("需要移动的区域", list(SLOT_NAMES),
                                     format_func=lambda n: LABELS[n], key="v5_slot")
        steps = st.select_slider("移动步长（像素）", options=[5, 10, 20, 40], value=10, key="v5_step")
        moves = st.columns(4)
        commands = (("← 左移", -steps, 0), ("→ 右移", steps, 0), ("↑ 上移", 0, -steps), ("↓ 下移", 0, steps))
        for col, (label, dx, dy) in zip(moves, commands):
            with col:
                if st.button(label, key=f"v5_move_{label}_{source_key}", use_container_width=True):
                    candidate = deepcopy(layout)
                    for name in SLOT_NAMES:
                        for i in range(4):
                            key = f"v5_rect_{source_key}_{name}_{i}"
                            candidate["slots"][name][i] = int(st.session_state.get(key, layout["slots"][name][i]))
                    candidate["slots"][selected_slot][0] += dx
                    candidate["slots"][selected_slot][1] += dy
                    try:
                        validate_layout(candidate)
                    except ValueError as exc:
                        st.warning(f"无法移动：{exc}")
                    else:
                        for idx in (0, 1):
                            st.session_state[f"v5_rect_{source_key}_{selected_slot}_{idx}"] = candidate["slots"][selected_slot][idx]
        st.markdown("**各区域位置**（X / Y / 宽 / 高，单位 px）")
        for name in SLOT_NAMES:
            st.caption(LABELS[name])
            coords = st.columns(4)
            defaults = layout["slots"][name]
            values = []
            for i, (label, col) in enumerate(zip(("X", "Y", "宽", "高"), coords)):
                with col:
                    values.append(int(st.number_input(
                        f"{LABELS[name]} {label}", min_value=0, max_value=1440,
                        value=int(defaults[i]), step=5, key=f"v5_rect_{source_key}_{name}_{i}")))
            layout["slots"][name] = values
        st.markdown("**模板颜色**")
        colors = layout["colors"]
        pick = st.columns(3)
        for i, (field, label) in enumerate((
            ("title_fill", "标题色块"), ("title_color", "标题字体"),
            ("panel", "面板"), ("body_text", "正文"),
            ("background", "背景"), ("accent", "参数标注"),
        )):
            with pick[i % 3]:
                colors[field] = st.color_picker(label, colors[field], key=f"v5_color_{source_key}_{field}")

    try:
        validate_layout(layout)
        payload = layout_json(layout)
        st.download_button("📐 下载布局 JSON，方便跨电脑复用", payload,
                           file_name="sku_layout_v5.json", mime="application/json", key="v5_download_layout")
        st.image(preview_regions(layout, UploadedPicture(ref.name, ref.getvalue()) if ref else None),
                 caption="实时位置预览：红=标题、蓝=产品、绿=原尺寸图、黄=参数；线框不会出现在最终图片里", use_container_width=True)
    except (OSError, ValueError) as exc:
        st.error(f"区域设置不合格：{exc}")
        return None, None, b""

    with st.expander("本机模板库：保存 / 删除", expanded=False):
        st.caption("模板库存放在项目的 .local/sku_templates/，不上传 GitHub，不保存商品图片。在线临时主机重启后可能丢失，请同时下载 JSON 备份。")
        new_name = st.text_input("模板名称", placeholder="例如：LS拉手-蓝白-横版", key="v5_name")
        overwrite = st.checkbox("覆盖同名模板", key="v5_overwrite")
        if st.button("保存当前布局到本机", key="v5_save"):
            try:
                actual = save_template(LIBRARY, new_name, layout, overwrite=overwrite)
                st.success(f"已保存本机模板：{actual}。建议同时下载 JSON 备份。")
            except (ValueError, OSError) as exc:
                st.error(f"保存失败：{exc}")
        if selected != "使用默认版式":
            sure = st.checkbox(f"确认删除模板「{selected}」", key="v5_delete_confirm")
            if st.button("删除选中的本机模板", disabled=not sure, key="v5_delete"):
                try:
                    delete_template(LIBRARY, selected)
                    st.success("已删除模板。请重新选择默认版式或其他模板。")
                except (ValueError, OSError) as exc:
                    st.error(f"删除失败：{exc}")
    return layout, clean, payload
