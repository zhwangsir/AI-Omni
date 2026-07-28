"""Registry：工具注册表 + 插件注册表。

- :class:`Tool`：单个可调用工具（name / description / emoji / schema / handler_func）
- :class:`ToolRegistry`：工具注册表，register_tool / get_tool / list_tools / unregister_tool
- :class:`PluginRegistry`：插件注册表，register / get / list_all / unregister

工具 handler 必须返回 JSON 字串（沿用 register(ctx) 契约，见 CLAUDE.md §二）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# TYPE_CHECKING 内导入避免运行时循环
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omni_sdk.plugin import OmniPlugin

ToolHandler = Callable[[dict[str, Any]], str]


@dataclass
class Tool:
    """单个可被 LLM 调用的工具。

    :ivar name: 工具唯一标识，snake_case（如 ``voice_status``）
    :ivar description: 工具用途（中文）
    :ivar emoji: Hermes CLI 展示用 emoji（沿用 WeBrain 惯例）
    :ivar schema: OpenAI function 风格 JSON Schema dict
    :ivar handler_func: 处理函数，接收 kwargs dict，返回 JSON 字符串
    """

    name: str
    description: str
    emoji: str
    schema: dict[str, Any]
    handler_func: ToolHandler

    def to_openai_schema(self) -> dict[str, Any]:
        """导出为 OpenAI function calling 格式 schema 片段。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }


@dataclass
class ToolRegistry:
    """工具注册表：管理多个 :class:`Tool` 实例。

    register_tool / get_tool / list_tools / unregister_tool。
    同名工具注册时覆盖旧实例。
    """

    _tools: dict[str, Tool] = field(default_factory=dict)

    def register_tool(
        self,
        name: str,
        description: str,
        emoji: str,
        schema: dict[str, Any],
        handler_func: ToolHandler,
    ) -> Tool:
        """注册一个工具；同名覆盖。

        :return: 注册的 :class:`Tool` 实例
        """
        tool = Tool(
            name=name,
            description=description,
            emoji=emoji,
            schema=schema,
            handler_func=handler_func,
        )
        self._tools[name] = tool
        return tool

    def get_tool(self, name: str) -> Tool | None:
        """按名查找工具；不存在返回 None。"""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """返回所有已注册工具名（按注册顺序）。"""
        return list(self._tools.keys())

    def unregister_tool(self, name: str) -> bool:
        """移除工具；不存在返回 False。"""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools


@dataclass
class PluginRegistry:
    """插件注册表：管理多个 OmniPlugin 实例。

    register / get / list_all / unregister。
    同名插件注册时覆盖旧实例。
    """

    _plugins: dict[str, OmniPlugin] = field(default_factory=dict)

    def register(self, plugin: OmniPlugin) -> None:
        """注册插件；按 ``plugin.name`` 索引，同名覆盖。"""
        self._plugins[plugin.name] = plugin

    def get(self, name: str) -> OmniPlugin | None:
        """按名查找插件；不存在返回 None。"""
        return self._plugins.get(name)

    def list_all(self) -> list[OmniPlugin]:
        """返回所有已注册插件（按注册顺序）。"""
        return list(self._plugins.values())

    def unregister(self, name: str) -> bool:
        """移除插件；不存在返回 False。"""
        if name in self._plugins:
            del self._plugins[name]
            return True
        return False

    def __len__(self) -> int:
        return len(self._plugins)
