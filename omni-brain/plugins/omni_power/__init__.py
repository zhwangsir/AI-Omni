"""omni_power：电源管理插件（macOS 锁屏/睡眠/关机/重启）。

继承 ``SystemPluginBase``（M15+ SDK），统一处理事件桥接与工具注册。

工具清单：
- ``system_lock_screen``  ：锁屏（pmset displaysleepnow）
- ``system_sleep``        ：睡眠（pmset sleepnow）
- ``system_shutdown``     ：关机（osascript，需 confirm=True 二次确认）
- ``system_restart``      ：重启（osascript，需 confirm=True 二次确认）

危险操作（shutdown/restart）必须传 ``confirm=True``，否则返回 E_CONFIRMATION_REQUIRED。
重型依赖（subprocess）惰性导入，测试全用 fake 后端，不执行真实系统命令。
保留旧式 ``register(ctx)`` 函数作为兼容入口。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from omni_sdk.system_plugin import SystemPluginBase

if TYPE_CHECKING:
    from omni_sdk.context import PluginContext

__all__ = ["PowerPlugin", "register"]

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """旧式 register(ctx) 入口：把 4 个 system_* 工具注册到上下文。

    保留此函数用于向后兼容与外部直接调用；
    内部委托给 ``PowerPlugin`` 实例完成注册。
    """
    from .tools import register as _tools_register

    _tools_register(ctx)


class PowerPlugin(SystemPluginBase):
    """omni_power 插件类，继承 SystemPluginBase。"""

    name: str = "omni_power"
    version: str = "0.1.0"
    description: str = "电源管理插件 - macOS 锁屏/睡眠/关机/重启，危险操作需二次确认"
    emoji: str = "⚡"
    event_domain: str = "system"

    def _build_tools_meta(self) -> list[dict[str, Any]]:
        """从 tools.TOOLS 构建工具元数据。"""
        from . import tools

        result = []
        for meta in tools.TOOLS:
            result.append({
                "name": meta["name"],
                "description": meta["description"],
                "emoji": meta["emoji"],
                "schema": meta["schema"],
                "handler": tools._make_handler(meta["handler_func"]),
            })
        return result

    async def on_load(self, ctx: PluginContext) -> None:
        """加载：注册工具并接入事件总线。"""
        await super().on_load(ctx)
        from . import tools

        bus = getattr(ctx, "event_bus", None)
        if bus is not None and callable(getattr(bus, "publish", None)):
            tools._runtime.event_publisher = bus
        self._logger.info("omni_power 插件已加载，注册 %d 个工具", len(tools.TOOLS))

    async def on_unload(self) -> None:
        """清理运行时引用（幂等）。"""
        from . import tools

        tools._runtime.event_publisher = None
        await super().on_unload()
