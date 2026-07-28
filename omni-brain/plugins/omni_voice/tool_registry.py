"""Tool 注册表：让雪莉可以调用外部工具（function calling）。

- :class:`Tool`：单个可调用工具的协议（name / description / parameters JSON Schema / execute）
- :class:`ToolRegistry`：工具注册表，支持注册、查找、分发调用、导出 OpenAI function schema
- M9 设计：ConversationAgent 持有 ToolRegistry，LLM 返回 tool_calls 时自动执行并回传结果
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


class ToolError(Exception):
    """工具调用错误。"""


@dataclass
class Tool:
    """一个可被 LLM 调用的工具。

    - ``name``：工具唯一标识（英文，snake_case，与 OpenAI function name 对齐）
    - ``description``：给 LLM 看的用途描述（中文或英文均可）
    - ``parameters``：JSON Schema dict（OpenAI function parameters 格式）
    - ``handler``：实际处理函数，接收反序列化后的 kwargs dict，返回 str（将作为 tool result 回传 LLM）
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]

    def to_openai_schema(self) -> dict[str, Any]:
        """导出 OpenAI function calling 格式的 schema 片段。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, arguments: str | dict[str, Any]) -> str:
        """执行工具，返回字符串结果。arguments 可为 JSON 字符串或 dict。"""
        if isinstance(arguments, str):
            try:
                kwargs = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError as exc:
                raise ToolError(f"工具 {self.name} 参数 JSON 解析失败: {exc}") from exc
        else:
            kwargs = arguments
        if not isinstance(kwargs, dict):
            raise ToolError(f"工具 {self.name} 参数必须是 object， got {type(kwargs).__name__}")
        try:
            result = self.handler(kwargs)
        except Exception as exc:
            raise ToolError(f"工具 {self.name} 执行失败: {exc}") from exc
        if not isinstance(result, str):
            result = json.dumps(result, ensure_ascii=False)
        return result


@dataclass
class ToolRegistry:
    """工具注册表：管理多个 Tool 实例。"""

    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        """注册一个工具；同名覆盖。"""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """移除一个工具（不存在则忽略）。"""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """按名称查找工具。"""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        """返回所有已注册工具名。"""
        return list(self._tools.keys())

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """导出全部工具的 OpenAI function schema 列表。"""
        return [t.to_openai_schema() for t in self._tools.values()]

    def dispatch(self, name: str, arguments: str | dict[str, Any]) -> str:
        """按名称分发调用；工具不存在或参数非法抛 ToolError。"""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"未知工具: {name}")
        return tool.execute(arguments)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
