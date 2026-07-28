"""omni_weather：天气情绪电台插件。

直接继承 ``OmniPlugin``（M15 SDK），在 ``on_load(ctx)`` 中把 8 个 ``weather_*`` 工具
注册到 ``ctx.tool_registry``，并接入事件总线（发布 ``weather.mood_changed`` /
``weather.home_hint`` / ``weather.updated``）。

工具清单：
- ``weather_get``           获取当前天气（含 mood / home_hint / music_tags）
- ``weather_forecast``      24h 预报
- ``weather_set_location``  设置城市（持久化到 ~/.ai-omni/weather/config.json）
- ``weather_get_location``  获取当前城市
- ``weather_get_mood``      仅获取当前情绪（轻量，前端轮询用）
- ``weather_refresh``       强制刷新缓存
- ``weather_search_city``   城市搜索（Geocoding）
- ``weather_status``        插件状态（cache/位置/最后更新）

重型依赖（httpx）惰性导入；测试全用 fake HTTP，不访问真实网络。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from omni_sdk.plugin import OmniPlugin

if TYPE_CHECKING:
    from omni_sdk.context import PluginContext

__all__ = ["WeatherPlugin", "register"]


logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """旧式 register(ctx) 入口：注册 8 个 weather_* 工具到上下文。

    保留此函数用于向后兼容与外部直接调用；
    ``WeatherPlugin.on_load`` 内部也复用本函数完成工具注册。
    """
    from .tools import register as _register

    _register(ctx)


class WeatherPlugin(OmniPlugin):
    """omni_weather 的 ``OmniPlugin`` 子类。

    ``on_load(ctx)`` 调用 ``register(ctx)`` 把 8 个 weather_* 工具
    注册到 ``ctx.tool_registry``，并把事件总线接入运行时（供发布
    ``weather.mood_changed`` / ``weather.home_hint`` / ``weather.updated``）。
    """

    name: str = "omni_weather"
    version: str = "0.1.0"
    description: str = "天气情绪电台（Open-Meteo + 情绪映射 + 视觉/音乐/家居联动建议）"
    emoji: str = "🌤️"

    def __init__(self) -> None:
        self._logger: logging.Logger = logging.getLogger(f"omni.{self.name}")

    async def on_load(self, ctx: PluginContext) -> None:
        """注册 8 个 weather_* 工具到 ctx.tool_registry 并接入事件总线。

        :param ctx: PluginContext，由 LifecycleHost 注入
        """
        register(ctx)
        from . import tools

        bus = getattr(ctx, "event_bus", None)
        if bus is not None and callable(getattr(bus, "publish", None)):
            tools._runtime.event_publisher = bus
        self._logger.info("omni_weather 插件已加载，注册 %d 个工具", len(tools.TOOLS))

    async def on_unload(self) -> None:
        """清空缓存与运行时引用（幂等）。"""
        from . import tools

        try:
            tools._runtime.cache.invalidate_all()
            tools._runtime.event_publisher = None
        except Exception:  # noqa: BLE001
            self._logger.debug("omni_weather on_unload 清理异常", exc_info=True)
        self._logger.info("omni_weather 插件已卸载")

    async def on_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """事件路由；当前 omni_weather 不订阅外部事件，默认空实现。"""
        return None
