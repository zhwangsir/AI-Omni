"""omni_home 迁移到 OmniPlugin 的兼容适配层测试（M15.10）。

验证：
- ``HomePlugin`` 继承 ``RegisterCompatPlugin``，元数据 name="omni_home"
- ``HomePlugin.on_load(ctx)`` 调用现有 ``register(ctx)``，工具落入 ``ctx.tool_registry``
- 旧式 ``register(ctx)`` 入口仍可直接调用（向后兼容，不破坏既有 230 个测试）
- ``manifest.json`` 存在且经 ``parse_manifest`` 合法
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from omni_sdk.compat import RegisterCompatPlugin
from omni_sdk.context import PluginContext
from omni_sdk.event_bus import EventBus
from omni_sdk.manifest import parse_manifest, validate_manifest
from omni_sdk.permissions import PermissionChecker
from omni_sdk.plugin import OmniPlugin
from omni_sdk.registry import ToolRegistry

from omni_home import HomePlugin, register


HOME_DIR = Path(__file__).resolve().parent.parent.parent / "omni_home"


def _make_plugin_context() -> PluginContext:
    """构造一份完整注入的 PluginContext，用于 on_load。"""
    return PluginContext(
        config={},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        plugin_name="omni_home",
    )


class _LegacyCtx:
    """旧式 register(ctx) 契约的 fake ctx，收集 register_tool 调用。"""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []
        self.event_bus: Any = None

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)


class TestHomePluginMetadata:
    def test_home_plugin_is_omni_plugin_subclass(self) -> None:
        """HomePlugin 是 OmniPlugin 子类。"""
        assert issubclass(HomePlugin, OmniPlugin)
        assert issubclass(HomePlugin, RegisterCompatPlugin)

    def test_home_plugin_metadata(self) -> None:
        """HomePlugin 元数据 name="omni_home"。"""
        plugin = HomePlugin()
        assert plugin.name == "omni_home"
        assert plugin.version
        assert plugin.description
        assert plugin.emoji

    def test_home_plugin_wraps_register(self) -> None:
        """HomePlugin 实例持有 register 函数引用。"""
        plugin = HomePlugin()
        assert hasattr(plugin, "_register_func")
        assert plugin._register_func is register


class TestHomePluginOnLoad:
    def test_home_plugin_on_load_calls_register(self) -> None:
        """on_load(ctx) 调用 register(ctx_adapter)，工具注册到 PluginContext.tool_registry。"""
        plugin = HomePlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        # omni_home 注册 6 个 home_* 工具
        tools = ctx.tool_registry.list_tools()
        assert "home_status" in tools
        assert "home_control" in tools
        assert "home_list" in tools
        assert len(tools) == 6

    def test_home_plugin_on_load_tool_has_schema(self) -> None:
        """on_load 后 tool_registry 中的工具携带 schema 与 handler_func。"""
        plugin = HomePlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool = ctx.tool_registry.get_tool("home_status")
        assert tool is not None
        assert tool.schema
        assert callable(tool.handler_func)

    def test_home_plugin_on_load_wires_event_bus(self) -> None:
        """on_load 后 event_bus 适配器接入运行时 event_publisher。"""
        plugin = HomePlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        from omni_home import tools
        assert tools._runtime.event_publisher is not None
        assert callable(getattr(tools._runtime.event_publisher, "publish", None))


class TestHomePluginBackwardCompat:
    def test_register_legacy_ctx_still_works(self) -> None:
        """旧式 register(ctx) 入口仍可直接调用。"""
        ctx = _LegacyCtx()
        register(ctx)
        assert len(ctx.tools) == 6
        names = [t["name"] for t in ctx.tools]
        assert "home_status" in names
        for tool in ctx.tools:
            assert tool["toolset"] == "omni_home"
            assert tool["description"]
            assert tool["emoji"]
            assert callable(tool["handler"])

    def test_home_plugin_on_unload_is_idempotent(self) -> None:
        """on_unload 默认空实现可多次调用（幂等）。"""
        plugin = HomePlugin()
        asyncio.run(plugin.on_unload())
        asyncio.run(plugin.on_unload())


class TestHomeManifest:
    def test_manifest_json_exists(self) -> None:
        """omni_home/manifest.json 文件存在。"""
        assert (HOME_DIR / "manifest.json").is_file()

    def test_manifest_json_parses(self) -> None:
        """manifest.json 经 parse_manifest 解析合法。"""
        data = json.loads((HOME_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert manifest.name == "omni_home"
        assert manifest.version
        errors = validate_manifest(manifest)
        assert "home_status" in manifest.tools

    def test_manifest_tools_match_registered(self) -> None:
        """manifest.tools 与 register(ctx) 实际注册的工具名一致。"""
        data = json.loads((HOME_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        ctx = _LegacyCtx()
        register(ctx)
        declared = set(manifest.tools)
        registered = {t["name"] for t in ctx.tools}
        assert declared == registered
