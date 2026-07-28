"""ToolRegistry 单元测试：工具注册、schema 导出、分发调用、错误处理。"""

from __future__ import annotations

import json

import pytest

from omni_voice.tool_registry import Tool, ToolError, ToolRegistry


@pytest.fixture()
def registry() -> ToolRegistry:
    return ToolRegistry()


def _make_echo_tool() -> Tool:
    return Tool(
        name="echo",
        description="回显输入文本",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string", "description": "要回显的文本"}},
            "required": ["text"],
        },
        handler=lambda kwargs: kwargs["text"],
    )


def _make_add_tool() -> Tool:
    return Tool(
        name="add",
        description="两数相加",
        parameters={
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
        },
        handler=lambda kwargs: str(kwargs["a"] + kwargs["b"]),
    )


class TestTool:
    """单个 Tool 的行为测试。"""

    def test_to_openai_schema(self) -> None:
        tool = _make_echo_tool()
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "echo"
        assert schema["function"]["description"] == "回显输入文本"
        assert "text" in schema["function"]["parameters"]["properties"]

    def test_execute_with_dict_args(self) -> None:
        tool = _make_echo_tool()
        result = tool.execute({"text": "hello"})
        assert result == "hello"

    def test_execute_with_json_string_args(self) -> None:
        tool = _make_add_tool()
        result = tool.execute(json.dumps({"a": 3, "b": 5}))
        assert result == "8"

    def test_execute_with_empty_json_string(self) -> None:
        tool = Tool(
            name="ping",
            description="ping",
            parameters={"type": "object", "properties": {}},
            handler=lambda _: "pong",
        )
        assert tool.execute("") == "pong"
        assert tool.execute("{}") == "pong"

    def test_execute_invalid_json_raises(self) -> None:
        tool = _make_echo_tool()
        with pytest.raises(ToolError, match="JSON 解析失败"):
            tool.execute("{not valid json")

    def test_execute_non_dict_args_raises(self) -> None:
        tool = _make_echo_tool()
        with pytest.raises(ToolError, match="参数必须是 object"):
            tool.execute([1, 2, 3])  # type: ignore[arg-type]

    def test_execute_handler_exception_wrapped(self) -> None:
        def boom(_: dict) -> str:
            raise ValueError("something broke")

        tool = Tool(name="boom", description="b", parameters={}, handler=boom)
        with pytest.raises(ToolError, match="执行失败"):
            tool.execute({})

    def test_execute_non_string_result_jsonified(self) -> None:
        tool = Tool(
            name="list_things",
            description="list",
            parameters={},
            handler=lambda _: {"items": [1, 2, 3]},
        )
        result = tool.execute({})
        parsed = json.loads(result)
        assert parsed["items"] == [1, 2, 3]


class TestToolRegistry:
    """ToolRegistry 行为测试。"""

    def test_register_and_get(self, registry: ToolRegistry) -> None:
        tool = _make_echo_tool()
        registry.register(tool)
        assert registry.get("echo") is tool
        assert registry.has("echo")
        assert "echo" in registry
        assert len(registry) == 1

    def test_unregister(self, registry: ToolRegistry) -> None:
        registry.register(_make_echo_tool())
        registry.unregister("echo")
        assert not registry.has("echo")
        assert len(registry) == 0
        registry.unregister("nonexistent")  # no error

    def test_names(self, registry: ToolRegistry) -> None:
        registry.register(_make_echo_tool())
        registry.register(_make_add_tool())
        assert set(registry.names()) == {"echo", "add"}

    def test_to_openai_tools(self, registry: ToolRegistry) -> None:
        registry.register(_make_echo_tool())
        registry.register(_make_add_tool())
        schemas = registry.to_openai_tools()
        assert len(schemas) == 2
        names = {s["function"]["name"] for s in schemas}
        assert names == {"echo", "add"}

    def test_dispatch_success(self, registry: ToolRegistry) -> None:
        registry.register(_make_add_tool())
        result = registry.dispatch("add", {"a": 10, "b": 20})
        assert result == "30"

    def test_dispatch_with_json_string(self, registry: ToolRegistry) -> None:
        registry.register(_make_echo_tool())
        result = registry.dispatch("echo", json.dumps({"text": "世界你好"}))
        assert result == "世界你好"

    def test_dispatch_unknown_tool_raises(self, registry: ToolRegistry) -> None:
        with pytest.raises(ToolError, match="未知工具"):
            registry.dispatch("nonexistent", {})

    def test_register_overwrites_same_name(self, registry: ToolRegistry) -> None:
        t1 = _make_echo_tool()
        t2 = Tool(
            name="echo",
            description="different echo",
            parameters={},
            handler=lambda _: "different",
        )
        registry.register(t1)
        registry.register(t2)
        assert registry.get("echo") is t2
        assert len(registry) == 1
