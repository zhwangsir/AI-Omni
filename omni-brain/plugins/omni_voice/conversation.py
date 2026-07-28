"""会话记忆层：在底层 AgentBridge 之上维护多轮对话历史 + 工具调用循环。

- :class:`ConversationAgent` 包装任意 :class:`AgentBridge`，
  在每次 ``chat(text)`` 时发送完整 messages 列表（system + 历史轮次 + 当前用户消息），
  支持 OpenAI function calling：若 LLM 返回 tool_calls，自动执行并回传结果，
  循环直到 LLM 返回纯文本回复。
- ``reset()`` 清空历史（用于会话超时或回到深层监听）。
- ``max_turns`` 控制滑动窗口：超过上限时丢弃最早的用户-助手轮次，保留 system。
- 底层 bridge 若实现 ``chat_messages(messages, tools)`` 方法则优先调用，
  否则回退到 ``chat(text)``（仅发送当前用户文本，无多轮/工具效果但兼容旧实现）。

M9 扩展：新增 tools 参数（ToolRegistry 或 None），开启工具调用循环。
最大工具迭代次数 ``MAX_TOOL_ITERATIONS`` 防止无限递归。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from .agent_bridge import AgentBridge, AgentResponse
from .tool_registry import ToolError, ToolRegistry

logger = logging.getLogger(__name__)

#: 单次 chat() 内最大工具调用轮次，防止无限循环
MAX_TOOL_ITERATIONS = 8


class ConversationAgent(AgentBridge):
    """维护多轮对话历史 + 工具调用循环的 Agent 包装器。"""

    DEFAULT_MAX_TURNS: int = 20

    def __init__(
        self,
        bridge: AgentBridge,
        system_prompt: str = "",
        max_turns: int = DEFAULT_MAX_TURNS,
        tools: ToolRegistry | None = None,
        on_tool_start: Callable[[str, dict[str, Any]], None] | None = None,
        on_tool_end: Callable[[str, str], None] | None = None,
    ):
        self._bridge = bridge
        self._system_prompt = system_prompt
        self._max_turns = max_turns
        self._tools = tools
        self._on_tool_start = on_tool_start
        self._on_tool_end = on_tool_end
        self._history: list[dict[str, Any]] = []

    @property
    def history(self) -> list[dict[str, Any]]:
        """返回对话历史的只读副本（不含 system 消息，含 tool_calls/tool 消息）。"""
        return [dict(m) for m in self._history]

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def tools(self) -> ToolRegistry | None:
        return self._tools

    def reset(self) -> None:
        """清空对话历史（续听超时或回到深层监听时调用）。"""
        self._history.clear()

    def chat(self, text: str) -> str:
        """发送一轮对话，携带历史和工具，返回最终文本回复并追加进历史。"""
        messages = self._build_messages(text)
        reply = self._run_chat_loop(messages)
        self._history.append({"role": "user", "content": text})
        self._history.append({"role": "assistant", "content": reply})
        self._truncate()
        return reply

    def _build_messages(self, text: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        messages.extend(self._history)
        messages.append({"role": "user", "content": text})
        return messages

    def _run_chat_loop(self, messages: list[dict[str, Any]]) -> str:
        """工具调用循环：LLM 返回 tool_calls 时执行工具并回传，直到得到文本回复。"""
        tools_schema = self._tools.to_openai_tools() if self._tools else None
        for _ in range(MAX_TOOL_ITERATIONS):
            response = self._call_bridge(messages, tools_schema)
            if not response.is_tool_call:
                return response.text

            # 追加 assistant 的 tool_calls 消息
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments,
                        },
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            # 执行每个工具调用，追加 tool 结果消息
            for tc in response.tool_calls:
                result = self._execute_tool(tc.name, tc.arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }
                )

        # 超过最大迭代次数：返回最后一次的文本或错误提示
        logger.warning("工具调用超过最大迭代次数 %d，截断返回", MAX_TOOL_ITERATIONS)
        last_response = self._call_bridge(messages, tools_schema)
        return last_response.text or "（工具调用次数过多，请重试）"

    def _execute_tool(self, name: str, arguments: str) -> str:
        """执行单个工具，返回结果字符串（错误时也返回错误描述而非抛异常）。"""
        if self._tools is None:
            return f"错误：没有可用的工具（请求了 {name}）"
        try:
            args_dict: dict[str, Any] = {}
            if arguments and arguments.strip():
                args_dict = json.loads(arguments)
        except json.JSONDecodeError:
            return f"错误：工具 {name} 参数 JSON 解析失败"

        if self._on_tool_start is not None:
            try:
                self._on_tool_start(name, args_dict)
            except Exception:
                logger.exception("on_tool_start 回调异常，已忽略")

        try:
            result = self._tools.dispatch(name, args_dict)
        except ToolError as exc:
            result = f"错误：{exc}"
        except Exception as exc:
            logger.exception("工具 %s 执行异常", name)
            result = f"错误：工具执行失败 - {exc}"

        if self._on_tool_end is not None:
            try:
                self._on_tool_end(name, result)
            except Exception:
                logger.exception("on_tool_end 回调异常，已忽略")

        return result

    def _call_bridge(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AgentResponse:
        """调用底层 bridge。优先 chat_messages(messages, tools)，否则回退 chat(text)。"""
        chat_messages = getattr(self._bridge, "chat_messages", None)
        if callable(chat_messages):
            try:
                return chat_messages(messages, tools=tools)
            except TypeError:
                # 旧签名不支持 tools 关键字参数，回退到无 tools 调用
                pass
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                last_user = m["content"]
                break
        return AgentResponse(content=self._bridge.chat(last_user))

    def _truncate(self) -> None:
        """滑动窗口：历史超过 max_turns 轮时，从头部丢弃最早的完整轮次。

        一轮 = 一个 user 消息及其后续所有消息（直到下一个 user 消息开头，不含）。
        这样 tool_calls/tool 结果消息跟所属 assistant 消息一起被截断，不会残留孤立条目。
        """
        while self._count_user_turns() > self._max_turns:
            self._drop_oldest_turn()

    def _count_user_turns(self) -> int:
        """统计历史中 user 消息数量（即完整轮次数）。"""
        return sum(1 for m in self._history if m.get("role") == "user")

    def _drop_oldest_turn(self) -> None:
        """丢弃最早一轮：从第一个 user 消息开始，到下一个 user 消息前（不含）为止。"""
        for i, m in enumerate(self._history):
            if m.get("role") == "user":
                end = i + 1
                while end < len(self._history) and self._history[end].get("role") != "user":
                    end += 1
                del self._history[i:end]
                return
        self._history.clear()
