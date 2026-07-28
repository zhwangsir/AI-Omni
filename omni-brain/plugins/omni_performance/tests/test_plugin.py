"""omni_performance 插件生命周期与 OmniPlugin 契约测试（M16-P1）。

验证：
- ``PerformancePlugin`` 直接继承 ``OmniPlugin``
- 元数据 name="omni_performance" 齐备
- ``on_load(ctx)`` 注册 3 个 system_* 性能监控工具
- ``manifest.json`` 经 parse_manifest 合法
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from omni_sdk.context import PluginContext
from omni_sdk.event_bus import EventBus
from omni_sdk.manifest import parse_manifest, validate_manifest
from omni_sdk.permissions import PermissionChecker
from omni_sdk.plugin import OmniPlugin
from omni_sdk.registry import ToolRegistry

from omni_performance import PerformancePlugin
from omni_performance.backends import FakePerformanceBackend


PERF_DIR = Path(__file__).resolve().parent.parent


def _make_plugin_context() -> PluginContext:
    """构造一份完整注入的 PluginContext。"""
    return PluginContext(
        config={},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        plugin_name="omni_performance",
    )


class TestPerformancePluginMetadata:
    def test_performance_plugin_is_omni_plugin_subclass(self) -> None:
        """PerformancePlugin 直接继承 OmniPlugin（非 LegacyPluginAdapter）。"""
        assert issubclass(PerformancePlugin, OmniPlugin)
        from omni_sdk.compat import LegacyPluginAdapter

        assert not issubclass(PerformancePlugin, LegacyPluginAdapter)

    def test_performance_plugin_metadata(self) -> None:
        """元数据齐备。"""
        plugin = PerformancePlugin()
        assert plugin.name == "omni_performance"
        assert plugin.version
        assert plugin.description
        assert plugin.emoji

    def test_performance_plugin_default_backend_is_none(self) -> None:
        """默认不实例化真实后端。"""
        plugin = PerformancePlugin()
        assert plugin._backend is None


class TestPerformancePluginOnLoad:
    def test_on_load_registers_three_tools(self) -> None:
        """on_load 注册 3 个 system_* 工具。"""
        plugin = PerformancePlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tools = ctx.tool_registry.list_tools()
        assert "system_get_cpu_usage" in tools
        assert "system_get_memory_usage" in tools
        assert "system_get_disk_usage" in tools
        assert len(tools) == 3

    def test_on_load_tool_has_schema_and_handler(self) -> None:
        """注册的工具携带 schema 与 handler_func。"""
        plugin = PerformancePlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool = ctx.tool_registry.get_tool("system_get_cpu_usage")
        assert tool is not None
        assert tool.schema
        assert callable(tool.handler_func)
        assert tool.description
        assert tool.emoji

    def test_on_load_injects_fake_backend(self) -> None:
        """config 携带 fake 后端时 on_load 注入。"""
        fake = FakePerformanceBackend()
        plugin = PerformancePlugin()
        ctx = PluginContext(
            config={"backend": fake},
            event_bus=EventBus(),
            tool_registry=ToolRegistry(),
            permission_checker=PermissionChecker(allowed=["tools.register"]),
            plugin_name="omni_performance",
        )
        asyncio.run(plugin.on_load(ctx))
        assert plugin._backend is fake

    def test_on_unload_is_idempotent(self) -> None:
        """on_unload 幂等。"""
        plugin = PerformancePlugin()
        asyncio.run(plugin.on_unload())
        asyncio.run(plugin.on_unload())


class TestPerformanceManifest:
    def test_manifest_json_exists(self) -> None:
        """manifest.json 存在。"""
        assert (PERF_DIR / "manifest.json").is_file()

    def test_manifest_json_parses(self) -> None:
        """manifest.json 解析合法。"""
        data = json.loads((PERF_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert manifest.name == "omni_performance"
        assert manifest.version
        errors = validate_manifest(manifest)
        assert errors == []

    def test_manifest_tools_match_registered(self) -> None:
        """manifest.tools 与实际注册工具一致。"""
        data = json.loads((PERF_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        plugin = PerformancePlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        declared = set(manifest.tools)
        registered = set(ctx.tool_registry.list_tools())
        assert declared == registered

    def test_manifest_no_events_declared(self) -> None:
        """性能监控插件不发布事件（仅查询，无副作用）。"""
        data = json.loads((PERF_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert manifest.events.publishes == []
        assert manifest.events.subscribes == []
