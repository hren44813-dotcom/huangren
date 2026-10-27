"""对导出图片做可验证的客观检查；不把结构/功效人工验收冒充为自动通过。"""
from __future__ import annotations

import io
from pathlib import PurePosixPath
from typing import Any

from PIL import Image, UnidentifiedImageError

from .generator import MAX_SEARCH_BYTES, SIZES

MANUAL_REVIEW = (
    "对照实物原图核对产品轮廓、孔位、锁舌/铰链和配件是否完整、未变形",
    "核对型号、材质、尺寸、应用场景与卖点是否具有真实依据",
    "检查文字是否清晰、无遮挡，排版是否符合目标平台最新要求",
)


def audit_export(name: str, data: bytes, mode: str) -> dict[str, Any]:
    """只验证格式、像素和白底/大小等可机器判定项目。"""
    checks: list[dict[str, Any]] = []

    def check(item: str, passed: bool, detail: str) -> None:
        checks.append({"item": item, "passed": bool(passed), "detail": detail})

    if mode not in SIZES:
        raise ValueError(f"未知图片模式：{mode}")
    suffix = PurePosixPath(name).suffix.lower()
    try:
        with Image.open(io.BytesIO(data)) as image:
            actual_size = image.size
            fmt = image.format
            image.load()
            corners = [(0, 0), (image.width - 1, 0),
                       (0, image.height - 1), (image.width - 1, image.height - 1),
                       (image.width // 2, 0), (0, image.height // 2),
                       (image.width - 1, image.height // 2), (image.width // 2, image.height - 1)]
            if mode == "search_white":
                rgb = image.convert("RGB")
                white_border = all(all(ch >= 251 for ch in rgb.getpixel(c)) for c in corners)
            else:
                white_border = None
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        check("文件可解码", False, "不是可读取的图像或数据损坏")
        return {"file": name, "mode": mode, "auto_pass": False, "checks": checks,
                "manual_review": list(MANUAL_REVIEW), "manual_status": "pending"}
    check("文件可解码", True, f"图像格式 {fmt}")
    check("尺寸", actual_size == SIZES[mode], f"实测 {actual_size[0]}×{actual_size[1]}，模板 {SIZES[mode][0]}×{SIZES[mode][1]}")
    check("扩展名/格式", (fmt == "JPEG" if suffix in {".jpg", ".jpeg"} else fmt == "PNG" if suffix == ".png" else False), f"文件名 {suffix}，内容格式 {fmt}")
    if mode == "search_white":
        check("白底边缘抽样", bool(white_border), "检查画布角落及边缘抽样点；不证明产品周围已完整抠图")
        check("搜推 JPG 大小", len(data) < MAX_SEARCH_BYTES, f"实测 {len(data):,} 字节，上限小于 {MAX_SEARCH_BYTES:,} 字节")
        check("搜推格式", fmt == "JPEG", "本项目白底搜推模板要求 JPG")
    return {"file": name, "mode": mode, "auto_pass": all(c["passed"] for c in checks),
            "checks": checks, "manual_review": list(MANUAL_REVIEW), "manual_status": "pending"}
