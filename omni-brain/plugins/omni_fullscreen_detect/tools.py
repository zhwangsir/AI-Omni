"""omni_fullscreen_detect 工具 handler 实现 + JSON Schema。

1 个工具：
- ``system_detect_fullscreen_app()``：检测当前全屏应用

handler 返回 JSON 字符串。
检测到全屏应用时发布 ``system.fullscreen_changed`` 事件。
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
SYSTEM_DETECT_FULLSCREEN_APP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}


# ---------------------------------------------------------------------------
# 工具 handler 工厂
# ---------------------------------------------------------------------------
def make_handlers(
    get_backend: Callable[[], Any],
    publish_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Callable[[dict[str, Any]], str]]:
    """构造 system_detect_fullscreen_app handler。

    :param get_backend: 返回当前后端（可能为 None）的回调
    :param publish_event: 可选的事件发布回调
    :return: {tool_name: handler_func}
    """

    def _detect_fullscreen_app(args: dict[str, Any]) -> str:
        """检测当前全屏应用。"""
        backend = get_backend()
        if backend is None:
            return _err("E_BACKEND_UNAVAILABLE", "全屏检测后端未初始化")
        try:
            result = backend.detect_fullscreen_app()
            # 检测到全屏应用时发布事件
            if result.get("fullscreen") and publish_event is not None:
                publish_event(
                    "system.fullscreen_changed",
                    {
                        "app": result.get("app"),
                        "pid": result.get("pid"),
                        "window_title": result.get("window_title"),
                        "fullscreen": True,
                    },
                )
            return _ok(result)
        except Exception as exc:  # noqa: BLE001
            logger.debug("system_detect_fullscreen_app 失败: %s", exc)
            return _err("E_BACKEND_ERROR", str(exc))

    return {"system_detect_fullscreen_app": _detect_fullscreen_app}


# ---------------------------------------------------------------------------
# 工具元数据
# ---------------------------------------------------------------------------
TOOLS_META: list[dict[str, Any]] = [
    {
        "name": "system_detect_fullscreen_app",
        "description": "检测当前 macOS 全屏应用（Accessibility API，不可用时降级为窗口标题检测）。",
        "emoji": "🔲",
        "schema": SYSTEM_DETECT_FULLSCREEN_APP_SCHEMA,
    },
]
