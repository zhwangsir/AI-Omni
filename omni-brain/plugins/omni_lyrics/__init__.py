"""omni_lyrics：多源歌词匹配插件（M18）。

实现多源歌词获取与同步显示，让雪莉播放音乐时同步显示歌词。

核心能力：
- LRC 格式解析（标准 / 逐字 / 双语翻译 / 元数据）
- 多源优先级链：本地 .lrc 文件 → 音频内嵌歌词 → 在线 API → 纯文本兜底
- 歌词同步：根据播放时间定位当前行 + 逐字高亮 + 用户偏移量

工具（5 个 ``lyrics_*``）：
- ``lyrics_get``        ：获取歌词
- ``lyrics_search``     ：搜索歌曲
- ``lyrics_set_offset`` ：设置用户偏移
- ``lyrics_upload``     ：上传/保存歌词到本地 .lrc
- ``lyrics_get_current``：返回当前行 + 逐字高亮

直接继承 ``OmniPlugin``（M15 SDK），在 ``on_load(ctx)`` 中把 5 个工具注册到
``ctx.tool_registry``。重型依赖（mutagen）惰性导入，测试全用 fake 后端。

跨插件复用：经 ``omni_music.sources.base.MusicSource`` 抽象接口获取歌曲/歌词，
不直接 import omni_music 内部模块（仅依赖抽象基类与 Song 模型）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from omni_sdk.plugin import OmniPlugin

if TYPE_CHECKING:
    from omni_sdk.context import PluginContext

__all__ = ["LyricsPlugin", "register"]

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """旧式 register(ctx) 入口：把 5 个 lyrics_* 工具注册到上下文。

    保留此函数用于向后兼容与外部直接调用；
    ``LyricsPlugin.on_load`` 内部也复用本函数完成工具注册。
    """
    from .tools import register as _register

    _register(ctx)


class LyricsPlugin(OmniPlugin):
    """omni_lyrics 的 ``OmniPlugin`` 子类。

    ``on_load(ctx)`` 调用 ``register(ctx)`` 把 5 个 lyrics_* 工具注册到
    ``ctx.tool_registry``。订阅 ``music.started`` / ``music.paused`` /
    ``music.stopped`` / ``music.track_changed`` 事件自动启停歌词同步。
    """

    name: str = "omni_lyrics"
    version: str = "0.1.0"
    description: str = (
        "多源歌词匹配插件 - LRC解析/多源优先级链/同步显示，"
        "支持本地.lrc/音频内嵌/在线API（复用 omni_music 源）"
    )
    emoji: str = "📜"

    def __init__(self) -> None:
        self._logger: logging.Logger = logging.getLogger(f"omni.{self.name}")
        self._ctx: Any = None

    async def on_load(self, ctx: PluginContext) -> None:
        """注册 5 个 lyrics_* 工具到 ctx.tool_registry，订阅音乐事件。

        :param ctx: PluginContext，由 LifecycleHost 注入
        """
        self._ctx = ctx
        register(ctx)
        from . import tools

        # 订阅音乐事件自动启停歌词同步
        if hasattr(ctx, "event_bus") and ctx.event_bus is not None:
            def _on_music_started(payload: dict[str, Any]) -> None:
                track_id = payload.get("track_id")
                if track_id:
                    tools.start_sync_for_song(str(track_id))

            def _on_music_paused(_payload: dict[str, Any]) -> None:
                # 暂停时保持同步状态但标记非活跃
                pass

            def _on_music_stopped(_payload: dict[str, Any]) -> None:
                tools.stop_sync()

            def _on_track_changed(payload: dict[str, Any]) -> None:
                track_id = payload.get("track_id")
                if track_id:
                    tools.start_sync_for_song(str(track_id))

            ctx.event_bus.subscribe("music.started", _on_music_started)
            ctx.event_bus.subscribe("music.paused", _on_music_paused)
            ctx.event_bus.subscribe("music.stopped", _on_music_stopped)
            ctx.event_bus.subscribe("music.track_changed", _on_track_changed)

        self._logger.info("omni_lyrics 插件已加载，注册 %d 个工具", len(tools.TOOLS))

    async def on_unload(self) -> None:
        """清理运行时引用（幂等）。"""
        from . import tools

        tools._reset_runtime()
        self._ctx = None
        self._logger.info("omni_lyrics 插件已卸载")
