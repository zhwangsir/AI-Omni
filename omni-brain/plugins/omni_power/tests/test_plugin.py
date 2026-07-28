"""omni_power PowerPlugin 生命周期测试 + manifest 校验。

验证：
- ``PowerPlugin`` 继承 ``OmniPlugin``，元数据 name="omni_power"
- ``PowerPlugin.on_load(ctx)`` 把 4 个 system_* 工具注册到 ``ctx.tool_registry``
- ``on_load`` 后事件总线接入运行时 event_publisher
- ``on_unload`` 清理引用且幂等
- ``manifest.json`` 存在且经 ``parse_manifest`` 合法
- manifest.tools 与实际注册工具名一致
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

from omni_power import PowerPlugin, register


POWER_DIR = Path(__file__).resolve().parent.parent


def _make_plugin_context() -> PluginContext:
    """构造一份完整注入的 PluginContext，用于 on_load。"""
    return PluginContext(
        config={},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        plugin_name="omni_power",
    )


class _LegacyCtx:
    """旧式 register(ctx) 契约的 fake ctx，收集 register_tool 调用。"""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []
        self.event_bus: Any = None

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)


class TestPowerPluginMetadata:
    def test_power_plugin_is_omni_plugin_subclass(self) -> None:
        """PowerPlugin 是 OmniPlugin 子类。"""
        assert issubclass(PowerPlugin, OmniPlugin)

    def test_power_plugin_metadata(self) -> None:
        """PowerPlugin 元数据 name="omni_power"。"""
        plugin = PowerPlugin()
        assert plugin.name == "omni_power"
        assert plugin.version
        assert plugin.description
        assert plugin.emoji

    def test_power_plugin_direct_subclass_not_compat(self) -> None:
        """PowerPlugin 直接继承 OmniPlugin，不经过 RegisterCompatPlugin。"""
        from omni_sdk.compat import LegacyPluginAdapter

        assert not issubclass(PowerPlugin, LegacyPluginAdapter)


class TestPowerPluginOnLoad:
    def test_on_load_calls_register(self) -> None:
        """on_load(ctx) 调用 register(ctx)，工具注册到 PluginContext.tool_registry。"""
        plugin = PowerPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tools = ctx.tool_registry.list_tools()
        assert "system_lock_screen" in tools
        assert "system_sleep" in tools
        assert "system_shutdown" in tools
        assert "system_restart" in tools
        assert len(tools) == 4

    def test_on_load_tool_has_schema(self) -> None:
        """on_load 后 tool_registry 中的工具携带 schema 与 handler_func。"""
        plugin = PowerPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool = ctx.tool_registry.get_tool("system_lock_screen")
        assert tool is not None
        assert tool.schema
        assert callable(tool.handler_func)

    def test_on_load_tool_handler_returns_json(self) -> None:
        """on_load 后调用 handler 返回合法 JSON 字符串。"""
        plugin = PowerPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool = ctx.tool_registry.get_tool("system_lock_screen")
        assert tool is not None
        result = tool.handler_func({"fake": True})
        data = json.loads(result)
        assert data["ok"] is True

    def test_on_load_wires_event_bus(self) -> None:
        """on_load 后 event_bus 接入运行时 event_publisher。"""
        plugin = PowerPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        from omni_power import tools

        assert tools._runtime.event_publisher is ctx.event_bus

    def test_on_unload_clears_event_publisher(self) -> None:
        """on_unload 清理运行时 event_publisher 引用。"""
        plugin = PowerPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        from omni_power import tools

        assert tools._runtime.event_publisher is not None
        asyncio.run(plugin.on_unload())
        assert tools._runtime.event_publisher is None

    def test_on_unload_is_idempotent(self) -> None:
        """on_unload 可多次调用（幂等）。"""
        plugin = PowerPlugin()
        asyncio.run(plugin.on_unload())
        asyncio.run(plugin.on_unload())


class TestPowerPluginBackwardCompat:
    def test_register_legacy_ctx_still_works(self) -> None:
        """旧式 register(ctx) 入口仍可直接调用（鸭子类型 ctx）。"""
        ctx = _LegacyCtx()
        register(ctx)
        assert len(ctx.tools) == 4
        names = [t["name"] for t in ctx.tools]
        assert "system_lock_screen" in names
        for tool in ctx.tools:
            assert tool["description"]
            assert tool["emoji"]
            assert callable(tool["handler_func"])

    def test_register_legacy_ctx_handler_returns_json(self) -> None:
        """旧式 ctx 收到的 handler 调用返回 JSON 字符串。"""
        ctx = _LegacyCtx()
        register(ctx)
        tool = next(t for t in ctx.tools if t["name"] == "system_lock_screen")
        result = tool["handler_func"]({"fake": True})
        data = json.loads(result)
        assert data["ok"] is True


class TestPowerManifest:
    def test_manifest_json_exists(self) -> None:
        """omni_power/manifest.json 文件存在。"""
        assert (POWER_DIR / "manifest.json").is_file()

    def test_manifest_json_parses(self) -> None:
        """manifest.json 经 parse_manifest 解析合法。"""
        data = json.loads((POWER_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert manifest.name == "omni_power"
        assert manifest.version
        assert manifest.description
        errors = validate_manifest(manifest)
        assert all("tools.register" not in e for e in errors)

    def test_manifest_tools_match_registered(self) -> None:
        """manifest.tools 与 register(ctx) 实际注册的工具名一致。"""
        data = json.loads((POWER_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        ctx = _LegacyCtx()
        register(ctx)
        declared = set(manifest.tools)
        registered = {t["name"] for t in ctx.tools}
        assert declared == registered

    def test_manifest_declares_power_action_event(self) -> None:
        """manifest.events.publishes 声明 system.power_action。"""
        data = json.loads((POWER_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert "system.power_action" in manifest.events.publishes

    def test_manifest_macos_only(self) -> None:
        """manifest.platforms 仅声明 macos。"""
        data = json.loads((POWER_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert manifest.platforms == ["macos"]
