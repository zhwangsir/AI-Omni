"""omni_weather WeatherPlugin 生命周期测试 + manifest 校验。

验证：
- ``WeatherPlugin`` 继承 ``OmniPlugin``，元数据 name="omni_weather"
- ``on_load(ctx)`` 把 8 个 weather_* 工具注册到 ``ctx.tool_registry``
- ``on_load`` 后事件总线接入运行时 event_publisher
- ``on_unload`` 清缓存且幂等
- ``manifest.json`` 合法且 tools 与实际注册一致
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from omni_sdk.context import PluginContext
from omni_sdk.event_bus import EventBus
from omni_sdk.manifest import parse_manifest, validate_manifest
from omni_sdk.permissions import PermissionChecker
from omni_sdk.plugin import OmniPlugin
from omni_sdk.registry import ToolRegistry

from omni_weather import WeatherPlugin, register


WEATHER_DIR = Path(__file__).resolve().parent.parent


def _make_plugin_context() -> PluginContext:
    """构造完整注入的 PluginContext。"""
    return PluginContext(
        config={},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(
            allowed=["network", "fs.read:~/.ai-omni/weather", "fs.write:~/.ai-omni/weather", "tools.register"]
        ),
        plugin_name="omni_weather",
    )


class _LegacyCtx:
    """旧式 register(ctx) 契约的 fake ctx，收集 register_tool 调用。"""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []
        self.event_bus: Any = None

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)


class TestWeatherPluginMetadata:
    def test_is_omni_plugin_subclass(self) -> None:
        assert issubclass(WeatherPlugin, OmniPlugin)

    def test_metadata(self) -> None:
        plugin = WeatherPlugin()
        assert plugin.name == "omni_weather"
        assert plugin.version == "0.1.0"
        assert plugin.description
        assert plugin.emoji

    def test_not_legacy_adapter(self) -> None:
        """直接继承 OmniPlugin，不经 LegacyPluginAdapter。"""
        from omni_sdk.compat import LegacyPluginAdapter

        assert not issubclass(WeatherPlugin, LegacyPluginAdapter)


class TestWeatherPluginOnLoad:
    def test_on_load_registers_eight_tools(self) -> None:
        plugin = WeatherPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tools = ctx.tool_registry.list_tools()
        assert "weather_get" in tools
        assert "weather_forecast" in tools
        assert "weather_set_location" in tools
        assert "weather_get_location" in tools
        assert "weather_get_mood" in tools
        assert "weather_refresh" in tools
        assert "weather_search_city" in tools
        assert "weather_status" in tools
        assert len(tools) == 8

    def test_on_load_tool_has_schema(self) -> None:
        plugin = WeatherPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool = ctx.tool_registry.get_tool("weather_get")
        assert tool is not None
        assert tool.schema
        assert callable(tool.handler_func)

    def test_on_load_wires_event_bus(self) -> None:
        plugin = WeatherPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        from omni_weather import tools as t

        assert t._runtime.event_publisher is ctx.event_bus

    def test_on_unload_clears_cache(self) -> None:
        plugin = WeatherPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        from omni_weather import tools as t

        # 预填充 cache
        t._runtime.cache.invalidate_all()
        asyncio.run(plugin.on_unload())
        # cache 应被清空
        assert t._runtime.cache.status()["entries"] == 0

    def test_on_unload_is_idempotent(self) -> None:
        plugin = WeatherPlugin()
        asyncio.run(plugin.on_unload())
        asyncio.run(plugin.on_unload())

    def test_on_event_default_noop(self) -> None:
        """on_event 默认空实现，不抛错。"""
        plugin = WeatherPlugin()
        asyncio.run(plugin.on_event("any.event", {"foo": "bar"}))


class TestWeatherPluginBackwardCompat:
    def test_register_legacy_ctx(self) -> None:
        ctx = _LegacyCtx()
        register(ctx)
        assert len(ctx.tools) == 8
        names = {t["name"] for t in ctx.tools}
        assert "weather_get" in names
        for tool in ctx.tools:
            assert tool["description"]
            assert tool["emoji"]
            assert callable(tool["handler_func"])


class TestWeatherManifest:
    def test_manifest_exists(self) -> None:
        assert (WEATHER_DIR / "manifest.json").is_file()

    def test_manifest_parses(self) -> None:
        data = json.loads((WEATHER_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert manifest.name == "omni_weather"
        assert manifest.version == "0.1.0"
        assert manifest.description
        errors = validate_manifest(manifest)
        # 工具名 snake_case、事件点分小写、权限前缀已知
        assert errors == [], f"manifest 软错误: {errors}"

    def test_manifest_tools_match_registered(self) -> None:
        data = json.loads((WEATHER_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        ctx = _LegacyCtx()
        register(ctx)
        declared = set(manifest.tools)
        registered = {t["name"] for t in ctx.tools}
        assert declared == registered

    def test_manifest_declares_events(self) -> None:
        data = json.loads((WEATHER_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert "weather.mood_changed" in manifest.events.publishes
        assert "weather.home_hint" in manifest.events.publishes
        assert "weather.updated" in manifest.events.publishes

    def test_manifest_platforms(self) -> None:
        data = json.loads((WEATHER_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert "macos" in manifest.platforms
        assert "linux" in manifest.platforms

    def test_manifest_permissions(self) -> None:
        data = json.loads((WEATHER_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert "network" in manifest.permissions
        assert "tools.register" in manifest.permissions
        # fs.read / fs.write 带路径参数
        assert any(p.startswith("fs.read") for p in manifest.permissions)
        assert any(p.startswith("fs.write") for p in manifest.permissions)
