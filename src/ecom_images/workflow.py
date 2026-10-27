"""离线电商图批处理：输入校验、模板变体、ZIP 导出；不做产品结构编辑。"""
from __future__ import annotations

import io
import json
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .generator import SIZES, build_job

MAX_UPLOAD = 12 * 1024 * 1024
MAX_INPUTS = 25
MAX_VARIANTS = 4
MAX_TOTAL_JOBS = 120
SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

# 所有变体仅改变排版背景与强调色，不会捏造卖点或产品视角。
STYLE_PRESETS = (
    ("#F4F7FA", "#0D7FF4"),
    ("#FFFFFF", "#175F9C"),
    ("#ECF2F4", "#087D83"),
    ("#F7F4ED", "#A9671C"),
)


@dataclass(frozen=True)
class UploadedPicture:
    name: str
    data: bytes


@dataclass
class BatchResult:
    images: list[tuple[str, bytes, dict[str, Any]]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def quality_audits(self) -> list[dict[str, Any]]:
        from .quality import audit_export
        return [audit_export(name, data, str(meta["mode"])) for name, data, meta in self.images]

    def zip_bytes(self) -> bytes:
        memory = io.BytesIO()
        manifest = {"success": [meta for _, _, meta in self.images], "errors": self.errors}
        audits = self.quality_audits()
        with zipfile.ZipFile(memory, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data, _ in self.images:
                archive.writestr(name, data)
            archive.writestr("report.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr("quality_report.json", json.dumps({
                "summary": {"auto_pass": sum(a["auto_pass"] for a in audits),
                            "auto_fail": sum(not a["auto_pass"] for a in audits),
                            "manual_review_pending": len(audits)},
                "audits": audits,
                "note": "自动通过仅表示文件可读、输出尺寸/格式等机器可测指标合格；产品一致性、文本真实性与平台审核须人工复核。",
            }, ensure_ascii=False, indent=2))
        return memory.getvalue()


def clean_stem(filename: str, index: int) -> str:
    """抹掉文件路径和控制字符，防止 ZIP 和临时目录路径穿越。"""
    normalized = str(filename).replace("\\", "/").split("/")[-1]
    stem = Path(normalized).stem[:60]
    stem = re.sub(r"[^\w\-]+", "_", stem, flags=re.UNICODE).strip("_.")
    return f"{index:02d}_{stem or 'image'}"


def validate_upload(picture: UploadedPicture) -> str:
    suffix = Path(str(picture.name).replace("\\", "/").split("/")[-1]).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("仅支持 PNG、JPG、JPEG、WEBP 图片")
    if not picture.data or len(picture.data) > MAX_UPLOAD:
        raise ValueError("单张文件应为非空且不超过 12 MB")
    try:
        with Image.open(io.BytesIO(picture.data)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("文件内容不是受支持的图像格式")
            if image.width < 100 or image.height < 100:
                raise ValueError("图片宽高至少 100px")
            if image.width * image.height > 40_000_000:
                raise ValueError("图片像素总数不得超过 4000 万")
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("图片文件无效或已损坏") from exc
    return suffix


def planned_count(number_of_inputs: int, modes: list[str], variants: int) -> int:
    if not modes or any(m not in SIZES for m in modes):
        raise ValueError("请至少选择一种有效的图片类型")
    if not (1 <= variants <= MAX_VARIANTS):
        raise ValueError("配色版本数只能是 1~4")
    if not 1 <= number_of_inputs <= MAX_INPUTS:
        raise ValueError(f"每批最多上传 {MAX_INPUTS} 张产品图")
    jobs = number_of_inputs * sum(1 if mode == "search_white" else variants for mode in modes)
    if jobs > MAX_TOTAL_JOBS:
        raise ValueError(f"单次最多生成 {MAX_TOTAL_JOBS} 张，请减少原图、类型或配色数")
    return jobs


def produce_images(
    pictures: list[UploadedPicture],
    modes: list[str],
    variants: int = 1,
    *,
    title: str = "",
    subtitle: str = "",
    brand: str = "",
    label: str = "",
    selling_points: list[str] | None = None,
    specs: list[dict[str, str]] | None = None,
    accent: str = "#0D7FF4",
    background: str = "#F4F7FA",
    logo: UploadedPicture | None = None,
) -> BatchResult:
    """制作图像并在内存返回结果；不上传服务器，不修改原图。各项失败独立记录。"""
    planned_count(len(pictures), modes, variants)
    selling_points = [p.strip() for p in (selling_points or []) if p.strip()]
    specs = [s for s in (specs or []) if s.get("value", "").strip()]
    if any(mode in {"sku", "main", "detail"} for mode in modes) and not title.strip():
        raise ValueError("主图、SKU 和详情页需要填写真实产品标题")
    if len(selling_points) > 3 or len(specs) > 4:
        raise ValueError("最多 3 条卖点、4 条规格")
    if logo is not None:
        validate_upload(logo)
    result = BatchResult()
    with tempfile.TemporaryDirectory(prefix="ecom_batch_") as temp:
        base = Path(temp)
        logo_path = None
        if logo:
            logo_path = base / f"brand{Path(logo.name).suffix.lower()}"
            logo_path.write_bytes(logo.data)
        for index, picture in enumerate(pictures, 1):
            name = clean_stem(picture.name, index)
            try:
                suffix = validate_upload(picture)
            except ValueError as exc:
                result.errors.append(f"{picture.name}: {exc}")
                continue
            source = base / f"{name}{suffix}"
            source.write_bytes(picture.data)
            for mode in modes:
                for version in range(1 if mode == "search_white" else variants):
                    style_bg, style_accent = STYLE_PRESETS[version]
                    # 用户自定义样式应用于首版，后续仅变化配色，不变化产品照片或孔位。
                    bg = background if version == 0 else style_bg
                    tone = accent if version == 0 else style_accent
                    output_name = f"{name}/{mode}_{version + 1:02d}.jpg"
                    target = base / "export" / output_name
                    job: dict[str, Any] = {
                        "mode": mode, "source": str(source), "output": str(target),
                        "title": title.strip(), "subtitle": subtitle.strip(),
                        "brand": brand.strip(), "label": label.strip(),
                        "selling_points": selling_points, "specs": specs,
                        "accent": tone, "background": bg,
                    }
                    if logo_path and mode in {"main", "detail"}:
                        job["logo"] = str(logo_path)
                    try:
                        meta = build_job(job, base)
                        meta = {**meta, "file": output_name, "source_name": picture.name,
                                "version": version + 1}
                        result.images.append((output_name, target.read_bytes(), meta))
                    except (OSError, RuntimeError, ValueError) as exc:
                        target.unlink(missing_ok=True)
                        result.errors.append(f"{picture.name} / {mode} 第{version + 1}版：{exc}")
    return result
