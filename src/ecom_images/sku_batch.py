"""Excel 商品 SKU 清单 + 图片 ZIP / 多文件上传 → 批量规格图。

不推断产品参数；只读取「SKU清单」工作表的显式值，不运行 Excel 公式。
为避免服务端引入重型 Excel 依赖，只用标准库安全读取 XLSX OOXML。
"""
from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
import io
import json
import posixpath
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .generator import build_job
from .quality import audit_export
from .workflow import BatchResult, MAX_UPLOAD, UploadedPicture, clean_stem, validate_upload

COLUMNS = (
    "SKU编码", "商品名称", "图片文件名", "型号", "孔距(mm)", "总长(mm)",
    "材质", "表面处理", "色块颜色", "标题字色", "尺寸图文件名",
)
REQUIRED_COLUMNS = ("SKU编码", "商品名称", "图片文件名")
MAX_ROWS = 80
MAX_IMAGES = 120
MAX_ZIP_UNCOMPRESSED = 400 * 1024 * 1024
MAX_XLSX_BYTES = 6 * 1024 * 1024
MAX_XML_BYTES = 12 * 1024 * 1024
MAIN_SHEET = "SKU清单"
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True)
class SkuRow:
    row_number: int
    data: dict[str, str]


@dataclass
class SkuBatchResult:
    images: list[tuple[str, bytes, dict[str, Any]]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def successes(self) -> int:
        return sum(r["status"] == "success" for r in self.rows)

    @property
    def failures(self) -> int:
        return sum(r["status"] == "failed" for r in self.rows)

    def zip_bytes(self) -> bytes:
        base = BatchResult(images=self.images, errors=[
            f"第{row['excel_row']}行 {row['sku']}: {row['message']}"
            for row in self.rows if row["status"] == "failed"
        ])
        buffer = io.BytesIO(base.zip_bytes())
        report = io.StringIO(newline="")
        writer = csv.DictWriter(report, fieldnames=["excel_row", "sku", "source_file", "status", "output_file", "message"])
        writer.writeheader()
        writer.writerows({key: _csv_safe(value) for key, value in row.items()} for row in self.rows)
        with zipfile.ZipFile(buffer, "a", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("sku_import_report.csv", "\ufeff" + report.getvalue())
            archive.writestr("sku_import_report.json", json.dumps(self.rows, ensure_ascii=False, indent=2))
        return buffer.getvalue()


def _safe_xml(archive: zipfile.ZipFile, name: str) -> ET.Element:
    try:
        member = archive.getinfo(name)
    except KeyError as exc:
        raise ValueError(f"Excel 缺少必要结构：{name}") from exc
    if member.file_size > MAX_XML_BYTES:
        raise ValueError("Excel XML 内容过大")
    raw = archive.read(name)
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Excel 包含不允许的 XML 声明")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("Excel XML 内容损坏") from exc


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    xml = _safe_xml(archive, "xl/sharedStrings.xml")
    return ["".join(t.text or "" for t in si.iter(f"{M}t")) for si in xml.findall(f"{M}si")]


def _sheet_filename(archive: zipfile.ZipFile) -> str:
    wb = _safe_xml(archive, "xl/workbook.xml")
    sheets = wb.find(f"{M}sheets")
    match = next((s for s in (list(sheets) if sheets is not None else []) if s.attrib.get("name") == MAIN_SHEET), None)
    if match is None:
        raise ValueError(f"找不到工作表「{MAIN_SHEET}」，请使用下载的 Excel 模板")
    relation_id = match.attrib.get(f"{R}id")
    relationships = _safe_xml(archive, "xl/_rels/workbook.xml.rels")
    rel = next((x for x in relationships.findall(f"{PKG}Relationship") if x.attrib.get("Id") == relation_id), None)
    if rel is None or rel.attrib.get("TargetMode") == "External":
        raise ValueError("Excel 工作表关系无效")
    target = rel.attrib.get("Target")
    if not target:
        raise ValueError("Excel 工作表目标路径缺失")
    result = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target))
    if not result.startswith("xl/worksheets/") or result not in archive.namelist():
        raise ValueError("Excel 工作表路径非法")
    return result


def _cell_text(cell: ET.Element, strings: list[str]) -> str:
    if cell.find(f"{M}f") is not None:
        raise ValueError("不允许公式单元格：请复制并粘贴为纯数值后导入")
    kind = cell.attrib.get("t")
    if kind == "inlineStr":
        inline = cell.find(f"{M}is")
        return "".join(t.text or "" for t in inline.iter(f"{M}t")) if inline is not None else ""
    v = cell.find(f"{M}v")
    raw = v.text if v is not None and v.text is not None else ""
    if kind == "s":
        try:
            index = int(raw)
            if index < 0:
                raise ValueError("共享字符串索引不能为负数")
            return strings[index]
        except (ValueError, IndexError) as exc:
            raise ValueError("Excel 共享字符串索引无效") from exc
    return raw


def read_sku_rows(file_data: bytes) -> list[SkuRow]:
    """读取自定义 XLSX 模板的 SKU清单；非空行最多 80 行。"""
    if not file_data or len(file_data) > MAX_XLSX_BYTES or not zipfile.is_zipfile(io.BytesIO(file_data)):
        raise ValueError("请上传有效且小于 6MB 的 .xlsx Excel 文件")
    with zipfile.ZipFile(io.BytesIO(file_data)) as archive:
        if len(archive.infolist()) > 250 or sum(x.file_size for x in archive.infolist()) > 35 * 1024 * 1024:
            raise ValueError("Excel 内容过大或结构异常")
        strings = _shared_strings(archive)
        sheet = _safe_xml(archive, _sheet_filename(archive))
        cells: dict[int, dict[int, str]] = {}
        for row in sheet.iter(f"{M}row"):
            for cell in row.findall(f"{M}c"):
                match = re.fullmatch(r"([A-Z]{1,3})([1-9]\d*)", cell.attrib.get("r", ""))
                if not match:
                    continue
                col = 0
                for letter in match.group(1):
                    col = col * 26 + ord(letter) - 64
                col -= 1
                number = int(match.group(2))
                if number > 2000:
                    continue
                if col < 32:
                    cells.setdefault(number, {})[col] = _cell_text(cell, strings).strip()
        header = cells.get(1, {})
        positions = {v: k for k, v in header.items()}
        missing = [n for n in REQUIRED_COLUMNS if n not in positions]
        if missing:
            raise ValueError("Excel 缺少必填列：" + "、".join(missing))
        duplicate_headers = [n for n in COLUMNS if list(header.values()).count(n) > 1]
        if duplicate_headers:
            raise ValueError("Excel 表头重复：" + "、".join(duplicate_headers))
        result: list[SkuRow] = []
        for number in sorted(n for n in cells if n >= 2):
            d = {k: cells[number].get(positions[k], "") if k in positions else "" for k in COLUMNS}
            if not any(d.values()):
                continue
            result.append(SkuRow(number, d))
            if len(result) > MAX_ROWS:
                raise ValueError(f"一次最多导入 {MAX_ROWS} 个 SKU，请分批处理")
        if not result:
            raise ValueError("SKU清单中没有数据，请从第2行开始填写")
        return result


def _image_basename(name: str) -> str:
    return str(name).replace("\\", "/").split("/")[-1].strip()


def unpack_image_zip(zip_data: bytes) -> list[UploadedPicture]:
    """读取 ZIP 中产品图，绝不解压到文件系统。拒绝重名及超大压缩包。"""
    if not zip_data or len(zip_data) > 70 * 1024 * 1024 or not zipfile.is_zipfile(io.BytesIO(zip_data)):
        raise ValueError("请上传有效且小于 70MB 的图片 ZIP")
    out: list[UploadedPicture] = []
    seen: set[str] = set()
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        if len(zf.infolist()) > MAX_IMAGES + 30 or sum(i.file_size for i in zf.infolist()) > MAX_ZIP_UNCOMPRESSED:
            raise ValueError("ZIP 文件数量或解压后大小超过限制")
        for item in zf.infolist():
            if item.is_dir() or _image_basename(item.filename).startswith("."):
                continue
            filename = _image_basename(item.filename)
            if Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            if item.file_size > MAX_UPLOAD:
                raise ValueError(f"图片超过 12MB：{filename}")
            if filename.casefold() in seen:
                raise ValueError(f"ZIP 中出现重名图片：{filename}")
            seen.add(filename.casefold())
            picture = UploadedPicture(filename, zf.read(item))
            out.append(picture)
            if len(out) > MAX_IMAGES:
                raise ValueError(f"图片数量最多 {MAX_IMAGES} 张")
    if not out:
        raise ValueError("ZIP 中没有支持的图片")
    return out


def _valid_hex(value: str, label: str) -> str:
    if not COLOR_RE.fullmatch(value):
        raise ValueError(f"{label}必须是 #RRGGBB 颜色，如 #0D7FF4")
    return value


def _dimension(value: str, column: str) -> str:
    """毫米字段只接受真实纯数字；阻止单位重复/公式/科学记数法。"""
    if not re.fullmatch(r"\d{1,6}(?:\.\d{1,3})?", value):
        raise ValueError(f"{column}必须为不含单位的正数，例如 200 或 228.5")
    try:
        if not (Decimal("0") < Decimal(value) <= Decimal("100000")):
            raise ValueError(f"{column}必须大于0且不超过100000毫米")
    except InvalidOperation as exc:
        raise ValueError(f"{column}的数字格式无效") from exc
    return value


def _csv_safe(value: Any) -> str:
    """Excel 打开 CSV 时避免用户输入成为公式。"""
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")) else value


def _specs(row: dict[str, str]) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    if row["型号"]:
        specs.append({"label": "型号", "value": row["型号"]})
    if row["孔距(mm)"]:
        specs.append({"label": "孔距", "value": f"{_dimension(row['孔距(mm)'], '孔距(mm)')} mm"})
    if row["总长(mm)"]:
        specs.append({"label": "总长", "value": f"{_dimension(row['总长(mm)'], '总长(mm)')} mm"})
    if row["材质"] or row["表面处理"]:
        value = " / ".join(v for v in (row["材质"], row["表面处理"]) if v)
        specs.append({"label": "材质/工艺", "value": value})
    return specs


def build_sku_batch(excel_data: bytes, pictures: list[UploadedPicture], *, template_style: str | None = None,
                    custom_layout: dict[str, Any] | None = None,
                    clean_template: UploadedPicture | None = None,
                    allowed_row_numbers: frozenset[int] | None = None) -> SkuBatchResult:
    """每行独立生成，失败行记录原因；不以其他图片替代缺失产品图。"""
    from .sku_template_v3 import THEMES, render_sku_template
    from .sku_layout_v4 import render_custom_sku, validate_layout
    from .sku_rules_v7 import validate_sku_fields
    if custom_layout is not None:
        if template_style is not None:
            raise ValueError("自定义 V4 布局不能同时使用 V3 固定预设")
        validate_layout(custom_layout)
    elif clean_template is not None:
        raise ValueError("只有 V4 自定义布局才能使用净背景")
    if template_style is not None and template_style not in THEMES:
        raise ValueError("无效的 SKU 风格预设")
    rows = read_sku_rows(excel_data)
    if not pictures or len(pictures) > MAX_IMAGES:
        raise ValueError(f"请上传 1~{MAX_IMAGES} 张产品图")
    image_lookup: dict[str, UploadedPicture] = {}
    for pic in pictures:
        name = _image_basename(pic.name)
        key = name.casefold()
        if not name or key in image_lookup:
            raise ValueError(f"图片文件名重复或无效：{pic.name}")
        image_lookup[key] = pic
    result = SkuBatchResult()
    seen_sku: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="sku_xlsx_") as folder:
        work = Path(folder)
        for row in rows:
            data = row.data
            sku = data["SKU编码"].strip()
            source_name = data["图片文件名"].strip()
            status = {"excel_row": row.row_number, "sku": sku, "source_file": source_name,
                      "status": "failed", "output_file": "", "message": ""}
            try:
                if allowed_row_numbers is not None and row.row_number not in allowed_row_numbers:
                    raise ValueError("预检查未通过，本行已跳过；先修正输入再生成")
                if sku.casefold() in seen_sku:
                    raise ValueError("SKU编码重复，请检查 Excel")
                seen_sku.add(sku.casefold())
                validate_sku_fields(data, uses_dimension_layer=template_style is not None or custom_layout is not None)
                pic = image_lookup.get(source_name.casefold())
                if pic is None:
                    raise ValueError("找不到对应产品图片，请核对图片文件名和扩展名")
                validate_upload(pic)
                if template_style is None and custom_layout is None:
                    accent = _valid_hex(data["色块颜色"] or "#0D7FF4", "色块颜色")
                    color = _valid_hex(data["标题字色"] or ("#000000" if accent.upper() in {"#F5C518", "#FFFF00"} else "#FFFFFF"), "标题字色")
                else:
                    # V3 固定主题不应用 Excel 的自定义颜色字段。
                    accent = color = ""
                stem = clean_stem(sku, row.row_number)
                suffix = Path(pic.name).suffix.lower()
                source = work / f"input_{row.row_number:04d}{suffix}"
                source.write_bytes(pic.data)
                output_name = f"SKU_{stem}.jpg"
                target = work / output_name
                specs = _specs(data)
                if template_style is None and custom_layout is None:
                    meta = build_job({
                        "mode": "sku", "source": str(source), "output": str(target),
                        "title": data["商品名称"].strip(), "specs": specs,
                        "accent": accent, "background": "#F4F7FA", "title_color": color,
                    }, work)
                    image_data = target.read_bytes()
                else:
                    drawing_name = data.get("尺寸图文件名", "").strip()
                    dimension_picture = None
                    if drawing_name:
                        if drawing_name != _image_basename(drawing_name) or drawing_name in {".", ".."}:
                            raise ValueError("尺寸图文件名不能包含路径")
                        dimension_picture = image_lookup.get(drawing_name.casefold())
                        if dimension_picture is None:
                            raise ValueError("找不到此 SKU 对应的原尺寸图，不以其他图片替代")
                    if custom_layout is not None:
                        image_data, meta = render_custom_sku(
                            pic, drawing=dimension_picture, title=data["商品名称"].strip(),
                            specs=specs, layout=custom_layout, clean_template=clean_template,
                        )
                    else:
                        image_data, meta = render_sku_template(
                            pic, drawing=dimension_picture, title=data["商品名称"].strip(),
                            specs=specs, style=template_style,
                        )
                audit = audit_export(output_name, image_data, "sku")
                if not audit["auto_pass"]:
                    raise ValueError("尺寸或格式自动质检未通过")
                meta.update({"file": output_name, "source_name": pic.name, "excel_row": row.row_number,
                             "sku": sku, "specs": specs})
                result.images.append((output_name, image_data, meta))
                status.update({"status": "success", "output_file": output_name, "message": "自动检查通过；待人工核对参数与结构"})
            except (OSError, RuntimeError, ValueError) as exc:
                status["message"] = str(exc)
            result.rows.append(status)
    return result
