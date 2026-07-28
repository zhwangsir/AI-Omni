"""omni_openclaw 统一错误码。"""

from __future__ import annotations

from typing import Any


def error_response(code: str, message: str, **extra: Any) -> dict[str, Any]:
    """构造标准错误响应字典。"""
    return {"ok": False, "error": {"code": code, "message": message, **extra}}


def success_response(**kwargs: Any) -> dict[str, Any]:
    """构造标准成功响应字典。"""
    return {"ok": True, **kwargs}
