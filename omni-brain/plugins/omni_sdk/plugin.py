"""OmniPlugin 基类：所有 omni_* 插件继承此类。

子类必须实现 ``on_load`` async 钩子；``on_unload`` / ``on_event`` / ``register_tools`` 提供默认空实现，
子类按需覆盖。元数据（name / version / description / emoji）作为类属性，子类覆盖。

参考：AGENTS.md §7.1 / CLAUDE.md §2.1。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from omni_sdk.context import PluginContext


class OmniPlugin(ABC):
    """插件基类：所有 M15 起新增的 ``omni_*`` 插件必须继承此类。

    子类约定：
    - 覆盖类属性 ``name`` / ``version`` / ``description`` / ``emoji``
    - 实现 async ``on_load(ctx)``（资源初始化、事件订阅、工具注册）
    - 按需覆盖 async ``on_unload``（释放资源，必须幂等）
    - 按需覆盖 async ``on_event``（事件分发回调）
    - 按需覆盖 sync ``register_tools(ctx)``（基类默认空实现，子类可读 manifest.tools 注册）
    """

    # 元数据（子类覆盖）
    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    emoji: str = ""

    @abstractmethod
    async def on_load(self, ctx: PluginContext) -> None:
        """插件加载时调用（async）：完成资源初始化、事件订阅、工具注册。

        :param ctx: PluginContext，由 LifecycleHost 注入
        :raises Exception: 加载失败抛异常，LifecycleHost 隔离错误不影响其他插件
        """
        ...

    async def on_unload(self) -> None:
        """插件卸载时调用（async）；默认空实现，必须可被多次调用（幂等）。

        子类覆盖时释放资源（关闭 WebSocket / 文件句柄 / 音频流）。
        """
        return None

    async def on_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """事件总线分发回调（async）；默认空实现。

        :param event_type: 点分小写事件类型
        :param payload: 事件负载 dict
        """
        return None

    def register_tools(self, ctx: PluginContext) -> None:
        """注册工具（sync）；默认空实现。

        子类可读取 manifest.tools 自动注册到 ctx.tool_registry，
        或直接调用 ctx.register_tool 追加自定义工具。
        """
        return None
