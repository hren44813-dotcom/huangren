"""可重复、非生成式的电商图片排版。产品像素只做等比例缩放/透明叠合。"""
from __future__ import annotations

import copy
import glob
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps

SIZES = {
    "search_white": (1440, 1440),
    "main": (1440, 1440),
    "portrait": (1440, 1920),
    "sku": (1440, 1440),
    "detail": (800, 1600),
}
MAX_SEARCH_BYTES = 3_000_000
FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _color(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise ValueError("颜色必须使用 #RRGGBB，例如 #0D7FF4")
    try:
        return ImageColor.getrgb(value)
    except ValueError as exc:
        raise ValueError(f"无效颜色：{value}") from exc


def _font(size: int, preferred: str | None = None) -> ImageFont.FreeTypeFont:
    for name in ([preferred] if preferred else []) + FONTS:
        if name and Path(name).is_file():
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
    raise RuntimeError("找不到可用字体。请安装 Noto Sans CJK，或在配置中设置 font_path。")


def _draw_fit(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], width: int,
              max_size: int, min_size: int, fill: str, font_path: str | None) -> int:
    if not isinstance(text, str):
        raise ValueError("标题、卖点和参数值必须为字符串")
    for size in range(max_size, min_size - 1, -2):
        font = _font(size, font_path)
        if draw.textbbox((0, 0), text, font=font)[2] <= width:
            draw.text(xy, text, font=font, fill=fill)
            return size
    raise ValueError(f"文案过长，可能遮挡产品，请缩短：{text[:30]}")


def _source(path: Path, *, min_side: int = 100) -> tuple[Image.Image, bool]:
    if not path.is_file():
        raise FileNotFoundError(f"找不到产品图：{path}。请将实物图片放入对应目录。")
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
    if image.width < min_side or image.height < min_side:
        raise ValueError(f"产品图分辨率过小：{path}；请提供至少 100×100 的图像")
    alpha = image.getchannel("A")
    has_transparency = alpha.getextrema()[0] < 255
    if has_transparency:
        bounds = alpha.getbbox()
        if not bounds:
            raise ValueError(f"产品图完全透明：{path}")
        image = image.crop(bounds)  # 仅裁透明画布，绝不裁掉产品像素
    return image, has_transparency


def _white_border(image: Image.Image, tolerance: int = 4) -> bool:
    """不把带环境背景的产品照片伪装成合规纯白搜推图。"""
    rgb = image.convert("RGB")
    w, h = rgb.size
    samples = []
    for x in (0, w // 2, w - 1):
        samples += [(x, 0), (x, h - 1)]
    for y in (h // 2,):
        samples += [(0, y), (w - 1, y)]
    return all(all(channel >= 255 - tolerance for channel in rgb.getpixel(p)) for p in samples)


def _contain(canvas: Image.Image, image: Image.Image, rectangle: tuple[int, int, int, int]) -> None:
    x, y, width, height = rectangle
    scale = min(width / image.width, height / image.height)
    new_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    resized = image.resize(new_size, Image.Resampling.LANCZOS)
    at = (x + (width - new_size[0]) // 2, y + (height - new_size[1]) // 2)
    canvas.paste(resized, at, resized.getchannel("A"))


def _brand(draw: ImageDraw.ImageDraw, canvas: Image.Image, job: dict[str, Any],
           base: Path, at: tuple[int, int], max_width: int) -> None:
    logo = job.get("logo")
    if logo:
        logo_path = _resolve(base, str(logo))
        image, _ = _source(logo_path, min_side=1)
        _contain(canvas, image, (*at, min(max_width, 360), 86))
    elif job.get("brand"):
        _draw_fit(draw, str(job["brand"]), at, max_width, 52, 26,
                  "#252C35", job.get("font_path"))


def _resolve(base: Path, name: str) -> Path:
    path = Path(name).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def _render(job: dict[str, Any], image: Image.Image, base: Path) -> Image.Image:
    mode = job["mode"]
    if mode not in SIZES:
        raise ValueError(f"未知图片模式：{mode}，可选：{', '.join(SIZES)}")
    accent = _color(job.get("accent", "#0D7FF4"))
    background = _color(job.get("background", "#F4F7FA"))
    font_path = job.get("font_path")
    if font_path:
        font_path = str(_resolve(base, str(font_path)))
    job = {**job, "font_path": font_path}

    if mode == "search_white":
        canvas = Image.new("RGB", SIZES[mode], "white")
        _contain(canvas, image, (90, 90, 1260, 1260))
        return canvas  # 搜推纯白图不允许任何营销字、Logo、框或阴影

    if mode == "portrait":
        canvas = Image.new("RGB", SIZES[mode], background)
        draw = ImageDraw.Draw(canvas)
        label = job.get("label")
        if label:
            _draw_fit(draw, str(label), (85, 92), 650, 44, 24,
                      "#222B36", font_path)
        _contain(canvas, image, (90, 225, 1260, 1510))
        return canvas

    if mode == "main":
        canvas = Image.new("RGB", SIZES[mode], background)
        draw = ImageDraw.Draw(canvas)
        _brand(draw, canvas, job, base, (80, 82), 550)
        title = str(job.get("title", ""))
        if title:
            _draw_fit(draw, title, (80, 325), 550, 78, 36, "#172532", font_path)
        subtitle = job.get("subtitle")
        if subtitle:
            _draw_fit(draw, str(subtitle), (83, 455), 510, 44, 28, "#526171", font_path)
        points = job.get("selling_points", [])
        if not isinstance(points, list) or len(points) > 3:
            raise ValueError("selling_points 必须是最多 3 条文案的列表")
        for index, point in enumerate(points):
            y = 605 + index * 110
            draw.rounded_rectangle((81, y, 565, y + 78), radius=12,
                                   fill=(238, 244, 251))
            draw.rounded_rectangle((81, y, 89, y + 78), radius=3, fill=accent)
            _draw_fit(draw, str(point), (110, y + 13), 435, 42, 26,
                      "#1A3146", font_path)
        _contain(canvas, image, (616, 245, 754, 1050))
        return canvas

    if mode == "sku":
        canvas = Image.new("RGB", SIZES[mode], background)
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle((60, 54, 1380, 168), radius=17, fill=accent)
        title = str(job.get("title", ""))
        if not title:
            raise ValueError("SKU 模式必须提供 title")
        title_fill = job.get("title_color", "#FFFFFF")
        _draw_fit(draw, title, (100, 76), 1210, 59, 28, title_fill, font_path)
        _contain(canvas, image, (90, 205, 1260, 850))
        specs = job.get("specs", [])
        if not isinstance(specs, list) or len(specs) > 4:
            raise ValueError("specs 必须是最多 4 项的列表")
        if specs:
            draw.rounded_rectangle((65, 1105, 1375, 1390), radius=20, fill="white")
            for index, spec in enumerate(specs):
                if not isinstance(spec, dict) or "label" not in spec or "value" not in spec:
                    raise ValueError("每条规格必须包含 label 和 value")
                x = 110 + (index % 2) * 645
                y = 1154 + (index // 2) * 115
                _draw_fit(draw, str(spec["label"]), (x, y), 210, 39, 24,
                          "#647384", font_path)
                _draw_fit(draw, str(spec["value"]), (x + 215, y), 390, 40, 24,
                          "#1E2934", font_path)
        return canvas

    # detail: 800px 宽，采用单页基础详情模块；可按需要后续拼接多页
    canvas = Image.new("RGB", SIZES[mode], background)
    draw = ImageDraw.Draw(canvas)
    _brand(draw, canvas, job, base, (54, 58), 450)
    title = str(job.get("title", ""))
    if title:
        _draw_fit(draw, title, (55, 200), 680, 60, 28, "#172532", font_path)
    _contain(canvas, image, (50, 325, 700, 850))
    points = job.get("selling_points", [])
    if not isinstance(points, list) or len(points) > 3:
        raise ValueError("detail 的 selling_points 最多 3 条")
    for index, point in enumerate(points):
        y = 1220 + index * 105
        draw.rounded_rectangle((55, y, 64, y + 65), radius=3, fill=accent)
        _draw_fit(draw, str(point), (88, y + 6), 625, 43, 24,
                  "#243240", font_path)
    return canvas


def _save(canvas: Image.Image, destination: Path, mode: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    ext = destination.suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        raise ValueError(f"输出文件需要 .jpg 或 .png 后缀：{destination}")
    if mode == "search_white" and ext not in (".jpg", ".jpeg"):
        raise ValueError("search_white 必须输出 JPG 才符合此模板规格")
    if ext == ".png":
        canvas.save(destination, format="PNG", optimize=True)
    else:
        for quality in (94, 90, 86, 82, 78, 74, 70, 65, 60):
            canvas.convert("RGB").save(destination, format="JPEG", quality=quality,
                                        optimize=True, subsampling=0)
            if mode != "search_white" or destination.stat().st_size < MAX_SEARCH_BYTES:
                break
        if mode == "search_white" and destination.stat().st_size >= MAX_SEARCH_BYTES:
            destination.unlink(missing_ok=True)
            raise ValueError("搜推白底 JPG 大于 3MB；请先优化原图，脚本不会偷偷缩小尺寸")


def _verify(destination: Path, mode: str) -> dict[str, Any]:
    with Image.open(destination) as saved:
        size = saved.size
        if size != SIZES[mode]:
            raise RuntimeError(f"输出尺寸异常：{destination} {size}")
        if mode == "search_white":
            if saved.format != "JPEG" or not _white_border(saved):
                raise RuntimeError(f"搜推图不是 JPG 纯白背景：{destination}")
    bytes_size = destination.stat().st_size
    if mode == "search_white" and bytes_size >= MAX_SEARCH_BYTES:
        raise RuntimeError("搜推图超出 3MB")
    return {"file": str(destination), "mode": mode,
            "width": size[0], "height": size[1], "bytes": bytes_size}


def build_job(job: dict[str, Any], base: Path) -> dict[str, Any]:
    if not isinstance(job, dict):
        raise ValueError("每个 job 必须是 JSON 对象")
    mode = job.get("mode")
    if mode not in SIZES:
        raise ValueError(f"mode 必须为 {', '.join(SIZES)}")
    if not job.get("source") or not job.get("output"):
        raise ValueError("每个 job 都必须包含 source 和 output")
    source = _resolve(base, str(job["source"]))
    destination = _resolve(base, str(job["output"]))
    if source == destination:
        raise ValueError("输出路径不能覆盖产品原图")
    image, has_transparency = _source(source)
    if mode == "search_white" and not has_transparency and not _white_border(image):
        raise ValueError(f"{source} 不是透明 PNG 或干净白底图；请先人工检查/抠图")
    canvas = _render(job, image, base)
    _save(canvas, destination, mode)
    return _verify(destination, mode)


def expand_jobs(config: dict[str, Any], base: Path) -> list[dict[str, Any]]:
    if not isinstance(config.get("jobs"), list) or not config["jobs"]:
        raise ValueError("配置必须包含非空 jobs 列表")
    expanded: list[dict[str, Any]] = []
    for job in config["jobs"]:
        if not isinstance(job, dict):
            raise ValueError("jobs 列表中每一项必须是对象")
        if "source_glob" not in job:
            expanded.append(copy.deepcopy(job))
            continue
        pattern = str(job["source_glob"])
        matches = sorted(glob.glob(str(_resolve(base, pattern)), recursive=True))
        matches = [s for s in matches if Path(s).is_file() and Path(s).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
        if not matches:
            raise ValueError(f"批量输入没有找到图片：{pattern}")
        if "output_pattern" not in job:
            raise ValueError("批量任务必须填写 output_pattern，例如 output/sku/{stem}_sku.jpg")
        for source in matches:
            spec = {k: copy.deepcopy(v) for k, v in job.items() if k not in ("source_glob", "output_pattern")}
            stem = Path(source).stem
            spec["source"] = source
            spec["output"] = str(job["output_pattern"]).replace("{stem}", stem)
            for field in ("title", "label"):
                if isinstance(spec.get(field), str):
                    spec[field] = spec[field].replace("{stem}", stem)
            expanded.append(spec)
    outputs = [str(_resolve(base, str(j["output"]))) for j in expanded if "output" in j]
    if len(outputs) != len(set(outputs)):
        raise ValueError("多个任务将写入同一输出路径，请更换 output 或 output_pattern")
    return expanded


def run_config(config_path: Path, base: Path | None = None) -> list[dict[str, Any]]:
    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    base = (base or Path.cwd()).resolve()
    return [build_job(job, base) for job in expand_jobs(config, base)]
