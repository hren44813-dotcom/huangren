"""标识 UI 生成时的输入快照，防止误下载上一件商品的图片。"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .workflow import UploadedPicture


def input_fingerprint(pictures: list[UploadedPicture], parameters: dict[str, Any],
                      logo: UploadedPicture | None = None) -> str:
    """图片内容、名字、表单参数任意变化都生成新指纹；不保存原图或密钥。"""
    digest = hashlib.sha256()
    normalized = json.dumps(parameters, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest.update(normalized.encode("utf-8"))
    for picture in [*pictures, *([logo] if logo is not None else [])]:
        name_bytes = picture.name.encode("utf-8", errors="replace")
        digest.update(len(name_bytes).to_bytes(8, "big"))
        digest.update(name_bytes)
        digest.update(len(picture.data).to_bytes(8, "big"))
        digest.update(picture.data)
    return digest.hexdigest()
