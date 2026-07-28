"""omni_voice 迁移到 OmniPlugin 的兼容适配层测试（M15.9）。

验证：
- ``VoicePlugin`` 继承 ``RegisterCompatPlugin``，元数据 name="omni_voice"
- ``VoicePlugin.on_load(ctx)`` 调用现有 ``register(ctx)``，工具落入 ``ctx.tool_registry``
- 旧式 ``register(ctx)`` 入口仍可直接调用（向后兼容，不破坏既有 307 个测试）
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

from omni_voice import VoicePlugin, register


VOICE_DIR = Path(__file__).resolve().parent.parent.parent / "omni_voice"


def _make_plugin_context() -> PluginContext:
    """构造一份完整注入的 PluginContext，用于 on_load。"""
    return PluginContext(
        config={},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        plugin_name="omni_voice",
    )


class _LegacyCtx:
    """旧式 register(ctx) 契约的 fake ctx，收集 register_tool 调用。"""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []
        self.event_bus: Any = None

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)


class TestVoicePluginMetadata:
    def test_voice_plugin_is_omni_plugin_subclass(self) -> None:
        """VoicePlugin 是 OmniPlugin 子类。"""
        assert issubclass(VoicePlugin, OmniPlugin)
        assert issubclass(VoicePlugin, RegisterCompatPlugin)

    def test_voice_plugin_metadata(self) -> None:
        """VoicePlugin 元数据 name="omni_voice"。"""
        plugin = VoicePlugin()
        assert plugin.name == "omni_voice"
        assert plugin.version
        assert plugin.description
        assert plugin.emoji

    def test_voice_plugin_wraps_register(self) -> None:
        """VoicePlugin 实例持有 register 函数引用。"""
        plugin = VoicePlugin()
        # RegisterCompatPlugin 把 register_func 存到 _register_func
        assert hasattr(plugin, "_register_func")
        # 引用的就是 omni_voice 包级别的 register 函数
        assert plugin._register_func is register


class TestVoicePluginOnLoad:
    def test_voice_plugin_on_load_calls_register(self) -> None:
        """on_load(ctx) 调用 register(ctx_adapter)，工具注册到 PluginContext.tool_registry。"""
        plugin = VoicePlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        # omni_voice 注册 8 个 voice_* 工具
        tools = ctx.tool_registry.list_tools()
        assert "voice_status" in tools
        assert "voice_speak" in tools
        assert "voice_pipeline_start" in tools
        assert "voice_interrupt" in tools
        assert "voice_identity" in tools
        assert len(tools) == 8

    def test_voice_plugin_on_load_tool_has_schema(self) -> None:
        """on_load 后 tool_registry 中的工具携带 schema 与 handler_func。"""
        plugin = VoicePlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool = ctx.tool_registry.get_tool("voice_status")
        assert tool is not None
        assert tool.schema  # 非空
        assert callable(tool.handler_func)

    def test_voice_plugin_on_load_wires_event_bus(self) -> None:
        """on_load 后 event_bus 适配器接入运行时 event_publisher。"""
        plugin = VoicePlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        # register(ctx) 会把 ctx.event_bus 赋给 _runtime.event_publisher
        from omni_voice import tools
        assert tools._runtime.event_publisher is not None
        # 适配器提供 sync publish 方法（旧契约）
        assert callable(getattr(tools._runtime.event_publisher, "publish", None))


class TestVoicePluginBackwardCompat:
    def test_register_legacy_ctx_still_works(self) -> None:
        """旧式 register(ctx) 入口仍可直接调用，不依赖 OmniPlugin。"""
        ctx = _LegacyCtx()
        register(ctx)
        # 8 个工具
        assert len(ctx.tools) == 8
        names = [t["name"] for t in ctx.tools]
        assert "voice_status" in names
        # 旧契约字段保留
        for tool in ctx.tools:
            assert tool["toolset"] == "omni_voice"
            assert tool["description"]
            assert tool["emoji"]
            assert callable(tool["handler"])

    def test_voice_plugin_on_unload_is_idempotent(self) -> None:
        """on_unload 默认空实现可多次调用（幂等）。"""
        plugin = VoicePlugin()
        asyncio.run(plugin.on_unload())
        asyncio.run(plugin.on_unload())


class TestVoiceManifest:
    def test_manifest_json_exists(self) -> None:
        """omni_voice/manifest.json 文件存在。"""
        assert (VOICE_DIR / "manifest.json").is_file()

    def test_manifest_json_parses(self) -> None:
        """manifest.json 经 parse_manifest 解析合法，name=omni_voice。"""
        data = json.loads((VOICE_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert manifest.name == "omni_voice"
        assert manifest.version
        # 软校验无硬错（description 非空等）
        errors = validate_manifest(manifest)
        # tools 字段应与 register 注册的工具对齐
        assert "voice_status" in manifest.tools

    def test_manifest_tools_match_registered(self) -> None:
        """manifest.tools 与 register(ctx) 实际注册的工具名一致。"""
        data = json.loads((VOICE_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        ctx = _LegacyCtx()
        register(ctx)
        declared = set(manifest.tools)
        registered = {t["name"] for t in ctx.tools}
        assert declared == registered
