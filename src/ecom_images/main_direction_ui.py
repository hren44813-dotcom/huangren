"""Streamlit 运营助理主图方向策划页。"""
from __future__ import annotations

import hashlib
import json

from .main_directions import ProductBrief, plan_directions
from .workflow import UploadedPicture, produce_images, validate_upload


def render(st, platform: str) -> None:
    st.subheader("主图方向自动策划｜先选方向，再生成")
    st.caption("使用人工填写的真实信息输出 3 个方向；不调用 AI，也不自动看图识别材质或尺寸。")
    photo = st.file_uploader("上传产品原图（策划时可不上传，正式制图必填）",
                             type=["png", "jpg", "jpeg", "webp"], key="direction_upload")
    if photo:
        st.image(photo, caption="产品参考原图", width=260)
    a, b = st.columns(2)
    with a:
        name = st.text_input("真实商品名称 / 型号（必填）", key="direction_product",
                             placeholder="如：MS705 转舌锁")
        category = st.selectbox("产品类别", ["工业锁具", "工业拉手", "工业铰链",
                                          "阻尼转轴", "其他工业五金"], key="direction_category")
        spec = st.text_input("已核实规格（可留空）", key="direction_spec",
                             placeholder="只写有依据的孔距、尺寸等")
    with b:
        features = st.text_input("已确认卖点（可留空）", key="direction_features",
                                 placeholder="只写真实产品资料支持的卖点")
        scene = st.text_input("已核实使用场景（可留空）", key="direction_scene")
        concern = st.text_input("买家顾虑（可留空）", key="direction_concern",
                                placeholder="如：担心安装孔位不匹配")
    brief = ProductBrief(name, category, features, spec, scene, concern, platform)
    signature = (brief, photo.name if photo else None,
                 hashlib.sha256(photo.getvalue()).hexdigest() if photo else None)

    if st.button("① 自动输出 3 个主图方向", type="primary", use_container_width=True):
        try:
            profile, ideas = plan_directions(brief)
            st.session_state["direction_plan"] = (signature, profile, ideas)
            st.session_state["direction_selected"] = None
            st.session_state.pop("direction_rendered", None)
        except ValueError as exc:
            st.error(str(exc))

    stored = st.session_state.get("direction_plan")
    if stored is None:
        return
    old_signature, profile, ideas = stored
    if signature != old_signature:
        st.warning("产品资料或图片已变化，请重新点击“自动输出 3 个主图方向”。")
        return

    st.markdown("#### ① 商品信息与买家顾虑")
    for key, value in profile.items():
        st.write(f"**{key}：** {value}")
    if not concern.strip():
        st.info("还未填写买家顾虑；请运营人员核实，不把模板内容冒充调研结论。")

    st.markdown("#### ② 三个可选主图方向")
    for idea in ideas:
        with st.container(border=True):
            st.markdown(f"**{idea.name}**")
            st.write(f"视觉重点：{idea.visual}")
            st.write(f"**点击理由：{idea.click_reason}**")
            st.caption(f"限制：{idea.limitations}")

    picked_key = st.radio("选择一个方向后再生成正式图",
                          [idea.key for idea in ideas],
                          format_func=lambda key: next(d.name for d in ideas if d.key == key),
                          index=None, key="direction_selected")
    if picked_key is None:
        return
    chosen = next(idea for idea in ideas if idea.key == picked_key)
    st.success(f"已选：{chosen.name}")
    st.caption("此处为现有 Pillow 基础排版，只调整配色与已核实文案；复杂场景和不同拍摄角度需另行设计。")
    plan = json.dumps({"product": profile, "direction": chosen.__dict__},
                      ensure_ascii=False, indent=2)
    st.download_button("下载方向策划 JSON", data=plan,
                       file_name="main_image_direction.json", mime="application/json",
                       key="direction_plan_download")

    if st.button("② 按已选方向生成基础主图（1440×1440）", use_container_width=True):
        if not photo:
            st.error("缺少真实产品原图，暂不能制作主图。")
        else:
            try:
                src = UploadedPicture(photo.name, photo.getvalue())
                validate_upload(src)
                result = produce_images([src], ["main"], 1, title=name.strip(),
                                        subtitle=chosen.headline,
                                        accent=chosen.accent, background=chosen.background)
                if result.errors:
                    for error in result.errors:
                        st.error(error)
                if result.images:
                    st.session_state["direction_rendered"] = (signature, picked_key, result)
            except (ValueError, OSError, RuntimeError) as exc:
                st.error(f"主图生成失败：{exc}")

    output = st.session_state.get("direction_rendered")
    if output and output[0] == signature and output[1] == picked_key:
        for _, content, meta in output[2].images:
            st.image(content, caption=f"{chosen.name} · {meta['width']}×{meta['height']}", width=420)
            st.download_button("下载基础主图 JPG", data=content,
                               file_name="main_image_1440.jpg", mime="image/jpeg",
                               key="direction_image_download")
        st.warning("请人工核对产品孔位、外形、文案和平台最新规格；模板尺寸不代表平台审核保证。")
