"""V5 本地 SKU 布局模板库：只保存布局 JSON，不保存商品图/密钥。"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .sku_layout_v4 import layout_from_json, layout_json

MAX_TEMPLATES = 80
NAME_RE = re.compile(r"[\w\u4e00-\u9fff\- ]{1,48}", re.UNICODE)


def template_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError("模板名称必须是文本")
    value = name.strip()
    if not NAME_RE.fullmatch(value) or value in {".", ".."}:
        raise ValueError("模板名称为1-48个字，仅可包含中文、字母、数字、空格、下划线或短横线")
    return value


def _root(directory: str | Path) -> Path:
    path = Path(directory)
    if path.is_symlink():
        raise ValueError("模板库目录不能是符号链接")
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _target(directory: str | Path, name: str) -> Path:
    root = _root(directory)
    target = root / (template_name(name) + ".json")
    if target.is_symlink():
        raise ValueError("不允许读取或覆盖符号链接")
    return target


def list_templates(directory: str | Path) -> list[str]:
    root = _root(directory)
    return sorted((p.stem for p in root.glob("*.json") if p.is_file() and not p.is_symlink()), key=str.casefold)


def save_template(directory: str | Path, name: str, layout: dict, *, overwrite: bool = False) -> str:
    payload = layout_json(layout)  # 先验证，失败时不得改动现有模板
    target = _target(directory, name)
    names = list_templates(directory)
    if not overwrite and any(n.casefold() == target.stem.casefold() for n in names):
        raise ValueError("模板名称已存在，请换一个名字，或勾选覆盖")
    if len(names) >= MAX_TEMPLATES and not target.exists():
        raise ValueError(f"最多保存 {MAX_TEMPLATES} 套模板，请先清理旧模板")
    if target.exists() and not overwrite:
        raise ValueError("模板名称已存在")
    # temp 与 target 在同一目录，确保替换是原子操作，不会留下半写文件。
    fd, temp_name = tempfile.mkstemp(prefix=".layout-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        if target.is_symlink():
            raise ValueError("不能覆盖符号链接")
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return target.stem


def load_template(directory: str | Path, name: str) -> dict:
    path = _target(directory, name)
    if not path.is_file():
        raise ValueError("模板不存在")
    if path.stat().st_size > 32 * 1024:
        raise ValueError("模板文件超过32KB")
    return layout_from_json(path.read_bytes())


def delete_template(directory: str | Path, name: str) -> None:
    path = _target(directory, name)
    if not path.is_file():
        raise ValueError("模板不存在")
    path.unlink()
