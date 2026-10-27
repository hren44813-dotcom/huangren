"""V3 工业 SKU 图风格预设：仅等比例叠放真实产品图和原尺寸图，不改写尺寸标注。"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from .generator import _contain, _draw_fit, _font
from .quality import audit_export
from .workflow import UploadedPicture, validate_upload

WIDTH = HEIGHT = 1440

@dataclass(frozen=True)
class TemplateTheme:
    name: str
    background: str
    header: str
    header_text: str
    accent: str
    panel: str
    body_text: str

THEMES = {
    "蓝白工业参数风": TemplateTheme("蓝白工业参数风", "#F4F7FA", "#0D7FF4", "#FFFFFF", "#0D7FF4", "#FFFFFF", "#162A3B"),
    "黄黑工业风": TemplateTheme("黄黑工业风", "#F8F8F4", "#F5C518", "#111820", "#F5C518", "#FFFFFF", "#17212B"),
    "灰白极简技术风": TemplateTheme("灰白极简技术风", "#F4F6F7", "#64748B", "#FFFFFF", "#64748B", "#FFFFFF", "#202B35"),
}


def _read_picture(file: UploadedPicture) -> Image.Image:
    """保持原产品结构与尺寸图文字：透明区可裁，主体只等比缩放。"""
    validate_upload(file)
    try:
        with Image.open(io.BytesIO(file.data)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGBA")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"无法读取图片：{file.name}") from exc
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] < 255:
        box = alpha.getbbox()
        if not box:
            raise ValueError(f"图片完全透明：{file.name}")
        image = image.crop(box)
    return image


def render_sku_template(product: UploadedPicture, *, drawing: UploadedPicture | None = None,
                        title: str, specs: list[dict[str, str]], style: str = "蓝白工业参数风") -> tuple[bytes, dict[str, Any]]:
    """一个 SKU 生成一个 1440 正方 JPG；图上没有任何推断出来的参数。"""
    if style not in THEMES:
        raise ValueError(f"未知 SKU 预设：{style}")
    if not title or not title.strip():
        raise ValueError("SKU 标题不能为空")
    if not isinstance(specs, list) or len(specs) > 4:
        raise ValueError("SKU 参数只能填写最多 4 组已核实值")
    for entry in specs:
        if not isinstance(entry, dict) or not isinstance(entry.get("label"), str) or not isinstance(entry.get("value"), str):
            raise ValueError("规格必须是 label、value 的文本字典")
    theme = THEMES[style]
    product_img = _read_picture(product)
    size_img = _read_picture(drawing) if drawing else None
    canvas = Image.new("RGB", (WIDTH, HEIGHT), theme.background)
    draw = ImageDraw.Draw(canvas)
    # 全部色块位于画布内，没有四周边框。
    draw.rounded_rectangle((52, 45, 1388, 178), radius=22, fill=theme.header)
    _draw_fit(draw, title.strip(), (99, 78), 1230, 62, 28, theme.header_text, None)
    draw.rounded_rectangle((57, 210, 1383, 1087), radius=22, fill=theme.panel)
    if size_img is None:
        _contain(canvas, product_img, (110, 260, 1220, 775))
    else:
        # 产品展示区、原尺寸图展示区独立：不会修改原图已有的数字和引线。
        _contain(canvas, product_img, (95, 256, 748, 766))
        draw.line((854, 295, 854, 1010), fill="#DCE3E8", width=3)
        _draw_fit(draw, "原始尺寸图", (895, 253), 410, 34, 24, theme.body_text, None)
        _contain(canvas, size_img, (895, 318, 416, 690))
    if specs:
        draw.rounded_rectangle((57, 1112, 1383, 1392), radius=22, fill=theme.panel)
        for idx, spec in enumerate(specs):
            x = 100 + (idx % 2) * 640
            y = 1147 + (idx // 2) * 114
            draw.rounded_rectangle((x, y + 4, x + 9, y + 66), radius=4, fill=theme.accent)
            _draw_fit(draw, spec["label"].strip(), (x + 24, y + 8), 185, 38, 22, "#64748B", None)
            _draw_fit(draw, spec["value"].strip(), (x + 216, y + 8), 360, 38, 22, theme.body_text, None)
    with io.BytesIO() as buffer:
        canvas.save(buffer, format="JPEG", quality=94, optimize=True, subsampling=0)
        raw = buffer.getvalue()
    quality = audit_export("SKU_template.jpg", raw, "sku")
    if not quality["auto_pass"]:
        raise RuntimeError("生成图片未通过尺寸/格式质检")
    return raw, {"mode": "sku", "width": WIDTH, "height": HEIGHT, "style": style,
                 "source_name": product.name, "dimension_source": drawing.name if drawing else None,
                 "product_preserved": "仅等比例缩放；原照片像素经 JPEG 编码，需人工核对",
                 "annotation_policy": "原尺寸图作为完整图片等比缩放；不重新绘制引线或数字",
                 "manual_review_required": True}
