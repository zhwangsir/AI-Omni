"""omni_performance：系统性能监控插件（M16-P1）。

继承 ``SystemPluginBase``（M15+ SDK），统一处理工具注册。

工具清单：
- system_get_cpu_usage
- system_get_memory_usage
- system_get_disk_usage

后端可缺省：未注入时返回 E_BACKEND_UNAVAILABLE（CLAUDE.md §三）。
性能监控为只读查询，无副作用，不发布事件。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from omni_sdk.system_plugin import SystemPluginBase

from .tools import TOOLS_META, make_handlers

if TYPE_CHECKING:
    from omni_sdk.context import PluginContext

__all__ = ["PerformancePlugin"]

logger = logging.getLogger(__name__)


class PerformancePlugin(SystemPluginBase):
    """系统性能监控插件，继承 SystemPluginBase。"""

    name: str = "omni_performance"
    version: str = "0.1.0"
    description: str = "系统性能监控插件 - CPU/内存/磁盘使用率查询"
    emoji: str = "📈"
    event_domain: str = "system"

    def _build_tools_meta(self) -> list[dict[str, Any]]:
        """构建工具元数据，使用 make_handlers 工厂。"""
        handlers = make_handlers(get_backend=lambda: self._backend)
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
        self._logger.info("omni_performance 插件已加载，注册 %d 个工具", len(TOOLS_META))
