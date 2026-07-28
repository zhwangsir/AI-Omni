"""omni_fullscreen_detect：全屏应用检测插件（M16-P1）。

继承 ``SystemPluginBase``（M15+ SDK），统一处理事件桥接与工具注册。

工具清单：
- system_detect_fullscreen_app

后端可缺省：未注入时返回 E_BACKEND_UNAVAILABLE。
检测到全屏应用时发布 ``system.fullscreen_changed`` 事件。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from omni_sdk.system_plugin import SystemPluginBase

from .tools import TOOLS_META, make_handlers

if TYPE_CHECKING:
    from omni_sdk.context import PluginContext

__all__ = ["FullscreenDetectPlugin"]

logger = logging.getLogger(__name__)


class FullscreenDetectPlugin(SystemPluginBase):
    """全屏应用检测插件，继承 SystemPluginBase。"""

    name: str = "omni_fullscreen_detect"
    version: str = "0.1.0"
    description: str = "全屏应用检测插件 - 检测当前 macOS 全屏应用"
    emoji: str = "🖥️"
    event_domain: str = "system"

    def _publish_full_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """直接发布完整事件名（保持向后兼容）。"""
        if self._event_bus is None:
            return
        try:
            from omni_sdk.utils import sync_to_async_publish
            sync_to_async_publish(self._event_bus.publish, event_type, payload)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("事件 %s 发布失败: %s", event_type, exc)

    def _publish_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """测试期望的方法别名，直接委托给 _publish_full_event。"""
        self._publish_full_event(event_type, payload)

    def _build_tools_meta(self) -> list[dict[str, Any]]:
        """构建工具元数据，使用 make_handlers 工厂。"""
        handlers = make_handlers(
            get_backend=lambda: self._backend,
            publish_event=self._publish_full_event,
        )
        result = []
        for meta in TOOLS_META:
            result.append({
                "name": meta["name"],
                "description": meta["description"],
                "emoji": meta["emoji"],
                "schema": meta["schema"],
                "handler": handlers[meta["name"]],
            })
        return result

    async def on_load(self, ctx: PluginContext) -> None:
        """注入后端并注册工具。"""
        await super().on_load(ctx)
        self._logger.info("omni_fullscreen_detect 插件已加载，注册 %d 个工具", len(TOOLS_META))
