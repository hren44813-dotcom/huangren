"""V6 SKU 制图前资料核验。仅验证完整性和映射，不核实商品真实性。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError
import io

from .sku_batch import (
    MAX_IMAGES, _image_basename, _specs, _valid_hex, read_sku_rows,
)
from .sku_template_v3 import THEMES
from .sku_rules_v7 import validate_sku_fields
from .workflow import UploadedPicture, validate_upload


@dataclass(frozen=True)
class PreflightReport:
    rows: list[dict[str, str | int]]
    image_count: int

    @property
    def ready(self) -> int:
        return sum(r["状态"] == "可生成" for r in self.rows)

    @property
    def blocked(self) -> int:
        return len(self.rows) - self.ready


def inspect_batch(excel_data: bytes, pictures: list[UploadedPicture], *,
                  template_style: str | None = None,
                  custom_layout: dict | None = None) -> PreflightReport:
    """不创建文件、不改原图；每行返回原因，批内不串用产品原图。"""
    if template_style is not None and template_style not in THEMES:
        raise ValueError("无效的 SKU 模板主题")
    if not pictures or len(pictures) > MAX_IMAGES:
        raise ValueError(f"请上传1到{MAX_IMAGES}张图片")
    if custom_layout is not None:
        from .sku_layout_v4 import validate_layout
        validate_layout(custom_layout)
    source: dict[str, UploadedPicture] = {}
    for pic in pictures:
        name = _image_basename(pic.name)
        if not name or name.casefold() in source:
            raise ValueError(f"上传图片有重名或无效文件名：{pic.name}")
        source[name.casefold()] = pic
    checked: dict[str, str | None] = {}

    def problem(name: str) -> str | None:
        key = name.casefold()
        if key not in source:
            return "图片文件名与上传的图片不匹配"
        if key not in checked:
            try:
                validate_upload(source[key])
                with Image.open(io.BytesIO(source[key].data)) as im:
                    im.verify()
                # 验证通过后重新读取像素；透明空图不应被标记为“可生成”。
                with Image.open(io.BytesIO(source[key].data)) as im:
                    if "A" in im.getbands() and im.getchannel("A").getextrema()[1] == 0:
                        raise ValueError("图片全透明，没有可见产品内容")
            except (ValueError, OSError, UnidentifiedImageError) as exc:
                checked[key] = f"图片文件损坏或不受支持：{exc}"
            else:
                checked[key] = None
        return checked[key]

    found: set[str] = set()
    output: list[dict[str, str | int]] = []
    for row in read_sku_rows(excel_data):
        data = row.data
        sku = data["SKU编码"].strip()
        photo = data["图片文件名"].strip()
        drawing = data.get("尺寸图文件名", "").strip()
        problems: list[str] = []
        if sku.casefold() in found:
            problems.append("SKU编码重复")
        found.add(sku.casefold())
        try:
            validate_sku_fields(data, uses_dimension_layer=template_style is not None or custom_layout is not None)
        except ValueError as exc:
            problems.append(str(exc))
        if photo:
            if photo != _image_basename(photo) or photo in (".", ".."):
                problems.append("产品图片文件名不能包含路径")
            else:
                issue = problem(photo)
                if issue:
                    problems.append(f"产品图：{issue}")
        if drawing and (template_style is not None or custom_layout is not None):
            if drawing != _image_basename(drawing) or drawing in (".", ".."):
                problems.append("尺寸图文件名不能包含路径")
            else:
                issue = problem(drawing)
                if issue:
                    problems.append(f"尺寸图：{issue}")
        output.append({"Excel行号": row.row_number, "SKU": sku,
                       "状态": "需修正" if problems else "可生成",
                       "原因": "；".join(problems) if problems else "图片及必填字段可用于制图；商品真实性待人工核对"})
    return PreflightReport(output, len(pictures))
