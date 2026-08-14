"""AgentBridge 测试：LiteLLMBridge 的 HTTP 行为（mock urllib）与 FakeAgentBridge。"""

from __future__ import annotations

import json
import urllib.error

import pytest

from omni_voice.agent_bridge import AgentBridge, FakeAgentBridge, LiteLLMBridge
from omni_voice.errors import VoiceError


class _FakeResponse:
    """模拟 urllib 响应：支持 with 协议与 read()。"""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._body


def _ok_body(text: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": text}}]}).encode("utf-8")


class TestLiteLLMBridge:
    def test_is_agent_bridge(self):
        bridge = LiteLLMBridge("http://x:4000/v1", "m")
        assert isinstance(bridge, AgentBridge)

    def test_payload_and_timeout(self, monkeypatch):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["timeout"] = timeout
            captured["content_type"] = req.headers.get("Content-type")
            return _FakeResponse(_ok_body("你好呀"))

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        bridge = LiteLLMBridge(
            "http://spark01:4000/v1/", "qwen3.6", system_prompt="你是 Omni", timeout_s=7.5
        )
        reply = bridge.chat("今天天气怎么样")

        assert reply == "你好呀"
        # 端点末尾斜杠被规整，路径正确拼接
        assert captured["url"] == "http://spark01:4000/v1/chat/completions"
        assert captured["method"] == "POST"
        assert captured["timeout"] == 7.5
        assert captured["content_type"] == "application/json"
        messages = captured["body"]["messages"]
        assert messages[0] == {"role": "system", "content": "你是 Omni"}
        assert messages[1] == {"role": "user", "content": "今天天气怎么样"}
        assert captured["body"]["model"] == "qwen3.6"

    def test_api_key_header(self, monkeypatch):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["auth"] = req.headers.get("Authorization")
            return _FakeResponse(_ok_body("ok"))

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        bridge = LiteLLMBridge("http://x/v1", "m", api_key="sk-test")
        bridge.chat("hi")
        assert captured["auth"] == "Bearer sk-test"

    def test_url_error_mapped(self, monkeypatch):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.URLError("连接被拒绝")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        bridge = LiteLLMBridge("http://x/v1", "m")
        with pytest.raises(VoiceError, match="LLM 请求失败"):
            bridge.chat("hi")

    def test_http_error_mapped(self, monkeypatch):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 500, "Internal", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        bridge = LiteLLMBridge("http://x/v1", "m")
        with pytest.raises(VoiceError, match="500"):
            bridge.chat("hi")

    def test_invalid_json_mapped(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: _FakeResponse(b"not-json"),
        )
        bridge = LiteLLMBridge("http://x/v1", "m")
        with pytest.raises(VoiceError, match="JSON"):
            bridge.chat("hi")

    def test_missing_choices_mapped(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: _FakeResponse(b'{"choices": []}'),
        )
        bridge = LiteLLMBridge("http://x/v1", "m")
        with pytest.raises(VoiceError, match="结构"):
            bridge.chat("hi")


class TestThinkBlockStripping:
    """reasoning 模型（Nemotron Reasoning 等）<think> 推理块剥离。

    真机事故（2026-07-30）：voice-status.json 的 reply 写入了整段英文推理过程，
    TTS 把推理逐字朗读。剥离必须发生在 _parse_response 层，保证下游
    （对话历史 / TTS / 状态文件）全部干净。
    """

    def _chat_with_body(self, monkeypatch, body: bytes) -> str:
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: _FakeResponse(body),
        )
        bridge = LiteLLMBridge("http://x/v1", "m")
        return bridge.chat("你好")

    def test_closed_think_block_is_stripped(self, monkeypatch):
        reply = self._chat_with_body(
            monkeypatch, _ok_body("<think>让我想想怎么回答</think>你好，我在。")
        )
        assert reply == "你好，我在。"

    def test_real_world_jul30_leak_is_stripped(self, monkeypatch):
        """7月30日状态文件真实泄漏案例：大段英文推理 + </think> + 中文回复。"""
        leaked = (
            "We need to respond as Sherry, concise natural, under 50 Chinese characters. "
            "Let's count characters...\n</think>\n你好我在等你指令呢有什么想要帮忙的吗"
        )
        reply = self._chat_with_body(monkeypatch, _ok_body(leaked))
        assert reply == "你好我在等你指令呢有什么想要帮忙的吗"

    def test_multiple_think_blocks_all_stripped(self, monkeypatch):
        reply = self._chat_with_body(
            monkeypatch, _ok_body("<think>第一段</think>中间<think>第二段</think>结尾")
        )
        assert reply == "中间结尾"

    def test_unclosed_think_block_discards_to_end(self, monkeypatch):
        """未闭合 <think>（流式截断/模型异常）：保守全部丢弃，不读推理内容。"""
        reply = self._chat_with_body(monkeypatch, _ok_body("前言<think>推理到一半被截断"))
        assert reply == "前言"

    def test_no_think_block_returned_as_is(self, monkeypatch):
        reply = self._chat_with_body(monkeypatch, _ok_body("普通回复没有推理块"))
        assert reply == "普通回复没有推理块"

    def test_only_think_block_returns_empty(self, monkeypatch):
        reply = self._chat_with_body(monkeypatch, _ok_body("<think>只有推理没有回复</think>"))
        assert reply == ""

    def test_orphan_close_then_unclosed_open_terminates(self, monkeypatch):
        """回归（2026-08-14 review 发现）：孤立 ``</think>`` 在前 + 未闭合 ``<think>``
        在后的组合形态曾让剥离循环每轮拼接使字符串无限增长、线程永久挂起。"""
        reply = self._chat_with_body(monkeypatch, _ok_body("推理</think>正式回复<think>截断"))
        assert reply == "正式回复"

    def test_none_content_stays_none(self, monkeypatch):
        """tool_call 场景 content 为 None：不触发剥离，保持 None。"""
        body = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "function": {"name": "t", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ]
            }
        ).encode("utf-8")
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: _FakeResponse(body),
        )
        bridge = LiteLLMBridge("http://x/v1", "m")
        resp = bridge.chat_messages([{"role": "user", "content": "hi"}])
        assert resp.content is None
        assert resp.is_tool_call


class TestFakeAgentBridge:
    def test_reply_queue(self):
        agent = FakeAgentBridge(replies=["答一", "答二"])
        assert agent.chat("问一") == "答一"
        assert agent.chat("问二") == "答二"
        assert agent.chat("问三") == ""  # 耗尽后默认空
        assert agent.messages == ["问一", "问二", "问三"]

    def test_error_raised_once(self):
        agent = FakeAgentBridge(replies=["ok"], error=VoiceError("agent 故障"))
        with pytest.raises(VoiceError, match="agent 故障"):
            agent.chat("hi")
        assert agent.chat("hi") == "ok"

    def test_system_prompt_stored(self):
        agent = FakeAgentBridge(system_prompt="提示词")
        assert agent.system_prompt == "提示词"
