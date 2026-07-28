"""omni_home：智能家居控制插件（Home Assistant 桥接 + 自然语言设备控制）。

对外暴露两个入口：
- ``register(ctx)``：Hermes/WeBrain 旧式插件契约（向后兼容，不破坏既有 230 个测试）
- ``HomePlugin``：M15 ``OmniPlugin`` 子类，经 ``omni_sdk.compat.RegisterCompatPlugin``
  包装 ``register(ctx)``，``on_load(ctx)`` 调用 ``register`` 把 home_* 工具注册到
  ``ctx.tool_registry``。迁移期两条入口并存（AGENTS.md §7 / CLAUDE.md §2.1）。

重型依赖（websocket-client 等）一律惰性导入，import 本包不会拉入任何第三方库。
"""

from __future__ import annotations

from typing import Any

from omni_sdk.compat import RegisterCompatPlugin

__all__ = ["register", "HomePlugin"]


def register(ctx) -> None:
    """Hermes/WeBrain 插件入口：把全部 home_* tools 注册到插件上下文。"""
    from .tools import register as _register

    _register(ctx)


class HomePlugin(RegisterCompatPlugin):
    """omni_home 的 ``OmniPlugin`` 适配子类。

    经 :class:`RegisterCompatPlugin` 包装现有 ``register(ctx)`` 函数：
    ``on_load(ctx)`` 构造 legacy ctx 适配器并调用 ``register(adapter)``，
    使 6 个 home_* 工具注册到 ``ctx.tool_registry``、事件总线接入运行时。
    保留 ``register(ctx)`` 入口向后兼容（M15 迁移期不破坏既有测试）。
    """

    name: str = "omni_home"
    version: str = "0.1.0"
    description: str = "智能家居控制插件 - Home Assistant 桥接 + 自然语言设备控制"
    emoji: str = "🏠"

    def __init__(self) -> None:
        super().__init__(register_func=register)
