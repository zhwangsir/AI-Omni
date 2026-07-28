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
