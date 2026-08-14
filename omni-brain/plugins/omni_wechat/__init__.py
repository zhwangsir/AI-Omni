"""omni_wechat：微信消息收发插件。

直连腾讯 iLink Bot API（``https://ilinkai.weixin.qq.com``），绕过 OpenClaw 网关
与 wechat-bridge 多跳链路，实现单跳收发。

工具清单：
- ``wechat_send``         发送文本消息
- ``wechat_status``       查询插件状态
- ``wechat_set_target``   设置默认接收人
- ``wechat_start_listen`` 启动长轮询监听
- ``wechat_stop_listen``  停止长轮询监听

事件发布：
- ``wechat.message_received``  收到新消息
- ``wechat.message_sent``      消息发送成功
- ``wechat.listen_started``    监听启动
- ``wechat.listen_stopped``    监听停止

凭据持久化到 ``~/.omni_wechat/accounts/<account>/``，与 OpenClaw 布局一致便于迁移。
重型依赖（httpx）惰性导入；测试全用 fake backend，不访问真实网络。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from omni_sdk.plugin import OmniPlugin

if TYPE_CHECKING:
    from omni_sdk.context import PluginContext

__all__ = ["WechatPlugin", "register"]

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """旧式 register(ctx) 入口：注册 5 个 wechat_* 工具到上下文。

    保留此函数用于向后兼容与外部直接调用；
    ``WechatPlugin.on_load`` 内部也复用本函数完成工具注册。
    """
    from .tools import register as _register

    _register(ctx)


class WechatPlugin(OmniPlugin):
    """omni_wechat 的 ``OmniPlugin`` 子类。"""

    name: str = "omni_wechat"
    version: str = "0.1.0"
    description: str = "微信消息收发插件（直连腾讯 iLink Bot API，支持发送与长轮询接收）"
    emoji: str = "💬"

    def __init__(self) -> None:
        self._logger: logging.Logger = logging.getLogger(f"omni.{self.name}")

    async def on_load(self, ctx: PluginContext) -> None:
        """注册 5 个 wechat_* 工具到 ctx.tool_registry 并接入事件总线。

        :param ctx: PluginContext，由 LifecycleHost 注入
        """
        register(ctx)
        from . import tools

        bus = getattr(ctx, "event_bus", None)
        if bus is not None and callable(getattr(bus, "publish", None)):
            tools._runtime.event_publisher = bus

        # 从 ctx.config 注入运行时配置（若提供）
        if ctx.config:
            from omni_wechat.config import WechatConfig

            try:
                tools._runtime.config = WechatConfig.from_dict(ctx.config)
            except ValueError as exc:
                self._logger.warning("omni_wechat 配置解析失败，使用默认配置: %s", exc)

        # 注入 backend（测试用 fake）
        backend = ctx.config.get("backend") if ctx.config else None
        if backend is not None:
            tools._runtime.backend = backend

        self._logger.info("omni_wechat 插件已加载，注册 %d 个工具", len(tools.TOOLS))

    async def on_unload(self) -> None:
        """停止监听、关闭客户端、关停后台事件循环线程（幂等）。"""
        import asyncio

        from . import tools

        try:
            # shutdown_runtime 是同步阻塞函数（内部提交到后台 loop 线程），
            # 经 to_thread 避免阻塞宿主事件循环
            await asyncio.to_thread(tools.shutdown_runtime)
        except Exception:  # noqa: BLE001
            self._logger.debug("omni_wechat on_unload 清理异常", exc_info=True)
        self._logger.info("omni_wechat 插件已卸载")

    async def on_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """事件路由；当前 omni_wechat 不订阅外部事件，默认空实现。"""
        return None
