"""PluginContext：LifecycleHost 注入到插件 ``on_load`` 的上下文。

提供 config / event_bus / tool_registry / permission_checker / logger 五大能力，
以及 register_tool / register_hook 委托方法（沿用 register(ctx) 兼容契约）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from omni_sdk.event_bus import EventBus
from omni_sdk.permissions import PermissionChecker
from omni_sdk.registry import ToolRegistry

if TYPE_CHECKING:
    pass


class PluginContext:
    """插件运行时上下文：聚合配置、事件总线、工具注册表、权限校验器、logger。

    register_tool / register_hook 为委托方法，分别转发到 tool_registry / event_bus，
    便于沿用 register(ctx) 契约的代码迁移到 OmniPlugin.on_load。
    """

    def __init__(
        self,
        config: dict[str, Any],
        event_bus: EventBus,
        tool_registry: ToolRegistry,
        permission_checker: PermissionChecker,
        logger: logging.Logger | None = None,
        plugin_name: str | None = None,
    ) -> None:
        """构造 PluginContext。

        :param config: 插件配置 dict（来自全局配置的 plugins.omni_<name> 段）
        :param event_bus: 事件总线
        :param tool_registry: 工具注册表
        :param permission_checker: 权限校验器
        :param logger: 可选 logger；未提供时按 plugin_name 构造 ``omni.<plugin_name>``
        :param plugin_name: 插件名（用于 logger 命名空间）
        """
        self.config: dict[str, Any] = config
        self.event_bus: EventBus = event_bus
        self.tool_registry: ToolRegistry = tool_registry
        self.permission_checker: PermissionChecker = permission_checker
        if logger is not None:
            self.logger: logging.Logger = logger
        else:
            ns = f"omni.{plugin_name}" if plugin_name else "omni.sdk"
            self.logger = logging.getLogger(ns)

    def register_tool(
        self,
        name: str,
        description: str,
        emoji: str,
        schema: dict[str, Any],
        handler_func: Callable[[dict[str, Any]], str],
    ) -> None:
        """委托给 tool_registry.register_tool。

        :param name: 工具名（snake_case）
        :param description: 工具用途
        :param emoji: CLI 展示用 emoji
        :param schema: JSON Schema dict
        :param handler_func: 处理函数，返回 JSON 字符串
        """
        self.tool_registry.register_tool(
            name=name,
            description=description,
            emoji=emoji,
            schema=schema,
            handler_func=handler_func,
        )

    def register_hook(self, event_type: str, callback: Callable[[dict[str, Any]], Any]) -> str:
        """委托给 event_bus.subscribe，返回 sub_id。

        :param event_type: 点分小写事件类型
        :param callback: 同步或异步回调
        :return: sub_id 字符串
        """
        return self.event_bus.subscribe(event_type, callback)
