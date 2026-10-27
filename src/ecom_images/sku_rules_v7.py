"""共享的 SKU 行校验规则：批前预检查和实际生成共用，防止两处行为分叉。"""
from __future__ import annotations

from .sku_batch import _dimension, _image_basename, _valid_hex


def validate_sku_fields(data: dict[str, str], *, uses_dimension_layer: bool) -> None:
    """校验格式和所选模板的字段支持；不推断或认证真实规格。"""
    sku = data["SKU编码"].strip()
    name = data["商品名称"].strip()
    product = data["图片文件名"].strip()
    drawing = data.get("尺寸图文件名", "").strip()
    if not sku or not name or not product:
        raise ValueError("SKU编码、商品名称、图片文件名均为必填")
    if len(sku) > 80:
        raise ValueError("SKU编码过长（最多80字符）")
    for value, label in ((product, "图片文件名"), (drawing, "尺寸图文件名")):
        if value and (value != _image_basename(value) or value in {".", ".."}):
            raise ValueError(f"{label}只能填写文件名，不能包含目录或路径")
    if drawing and not uses_dimension_layer:
        raise ValueError("V2经典模板不支持单独尺寸图，请切换V3/V4/V5模板，或清空尺寸图文件名")
    for key in ("孔距(mm)", "总长(mm)"):
        value = data.get(key, "").strip()
        if value:
            _dimension(value, key)
    if not uses_dimension_layer:
        accent = _valid_hex(data["色块颜色"] or "#0D7FF4", "色块颜色")
        _valid_hex(data["标题字色"] or ("#000000" if accent.upper() in {"#F5C518", "#FFFF00"} else "#FFFFFF"), "标题字色")
