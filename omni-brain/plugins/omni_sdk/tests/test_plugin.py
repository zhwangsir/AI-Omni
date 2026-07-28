"""OmniPlugin 基类单元测试：抽象性/子类约束/元数据默认值/生命周期顺序/事件钩子。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from omni_sdk.context import PluginContext
from omni_sdk.event_bus import EventBus
from omni_sdk.permissions import PermissionChecker
from omni_sdk.plugin import OmniPlugin
from omni_sdk.registry import ToolRegistry


def _make_ctx() -> PluginContext:
    return PluginContext(
        config={},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        plugin_name="omni_test",
    )


def test_omni_plugin_is_abstract() -> None:
    """OmniPlugin 是抽象类，不能直接实例化。"""
    with pytest.raises(TypeError):
        OmniPlugin()  # type: ignore[abstract]


def test_subclass_must_implement_on_load() -> None:
    """子类未实现 on_load 不能实例化。"""

    class _Bad(OmniPlugin):
        name = "omni_bad"

    with pytest.raises(TypeError):
        _Bad()  # type: ignore[abstract]


def test_subclass_with_on_load_can_instantiate() -> None:
    """子类实现 on_load 后可实例化。"""

    class _Good(OmniPlugin):
        name = "omni_good"

        async def on_load(self, ctx: PluginContext) -> None:
            return None

    p = _Good()
    assert p.name == "omni_good"


def test_metadata_defaults() -> None:
    """未指定元数据时使用默认值。"""

    class _P(OmniPlugin):
        name = "omni_p"

        async def on_load(self, ctx: PluginContext) -> None:
            return None

    p = _P()
    assert p.version == "0.1.0"
    assert p.description == ""
    assert p.emoji == ""


def test_metadata_subclass_override() -> None:
    """子类可覆盖元数据。"""

    class _P(OmniPlugin):
        name = "omni_voice"
        version = "1.2.3"
        description = "语音插件"
        emoji = "🎙️"

        async def on_load(self, ctx: PluginContext) -> None:
            return None

    p = _P()
    assert p.version == "1.2.3"
    assert p.description == "语音插件"
    assert p.emoji == "🎙️"


def test_lifecycle_hooks_called_in_order() -> None:
    """on_load 先于 on_unload 被调用。"""

    class _P(OmniPlugin):
        name = "omni_p"
        call_log: list[str] = []

        async def on_load(self, ctx: PluginContext) -> None:
            self.call_log.append("on_load")

        async def on_unload(self) -> None:
            self.call_log.append("on_unload")

    p = _P()
    asyncio.run(p.on_load(_make_ctx()))
    asyncio.run(p.on_unload())
    assert p.call_log == ["on_load", "on_unload"]


def test_on_unload_default_implementation_is_noop() -> None:
    """基类 on_unload 默认空实现，可被多次调用（幂等）。"""

    class _P(OmniPlugin):
        name = "omni_p"

        async def on_load(self, ctx: PluginContext) -> None:
            return None

    p = _P()
    asyncio.run(p.on_unload())
    asyncio.run(p.on_unload())  # 幂等，不抛错


def test_on_event_default_implementation_is_noop() -> None:
    """基类 on_event 默认空实现，可被调用不抛错。"""

    class _P(OmniPlugin):
        name = "omni_p"

        async def on_load(self, ctx: PluginContext) -> None:
            return None

    p = _P()
    asyncio.run(p.on_event("voice.tick", {"v": 1}))


def test_on_event_receives_events() -> None:
    """on_event 钩子被调用时收到 event_type 与 payload。"""

    class _P(OmniPlugin):
        name = "omni_p"
        seen: list[tuple[str, dict]] = []

        async def on_load(self, ctx: PluginContext) -> None:
            return None

        async def on_event(self, event_type: str, payload: dict) -> None:
            self.seen.append((event_type, payload))

    p = _P()
    asyncio.run(p.on_event("voice.state_changed", {"state": "wake_listening"}))
    assert p.seen == [("voice.state_changed", {"state": "wake_listening"})]


def test_register_tools_default_implementation_is_noop() -> None:
    """基类 register_tools 默认空实现。"""

    class _P(OmniPlugin):
        name = "omni_p"

        async def on_load(self, ctx: PluginContext) -> None:
            return None

    p = _P()
    ctx = _make_ctx()
    p.register_tools(ctx)
    assert ctx.tool_registry.list_tools() == []


def test_register_tools_subclass_registers_tools() -> None:
    """子类覆盖 register_tools 后可注册工具到 ctx.tool_registry。"""
    import json

    class _P(OmniPlugin):
        name = "omni_p"

        async def on_load(self, ctx: PluginContext) -> None:
            return None

        def register_tools(self, ctx: PluginContext) -> None:
            ctx.register_tool(
                name="voice_status",
                description="状态",
                emoji="🎙️",
                schema={"type": "object"},
                handler_func=lambda kw: json.dumps({"ok": True}),
            )

    p = _P()
    ctx = _make_ctx()
    p.register_tools(ctx)
    assert "voice_status" in ctx.tool_registry.list_tools()
