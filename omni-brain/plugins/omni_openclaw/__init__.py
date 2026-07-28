"""omni_openclaw：OpenClaw 智能通信网关插件。

对外暴露两个入口：
- ``register(ctx)``：Hermes/WeBrain 旧式插件契约
- ``OpenClawPlugin``：M15 ``OmniPlugin`` 子类，经 ``omni_sdk.compat.RegisterCompatPlugin``
  包装 ``register(ctx)``

所有 OpenClaw 调用只通过 HTTP 与配置文件进行，不修改 OpenClaw 源码。
"""

from __future__ import annotations

from omni_sdk.compat import RegisterCompatPlugin

__all__ = ["register", "OpenClawPlugin"]


def register(ctx) -> None:
    """把 openclaw_* 工具注册到插件上下文。"""
    from .tools import register as _register

    _register(ctx)


class OpenClawPlugin(RegisterCompatPlugin):
    """omni_openclaw 的 OmniPlugin 适配子类。"""

    name: str = "omni_openclaw"
    version: str = "0.1.0"
    description: str = "OpenClaw 智能通信网关 - 微信/多模态/智能家居/巡检/AICG"
    emoji: str = "🐾"

    def __init__(self) -> None:
        super().__init__(register_func=register)
