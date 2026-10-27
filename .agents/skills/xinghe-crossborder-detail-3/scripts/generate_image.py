#!/usr/bin/env python3
"""Unified image generation script with route split:
reference images -> /images/edits
text-only prompts -> /images/generations
"""

from __future__ import annotations

import argparse
import base64
import binascii
import http.client
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ENV_GENERATIONS_URL = "OPENAI_IMAGE_GENERATIONS_URL"
ENV_EDITS_URL = "OPENAI_IMAGE_EDITS_URL"
ENV_MODEL = "OPENAI_IMAGE_MODEL"
ENV_API_KEY = "OPENAI_IMAGE_API_KEY"
ENV_ALIASES = {
    ENV_GENERATIONS_URL: ("IMG_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE", "BASE_URL"),
    ENV_EDITS_URL: ("IMG_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE", "BASE_URL"),
    ENV_MODEL: ("IMG_MODEL", "IMAGE_MODEL", "OPENAI_MODEL"),
    ENV_API_KEY: ("IMG_API_KEY", "OPENAI_API_KEY", "API_KEY"),
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
VALID_RESOLUTIONS = ("1k", "2k", "4k")

PIXEL_TO_RATIO: dict[str, str] = {
    "1024x1024": "1:1", "2048x2048": "1:1",
    "1536x1024": "3:2", "2048x1360": "3:2",
    "1024x1536": "2:3", "1360x2048": "2:3",
    "1024x768": "4:3", "2048x1536": "4:3",
    "768x1024": "3:4", "1536x2048": "3:4",
    "1280x1024": "5:4", "2560x2048": "5:4",
    "1024x1280": "4:5", "2048x2560": "4:5",
    "1536x864": "16:9", "2048x1152": "16:9", "3840x2160": "16:9",
    "864x1536": "9:16", "1152x2048": "9:16", "2160x3840": "9:16",
    "2048x1024": "2:1", "2688x1344": "2:1", "3840x1920": "2:1",
    "1024x2048": "1:2", "1344x2688": "1:2", "1920x3840": "1:2",
    "2016x864": "21:9", "2688x1152": "21:9", "3840x1648": "21:9",
    "864x2016": "9:21", "1152x2688": "9:21", "1648x3840": "9:21",
}


def fail(message: str, exit_code: int = 1) -> None:
    print(f"错误：{message}", file=sys.stderr)
    raise SystemExit(exit_code)


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt:
        prompt = args.prompt.strip()
    else:
        try:
            prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            fail(f"无法读取 prompt 文件：{exc}")
    if not prompt:
        fail("prompt 不能为空。")
    return prompt


def strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def find_default_env_file() -> Path | None:
    for directory in (Path.cwd(), *Path.cwd().parents):
        env_file = directory / ".env"
        if env_file.is_file():
            return env_file
    return None


def load_env_file(env_file: Path | None) -> None:
    if env_file is None:
        return
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        fail(f"无法读取 .env 文件：{exc}")
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            fail(".env 格式不正确，应为 KEY=value")
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = strip_env_value(value)


def require_config(name: str) -> str:
    candidates = (name, *ENV_ALIASES.get(name, ()))
    for candidate in candidates:
        value = os.environ.get(candidate, "").strip()
        if value:
            return value
    fail(f"缺少配置 {name}，兼容变量：{', '.join(candidates)}")


def require_endpoint(name: str, suffix: str) -> str:
    candidates = (name, *ENV_ALIASES.get(name, ()))
    for candidate in candidates:
        value = os.environ.get(candidate, "").strip()
        if value:
            normalized = value.rstrip("/")
            return normalized if normalized.endswith(suffix) else f"{normalized}{suffix}"
    fail(f"缺少配置 {name}，兼容变量：{', '.join(candidates)}")


def detect_mode(base_url: str, explicit_mode: str | None) -> str:
    if explicit_mode in ("sync", "async"):
        return explicit_mode
    if "xinghe.xin" in base_url.lower():
        return "sync"
    if "apimart" in base_url.lower():
        return "async"
    return "sync"


def size_to_ratio(size: str) -> str:
    if ":" in size:
        return size
    lower = size.lower()
    if lower in PIXEL_TO_RATIO:
        return PIXEL_TO_RATIO[lower]
    if "x" in lower:
        width_text, height_text = lower.split("x", 1)
        if width_text.isdigit() and height_text.isdigit():
            width = int(width_text)
            height = int(height_text)
            if width > 0 and height > 0:
                divisor = math.gcd(width, height)
                return f"{width // divisor}:{height // divisor}"
    fail(f"无法将像素尺寸 '{size}' 转换为比例。")


def encode_image_data_uri(image_path: str) -> str:
    path = Path(image_path)
    if not path.is_file():
        fail(f"参考图片不存在：{image_path}")
    suffix = path.suffix.lower().lstrip(".")
    mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
    mime = mime_map.get(suffix)
    if not mime:
        fail(f"不支持的图片格式：{suffix}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        fail(f"无法读取参考图片：{exc}")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def normalize_images(image_arg: str | list[str] | None) -> list[str]:
    if not image_arg:
        return []
    if isinstance(image_arg, list):
        return [item for item in image_arg if item]
    return [image_arg]


def http_post(url: str, api_key: str, payload: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        fail(f"接口返回 HTTP {exc.code}：{detail}")
    except urllib.error.URLError as exc:
        fail(f"无法连接接口：{exc.reason}")
    except (http.client.RemoteDisconnected, TimeoutError):
        fail("接口连接失败或超时，请稍后重试。")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        fail(f"接口返回的不是有效 JSON：{raw[:500]}")
    if not isinstance(parsed, dict):
        fail("接口返回格式不正确：顶层结果不是对象。")
    return parsed


def http_get(url: str, api_key: str, timeout: int = 30) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {api_key}", "User-Agent": UA}, method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        fail(f"查询接口返回 HTTP {exc.code}：{detail}")
    except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError):
        fail("查询接口连接失败或超时。")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        fail(f"查询接口返回的不是有效 JSON：{raw[:500]}")


def save_image(item: dict[str, Any], output_dir: Path, index: int) -> Path:
    if item.get("b64_json") or item.get("base64") or item.get("image_base64"):
        encoded = item.get("b64_json") or item.get("base64") or item.get("image_base64")
        bytes_data = base64.b64decode(encoded)
        ext = "png"
    elif item.get("url"):
        image_url = item["url"]
        suffix = Path(urllib.parse.urlparse(image_url).path).suffix.lower().lstrip(".") or "png"
        ext = "jpg" if suffix == "jpeg" else suffix
        req = urllib.request.Request(image_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as resp:
            bytes_data = resp.read()
    else:
        fail(f"图片结果缺少 url 或 b64_json：{item}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"image-{time.strftime('%Y%m%d-%H%M%S')}-{index:02d}.{ext}"
    output_path.write_bytes(bytes_data)
    return output_path


def save_sync_images(result: dict[str, Any], output_dir: Path, fmt: str) -> list[Path]:
    data = result.get("data")
    if not isinstance(data, list) or not data:
        fail("接口返回中没有 data 图片数组。")
    paths: list[Path] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            fail("接口返回格式不正确：data 中存在非对象项。")
        if item.get("b64_json"):
            encoded = item["b64_json"]
            try:
                image_bytes = base64.b64decode(encoded)
            except (binascii.Error, ValueError) as exc:
                fail(f"无法解码 b64_json：{exc}")
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / f"image-{time.strftime('%Y%m%d-%H%M%S')}-{index:02d}.{fmt}"
            path.write_bytes(image_bytes)
            paths.append(path)
        elif item.get("url"):
            req = urllib.request.Request(item["url"], headers={"User-Agent": UA})
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / f"image-{time.strftime('%Y%m%d-%H%M%S')}-{index:02d}.{fmt}"
            with urllib.request.urlopen(req, timeout=120) as resp:
                path.write_bytes(resp.read())
            paths.append(path)
        else:
            fail("图片结果缺少 url 或 b64_json。")
    return paths


def build_sync_payload(args: argparse.Namespace, prompt: str, model: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model, "prompt": prompt, "n": args.n, "size": args.size}
    if args.quality:
        payload["quality"] = args.quality
    images = normalize_images(args.image)
    if images:
        payload["image_urls"] = [encode_image_data_uri(image_path) for image_path in images]
    return payload


def build_async_payload(args: argparse.Namespace, prompt: str, model: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size_to_ratio(args.size),
        "resolution": args.resolution,
    }
    images = normalize_images(args.image)
    if images:
        payload["image_urls"] = [encode_image_data_uri(image_path) for image_path in images]
    return payload


def run_sync(endpoint: str, api_key: str, payload: dict[str, Any], output_dir: Path, fmt: str) -> list[Path]:
    print(f"[sync] 提交请求到 {endpoint}...", file=sys.stderr)
    result = http_post(endpoint, api_key, payload, timeout=120)
    return save_sync_images(result, output_dir, fmt)


def run_async(endpoint: str, api_key: str, payload: dict[str, Any], output_dir: Path, fmt: str,
              poll_interval: int, timeout: int) -> list[Path]:
    print(f"[async] 提交异步任务到 {endpoint}...", file=sys.stderr)
    result = http_post(endpoint, api_key, payload, timeout=30)
    data = result.get("data")
    if not isinstance(data, list) or not data:
        fail("提交响应缺少 data 数组。")
    task_id = data[0].get("task_id")
    if not task_id:
        fail("提交响应缺少 task_id。")
    time.sleep(15)
    start = time.time()
    while True:
        if time.time() - start > timeout:
            fail(f"任务 {task_id} 超时。")
        result = http_get(f"{endpoint.rsplit('/images/', 1)[0]}/tasks/{task_id}", api_key)
        task_data = result.get("data", {})
        status = task_data.get("status", "")
        if status == "completed":
            break
        if status == "failed":
            fail(f"任务 {task_id} 失败。")
        time.sleep(poll_interval)
    images = task_data.get("result", {}).get("images", [])
    if not isinstance(images, list) or not images:
        fail("任务结果缺少 images。")
    paths: list[Path] = []
    for index, img_item in enumerate(images, start=1):
        url_list = img_item.get("url")
        if not isinstance(url_list, list) or not url_list:
            fail("任务结果缺少 url 列表。")
        req = urllib.request.Request(url_list[0], headers={"User-Agent": UA})
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"image-{time.strftime('%Y%m%d-%H%M%S')}-{index:02d}.{fmt}"
        with urllib.request.urlopen(req, timeout=120) as resp:
            path.write_bytes(resp.read())
        paths.append(path)
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unified ecommerce image generation script.")
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt", help="Direct prompt.")
    prompt_group.add_argument("--prompt-file", help="Prompt file path.")
    parser.add_argument("--output-dir", default="generated-images")
    parser.add_argument("--env-file")
    parser.add_argument("--mode", choices=("sync", "async"))
    parser.add_argument("--size", default="1:1")
    parser.add_argument("--resolution", default="2k", choices=VALID_RESOLUTIONS)
    parser.add_argument("--quality")
    parser.add_argument("--n", type=int, default=1)
    parser.add_argument("--image", action="append", help="Reference image path; repeatable.")
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--format", choices=("png", "jpeg", "webp"), default="png")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    env_file = Path(args.env_file) if args.env_file else find_default_env_file()
    load_env_file(env_file)
    prompt = read_prompt(args)
    generations_url = require_endpoint(ENV_GENERATIONS_URL, "/images/generations")
    edits_url = require_endpoint(ENV_EDITS_URL, "/images/edits")
    model = require_config(ENV_MODEL)
    api_key = require_config(ENV_API_KEY)
    endpoint = edits_url if normalize_images(args.image) else generations_url

    mode = detect_mode(endpoint, args.mode)
    print(f"API 模式: {mode} | endpoint={endpoint} | model={model}", file=sys.stderr)

    if mode == "async":
        payload = build_async_payload(args, prompt, model)
        paths = run_async(endpoint, api_key, payload, Path(args.output_dir), args.format, args.poll_interval, args.timeout)
    else:
        payload = build_sync_payload(args, prompt, model)
        paths = run_sync(endpoint, api_key, payload, Path(args.output_dir), args.format)

    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
