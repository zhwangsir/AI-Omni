"""omni_weather tools 测试：8 个 weather_* 工具。

全部 fake 后端驱动（monkeypatch httpx.get / 预置 fake backend），
不访问真实网络。每个测试用 ``_reset_runtime()`` 隔离进程内单例。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from omni_weather import tools
from omni_weather.backends.geocoding import GeocodingBackend
from omni_weather.backends.ip_location import IpLocationBackend
from omni_weather.backends.open_meteo import OpenMeteoBackend


def _parse(result: str) -> dict:
    """工具返回的是 JSON 字符串，解析为 dict。"""
    assert isinstance(result, str)
    return json.loads(result)


def _fake_weather_response(temp: float = 22.0, code: int = 0) -> dict[str, Any]:
    """Open-Meteo 风格 fake 响应。"""
    return {
        "current": {
            "temperature_2m": temp,
            "relative_humidity_2m": 60,
            "wind_speed_10m": 2.0,
            "weather_code": code,
            "apparent_temperature": temp + 0.5,
        },
        "hourly": {
            "time": ["2026-07-27T00:00"] * 24,
            "temperature_2m": [temp + i * 0.1 for i in range(24)],
            "weather_code": [code] * 24,
            "precipitation_probability": [10] * 24,
        },
    }


class _FakeResp:
    def __init__(self, data: Any, status: int = 200) -> None:
        self._data = data
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._data


@pytest.fixture(autouse=True)
def fresh_runtime(monkeypatch, tmp_path):
    """每个测试前重置运行时单例，并把 config 路径指向 tmp_path。"""
    monkeypatch.setenv("AI_OMNI_WEATHER_CONFIG", str(tmp_path / "config.json"))
    rt = tools._reset_runtime()
    yield rt


@pytest.fixture
def patch_httpx(monkeypatch):
    """patch httpx.get 返回预制的 Open-Meteo 数据。"""
    import httpx

    def fake_get(url: str, **kwargs: Any) -> _FakeResp:
        if "geocoding-api" in url:
            return _FakeResp(
                {
                    "results": [
                        {
                            "name": "北京",
                            "latitude": 39.9042,
                            "longitude": 116.4074,
                            "country": "China",
                            "admin1": "Beijing",
                            "timezone": "Asia/Shanghai",
                            "population": 21540000,
                        }
                    ]
                }
            )
        if "ip-api" in url:
            return _FakeResp(
                {
                    "status": "success",
                    "lat": 39.9042,
                    "lon": 116.4074,
                    "city": "Beijing",
                    "regionName": "Beijing",
                    "country": "China",
                    "query": "1.2.3.4",
                }
            )
        # Open-Meteo
        return _FakeResp(_fake_weather_response())

    monkeypatch.setattr(httpx, "get", fake_get)


# ---------------------------------------------------------------------------
# weather_get
# ---------------------------------------------------------------------------
class TestWeatherGet:
    def test_get_with_location(self, patch_httpx):
        """已配置位置时返回当前天气 + mood + home_hint + music_tags。"""
        tools._runtime.location = {"city": "北京", "lat": 39.9042, "lon": 116.4074}
        data = _parse(tools.weather_get(fake=True))
        assert data["ok"] is True
        payload = data["data"]
        assert payload["current"]["temperature"] == 22.0
        assert payload["current"]["weather_code"] == 0
        assert payload["mood"]["mood"] == "sunny"
        assert "music_tags" in payload
        assert "home_hint" in payload
        assert payload["city"] == "北京"
        assert "cached_at" in payload

    def test_get_without_location_uses_ip(self, patch_httpx):
        """未配置位置时降级用 IP 定位。"""
        data = _parse(tools.weather_get(fake=True))
        assert data["ok"] is True
        assert data["data"]["city"] == "Beijing" or data["data"]["city"] is None

    def test_get_no_location_and_ip_fails(self, monkeypatch):
        """无位置 + IP 失败 → 返回 E_LOCATION_REQUIRED。"""
        import httpx

        def fake_get(url, **kw):
            return _FakeResp({"status": "fail", "message": "private"}, status=200)

        monkeypatch.setattr(httpx, "get", fake_get)
        data = _parse(tools.weather_get(fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_LOCATION_REQUIRED"

    def test_get_publishes_mood_changed_event(self, patch_httpx):
        """get 成功后发布 weather.mood_changed 事件。"""
        events: list[tuple[str, dict[str, Any]]] = []

        class _Bus:
            def publish(self, event_type, payload):
                events.append((event_type, payload))

        tools._runtime.event_publisher = _Bus()
        tools._runtime.location = {"city": "北京", "lat": 39.9042, "lon": 116.4074}
        tools.weather_get(fake=True)
        types = [e[0] for e in events]
        assert "weather.mood_changed" in types
        assert "weather.updated" in types

    def test_get_publishes_home_hint_event(self, patch_httpx, monkeypatch):
        """下雨时 get 发布 weather.home_hint 事件。"""
        import httpx

        rainy = _fake_weather_response(code=61)
        monkeypatch.setattr(httpx, "get", lambda url, **kw: _FakeResp(rainy))
        events: list[tuple[str, dict[str, Any]]] = []

        class _Bus:
            def publish(self, event_type, payload):
                events.append((event_type, payload))

        tools._runtime.event_publisher = _Bus()
        tools._runtime.location = {"city": "北京", "lat": 39.9042, "lon": 116.4074}
        tools.weather_get(fake=True)
        hint_events = [e for e in events if e[0] == "weather.home_hint"]
        assert len(hint_events) >= 1


# ---------------------------------------------------------------------------
# weather_forecast
# ---------------------------------------------------------------------------
class TestWeatherForecast:
    def test_forecast_returns_24h(self, patch_httpx):
        """forecast 返回 24 条小时预报。"""
        tools._runtime.location = {"city": "北京", "lat": 39.9042, "lon": 116.4074}
        data = _parse(tools.weather_forecast(fake=True))
        assert data["ok"] is True
        assert len(data["data"]["hourly"]) == 24

    def test_forecast_no_location(self, patch_httpx):
        """未配置位置时 forecast 降级用 IP。"""
        data = _parse(tools.weather_forecast(fake=True))
        assert data["ok"] is True


# ---------------------------------------------------------------------------
# weather_set_location / weather_get_location
# ---------------------------------------------------------------------------
class TestWeatherLocation:
    def test_set_location_persists(self, tmp_path, patch_httpx):
        """set_location 持久化城市配置到 config.json。"""
        data = _parse(tools.weather_set_location(city="北京", fake=True))
        assert data["ok"] is True
        assert data["data"]["city"] == "北京"
        # 配置文件已写入
        cfg_path = Path(tmp_path / "config.json")
        assert cfg_path.exists()
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg["city"] == "北京"
        assert cfg["lat"] == 39.9042
        assert cfg["lon"] == 116.4074
        # 运行时 location 也被更新
        assert tools._runtime.location["city"] == "北京"

    def test_set_location_unknown_city(self, monkeypatch):
        """未知城市 → E_CITY_NOT_FOUND。"""
        import httpx

        monkeypatch.setattr(httpx, "get", lambda url, **kw: _FakeResp({"results": []}))
        data = _parse(tools.weather_set_location(city="不存在的城市", fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_CITY_NOT_FOUND"

    def test_set_location_empty_city(self):
        """空字符串 → E_INVALID_ARG。"""
        data = _parse(tools.weather_set_location(city="", fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARG"

    def test_set_location_explicit_lat_lon(self, tmp_path):
        """直接传 lat/lon 时不走 geocoding。"""
        data = _parse(
            tools.weather_set_location(city="自定义", lat=30.0, lon=120.0, fake=True)
        )
        assert data["ok"] is True
        assert data["data"]["lat"] == 30.0
        assert data["data"]["lon"] == 120.0

    def test_get_location_when_configured(self, patch_httpx):
        """已配置 → 返回当前位置。"""
        tools._runtime.location = {"city": "北京", "lat": 39.9, "lon": 116.4}
        data = _parse(tools.weather_get_location(fake=True))
        assert data["ok"] is True
        assert data["data"]["city"] == "北京"

    def test_get_location_when_not_configured(self, tmp_path):
        """未配置 → ok:false + E_LOCATION_REQUIRED。"""
        data = _parse(tools.weather_get_location(fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_LOCATION_REQUIRED"

    def test_get_location_loads_from_config(self, tmp_path, patch_httpx):
        """启动后从 config.json 加载位置。"""
        cfg_path = Path(tmp_path / "config.json")
        cfg_path.write_text(
            json.dumps({"city": "上海", "lat": 31.2, "lon": 121.5}),
            encoding="utf-8",
        )
        # 重置 runtime 触发从 config 加载
        tools._reset_runtime()
        data = _parse(tools.weather_get_location(fake=True))
        assert data["ok"] is True
        assert data["data"]["city"] == "上海"
        assert data["data"]["lat"] == 31.2


# ---------------------------------------------------------------------------
# weather_get_mood
# ---------------------------------------------------------------------------
class TestWeatherGetMood:
    def test_get_mood_lightweight(self, patch_httpx):
        """get_mood 仅返回 mood 字段（轻量，供前端轮询）。"""
        tools._runtime.location = {"city": "北京", "lat": 39.9, "lon": 116.4}
        data = _parse(tools.weather_get_mood(fake=True))
        assert data["ok"] is True
        assert data["data"]["mood"] == "sunny"
        # 不应包含完整 weather 数据
        assert "hourly" not in data["data"]

    def test_get_mood_no_location(self, monkeypatch):
        """无位置 + IP 失败 → E_LOCATION_REQUIRED。"""
        import httpx

        monkeypatch.setattr(httpx, "get", lambda url, **kw: _FakeResp({"status": "fail", "message": "x"}))
        data = _parse(tools.weather_get_mood(fake=True))
        assert data["ok"] is False


# ---------------------------------------------------------------------------
# weather_refresh
# ---------------------------------------------------------------------------
class TestWeatherRefresh:
    def test_refresh_invalidates_and_refetches(self, patch_httpx):
        """refresh 强制刷新缓存。"""
        tools._runtime.location = {"city": "北京", "lat": 39.9, "lon": 116.4}
        # 先填充缓存
        tools.weather_get(fake=True)
        # 刷新
        data = _parse(tools.weather_refresh(fake=True))
        assert data["ok"] is True
        assert "refreshed_at" in data["data"]


# ---------------------------------------------------------------------------
# weather_search_city
# ---------------------------------------------------------------------------
class TestWeatherSearchCity:
    def test_search_returns_results(self, patch_httpx):
        """search 返回标准化城市列表。"""
        data = _parse(tools.weather_search_city(keyword="北京", fake=True))
        assert data["ok"] is True
        assert len(data["data"]["results"]) >= 1
        assert data["data"]["results"][0]["name"] == "北京"

    def test_search_empty_keyword(self):
        """空关键词 → E_INVALID_ARG。"""
        data = _parse(tools.weather_search_city(keyword="", fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARG"


# ---------------------------------------------------------------------------
# weather_status
# ---------------------------------------------------------------------------
class TestWeatherStatus:
    def test_status_reports_state(self, patch_httpx):
        """status 返回 cache/位置/最后更新时间。"""
        tools._runtime.location = {"city": "北京", "lat": 39.9, "lon": 116.4}
        tools.weather_get(fake=True)
        data = _parse(tools.weather_status(fake=True))
        assert data["ok"] is True
        assert "cache" in data["data"]
        assert "location" in data["data"]
        assert data["data"]["location"]["city"] == "北京"

    def test_status_no_location(self):
        """未配置位置 → status 仍返回 ok（location=null）。"""
        data = _parse(tools.weather_status(fake=True))
        assert data["ok"] is True
        assert data["data"]["location"] is None


# ---------------------------------------------------------------------------
# 工具元数据 + 注册
# ---------------------------------------------------------------------------
class TestToolsMetadata:
    def test_tools_count(self):
        """TOOLS 注册表包含 8 个工具。"""
        assert len(tools.TOOLS) == 8

    def test_tools_names_match_manifest(self):
        """工具名与任务规约 8 个一致。"""
        names = {m["name"] for m in tools.TOOLS}
        expected = {
            "weather_get",
            "weather_forecast",
            "weather_set_location",
            "weather_get_location",
            "weather_get_mood",
            "weather_refresh",
            "weather_search_city",
            "weather_status",
        }
        assert names == expected

    def test_each_tool_has_schema_and_handler(self):
        """每个工具元数据含 name/description/emoji/schema/handler_func。"""
        for meta in tools.TOOLS:
            assert meta["name"]
            assert meta["description"]
            assert meta["emoji"]
            assert "parameters" in meta["schema"]
            assert meta["schema"]["parameters"]["type"] == "object"
            assert callable(meta["handler_func"])

    def test_set_location_schema_has_city_required(self):
        """weather_set_location schema 声明 city 为 string 必填。"""
        meta = next(m for m in tools.TOOLS if m["name"] == "weather_set_location")
        props = meta["schema"]["parameters"]["properties"]
        assert props["city"]["type"] == "string"
        assert "city" in meta["schema"]["parameters"]["required"]

    def test_search_city_schema_has_keyword_required(self):
        """weather_search_city schema 声明 keyword 必填。"""
        meta = next(m for m in tools.TOOLS if m["name"] == "weather_search_city")
        assert "keyword" in meta["schema"]["parameters"]["required"]


class TestRegister:
    def test_register_registers_eight_tools(self):
        """register(ctx) 注册 8 个 weather_* 工具。"""

        class _Ctx:
            def __init__(self):
                self.tools = []
                self.event_bus = None

            def register_tool(self, **kwargs):
                self.tools.append(kwargs)

        ctx = _Ctx()
        tools.register(ctx)
        assert len(ctx.tools) == 8
        for t in ctx.tools:
            assert t["description"]
            assert t["emoji"]
            assert callable(t["handler_func"])

    def test_register_wires_event_bus(self):
        """register(ctx) 把 ctx.event_bus 接入运行时 event_publisher。"""

        class _Bus:
            def publish(self, *a, **kw):
                pass

        class _Ctx:
            def __init__(self):
                self.tools = []
                self.event_bus = _Bus()

            def register_tool(self, **kwargs):
                self.tools.append(kwargs)

        ctx = _Ctx()
        tools.register(ctx)
        assert tools._runtime.event_publisher is ctx.event_bus

    def test_make_handler_args_dict(self, patch_httpx):
        """_make_handler 包装后的 handler 接受 args dict 返回 JSON。"""
        tools._runtime.location = {"city": "北京", "lat": 39.9, "lon": 116.4}
        handler = tools._make_handler(tools.weather_status)
        result = handler({"fake": True})
        data = _parse(result)
        assert data["ok"] is True

    def test_make_handler_invalid_args_returns_error(self):
        """_make_handler 在参数错误时返回 ok:false 而非抛错。"""
        handler = tools._make_handler(tools.weather_set_location)
        result = handler({"city": ""})
        data = _parse(result)
        assert data["ok"] is False


# ---------------------------------------------------------------------------
# async EventBus 集成
# ---------------------------------------------------------------------------
class TestAsyncEventBusIntegration:
    def test_get_publishes_to_real_event_bus(self, patch_httpx):
        """get 接入真实 EventBus（async publish）时事件被分发。"""
        import asyncio

        from omni_sdk.event_bus import EventBus

        bus = EventBus()
        received: list[dict] = []

        async def _collect(payload):
            received.append(payload)

        bus.subscribe("weather.mood_changed", _collect)
        bus.subscribe("weather.updated", _collect)

        tools._runtime.event_publisher = bus
        tools._runtime.location = {"city": "北京", "lat": 39.9, "lon": 116.4}

        async def _run():
            tools.weather_get(fake=True)
            await asyncio.sleep(0.01)

        asyncio.run(_run())
        assert len(received) >= 2

    def test_publish_with_none_bus_is_noop(self, patch_httpx):
        """event_publisher 为 None 时不抛错。"""
        tools._runtime.event_publisher = None
        tools._runtime.location = {"city": "北京", "lat": 39.9, "lon": 116.4}
        result = tools.weather_get(fake=True)
        data = _parse(result)
        assert data["ok"] is True

    def test_publish_with_bad_bus_swallowed(self, patch_httpx):
        """bus.publish 抛异常时被吞掉，不影响工具返回。"""

        class _BadBus:
            def publish(self, *a, **kw):
                raise RuntimeError("bus broken")

        tools._runtime.event_publisher = _BadBus()
        tools._runtime.location = {"city": "北京", "lat": 39.9, "lon": 116.4}
        result = tools.weather_get(fake=True)
        data = _parse(result)
        assert data["ok"] is True
