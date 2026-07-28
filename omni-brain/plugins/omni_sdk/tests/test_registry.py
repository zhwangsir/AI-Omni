"""Registry 单元测试：PluginRegistry 与 ToolRegistry 注册/查找/列表/注销，handler 返回 JSON 字串。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from omni_sdk.registry import PluginRegistry, Tool, ToolRegistry


def _make_handler(result: dict[str, Any]):
    """构造一个返回 JSON 字串的 handler（符合 register(ctx) 契约）。"""

    def _h(kwargs: dict[str, Any]) -> str:
        return json.dumps(result, ensure_ascii=False)

    return _h


def _make_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "文本"}},
        "required": ["text"],
    }


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------
def test_tool_registry_register_and_get() -> None:
    """注册工具后按名查找得到 Tool 实例。"""
    reg = ToolRegistry()
    reg.register_tool(
        name="voice_status",
        description="查询语音管道状态",
        emoji="🎙️",
        schema=_make_schema(),
        handler_func=_make_handler({"ok": True, "state": "idle"}),
    )
    tool = reg.get_tool("voice_status")
    assert tool is not None
    assert tool.name == "voice_status"
    assert tool.description == "查询语音管道状态"
    assert tool.emoji == "🎙️"
    assert tool.schema == _make_schema()


def test_tool_registry_get_unknown_returns_none() -> None:
    """查找不存在的工具返回 None。"""
    reg = ToolRegistry()
    assert reg.get_tool("nonexistent") is None


def test_tool_registry_list_tools() -> None:
    """list_tools 返回所有已注册工具名。"""
    reg = ToolRegistry()
    reg.register_tool("a", "工具A", "🎙️", {}, _make_handler({"ok": True}))
    reg.register_tool("b", "工具B", "🏠", {}, _make_handler({"ok": True}))
    names = reg.list_tools()
    assert sorted(names) == ["a", "b"]


def test_tool_registry_unregister() -> None:
    """unregister_tool 移除工具；不存在时返回 False。"""
    reg = ToolRegistry()
    reg.register_tool("a", "工具A", "🎙️", {}, _make_handler({"ok": True}))
    assert reg.unregister_tool("a") is True
    assert reg.get_tool("a") is None
    assert reg.unregister_tool("a") is False


def test_tool_registry_register_overwrites_same_name() -> None:
    """同名工具注册应覆盖。"""
    reg = ToolRegistry()
    reg.register_tool("a", "old", "🎙️", {}, _make_handler({"v": 1}))
    reg.register_tool("a", "new", "🏠", {}, _make_handler({"v": 2}))
    tool = reg.get_tool("a")
    assert tool is not None
    assert tool.description == "new"
    assert tool.emoji == "🏠"


def test_tool_handler_returns_json_string() -> None:
    """handler 调用结果必须是 JSON 字符串。"""
    reg = ToolRegistry()
    reg.register_tool(
        "voice_status",
        "查询状态",
        "🎙️",
        _make_schema(),
        _make_handler({"ok": True, "data": {"state": "idle"}}),
    )
    tool = reg.get_tool("voice_status")
    assert tool is not None
    result = tool.handler_func({"text": "hello"})
    assert isinstance(result, str)
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["data"]["state"] == "idle"


def test_tool_to_openai_schema() -> None:
    """Tool 导出 OpenAI function 风格 schema。"""
    tool = Tool(
        name="voice_status",
        description="查询状态",
        emoji="🎙️",
        schema=_make_schema(),
        handler_func=_make_handler({"ok": True}),
    )
    schema = tool.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "voice_status"
    assert schema["function"]["description"] == "查询状态"
    assert schema["function"]["parameters"] == _make_schema()


def test_tool_registry_len_and_contains() -> None:
    """__len__ 与 __contains__ 行为。"""
    reg = ToolRegistry()
    assert len(reg) == 0
    assert "a" not in reg
    reg.register_tool("a", "工具A", "🎙️", {}, _make_handler({"ok": True}))
    assert len(reg) == 1
    assert "a" in reg


# ---------------------------------------------------------------------------
# PluginRegistry
# ---------------------------------------------------------------------------
class _FakePlugin:
    """测试用 fake plugin 占位（避免 import OmniPlugin 形成循环）。"""

    def __init__(self, name: str) -> None:
        self.name = name


def test_plugin_registry_register_and_get() -> None:
    """注册插件后按名查找得到插件实例。"""
    reg = PluginRegistry()
    p = _FakePlugin("omni_voice")
    reg.register(p)
    assert reg.get("omni_voice") is p


def test_plugin_registry_get_unknown_returns_none() -> None:
    """查找不存在插件返回 None。"""
    reg = PluginRegistry()
    assert reg.get("nonexistent") is None


def test_plugin_registry_list_all() -> None:
    """list_all 返回所有已注册插件。"""
    reg = PluginRegistry()
    reg.register(_FakePlugin("omni_voice"))
    reg.register(_FakePlugin("omni_home"))
    names = [p.name for p in reg.list_all()]
    assert sorted(names) == ["omni_home", "omni_voice"]


def test_plugin_registry_unregister() -> None:
    """unregister 移除插件；不存在时返回 False。"""
    reg = PluginRegistry()
    reg.register(_FakePlugin("omni_voice"))
    assert reg.unregister("omni_voice") is True
    assert reg.get("omni_voice") is None
    assert reg.unregister("omni_voice") is False


def test_plugin_registry_register_overwrites_same_name() -> None:
    """同名插件注册应覆盖。"""
    reg = PluginRegistry()
    old = _FakePlugin("omni_voice")
    new = _FakePlugin("omni_voice")
    reg.register(old)
    reg.register(new)
    assert reg.get("omni_voice") is new


def test_plugin_registry_len() -> None:
    """__len__ 返回插件数。"""
    reg = PluginRegistry()
    assert len(reg) == 0
    reg.register(_FakePlugin("omni_voice"))
    assert len(reg) == 1
