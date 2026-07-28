"""omni_music：音乐源接入插件（M17）。

M17.1-M17.4 基础架构阶段：
- 数据模型（Song/Playlist/Artist/MusicSourceEnum）
- MusicSource 抽象基类 + FakeMusicSource
- Cookie AES-256-GCM 加密存储（CookieStore + FakeCookieStore）
- 扫码登录通用流程（QRLoginFlow + FakeQRLoginFlow）

工具（M17.1-M17.4 占位 2 个，完整 12 工具在 M17.9）：
- ``music_search``       ：搜索歌曲
- ``music_get_login_qr`` ：发起扫码登录

合规说明（D17.4）：仅免费/试听曲目，VIP 曲目提示需登录，不提供破解。
仅个人学习用途。

直接继承 ``OmniPlugin``（M15 SDK），在 ``on_load(ctx)`` 中把占位工具注册到
``ctx.tool_registry``，重型依赖惰性导入，测试全用 fake 后端。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from omni_sdk.plugin import OmniPlugin

if TYPE_CHECKING:
    from omni_sdk.context import PluginContext

__all__ = ["MusicPlugin", "register"]

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """旧式 register(ctx) 入口：把 2 个占位 music_* 工具注册到上下文。

    保留此函数用于向后兼容与外部直接调用；
    ``MusicPlugin.on_load`` 内部也复用本函数完成工具注册。
    """
    from .tools import register as _register

    _register(ctx)


class MusicPlugin(OmniPlugin):
    """omni_music 的 ``OmniPlugin`` 子类。

    ``on_load(ctx)`` 调用 ``register(ctx)`` 把占位 music_* 工具注册到
    ``ctx.tool_registry``。M17.1-M17.4 阶段仅注册 2 个工具，完整 12 工具在 M17.9。
    订阅 ``system.volume_changed`` 事件调整播放增益。
    """

    name: str = "omni_music"
    version: str = "0.1.0"
    description: str = (
        "音乐源接入插件 - 多源搜索/扫码登录/Cookie加密存储，"
        "支持网易云/QQ/本地音乐（仅免费试听，VIP 需登录）"
    )
    emoji: str = "🎵"

    def __init__(self) -> None:
        self._logger: logging.Logger = logging.getLogger(f"omni.{self.name}")
        self._ctx: Any = None

    async def on_load(self, ctx: PluginContext) -> None:
        """注册占位 music_* 工具到 ctx.tool_registry，订阅系统音量事件。

        :param ctx: PluginContext，由 LifecycleHost 注入
        """
        self._ctx = ctx
        register(ctx)
        from . import tools

        # 订阅系统音量变化事件
        if hasattr(ctx, "event_bus") and ctx.event_bus is not None:
            def _on_volume_changed(payload: dict[str, Any]) -> None:
                volume = payload.get("volume", 1.0)
                if isinstance(volume, (int, float)):
                    gain = float(volume) / 100.0 if volume > 1 else float(volume)
                    tools.set_volume_gain(gain)

            ctx.event_bus.subscribe("system.volume_changed", _on_volume_changed)

        self._logger.info("omni_music 插件已加载，注册 %d 个工具", len(tools.TOOLS))

    async def on_unload(self) -> None:
        """清理运行时引用（幂等）。"""
        from . import tools

        tools._reset_runtime()
        self._ctx = None
        self._logger.info("omni_music 插件已卸载")
