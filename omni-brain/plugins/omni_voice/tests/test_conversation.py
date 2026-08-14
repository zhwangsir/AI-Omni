"""ConversationAgent 测试：多轮对话历史、滑动窗口、工具调用循环。"""

from __future__ import annotations

import pytest

from omni_voice.agent_bridge import AgentBridge, AgentResponse, FakeAgentBridge, ToolCallRequest
from omni_voice.conversation import ConversationAgent, MAX_TOOL_ITERATIONS
from omni_voice.tool_registry import Tool, ToolRegistry


class _RecordingBridge(AgentBridge):
    """记录收到的 messages 列表 + tools 参数的测试桥接。"""

    def __init__(self, reply: str = "收到"):
        self.reply = reply
        self.calls: list[tuple[list[dict], list[dict] | None]] = []

    def chat(self, text: str) -> str:
        return self.reply

    def chat_messages(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AgentResponse:
        self.calls.append(([dict(m) for m in messages], tools))
        return AgentResponse(content=self.reply)


class _ToolCallBridge(AgentBridge):
    """模拟 LLM 两次返回 tool_calls，第三次返回文本。"""

    def __init__(self, tool_name: str, tool_args: dict, final_reply: str):
        self._tool_name = tool_name
        self._tool_args = tool_args
        self._final_reply = final_reply
        self.call_count = 0

    def chat(self, text: str) -> str:
        return self._final_reply

    def chat_messages(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AgentResponse:
        self.call_count += 1
        if self.call_count == 1:
            import json as _json
            return AgentResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name=self._tool_name,
                        arguments=_json.dumps(self._tool_args, ensure_ascii=False),
                    )
                ],
            )
        return AgentResponse(content=self._final_reply)


class _MultiToolBridge(AgentBridge):
    """模拟 LLM 返回多个并行 tool_calls，然后返回文本。"""

    def __init__(self, tool_specs: list[tuple[str, dict]], final_reply: str):
        self._tool_specs = tool_specs
        self._final_reply = final_reply
        self.call_count = 0

    def chat(self, text: str) -> str:
        return self._final_reply

    def chat_messages(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AgentResponse:
        import json as _json
        self.call_count += 1
        if self.call_count == 1:
            return AgentResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{i}",
                        name=name,
                        arguments=_json.dumps(args, ensure_ascii=False),
                    )
                    for i, (name, args) in enumerate(self._tool_specs)
                ],
            )
        return AgentResponse(content=self._final_reply)


class TestConversationAgentBasics:
    def test_is_agent_bridge(self):
        agent = ConversationAgent(FakeAgentBridge(), system_prompt="你是助手")
        assert isinstance(agent, AgentBridge)

    def test_first_call_sends_system_and_user(self):
        inner = _RecordingBridge("好的")
        agent = ConversationAgent(inner, system_prompt="你是雪莉")
        reply = agent.chat("今天星期几")
        assert reply == "好的"
        assert len(inner.calls) == 1
        msgs, tools = inner.calls[0]
        assert tools is None  # 无工具注册时不发 tools 参数
        assert msgs[0] == {"role": "system", "content": "你是雪莉"}
        assert msgs[1] == {"role": "user", "content": "今天星期几"}

    def test_second_call_includes_history(self):
        inner = _RecordingBridge("明天周三")
        agent = ConversationAgent(inner, system_prompt="你是雪莉")
        agent.chat("今天星期几")
        agent.chat("明天呢")
        assert len(inner.calls) == 2
        msgs2, _ = inner.calls[1]
        assert len(msgs2) == 4
        assert msgs2[0] == {"role": "system", "content": "你是雪莉"}
        assert msgs2[1] == {"role": "user", "content": "今天星期几"}
        assert msgs2[2] == {"role": "assistant", "content": "明天周三"}
        assert msgs2[3] == {"role": "user", "content": "明天呢"}

    def test_reset_clears_history(self):
        inner = _RecordingBridge("好的")
        agent = ConversationAgent(inner, system_prompt="你是雪莉")
        agent.chat("你好")
        agent.reset()
        agent.chat("在吗")
        msgs, _ = inner.calls[1]
        assert len(msgs) == 2
        assert msgs[0] == {"role": "system", "content": "你是雪莉"}
        assert msgs[1] == {"role": "user", "content": "在吗"}

    def test_history_window_truncates_old_turns(self):
        inner = _RecordingBridge("答")
        agent = ConversationAgent(inner, system_prompt="sys", max_turns=2)
        agent.chat("1")
        agent.chat("2")
        agent.chat("3")
        msgs, _ = inner.calls[2]
        assert msgs[1] == {"role": "user", "content": "1"}  # 第一轮仍在 messages 中（发给 LLM）
        hist = agent.history
        assert len(hist) == 4  # max_turns=2 → 4 entries (user+assistant * 2)
        assert hist[0] == {"role": "user", "content": "2"}  # 截断后最早是第二轮
        assert hist[3] == {"role": "assistant", "content": "答"}

    def test_default_max_turns_large_enough(self):
        inner = _RecordingBridge("答")
        agent = ConversationAgent(inner, system_prompt="sys")
        for i in range(15):
            agent.chat(f"turn{i}")
        msgs, _ = inner.calls[-1]
        assert len(msgs) == 1 + 14 * 2 + 1  # system + 14轮历史 + 当前user

    def test_reset_is_idempotent(self):
        inner = _RecordingBridge("答")
        agent = ConversationAgent(inner, system_prompt="sys")
        agent.reset()
        agent.reset()
        agent.chat("hi")
        assert len(inner.calls) == 1
        msgs, _ = inner.calls[0]
        assert len(msgs) == 2

    def test_inner_chat_error_propagates(self):
        from omni_voice.errors import VoiceError

        class ErrorBridge(AgentBridge):
            def chat(self, text: str) -> str:
                raise VoiceError("LLM 故障")

            def chat_messages(
                self, messages: list[dict], tools: list[dict] | None = None
            ) -> AgentResponse:
                raise VoiceError("LLM 故障")

        agent = ConversationAgent(ErrorBridge(), system_prompt="sys")
        with pytest.raises(VoiceError, match="LLM 故障"):
            agent.chat("hi")
        assert len(agent.history) == 0

    def test_history_property_exposes_readonly_view(self):
        inner = _RecordingBridge("答")
        agent = ConversationAgent(inner, system_prompt="sys")
        agent.chat("你好")
        hist = agent.history
        assert len(hist) == 2
        hist_copy = hist.copy()
        hist_copy.append({"role": "user", "content": "篡改"})
        assert len(agent.history) == 2


class TestConversationAgentWithFakeBridge:
    """用 FakeAgentBridge 验证与现有 fake 后端的兼容性。"""

    def test_fake_bridge_compatibility(self):
        fake = FakeAgentBridge(replies=["我是雪莉", "今天晴天"])
        agent = ConversationAgent(fake, system_prompt="你是雪莉")
        r1 = agent.chat("你是谁")
        r2 = agent.chat("今天天气")
        assert r1 == "我是雪莉"
        assert r2 == "今天晴天"
        assert len(fake.call_history) == 2
        assert fake.call_history[0][-1]["content"] == "你是谁"
        assert fake.call_history[1][-1]["content"] == "今天天气"


class TestConversationAgentToolCalling:
    """M9：工具调用循环测试。"""

    def test_tools_schema_sent_when_tools_registered(self):
        inner = _RecordingBridge("开灯成功")
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="turn_on_light",
                description="开灯",
                parameters={"type": "object", "properties": {"room": {"type": "string"}}},
                handler=lambda kw: "灯已开",
            )
        )
        agent = ConversationAgent(inner, system_prompt="你是助手", tools=registry)
        agent.chat("开灯")
        _, tools_sent = inner.calls[0]
        assert tools_sent is not None
        assert len(tools_sent) == 1
        assert tools_sent[0]["function"]["name"] == "turn_on_light"

    def test_single_tool_call_loop(self):
        """LLM 返回一个 tool_call → 执行工具 → 再调 LLM → 返回最终文本。"""
        executed: list[tuple[str, dict]] = []

        def handler(kwargs: dict) -> str:
            executed.append(("turn_on_light", kwargs))
            return "客厅灯已打开"

        registry = ToolRegistry()
        registry.register(
            Tool(
                name="turn_on_light",
                description="开灯",
                parameters={"type": "object", "properties": {"room": {"type": "string"}}},
                handler=handler,
            )
        )
        inner = _ToolCallBridge("turn_on_light", {"room": "客厅"}, "好的，客厅灯已为你打开")
        tool_starts: list[tuple[str, dict]] = []
        agent = ConversationAgent(
            inner, system_prompt="你是助手", tools=registry,
            on_tool_start=lambda name, args: tool_starts.append((name, args)),
        )
        reply = agent.chat("打开客厅的灯")
        assert reply == "好的，客厅灯已为你打开"
        assert len(executed) == 1
        assert executed[0] == ("turn_on_light", {"room": "客厅"})
        assert len(tool_starts) == 1
        assert tool_starts[0] == ("turn_on_light", {"room": "客厅"})
        assert inner.call_count == 2  # 第一次返回 tool_call，第二次返回文本

    def test_multiple_parallel_tool_calls(self):
        """LLM 返回多个 tool_calls → 全部执行 → 再调 LLM 返回文本。"""
        executed: list[str] = []

        def make_handler(name: str):
            def h(kwargs: dict) -> str:
                executed.append(name)
                return f"{name} ok"
            return h

        registry = ToolRegistry()
        for name in ["get_weather", "get_time"]:
            registry.register(
                Tool(
                    name=name,
                    description=f"{name} tool",
                    parameters={"type": "object", "properties": {}},
                    handler=make_handler(name),
                )
            )
        inner = _MultiToolBridge(
            [("get_weather", {}), ("get_time", {})],
            "今天晴天，现在下午3点",
        )
        agent = ConversationAgent(inner, system_prompt="你是助手", tools=registry)
        reply = agent.chat("今天天气怎么样？现在几点？")
        assert reply == "今天晴天，现在下午3点"
        assert set(executed) == {"get_weather", "get_time"}
        assert inner.call_count == 2

    def test_tool_error_returns_error_string(self):
        """工具执行失败时返回错误字符串，不抛异常（LLM 可看到错误信息）。"""
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="failing_tool",
                description="会失败的工具",
                parameters={"type": "object", "properties": {}},
                handler=lambda _: (_ for _ in ()).throw(RuntimeError("设备离线")),
            )
        )

        class _ErrorToolBridge(AgentBridge):
            def __init__(self):
                self.call_count = 0

            def chat(self, text: str) -> str:
                return "出问题了"

            def chat_messages(
                self, messages: list[dict], tools: list[dict] | None = None
            ) -> AgentResponse:
                self.call_count += 1
                if self.call_count == 1:
                    return AgentResponse(
                        content=None,
                        tool_calls=[ToolCallRequest(id="c1", name="failing_tool", arguments="{}")],
                    )
                # 第二次：LLM 应该看到 tool 消息包含错误信息
                tool_msg = [m for m in messages if m.get("role") == "tool"]
                assert len(tool_msg) == 1
                assert "错误" in tool_msg[0]["content"] or "失败" in tool_msg[0]["content"]
                return AgentResponse(content="灯控设备好像离线了")

        agent = ConversationAgent(_ErrorToolBridge(), system_prompt="你是助手", tools=registry)
        reply = agent.chat("开灯")
        assert "离线" in reply

    def test_max_tool_iterations_protection(self):
        """防止无限工具调用循环。"""

        class _InfiniteToolBridge(AgentBridge):
            def __init__(self):
                self.call_count = 0

            def chat(self, text: str) -> str:
                return "fallback"

            def chat_messages(
                self, messages: list[dict], tools: list[dict] | None = None
            ) -> AgentResponse:
                self.call_count += 1
                return AgentResponse(
                    content=None,
                    tool_calls=[ToolCallRequest(id=f"c{self.call_count}", name="echo", arguments="{}")],
                )

        registry = ToolRegistry()
        registry.register(
            Tool(name="echo", description="echo", parameters={}, handler=lambda _: "ok")
        )
        agent = ConversationAgent(_InfiniteToolBridge(), system_prompt="你是助手", tools=registry)
        reply = agent.chat("loop")
        assert "过多" in reply or reply == "fallback"  # 截断提示或 fallback

    def test_no_tools_registered_passes_none_tools(self):
        """无工具时不传 tools 参数，LLM 正常返回文本。"""
        inner = _RecordingBridge("纯文本回复")
        agent = ConversationAgent(inner, system_prompt="你是助手")
        reply = agent.chat("你好")
        assert reply == "纯文本回复"
        _, tools = inner.calls[0]
        assert tools is None


class _RawToolCallBridge(AgentBridge):
    """首轮返回原生 arguments 字符串的 tool_call，次轮回放 tool 消息后返回文本。"""

    def __init__(self, tool_name: str, raw_arguments: str, final_reply: str = "最终回复"):
        self._tool_name = tool_name
        self._raw_arguments = raw_arguments
        self._final_reply = final_reply
        self.call_count = 0
        self.tool_messages: list[dict] = []

    def chat(self, text: str) -> str:
        return self._final_reply

    def chat_messages(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AgentResponse:
        self.call_count += 1
        if self.call_count == 1:
            return AgentResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="c1", name=self._tool_name, arguments=self._raw_arguments
                    )
                ],
            )
        self.tool_messages = [m for m in messages if m.get("role") == "tool"]
        return AgentResponse(content=self._final_reply)


def _make_echo_registry() -> ToolRegistry:
    """构造含一个 echo 工具的注册表。"""
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="echo",
            description="回声",
            parameters={"type": "object", "properties": {}},
            handler=lambda kw: "echo ok",
        )
    )
    return registry


class TestConversationAgentProperties:
    """system_prompt / tools 只读属性。"""

    def test_system_prompt_property(self):
        agent = ConversationAgent(FakeAgentBridge(), system_prompt="你是雪莉")
        assert agent.system_prompt == "你是雪莉"

    def test_tools_property(self):
        registry = _make_echo_registry()
        agent = ConversationAgent(FakeAgentBridge(), system_prompt="s", tools=registry)
        assert agent.tools is registry
        agent_no_tools = ConversationAgent(FakeAgentBridge(), system_prompt="s")
        assert agent_no_tools.tools is None


class TestExecuteToolErrorPaths:
    """_execute_tool 各错误分支（M32.26 覆盖率提升）。"""

    def test_execute_tool_without_tools_registry(self):
        """LLM 请求工具但未注册工具表 → 回传"没有可用的工具"错误串。"""
        inner = _RawToolCallBridge("any_tool", "{}")
        agent = ConversationAgent(inner, system_prompt="s")  # tools=None
        reply = agent.chat("调用工具")
        assert reply == "最终回复"
        assert len(inner.tool_messages) == 1
        assert inner.tool_messages[0]["content"] == "错误：没有可用的工具（请求了 any_tool）"

    def test_execute_tool_invalid_json_arguments(self):
        """arguments 非合法 JSON → 回传参数解析失败错误串，不调用工具。"""
        executed: list[dict] = []
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="echo",
                description="回声",
                parameters={"type": "object", "properties": {}},
                handler=lambda kw: executed.append(kw) or "echo ok",
            )
        )
        inner = _RawToolCallBridge("echo", "{not valid json")
        agent = ConversationAgent(inner, system_prompt="s", tools=registry)
        reply = agent.chat("调用工具")
        assert reply == "最终回复"
        assert inner.tool_messages[0]["content"] == "错误：工具 echo 参数 JSON 解析失败"
        assert executed == []

    def test_dispatch_non_tool_error_returns_error_string(self):
        """工具 dispatch 抛非 ToolError 异常 → 回传"工具执行失败"错误串。

        用返回不可 JSON 序列化对象（object()）的 handler：Tool.execute 的
        json.dumps 抛 TypeError（非 ToolError），走 except Exception 分支。
        """
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="bad_result",
                description="返回坏结果",
                parameters={"type": "object", "properties": {}},
                handler=lambda kw: object(),
            )
        )
        tool_ends: list[tuple[str, str]] = []
        inner = _RawToolCallBridge("bad_result", "{}")
        agent = ConversationAgent(
            inner, system_prompt="s", tools=registry,
            on_tool_end=lambda name, result: tool_ends.append((name, result)),
        )
        reply = agent.chat("调用工具")
        assert reply == "最终回复"
        content = inner.tool_messages[0]["content"]
        assert content.startswith("错误：工具执行失败 - ")
        assert tool_ends == [("bad_result", content)]

    def test_on_tool_start_exception_swallowed(self):
        """on_tool_start 回调抛异常被吞，工具照常执行。"""
        executed: list[dict] = []
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="echo",
                description="回声",
                parameters={"type": "object", "properties": {}},
                handler=lambda kw: executed.append(kw) or "echo ok",
            )
        )

        def _boom_start(name: str, args: dict) -> None:
            raise RuntimeError("UI 回调故障")

        inner = _RawToolCallBridge("echo", "{}")
        agent = ConversationAgent(
            inner, system_prompt="s", tools=registry, on_tool_start=_boom_start
        )
        reply = agent.chat("调用工具")
        assert reply == "最终回复"
        assert executed == [{}]
        assert inner.tool_messages[0]["content"] == "echo ok"

    def test_on_tool_end_exception_swallowed(self):
        """on_tool_end 回调抛异常被吞，工具结果照常回传 LLM。"""
        registry = _make_echo_registry()

        def _boom_end(name: str, result: str) -> None:
            raise RuntimeError("UI 回调故障")

        inner = _RawToolCallBridge("echo", "{}")
        agent = ConversationAgent(
            inner, system_prompt="s", tools=registry, on_tool_end=_boom_end
        )
        reply = agent.chat("调用工具")
        assert reply == "最终回复"
        assert inner.tool_messages[0]["content"] == "echo ok"


class TestCallBridgeFallback:
    """_call_bridge 回退路径：bridge 无 chat_messages / 旧签名 TypeError。"""

    def test_bridge_without_chat_messages_falls_back_to_chat(self):
        """bridge 无 chat_messages 属性 → 回退 chat(最后一条用户文本)。"""

        class _ChatOnlyBridge:
            """不实现 chat_messages 的旧式 bridge（鸭子类型）。"""

            def __init__(self) -> None:
                self.texts: list[str] = []

            def chat(self, text: str) -> str:
                self.texts.append(text)
                return "旧桥回复"

        inner = _ChatOnlyBridge()
        agent = ConversationAgent(inner, system_prompt="sys")
        assert agent.chat("第一条") == "旧桥回复"
        assert agent.chat("第二条") == "旧桥回复"
        # 回退路径发送的是最后一条 str content 的 user 消息
        assert inner.texts == ["第一条", "第二条"]

    def test_chat_messages_type_error_falls_back_to_chat(self):
        """chat_messages 旧签名（无 tools 参数）→ TypeError 后回退 chat(text)。"""

        class _OldSignatureBridge(AgentBridge):
            def __init__(self) -> None:
                self.texts: list[str] = []

            def chat(self, text: str) -> str:
                self.texts.append(text)
                return "旧签名回复"

            def chat_messages(self, messages: list[dict]) -> AgentResponse:
                # 无 tools 关键字参数：带 tools 调用时 Python 抛 TypeError
                return AgentResponse(content="不应到达")

        inner = _OldSignatureBridge()
        registry = _make_echo_registry()  # tools_schema 非 None，确保带 tools 调用
        agent = ConversationAgent(inner, system_prompt="sys", tools=registry)
        assert agent.chat("你好") == "旧签名回复"
        assert agent.chat("再说一次") == "旧签名回复"
        assert inner.texts == ["你好", "再说一次"]


class TestDropOldestTurnEdge:
    """_drop_oldest_turn 边界：历史无 user 消息时整体清空。"""

    def test_drop_oldest_turn_without_user_message_clears_history(self):
        agent = ConversationAgent(FakeAgentBridge(), system_prompt="sys")
        agent._history.append({"role": "assistant", "content": "孤儿回复"})
        agent._drop_oldest_turn()
        assert agent.history == []
