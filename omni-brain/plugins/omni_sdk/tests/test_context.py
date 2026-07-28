"""PluginContext 单元测试：注入能力持有 + register_tool/register_hook 委托。"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from omni_sdk.context import PluginContext
from omni_sdk.event_bus import EventBus
from omni_sdk.permissions import PermissionChecker
from omni_sdk.registry import ToolRegistry


def _make_context() -> PluginContext:
    """构造一份完整注入的 PluginContext。"""
    return PluginContext(
        config={"sample_rate": 16000},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        logger=logging.getLogger("omni.test"),
    )


def test_context_holds_config() -> None:
    """ctx.config 保留注入的 dict。"""
    ctx = _make_context()
    assert ctx.config == {"sample_rate": 16000}


def test_context_holds_event_bus() -> None:
    """ctx.event_bus 是注入的 EventBus 实例。"""
    ctx = _make_context()
    assert isinstance(ctx.event_bus, EventBus)


def test_context_holds_tool_registry() -> None:
    """ctx.tool_registry 是注入的 ToolRegistry 实例。"""
    ctx = _make_context()
    assert isinstance(ctx.tool_registry, ToolRegistry)


def test_context_holds_permission_checker() -> None:
    """ctx.permission_checker 是注入的 PermissionChecker 实例。"""
    ctx = _make_context()
    assert isinstance(ctx.permission_checker, PermissionChecker)


def test_context_holds_logger() -> None:
    """ctx.logger 是注入的 Logger。"""
    ctx = _make_context()
    assert isinstance(ctx.logger, logging.Logger)
    assert ctx.logger.name == "omni.test"


def test_context_register_tool_delegates_to_registry() -> None:
    """ctx.register_tool 委托给 tool_registry.register_tool。"""

    def _h(kwargs: dict[str, Any]) -> str:
        return '{"ok": true}'

    ctx = _make_context()
    ctx.register_tool(
        name="voice_status",
        description="状态查询",
        emoji="🎙️",
        schema={"type": "object"},
        handler_func=_h,
    )
    tool = ctx.tool_registry.get_tool("voice_status")
    assert tool is not None
    assert tool.description == "状态查询"


def test_context_register_hook_delegates_to_event_bus() -> None:
    """ctx.register_hook 委托给 event_bus.subscribe，返回 sub_id。"""
    ctx = _make_context()
    sub_id = ctx.register_hook("voice.state_changed", lambda p: None)
    assert isinstance(sub_id, str)
    assert len(sub_id) > 0


def test_context_register_hook_callback_receives_event() -> None:
    """register_hook 注册的回调在 publish 时被调用。"""
    import asyncio

    ctx = _make_context()
    seen: list[dict] = []
    ctx.register_hook("voice.tick", lambda p: seen.append(p))
    asyncio.run(ctx.event_bus.publish("voice.tick", {"v": 1}))
    assert seen == [{"v": 1}]


def test_context_logger_namespace_uses_plugin_name() -> None:
    """若提供 plugin_name，logger 命名空间为 omni.<plugin_name>。"""
    ctx = PluginContext(
        config={},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(),
        plugin_name="omni_voice",
    )
    assert ctx.logger.name == "omni.omni_voice"


def test_context_default_logger_when_not_provided() -> None:
    """未提供 logger 且未提供 plugin_name 时使用默认命名空间 omni.sdk。"""
    ctx = PluginContext(
        config={},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(),
    )
    assert ctx.logger.name == "omni.sdk"
