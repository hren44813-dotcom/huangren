"""星河技能 CLI 的可选调用桥接。只有用户明确点击生成才向第三方发送图片。"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

from .workflow import UploadedPicture, validate_upload

ROOT = Path(__file__).resolve().parents[2]
XINGHE_SCRIPT = ROOT / ".agents/skills/xinghe-crossborder-detail-3/scripts/generate_image.py"
BASE_URL = "https://xinghe.xin/v1"  # 已安装技能给定的第三方服务，不从用户输入读取主机地址。


def generate_xinghe(
    image: UploadedPicture,
    *,
    api_key: str,
    model: str,
    prompt: str,
    ratio: str = "3:4",
    resolution: str = "2k",
    quantity: int = 1,
    consent: bool = False,
) -> bytes:
    """返回 ZIP 字节；不会保存密钥。真实调用可能产生费用并发送商品图片。"""
    if not consent:
        raise ValueError("调用第三方接口前必须确认上传与费用提示")
    if not api_key.strip():
        raise ValueError("请填写第三方 API 密钥")
    if not model.strip() or len(model) > 100:
        raise ValueError("模型名称不能为空，且需少于 100 字")
    if not prompt.strip() or len(prompt) > 8000:
        raise ValueError("请填写 1~8000 字的提示词")
    if ratio not in {"1:1", "3:4", "4:3", "16:9", "9:16"}:
        raise ValueError("不支持的生图比例")
    if resolution not in {"1k", "2k", "4k"} or not 1 <= quantity <= 4:
        raise ValueError("无效分辨率或生成数量")
    if not XINGHE_SCRIPT.is_file():
        raise RuntimeError("仓库内未找到星河技能的生图脚本")
    suffix = validate_upload(image)
    with tempfile.TemporaryDirectory(prefix="xinghe_ui_") as temp:
        base = Path(temp)
        image_path = base / f"reference{suffix}"
        image_path.write_bytes(image.data)
        output = base / "generated"
        env = os.environ.copy()
        # 覆盖可能来自 .env 的旧设置；密钥仅存在子进程环境变量中。
        env.update({
            "OPENAI_IMAGE_API_KEY": api_key.strip(),
            "OPENAI_IMAGE_GENERATIONS_URL": BASE_URL,
            "OPENAI_IMAGE_EDITS_URL": BASE_URL,
            "OPENAI_IMAGE_MODEL": model.strip(),
        })
        command = [sys.executable, str(XINGHE_SCRIPT), "--prompt", prompt.strip(),
                   "--image", str(image_path), "--output-dir", str(output),
                   "--size", ratio, "--resolution", resolution,
                   "--n", str(quantity), "--format", "png", "--mode", "sync"]
        try:
            process = subprocess.run(command, cwd=base, env=env, capture_output=True,
                                     text=True, timeout=240, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("第三方接口响应超时，可能仍产生接口费用；请先到服务商后台核实") from exc
        if process.returncode != 0:
            details = (process.stderr or process.stdout or "未知错误").replace(api_key.strip(), "***")
            raise RuntimeError(f"星河接口生成失败：{details[-600:]}")
        images = sorted(p for p in output.rglob("*") if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".webp"})
        if not images:
            raise RuntimeError("接口未返回可用图片，请查看服务商调用记录")
        if len(images) > quantity:
            raise RuntimeError("接口实际返回图片数超过请求数量，拒绝继续打包")
        validated = []
        for item in images:
            content = item.read_bytes()
            try:
                validate_upload(UploadedPicture(item.name, content))
            except ValueError as exc:
                raise RuntimeError(f"接口返回图片不合格：{item.name}：{exc}") from exc
            # 服务商偶尔返回 JPG 字节却使用 PNG 文件名；以实际文件内容确定后缀。
            with Image.open(io.BytesIO(content)) as verified:
                suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(verified.format)
            if suffix is None:
                raise RuntimeError("服务商图片格式不受支持")
            validated.append((suffix, content))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            for index, (suffix, content) in enumerate(validated, 1):
                zip_file.writestr(f"xinghe_{index:02d}{suffix}", content)
        return stream.getvalue()
