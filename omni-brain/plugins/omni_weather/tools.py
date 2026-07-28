"""omni_weather 工具实现：8 个 ``weather_*`` 工具。

工具清单：
- ``weather_get``           获取当前天气（含 mood / home_hint / music_tags）
- ``weather_forecast``      24h 预报
- ``weather_set_location``  设置城市（持久化到 config.json）
- ``weather_get_location``  获取当前城市
- ``weather_get_mood``      仅获取当前情绪（轻量，前端轮询用）
- ``weather_refresh``       强制刷新缓存
- ``weather_search_city``   城市搜索（Geocoding）
- ``weather_status``        插件状态（cache/位置/最后更新）

工具统一返回 JSON 字符串 ``{"ok": true, "data": ...}`` /
``{"ok": false, "error": {"code": "E_XXX", "message": "..."}}``。

重型依赖（httpx）惰性导入（CLAUDE.md §三）；测试全用 fake HTTP（monkeypatch httpx.get）。
事件总线发布 ``weather.mood_changed`` / ``weather.home_hint`` / ``weather.updated``。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable

from omni_weather.backends.fake_open_meteo import (
    FakeGeocodingBackend,
    FakeIpLocationBackend,
    FakeOpenMeteoBackend,
)
from omni_weather.backends.geocoding import GeocodingBackend
from omni_weather.backends.ip_location import IpLocationBackend
from omni_weather.backends.open_meteo import OpenMeteoBackend
from omni_weather.cache import WeatherCache
from omni_weather.config_store import load_config, save_config
from omni_weather.home_action import build_home_hint
from omni_weather.mood_playlist import recommend_playlist_tags
from omni_weather.weather_mood import get_mood

try:
    from omni_sdk.utils import TaskTracker
    _HAS_TASK_TRACKER = True
except ImportError:
    _HAS_TASK_TRACKER = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 运行时单例
# ---------------------------------------------------------------------------
class Runtime:
    """进程内运行时：持有缓存、后端实例、当前位置、事件发布器。

    ``location`` 为 ``None`` 时表示未配置城市，工具调用会降级用 IP 定位。
    启动时从 config.json 加载位置（``load_location_from_config``）。
    """

    def __init__(self) -> None:
        self.cache: WeatherCache = WeatherCache()
        self.open_meteo: OpenMeteoBackend = OpenMeteoBackend()
        self.geocoding: GeocodingBackend = GeocodingBackend()
        self.ip_location: IpLocationBackend = IpLocationBackend()
        self.fake_open_meteo: FakeOpenMeteoBackend = FakeOpenMeteoBackend()
        self.fake_geocoding: FakeGeocodingBackend = FakeGeocodingBackend()
        self.fake_ip_location: FakeIpLocationBackend = FakeIpLocationBackend()
        self.location: dict[str, Any] | None = None
        self.event_publisher: Any = None
        self.last_mood: str | None = None
        self.task_tracker: Any = TaskTracker() if _HAS_TASK_TRACKER else None
        self.use_fake_backends: bool = False

    def get_backends(self, fake: bool = False) -> tuple[Any, Any, Any]:
        """根据 use_fake_backends 标志选择后端实例。

        ``fake`` 参数保留用于向后兼容，但只有显式设置 ``use_fake_backends=True``
        时才使用内置 Fake 后端（CLI --fake 会设置此标志）。
        """
        if self.use_fake_backends:
            return self.fake_open_meteo, self.fake_geocoding, self.fake_ip_location
        return self.open_meteo, self.geocoding, self.ip_location


_runtime = Runtime()


def _reset_runtime(runtime: Runtime | None = None) -> Runtime:
    """替换进程内运行时（测试隔离用），返回新实例。"""
    global _runtime
    _runtime = runtime or Runtime()
    # 从 config 加载位置（若已存在配置）
    cfg = load_config()
    if cfg.get("city") and cfg.get("lat") is not None and cfg.get("lon") is not None:
        _runtime.location = {
            "city": cfg["city"],
            "lat": float(cfg["lat"]),
            "lon": float(cfg["lon"]),
        }
    return _runtime


# ---------------------------------------------------------------------------
# JSON 响应约定
# ---------------------------------------------------------------------------
def _ok(data: Any) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False)


def _err(code: str, message: str) -> str:
    return json.dumps(
        {"ok": False, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )


def _publish(rt: Runtime, event_type: str, payload: dict[str, Any]) -> None:
    """向事件总线发布事件（未接入总线时静默跳过）。

    兼容同步 publish 与 async publish（omni_sdk.EventBus）：
    若 ``bus.publish`` 返回 coroutine，使用 TaskTracker 跟踪（P0-1 修复）。
    """
    bus = rt.event_publisher
    if bus is None or not callable(getattr(bus, "publish", None)):
        return
    import copy
    payload_snapshot = copy.deepcopy(payload)
    try:
        result = bus.publish(event_type, payload_snapshot)
        if asyncio.iscoroutine(result):
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(result)
                if rt.task_tracker is not None and hasattr(rt.task_tracker, 'add'):
                    rt.task_tracker.add(task)
            except RuntimeError:
                asyncio.run(result)
    except Exception:  # noqa: BLE001 - 总线异常不应拖垮工具调用
        logger.debug("事件发布失败: %s", event_type, exc_info=True)


# ---------------------------------------------------------------------------
# 取位置（runtime → IP 定位 fallback）
# ---------------------------------------------------------------------------
def _resolve_location(rt: Runtime, fake: bool = False) -> dict[str, Any]:
    """取当前位置；runtime.location 优先，缺失则降级 IP 定位。

    :param fake: 是否使用 fake 后端
    :return: ``{"ok": True, "lat", "lon", "city"}`` 或错误 dict
    """
    _, _, ip_location = rt.get_backends(fake)
    if rt.location is not None:
        return {
            "ok": True,
            "lat": rt.location["lat"],
            "lon": rt.location["lon"],
            "city": rt.location.get("city"),
        }
    # IP 定位 fallback
    result = ip_location.locate()
    if not result.get("ok"):
        return {
            "ok": False,
            "error": {
                "code": "E_LOCATION_REQUIRED",
                "message": "未配置城市且 IP 定位失败：" + result.get("error", {}).get("message", ""),
            },
        }
    return {
        "ok": True,
        "lat": result["lat"],
        "lon": result["lon"],
        "city": result.get("city"),
    }


def _fetch_weather(rt: Runtime, lat: float, lon: float, city: str | None = None, fake: bool = False) -> dict[str, Any]:
    """经缓存拉取天气数据。"""
    open_meteo, _, _ = rt.get_backends(fake)
    if fake:
        return open_meteo.get_weather(lat, lon, city=city)
    return rt.cache.get(lat, lon, lambda la, lo: open_meteo.get_weather(la, lo, city=city))


# ---------------------------------------------------------------------------
# 工具元数据注册表
# ---------------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = []


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    required: list[str] | None = None,
    emoji: str = "",
) -> Callable:
    """@tool 装饰器：为函数附加 tool schema 元数据并登记到 TOOLS。"""

    def decorator(func: Callable) -> Callable:
        TOOLS.append(
            {
                "name": name,
                "description": description,
                "emoji": emoji,
                "schema": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": parameters,
                        "required": list(required or []),
                    },
                },
                "handler_func": func,
            }
        )
        return func

    return decorator


_FAKE_PARAM = {
    "type": "boolean",
    "description": "为 true 时使用 fake 后端（演示/测试，不访问真实网络）。",
}


# ---------------------------------------------------------------------------
# Tool 1：获取当前天气
# ---------------------------------------------------------------------------
@tool(
    name="weather_get",
    description="获取当前天气：温度/湿度/风速/天气代码 + 情绪映射 + 家居建议 + 歌单标签。"
    "未配置城市时自动用 IP 定位。",
    parameters={"fake": _FAKE_PARAM},
    emoji="🌤️",
)
def weather_get(fake: bool = False) -> str:
    """获取当前天气 + mood + home_hint + music_tags。"""
    try:
        rt = _runtime
        loc = _resolve_location(rt, fake=fake)
        if not loc.get("ok"):
            return _err(loc["error"]["code"], loc["error"]["message"])
        lat = loc["lat"]
        lon = loc["lon"]
        city = loc.get("city")
        weather = _fetch_weather(rt, lat, lon, city=city, fake=fake)
        if not weather.get("ok"):
            return _err(
                weather.get("error", {}).get("code", "E_BACKEND_UNAVAILABLE"),
                weather.get("error", {}).get("message", "天气获取失败"),
            )
        # 派生 mood / home_hint / music_tags
        weather_code = weather.get("current", {}).get("weather_code")
        mood = get_mood(weather_code if isinstance(weather_code, int) else None)
        home_hint = build_home_hint(weather, mood=mood.mood)
        music_tags = recommend_playlist_tags(mood.mood)

        payload = {
            "current": weather["current"],
            "city": city,
            "mood": mood.to_dict(),
            "music_tags": music_tags,
            "home_hint": home_hint,
            "cached": weather.get("cached", False),
            "cached_at": weather.get("cached_at"),
        }

        # 发布事件
        _publish(
            rt,
            "weather.mood_changed",
            {
                "mood": mood.mood,
                "music_tags": music_tags,
                "city": city,
                "weather_code": weather_code,
                "timestamp": _iso_now(),
            },
        )
        _publish(
            rt,
            "weather.updated",
            {
                "city": city,
                "temperature": weather["current"].get("temperature"),
                "weather_code": weather_code,
                "timestamp": _iso_now(),
            },
        )
        if home_hint["actions"]:
            _publish(
                rt,
                "weather.home_hint",
                {
                    "actions": home_hint["actions"],
                    "summary": home_hint["summary"],
                    "city": city,
                    "timestamp": _iso_now(),
                },
            )

        # mood 变化跟踪
        rt.last_mood = mood.mood
        return _ok(payload)
    except Exception as exc:  # noqa: BLE001
        logger.debug("weather_get 失败: %s", exc, exc_info=True)
        return _err("E_INTERNAL", str(exc))


# ---------------------------------------------------------------------------
# Tool 2：24h 预报
# ---------------------------------------------------------------------------
@tool(
    name="weather_forecast",
    description="获取未来 24 小时天气预报：每小时温度/天气代码/降水概率。",
    parameters={"fake": _FAKE_PARAM},
    emoji="📅",
)
def weather_forecast(fake: bool = False) -> str:
    """返回 24h 预报。"""
    try:
        rt = _runtime
        loc = _resolve_location(rt, fake=fake)
        if not loc.get("ok"):
            return _err(loc["error"]["code"], loc["error"]["message"])
        weather = _fetch_weather(rt, loc["lat"], loc["lon"], city=loc.get("city"), fake=fake)
        if not weather.get("ok"):
            return _err(
                weather.get("error", {}).get("code", "E_BACKEND_UNAVAILABLE"),
                weather.get("error", {}).get("message", "天气获取失败"),
            )
        return _ok(
            {
                "hourly": weather.get("hourly", []),
                "city": loc.get("city"),
                "cached_at": weather.get("cached_at"),
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("weather_forecast 失败: %s", exc, exc_info=True)
        return _err("E_INTERNAL", str(exc))


# ---------------------------------------------------------------------------
# Tool 3：设置城市
# ---------------------------------------------------------------------------
@tool(
    name="weather_set_location",
    description="设置当前城市：传 city 名走 Geocoding 解析经纬度；也可直接传 lat/lon 跳过解析。"
    "配置持久化到 ~/.ai-omni/weather/config.json。",
    parameters={
        "city": {
            "type": "string",
            "description": "城市名（如：北京 / Shanghai）；与 lat/lon 二选一",
        },
        "lat": {
            "type": "number",
            "description": "纬度（与 lon 一起传入时跳过 geocoding）",
        },
        "lon": {
            "type": "number",
            "description": "经度（与 lat 一起传入时跳过 geocoding）",
        },
        "fake": _FAKE_PARAM,
    },
    required=["city"],
    emoji="📍",
)
def weather_set_location(
    city: str,
    lat: float | None = None,
    lon: float | None = None,
    fake: bool = False,
) -> str:
    """设置城市并持久化；返回新位置。"""
    try:
        if not isinstance(city, str) or not city.strip():
            return _err("E_INVALID_ARG", "city 不能为空")
        city = city.strip()

        if lat is not None and lon is not None:
            # 直接传经纬度，不走 geocoding
            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except (TypeError, ValueError):
                return _err("E_INVALID_ARG", f"lat/lon 必须为数字: lat={lat!r}, lon={lon!r}")
        else:
            # geocoding 解析
            _, geocoding, _ = _runtime.get_backends(fake)
            result = geocoding.search(city, limit=1)
            if not result.get("ok"):
                return _err(
                    result.get("error", {}).get("code", "E_GEOCODING_FAILED"),
                    result.get("error", {}).get("message", "城市解析失败"),
                )
            results = result.get("results", [])
            if not results:
                return _err("E_CITY_NOT_FOUND", f"未找到城市: {city}")
            first = results[0]
            lat_f = float(first["lat"])
            lon_f = float(first["lon"])
            # 用 API 返回的标准名替换（避免大小写/拼写差异）
            if first.get("name"):
                city = first["name"]

        _runtime.location = {"city": city, "lat": lat_f, "lon": lon_f}
        save_config({"city": city, "lat": lat_f, "lon": lon_f})
        return _ok({"city": city, "lat": lat_f, "lon": lon_f, "saved": True})
    except Exception as exc:  # noqa: BLE001
        logger.debug("weather_set_location 失败: %s", exc, exc_info=True)
        return _err("E_INTERNAL", str(exc))


# ---------------------------------------------------------------------------
# Tool 4：获取当前位置
# ---------------------------------------------------------------------------
@tool(
    name="weather_get_location",
    description="获取当前配置的城市与经纬度；未配置时返回 E_LOCATION_REQUIRED。",
    parameters={"fake": _FAKE_PARAM},
    emoji="🗺️",
)
def weather_get_location(fake: bool = False) -> str:
    """返回当前位置。"""
    try:
        if _runtime.location is None:
            return _err("E_LOCATION_REQUIRED", "未配置城市，请先调用 weather_set_location")
        loc = _runtime.location
        return _ok({"city": loc["city"], "lat": loc["lat"], "lon": loc["lon"]})
    except Exception as exc:  # noqa: BLE001
        logger.debug("weather_get_location 失败: %s", exc, exc_info=True)
        return _err("E_INTERNAL", str(exc))


# ---------------------------------------------------------------------------
# Tool 5：仅获取情绪（轻量）
# ---------------------------------------------------------------------------
@tool(
    name="weather_get_mood",
    description="仅获取当前天气情绪（轻量，供前端轮询用）。返回 mood 名 + 调色板 + 粒子参数。",
    parameters={"fake": _FAKE_PARAM},
    emoji="🎨",
)
def weather_get_mood(fake: bool = False) -> str:
    """返回 mood 描述符（不含完整 weather 数据）。"""
    try:
        rt = _runtime
        loc = _resolve_location(rt, fake=fake)
        if not loc.get("ok"):
            return _err(loc["error"]["code"], loc["error"]["message"])
        weather = _fetch_weather(rt, loc["lat"], loc["lon"], city=loc.get("city"), fake=fake)
        if not weather.get("ok"):
            return _err(
                weather.get("error", {}).get("code", "E_BACKEND_UNAVAILABLE"),
                weather.get("error", {}).get("message", "天气获取失败"),
            )
        weather_code = weather.get("current", {}).get("weather_code")
        mood = get_mood(weather_code if isinstance(weather_code, int) else None)
        rt.last_mood = mood.mood
        return _ok(
            {
                "mood": mood.mood,
                "description": mood.description,
                "color_palette": mood.color_palette,
                "particle_params": mood.particle_params,
                "cached_at": weather.get("cached_at"),
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("weather_get_mood 失败: %s", exc, exc_info=True)
        return _err("E_INTERNAL", str(exc))


# ---------------------------------------------------------------------------
# Tool 6：强制刷新缓存
# ---------------------------------------------------------------------------
@tool(
    name="weather_refresh",
    description="强制刷新天气缓存：清除当前位置缓存并重新拉取。返回刷新时间。",
    parameters={"fake": _FAKE_PARAM},
    emoji="🔄",
)
def weather_refresh(fake: bool = False) -> str:
    """强制刷新缓存。"""
    try:
        rt = _runtime
        loc = _resolve_location(rt, fake=fake)
        if not loc.get("ok"):
            return _err(loc["error"]["code"], loc["error"]["message"])
        if not fake:
            rt.cache.invalidate(loc["lat"], loc["lon"])
        # 重新拉取（触发刷新）
        weather = _fetch_weather(rt, loc["lat"], loc["lon"], city=loc.get("city"), fake=fake)
        if not weather.get("ok"):
            return _err(
                weather.get("error", {}).get("code", "E_BACKEND_UNAVAILABLE"),
                weather.get("error", {}).get("message", "天气获取失败"),
            )
        return _ok(
            {
                "refreshed_at": _iso_now(),
                "cached_at": weather.get("cached_at"),
                "city": loc.get("city"),
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("weather_refresh 失败: %s", exc, exc_info=True)
        return _err("E_INTERNAL", str(exc))


# ---------------------------------------------------------------------------
# Tool 7：城市搜索
# ---------------------------------------------------------------------------
@tool(
    name="weather_search_city",
    description="搜索城市（Geocoding）：返回城市名/经纬度/国家/区域。用于 weather_set_location 前的候选查询。",
    parameters={
        "keyword": {
            "type": "string",
            "description": "城市名关键词（如：北京 / Shanghai / new york）",
        },
        "limit": {
            "type": "integer",
            "description": "返回上限，默认 5",
            "default": 5,
        },
        "fake": _FAKE_PARAM,
    },
    required=["keyword"],
    emoji="🔍",
)
def weather_search_city(keyword: str, limit: int = 5, fake: bool = False) -> str:
    """城市搜索。"""
    try:
        if not isinstance(keyword, str) or not keyword.strip():
            return _err("E_INVALID_ARG", "keyword 不能为空")
        _, geocoding, _ = _runtime.get_backends(fake)
        result = geocoding.search(keyword, limit=limit)
        if not result.get("ok"):
            return _err(
                result.get("error", {}).get("code", "E_GEOCODING_FAILED"),
                result.get("error", {}).get("message", "城市搜索失败"),
            )
        return _ok({"results": result["results"], "count": result["count"]})
    except Exception as exc:  # noqa: BLE001
        logger.debug("weather_search_city 失败: %s", exc, exc_info=True)
        return _err("E_INTERNAL", str(exc))


# ---------------------------------------------------------------------------
# Tool 8：插件状态
# ---------------------------------------------------------------------------
@tool(
    name="weather_status",
    description="查询插件状态：缓存条数 / 当前位置 / 最后更新时间 / 最后情绪。",
    parameters={"fake": _FAKE_PARAM},
    emoji="📊",
)
def weather_status(fake: bool = False) -> str:
    """返回插件状态。"""
    try:
        rt = _runtime
        return _ok(
            {
                "cache": rt.cache.status(),
                "location": rt.location,
                "last_mood": rt.last_mood,
                "timestamp": _iso_now(),
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("weather_status 失败: %s", exc, exc_info=True)
        return _err("E_INTERNAL", str(exc))


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _iso_now() -> str:
    """当前时间 ISO8601 字符串。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


# ---------------------------------------------------------------------------
# 注册入口
# ---------------------------------------------------------------------------
def _make_handler(func: Callable) -> Callable:
    """把工具函数适配为 registry handler：``(args: dict, **kw) -> JSON 字符串``。"""

    def handler(args: dict[str, Any], **_: Any) -> str:
        try:
            return func(**(args or {}))
        except Exception as exc:  # noqa: BLE001
            logger.debug("weather tool %s 调用失败: %s", getattr(func, "__name__", "?"), exc)
            return _err("E_INVALID_ARGS", str(exc))

    return handler


def register(ctx) -> None:
    """把 8 个 weather_* tools 注册到插件上下文；若 ctx 携带事件总线则接入。

    使用 M15 新式 ``ctx.register_tool(name, description, emoji, schema, handler_func)`` 签名。
    """
    for meta in TOOLS:
        ctx.register_tool(
            name=meta["name"],
            description=meta["description"],
            emoji=meta["emoji"],
            schema=meta["schema"],
            handler_func=_make_handler(meta["handler_func"]),
        )
    bus = getattr(ctx, "event_bus", None)
    if bus is not None and callable(getattr(bus, "publish", None)):
        _runtime.event_publisher = bus
    # 启动时从 config 加载位置
    cfg = load_config()
    if cfg.get("city") and cfg.get("lat") is not None and cfg.get("lon") is not None:
        _runtime.location = {
            "city": cfg["city"],
            "lat": float(cfg["lat"]),
            "lon": float(cfg["lon"]),
        }
    logger.info("omni_weather 插件已注册 %d 个 tools", len(TOOLS))
