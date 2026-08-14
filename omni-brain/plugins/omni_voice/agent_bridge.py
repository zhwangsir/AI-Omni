"""LLM Agent 桥接层。

- :class:`AgentResponse` ：LLM 回复结构（content 文本 或 tool_calls 工具调用列表）
- :class:`ToolCallRequest` ：单次工具调用请求（id / name / arguments）
- :class:`AgentBridge`    ：抽象接口 ``chat(text) -> str`` + ``chat_with_tools`` 可选能力
- :class:`LiteLLMBridge`  ：OpenAI 兼容端点（仅用 urllib 标准库，无第三方依赖），
  默认指向 Workstation Nemotron vLLM（:8000/v1），AI-Omni 不自行加载本地模型（AGENTS.md §四）
- :class:`FakeAgentBridge`：可编程 fake（测试/演示用），支持 tool_calls 模拟

M8 扩展：LiteLLMBridge 新增 ``chat_messages(messages)`` 支持发送完整消息列表。
M9 扩展：新增 ``chat_with_tools`` 支持 OpenAI function calling，返回 ``AgentResponse``。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .errors import VoiceError

logger = logging.getLogger(__name__)

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def strip_think_block(content: str) -> str:
    """剥离 reasoning 模型（Nemotron Reasoning 等）输出的 ``<think>`` 推理块。

    真机事故（2026-07-30）：voice-status.json 的 reply 写入整段英文推理过程，
    TTS 把推理逐字朗读。剥离集中在响应解析层，保证下游（对话历史 / TTS /
    状态文件）全部干净。

    规则：
    - 闭合块 ``<think>...</think>`` 全部移除（可出现多个）；
    - 孤立 ``</think>``（vLLM 把起始标签作为特殊 token 吃掉，content 里只剩
      推理内容 + 闭合标签，7月30日真机泄漏即此形态）：开头到首个闭合标签
      全部丢弃；
    - 未闭合 ``<think>``（流式截断 / 模型异常）：从自身到末尾保守丢弃，
      宁缺毋滥——推理内容绝不进 TTS；
    - 无 think 块时原样返回。
    """
    if not content:
        return content
    text = content
    # 闭合块全部移除；遇未闭合 <think>（start 之后找不到闭合标签）从自身到末尾
    # 丢弃并终止循环——end == -1 时继续拼接会让字符串无限增长（死循环事故）。
    while _THINK_OPEN in text:
        start = text.find(_THINK_OPEN)
        end = text.find(_THINK_CLOSE, start)
        if end == -1:
            text = text[:start]
            break
        text = text[:start] + text[end + len(_THINK_CLOSE) :]
    # 孤立 </think>：开头到首个闭合标签全部丢弃
    if _THINK_CLOSE in text:
        text = text[text.find(_THINK_CLOSE) + len(_THINK_CLOSE) :]
    return text.strip()


@dataclass
class ToolCallRequest:
    """LLM 请求调用一个工具。"""

    id: str
    name: str
    arguments: str  # JSON 字符串（原样传给 Tool.execute）


@dataclass
class AgentResponse:
    """LLM 响应：要么是文本回复，要么是工具调用请求列表（可同时有 content，通常为 null）。"""

    content: str | None = None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)

    @property
    def is_tool_call(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def text(self) -> str:
        """获取文本内容（兼容旧代码：无 content 时返回空串）。"""
        return self.content or ""


class AgentBridge(ABC):
    """对话 Agent 抽象：输入用户文本，输出回复。"""

    @abstractmethod
    def chat(self, text: str) -> str:
        """发送一轮对话，返回 Agent 文本回复（向后兼容）。"""

    def chat_messages(self, messages: list[dict[str, Any]]) -> AgentResponse:
        """发送完整消息列表，返回 AgentResponse（支持 tool_calls）。

        默认实现：回退到 chat(last_user_text)，包装为纯文本 AgentResponse。
        子类覆盖以支持多轮对话和工具调用。
        """
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                last_user = m["content"]
                break
        return AgentResponse(content=self.chat(last_user))


class LiteLLMBridge(AgentBridge):
    """OpenAI 兼容的 chat/completions 端点桥接（LiteLLM / vLLM / SGLang 等通用）。

    只用标准库 urllib 发 POST；网络/协议错误统一映射为 :class:`VoiceError`。
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        system_prompt: str = "",
        timeout_s: float = 30.0,
        api_key: str | None = None,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.system_prompt = system_prompt
        self.timeout_s = timeout_s
        self.api_key = api_key

    def chat(self, text: str) -> str:
        messages: list[dict[str, Any]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": text})
        return self.chat_messages(messages).text

    def chat_messages(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AgentResponse:
        """发送完整消息列表，可选携带 tools schema。

        返回 AgentResponse：含 content 文本 或 tool_calls（或两者都有）。
        """
        url = f"{self.endpoint}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            code = exc.code
            # M32.23：关闭异常持有的底层响应资源（Python 3.14 起未关闭触发
            # ResourceWarning；真实运行时对应未释放的 socket 连接）。
            exc.close()
            raise VoiceError(f"LLM 请求失败 HTTP {code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise VoiceError(f"LLM 请求失败: {exc}") from exc
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise VoiceError(f"LLM 返回非 JSON 内容: {exc}") from exc
        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> AgentResponse:
        """解析 OpenAI 格式的响应 JSON 为 AgentResponse。"""
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise VoiceError(f"LLM 返回结构异常: {data!r}") from exc

        content = message.get("content")
        # reasoning 模型（Nemotron Reasoning 等）推理块剥离：只保留最终回复，
        # None（tool_call 场景）不处理。
        if content is not None:
            content = strip_think_block(content)
        tool_calls_raw = message.get("tool_calls") or []
        tool_calls: list[ToolCallRequest] = []
        for tc in tool_calls_raw:
            fn = tc.get("function", {})
            tool_calls.append(
                ToolCallRequest(
                    id=tc.get("id", ""),
                    name=fn.get("name", ""),
                    arguments=fn.get("arguments", "{}"),
                )
            )
        return AgentResponse(content=content, tool_calls=tool_calls)


class FakeAgentBridge(AgentBridge):
    """可编程 Agent fake：按预设队列回复，支持 tool_calls 模拟，记录所有消息。

    ``error`` 非空时首次调用抛出该异常（仅一次），用于测试异常恢复。

    历史记录：
    - ``messages``：每次 chat() 调用的用户文本列表（向后兼容旧测试）
    - ``call_history``：每次 chat_messages() 调用的完整 messages 参数列表（新接口）
    - ``tools_history``：每次调用的 tools 参数
    """

    def __init__(
        self,
        replies: list[str | AgentResponse] | None = None,
        system_prompt: str = "",
        error: Exception | None = None,
    ):
        self._queue: deque[str | AgentResponse] = deque(replies or [])
        self.system_prompt = system_prompt
        self.error = error
        self.messages: list[str] = []
        self.call_history: list[list[dict[str, Any]]] = []
        self.tools_history: list[list[dict[str, Any]] | None] = []

    def chat(self, text: str) -> str:
        """向后兼容：记录用户文本，包装为单轮调用（无 tools）。"""
        self.messages.append(text)
        resp = self.chat_messages([{"role": "user", "content": text}])
        return resp.text

    def chat_messages(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AgentResponse:
        self.call_history.append(list(messages))
        self.tools_history.append(tools)
        if self.error is not None:
            error, self.error = self.error, None
            raise error
        if self._queue:
            item = self._queue.popleft()
            if isinstance(item, AgentResponse):
                return item
            return AgentResponse(content=item)
        return AgentResponse(content="")
