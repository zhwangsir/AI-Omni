"""omni_process 插件生命周期与 OmniPlugin 契约测试（M16-P1）。

验证：
- ``ProcessPlugin`` 直接继承 ``OmniPlugin``（非 LegacyPluginAdapter）
- 元数据 name="omni_process" / version / description / emoji 齐备
- ``on_load(ctx)`` 把 3 个 system_* 工具注册到 ``ctx.tool_registry``
- ``on_unload`` 可多次调用（幂等）
- ``manifest.json`` 经 parse_manifest 合法且与注册工具一致
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

from omni_process import ProcessPlugin
from omni_process.backends import FakeProcessBackend


PROCESS_DIR = Path(__file__).resolve().parent.parent


def _make_plugin_context() -> PluginContext:
    """构造一份完整注入的 PluginContext，用于 on_load。"""
    return PluginContext(
        config={},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        plugin_name="omni_process",
    )


class TestProcessPluginMetadata:
    def test_process_plugin_is_omni_plugin_subclass(self) -> None:
        """ProcessPlugin 直接继承 OmniPlugin（非 LegacyPluginAdapter）。"""
        assert issubclass(ProcessPlugin, OmniPlugin)
        # 确认不是 LegacyPluginAdapter 子类（M16 新插件走原生 SDK）
        from omni_sdk.compat import LegacyPluginAdapter

        assert not issubclass(ProcessPlugin, LegacyPluginAdapter)

    def test_process_plugin_metadata(self) -> None:
        """ProcessPlugin 元数据齐备。"""
        plugin = ProcessPlugin()
        assert plugin.name == "omni_process"
        assert plugin.version
        assert plugin.description
        assert plugin.emoji

    def test_process_plugin_default_backend_is_none(self) -> None:
        """默认构造不实例化真实后端（惰性初始化）。"""
        plugin = ProcessPlugin()
        assert plugin._backend is None


class TestProcessPluginOnLoad:
    def test_on_load_registers_three_tools(self) -> None:
        """on_load(ctx) 注册 3 个 system_* 工具。"""
        plugin = ProcessPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tools = ctx.tool_registry.list_tools()
        assert "system_list_processes" in tools
        assert "system_kill_process" in tools
        assert "system_start_process" in tools
        assert len(tools) == 3

    def test_on_load_tool_has_schema_and_handler(self) -> None:
        """注册的工具携带 schema 与 handler_func。"""
        plugin = ProcessPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool = ctx.tool_registry.get_tool("system_list_processes")
        assert tool is not None
        assert tool.schema
        assert callable(tool.handler_func)
        assert tool.description
        assert tool.emoji

    def test_on_load_injects_fake_backend(self) -> None:
        """config 携带 fake 后端时 on_load 注入到插件。"""
        fake = FakeProcessBackend()
        plugin = ProcessPlugin()
        ctx = PluginContext(
            config={"backend": fake},
            event_bus=EventBus(),
            tool_registry=ToolRegistry(),
            permission_checker=PermissionChecker(allowed=["tools.register"]),
            plugin_name="omni_process",
        )
        asyncio.run(plugin.on_load(ctx))
        assert plugin._backend is fake

    def test_on_unload_is_idempotent(self) -> None:
        """on_unload 默认空实现可多次调用。"""
        plugin = ProcessPlugin()
        asyncio.run(plugin.on_unload())
        asyncio.run(plugin.on_unload())


class TestProcessManifest:
    def test_manifest_json_exists(self) -> None:
        """manifest.json 文件存在。"""
        assert (PROCESS_DIR / "manifest.json").is_file()

    def test_manifest_json_parses(self) -> None:
        """manifest.json 经 parse_manifest 解析合法。"""
        data = json.loads((PROCESS_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert manifest.name == "omni_process"
        assert manifest.version
        # 软校验不应有错误
        errors = validate_manifest(manifest)
        assert errors == []

    def test_manifest_tools_match_registered(self) -> None:
        """manifest.tools 与 on_load 实际注册的工具一致。"""
        data = json.loads((PROCESS_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        plugin = ProcessPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        declared = set(manifest.tools)
        registered = set(ctx.tool_registry.list_tools())
        assert declared == registered

    def test_manifest_declares_process_events(self) -> None:
        """manifest 声明 process_killed / process_started 事件。"""
        data = json.loads((PROCESS_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert "system.process_killed" in manifest.events.publishes
        assert "system.process_started" in manifest.events.publishes
