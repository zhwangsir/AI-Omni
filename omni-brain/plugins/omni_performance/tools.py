"""omni_performance 工具 handler 实现 + JSON Schema。

3 个工具：
- ``system_get_cpu_usage()``：CPU 使用率
- ``system_get_memory_usage()``：内存使用
- ``system_get_disk_usage(path="/")``：磁盘使用

handler 返回 JSON 字符串：``{"ok": true, ...}`` / ``{"ok": false, "error": {...}}``。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _ok(data: dict[str, Any]) -> str:
    """成功响应。"""
    return json.dumps({"ok": True, **data}, ensure_ascii=False)


def _err(code: str, message: str) -> str:
    """失败响应。"""
    return json.dumps(
        {"ok": False, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# JSON Schema
# ---------------------------------------------------------------------------
SYSTEM_GET_CPU_USAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

SYSTEM_GET_MEMORY_USAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

SYSTEM_GET_DISK_USAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "磁盘挂载路径，默认 /。",
            "default": "/",
        }
    },
    "required": [],
}


# ---------------------------------------------------------------------------
# 工具 handler 工厂
# ---------------------------------------------------------------------------
def make_handlers(
    get_backend: Callable[[], Any],
) -> dict[str, Callable[[dict[str, Any]], str]]:
    """构造 3 个 system_* 性能监控 handler。

    :param get_backend: 返回当前后端（可能为 None）的回调
    :return: {tool_name: handler_func}
    """

    def _get_cpu_usage(args: dict[str, Any]) -> str:
        """返回 CPU 使用率。"""
        backend = get_backend()
        if backend is None:
            return _err("E_BACKEND_UNAVAILABLE", "性能后端未初始化")
        try:
            result = backend.get_cpu_usage()
            return _ok(result)
        except Exception as exc:  # noqa: BLE001
            logger.debug("system_get_cpu_usage 失败: %s", exc)
            return _err("E_BACKEND_ERROR", str(exc))

    def _get_memory_usage(args: dict[str, Any]) -> str:
        """返回内存使用。"""
        backend = get_backend()
        if backend is None:
            return _err("E_BACKEND_UNAVAILABLE", "性能后端未初始化")
        try:
            result = backend.get_memory_usage()
            return _ok(result)
        except Exception as exc:  # noqa: BLE001
            logger.debug("system_get_memory_usage 失败: %s", exc)
            return _err("E_BACKEND_ERROR", str(exc))

    def _get_disk_usage(args: dict[str, Any]) -> str:
        """返回磁盘使用。"""
        backend = get_backend()
        if backend is None:
            return _err("E_BACKEND_UNAVAILABLE", "性能后端未初始化")
        path = args.get("path", "/")
        if not isinstance(path, str) or not path.strip():
            return _err("E_INVALID_PARAM", f"path 必须为非空字符串，got {path!r}")
        try:
            result = backend.get_disk_usage(path=path.strip())
            return _ok(result)
        except Exception as exc:  # noqa: BLE001
            logger.debug("system_get_disk_usage 失败: %s", exc)
            return _err("E_BACKEND_ERROR", str(exc))

    return {
        "system_get_cpu_usage": _get_cpu_usage,
        "system_get_memory_usage": _get_memory_usage,
        "system_get_disk_usage": _get_disk_usage,
    }


# ---------------------------------------------------------------------------
# 工具元数据
# ---------------------------------------------------------------------------
TOOLS_META: list[dict[str, Any]] = [
    {
        "name": "system_get_cpu_usage",
        "description": "查询系统 CPU 使用率（百分比）与逻辑核心数。",
        "emoji": "🧠",
        "schema": SYSTEM_GET_CPU_USAGE_SCHEMA,
    },
    {
        "name": "system_get_memory_usage",
        "description": "查询系统内存使用情况（总量/可用/使用率）。",
        "emoji": "💾",
        "schema": SYSTEM_GET_MEMORY_USAGE_SCHEMA,
    },
    {
        "name": "system_get_disk_usage",
        "description": "查询指定路径的磁盘使用情况（总量/已用/可用/使用率）。",
        "emoji": "💿",
        "schema": SYSTEM_GET_DISK_USAGE_SCHEMA,
    },
]
