"""omni_fullscreen_detect 插件生命周期与契约测试（M16-P1）。

验证：
- ``FullscreenDetectPlugin`` 直接继承 ``OmniPlugin``
- 元数据 name="omni_fullscreen_detect" 齐备
- ``on_load(ctx)`` 注册 1 个 system_detect_fullscreen_app 工具
- ``manifest.json`` 合法
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

from omni_fullscreen_detect import FullscreenDetectPlugin
from omni_fullscreen_detect.backends import FakeFullscreenBackend


FULLSCREEN_DIR = Path(__file__).resolve().parent.parent


def _make_plugin_context() -> PluginContext:
    """构造一份完整注入的 PluginContext。"""
    return PluginContext(
        config={},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        plugin_name="omni_fullscreen_detect",
    )


class TestFullscreenDetectPluginMetadata:
    def test_plugin_is_omni_plugin_subclass(self) -> None:
        """FullscreenDetectPlugin 直接继承 OmniPlugin。"""
        assert issubclass(FullscreenDetectPlugin, OmniPlugin)
        from omni_sdk.compat import LegacyPluginAdapter

        assert not issubclass(FullscreenDetectPlugin, LegacyPluginAdapter)

    def test_plugin_metadata(self) -> None:
        """元数据齐备。"""
        plugin = FullscreenDetectPlugin()
        assert plugin.name == "omni_fullscreen_detect"
        assert plugin.version
        assert plugin.description
        assert plugin.emoji

    def test_plugin_default_backend_is_none(self) -> None:
        """默认不实例化真实后端。"""
        plugin = FullscreenDetectPlugin()
        assert plugin._backend is None


class TestFullscreenDetectPluginOnLoad:
    def test_on_load_registers_one_tool(self) -> None:
        """on_load 注册 1 个 system_detect_fullscreen_app 工具。"""
        plugin = FullscreenDetectPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tools = ctx.tool_registry.list_tools()
        assert "system_detect_fullscreen_app" in tools
        assert len(tools) == 1

    def test_on_load_tool_has_schema_and_handler(self) -> None:
        """注册的工具携带 schema 与 handler_func。"""
        plugin = FullscreenDetectPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool = ctx.tool_registry.get_tool("system_detect_fullscreen_app")
        assert tool is not None
        assert tool.schema
        assert callable(tool.handler_func)
        assert tool.description
        assert tool.emoji

    def test_on_load_injects_fake_backend(self) -> None:
        """config 携带 fake 后端时 on_load 注入。"""
        fake = FakeFullscreenBackend()
        plugin = FullscreenDetectPlugin()
        ctx = PluginContext(
            config={"backend": fake},
            event_bus=EventBus(),
            tool_registry=ToolRegistry(),
            permission_checker=PermissionChecker(allowed=["tools.register"]),
            plugin_name="omni_fullscreen_detect",
        )
        asyncio.run(plugin.on_load(ctx))
        assert plugin._backend is fake

    def test_on_unload_is_idempotent(self) -> None:
        """on_unload 幂等。"""
        plugin = FullscreenDetectPlugin()
        asyncio.run(plugin.on_unload())
        asyncio.run(plugin.on_unload())


class TestFullscreenDetectManifest:
    def test_manifest_json_exists(self) -> None:
        """manifest.json 存在。"""
        assert (FULLSCREEN_DIR / "manifest.json").is_file()

    def test_manifest_json_parses(self) -> None:
        """manifest.json 解析合法。"""
        data = json.loads(
            (FULLSCREEN_DIR / "manifest.json").read_text(encoding="utf-8")
        )
        manifest = parse_manifest(data)
        assert manifest.name == "omni_fullscreen_detect"
        assert manifest.version
        errors = validate_manifest(manifest)
        assert errors == []

    def test_manifest_tools_match_registered(self) -> None:
        """manifest.tools 与实际注册工具一致。"""
        data = json.loads(
            (FULLSCREEN_DIR / "manifest.json").read_text(encoding="utf-8")
        )
        manifest = parse_manifest(data)
        plugin = FullscreenDetectPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        declared = set(manifest.tools)
        registered = set(ctx.tool_registry.list_tools())
        assert declared == registered

    def test_manifest_declares_fullscreen_event(self) -> None:
        """manifest 声明 system.fullscreen_changed 事件。"""
        data = json.loads(
            (FULLSCREEN_DIR / "manifest.json").read_text(encoding="utf-8")
        )
        manifest = parse_manifest(data)
        assert "system.fullscreen_changed" in manifest.events.publishes
