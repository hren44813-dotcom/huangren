"""AI 结果缓存与输入快照绑定，避免替换图片/提示词后展示旧结果。"""
from __future__ import annotations

from .session_guard import input_fingerprint
from .workflow import UploadedPicture


def ai_request_fingerprint(photo: UploadedPicture | None, *, platform: str,
                           prompt: str, ratio: str, resolution: str,
                           quantity: int, model: str) -> str:
    """不记录 API Key 或同意状态；只绑定真正决定图片内容的请求参数。"""
    return input_fingerprint([photo] if photo is not None else [], {
        "workflow": "xinghe_ai", "platform": platform, "prompt": prompt,
        "ratio": ratio, "resolution": resolution, "quantity": quantity,
        "model": model,
    })


def valid_cached_ai_result(saved: object, fingerprint: str) -> bytes | None:
    if not (isinstance(saved, tuple) and len(saved) == 2 and
            saved[0] == fingerprint and isinstance(saved[1], bytes)):
        return None
    return saved[1]
