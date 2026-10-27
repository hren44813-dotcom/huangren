"""V4 可校准 SKU 模板布局：区域坐标按 1440px 画布保存，不识别或重画商品结构。"""
from __future__ import annotations

import io
import json
import re
from typing import Any

from PIL import Image, ImageDraw, ImageOps

from .generator import _contain, _draw_fit
from .quality import audit_export
from .sku_template_v3 import THEMES, _read_picture
from .workflow import UploadedPicture, validate_upload

SIZE = 1440
MAX_JSON = 32 * 1024
SLOT_NAMES = ("title", "product", "drawing", "specs")
LABELS = {"title": "标题", "product": "产品图", "drawing": "尺寸图", "specs": "参数表"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def default_layout(style: str = "蓝白工业参数风") -> dict[str, Any]:
    if style not in THEMES:
        raise ValueError("找不到指定工业模板风格")
    theme = THEMES[style]
    return {
        "version": 1,
        "canvas": [SIZE, SIZE],
        "style": style,
        "colors": {
            "background": theme.background,
            "title_fill": theme.header,
            "title_color": theme.header_text,
            "panel": theme.panel,
            "body_text": theme.body_text,
            "accent": theme.accent,
        },
        "slots": {
            "title": [52, 42, 1336, 146],
            "product": [76, 225, 776, 815],
            "drawing": [880, 225, 480, 815],
            "specs": [52, 1100, 1336, 280],
        },
    }


def validate_layout(layout: Any) -> dict[str, Any]:
    """完整验证 JSON 布局：拒绝越界、区域重叠、非整数坐标与未知字段。"""
    if not isinstance(layout, dict) or set(layout) != {"version", "canvas", "style", "colors", "slots"}:
        raise ValueError("布局文件缺少必要字段，或包含不支持的字段")
    if type(layout["version"]) is not int or layout["version"] != 1 or layout["canvas"] != [SIZE, SIZE]:
        raise ValueError("仅支持版本1、1440×1440的模板布局")
    if layout["style"] not in THEMES:
        raise ValueError("模板风格不受支持")
    c = layout["colors"]
    if not isinstance(c, dict) or set(c) != {"background", "title_fill", "title_color", "panel", "body_text", "accent"}:
        raise ValueError("模板颜色配置无效")
    for key, value in c.items():
        if not isinstance(value, str) or not HEX.fullmatch(value):
            raise ValueError(f"颜色 {key} 必须是 #RRGGBB")
    s = layout["slots"]
    if not isinstance(s, dict) or set(s) != set(SLOT_NAMES):
        raise ValueError("必须指定标题、产品图、尺寸图、参数表四块区域")
    rects: dict[str, tuple[int, int, int, int]] = {}
    for name in SLOT_NAMES:
        rect = s[name]
        if not isinstance(rect, list) or len(rect) != 4 or any(type(v) is not int for v in rect):
            raise ValueError(f"{LABELS[name]}坐标必须是4个整数")
        x, y, w, h = rect
        if x < 20 or y < 20 or w < 160 or h < 65 or x + w > SIZE - 20 or y + h > SIZE - 20:
            raise ValueError(f"{LABELS[name]}区域越界或太小，请保留20px画布边距")
        rects[name] = (x, y, w, h)
    for i, a in enumerate(SLOT_NAMES):
        xa, ya, wa, ha = rects[a]
        for b in SLOT_NAMES[i + 1:]:
            xb, yb, wb, hb = rects[b]
            if min(xa + wa, xb + wb) > max(xa, xb) and min(ya + ha, yb + hb) > max(ya, yb):
                raise ValueError(f"{LABELS[a]}与{LABELS[b]}位置重叠，请调整")
    return layout


def layout_from_json(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > MAX_JSON:
        raise ValueError("JSON 布局文件为空或超过32KB")
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("模板 JSON 格式不正确") from exc
    return validate_layout(value)


def layout_json(layout: dict[str, Any]) -> bytes:
    validate_layout(layout)
    return json.dumps(layout, ensure_ascii=False, indent=2).encode("utf-8")


def _background(template: UploadedPicture | None, background_color: str) -> Image.Image:
    if template is None:
        return Image.new("RGB", (SIZE, SIZE), background_color)
    validate_upload(template)
    with Image.open(io.BytesIO(template.data)) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
    if image.size != (SIZE, SIZE):
        raise ValueError("净背景模板必须为1440×1440，避免背景拉伸变形")
    return image


def preview_regions(layout: dict[str, Any], reference: UploadedPicture | None = None) -> bytes:
    """显示区块线框，仅用于位置预览。参考图不用于产品输出。"""
    validate_layout(layout)
    image = _background(reference, layout["colors"]["background"])
    draw = ImageDraw.Draw(image)
    for name, color in zip(SLOT_NAMES, ("#E84855", "#0D7FF4", "#16A34A", "#E0A800")):
        x, y, w, h = layout["slots"][name]
        draw.rectangle((x, y, x + w - 1, y + h - 1), outline=color, width=7)
    b = io.BytesIO()
    image.save(b, format="PNG")
    return b.getvalue()


def render_custom_sku(
    product: UploadedPicture,
    *, drawing: UploadedPicture | None,
    title: str,
    specs: list[dict[str, str]],
    layout: dict[str, Any],
    clean_template: UploadedPicture | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """根据自定义区块重排真实图层，原图片仅裁透明外边距和等比缩放。"""
    validate_layout(layout)
    if not title or not isinstance(title, str) or not title.strip():
        raise ValueError("SKU 标题不能为空")
    if not isinstance(specs, list) or len(specs) > 4 or any(
        not isinstance(item, dict) or not isinstance(item.get("label"), str)
        or not isinstance(item.get("value"), str) for item in specs
    ):
        raise ValueError("参数必须是最多4条真实 label/value 文本")
    product_image = _read_picture(product)
    drawing_image = _read_picture(drawing) if drawing else None
    colors, rects = layout["colors"], layout["slots"]
    canvas = _background(clean_template, colors["background"])
    draw = ImageDraw.Draw(canvas)

    # 在模板指定区域覆盖纯色面板，确保只保留正确的标题、产品和原尺寸图。
    for name in SLOT_NAMES:
        x, y, w, h = rects[name]
        draw.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=14,
                               fill=colors["title_fill"] if name == "title" else colors["panel"])
    x, y, w, h = rects["title"]
    _draw_fit(draw, title.strip(), (x + 24, y + max(6, (h - 65)//2)), w - 48,
              max_size=min(62, h - 16), min_size=22, fill=colors["title_color"], font_path=None)

    def image_in_slot(image: Image.Image, name: str) -> None:
        x, y, w, h = rects[name]
        margin = max(12, min(30, w // 25, h // 25))
        _contain(canvas, image, (x + margin, y + margin, w - margin*2, h - margin*2))

    image_in_slot(product_image, "product")
    if drawing_image is not None:
        image_in_slot(drawing_image, "drawing")

    x, y, w, h = rects["specs"]
    if specs:
        # 对照行固定在参数栏内部；文字过长会报错，不遮挡其他区块。
        rows = 2 if len(specs) > 2 else 1
        cols = 2 if len(specs) > 1 else 1
        cell_w = (w - 40) // cols
        cell_h = (h - 34) // rows
        for i, entry in enumerate(specs):
            col, row = i % cols, i // cols
            px = x + 20 + col * cell_w
            py = y + 17 + row * cell_h
            draw.rectangle((px, py + 5, px + 7, py + min(52, cell_h - 20)), fill=colors["accent"])
            value_text = entry["value"].strip()
            label_text = entry["label"].strip()
            if not label_text or not value_text:
                raise ValueError("参数名称或内容不能为空")
            name_width = min(170, max(80, cell_w // 3))
            available_value = cell_w - name_width - 34
            if available_value < 95:
                raise ValueError("参数区域太窄，请增加宽度")
            max_font = min(31, max(22, cell_h - 22))
            _draw_fit(draw, label_text, (px + 18, py + 12), name_width - 16,
                      max_size=max_font, min_size=18, fill=colors["body_text"], font_path=None)
            _draw_fit(draw, value_text, (px + name_width + 18, py + 12), available_value,
                      max_size=max_font, min_size=18, fill=colors["body_text"], font_path=None)
    with io.BytesIO() as dest:
        canvas.save(dest, format="JPEG", quality=94, optimize=True, subsampling=0)
        raw = dest.getvalue()
    if not audit_export("V4_SKU.jpg", raw, "sku")["auto_pass"]:
        raise ValueError("自定义版式未通过像素/格式自动质检")
    return raw, {
        "mode": "sku", "width": SIZE, "height": SIZE, "template_version": 4,
        "layout": json.loads(json.dumps(layout, ensure_ascii=False)),
        "source_name": product.name,
        "dimension_source": drawing.name if drawing else None,
        "background_source": clean_template.name if clean_template else None,
        "product_preserved": "原图仅裁透明外边距、等比例缩放和JPEG编码；无结构重绘",
        "annotation_policy": "尺寸图原样等比放入指定区域，不重新绘制标注",
        "manual_review_required": True,
    }
