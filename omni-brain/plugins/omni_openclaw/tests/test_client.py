"""omni_openclaw OpenClawClient 测试。"""

from __future__ import annotations

from typing import Any

import pytest

from omni_openclaw.client import OpenClawClient
from omni_openclaw.config import OpenClawConfig


class FakeBackend:
    """内存中的 fake OpenClaw 后端，用于测试。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: dict[str, Any] = {}

    def add_response(self, method: str, path: str, status: int, body: Any) -> None:
        """注册对 method+path 的响应。"""
        self.responses[(method.upper(), path)] = (status, body)

    async def request(self, method: str, path: str, **kwargs: Any) -> tuple[int, Any]:
        """模拟 HTTP 请求。"""
        self.calls.append({"method": method.upper(), "path": path, "kwargs": kwargs})
        status, body = self.responses.get((method.upper(), path), (404, {"error": "not found"}))
        return status, body


@pytest.fixture
def fake_backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def wechat_bridge_backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def client(
    fake_backend: FakeBackend,
    wechat_bridge_backend: FakeBackend,
) -> OpenClawClient:
    return OpenClawClient(
        config=OpenClawConfig(),
        backend=fake_backend,
        wechat_bridge_backend=wechat_bridge_backend,
    )


@pytest.fixture
def llm_backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def multimodal_client(
    fake_backend: FakeBackend,
    llm_backend: FakeBackend,
    wechat_bridge_backend: FakeBackend,
) -> OpenClawClient:
    return OpenClawClient(
        config=OpenClawConfig(),
        backend=fake_backend,
        llm_backend=llm_backend,
        wechat_bridge_backend=wechat_bridge_backend,
    )


class TestHealthCheck:
    """健康检查测试。"""

    @pytest.mark.asyncio
    async def test_health_ok(self, client: OpenClawClient, fake_backend: FakeBackend) -> None:
        """网关返回 200 时健康检查应通过。"""
        fake_backend.add_response("GET", "/health", 200, {"status": "ok", "version": "2026.7.1-2"})
        result = await client.health_check()
        assert result["ok"] is True
        assert result["version"] == "2026.7.1-2"

    @pytest.mark.asyncio
    async def test_health_fail(self, client: OpenClawClient, fake_backend: FakeBackend) -> None:
        """网关返回非 200 时健康检查应失败。"""
        fake_backend.add_response("GET", "/health", 503, {"status": "degraded"})
        result = await client.health_check()
        assert result["ok"] is False
        assert result["status_code"] == 503

    @pytest.mark.asyncio
    async def test_health_timeout(self, client: OpenClawClient, fake_backend: FakeBackend) -> None:
        """后端抛异常时应返回 E_GATEWAY_UNAVAILABLE。"""

        async def raise_timeout(*args: Any, **kwargs: Any) -> Any:
            raise TimeoutError("connection timeout")

        fake_backend.request = raise_timeout  # type: ignore[assignment]
        result = await client.health_check()
        assert result["ok"] is False
        assert result["error"]["code"] == "E_GATEWAY_UNAVAILABLE"


class TestWeChatSend:
    """微信消息发送测试（经 wechat-bridge）。"""

    @pytest.mark.asyncio
    async def test_send_wechat_message(
        self,
        client: OpenClawClient,
        wechat_bridge_backend: FakeBackend,
    ) -> None:
        """发送微信消息应构造正确的 Alertmanager 告警请求。"""
        wechat_bridge_backend.add_response("POST", "/wechat", 200, {"status": "sent"})
        result = await client.send_wechat_message(
            message="你好，雪莉",
            target="o9cq804L_KWMLwn6nzTphaGmXn1c@im.wechat",
            account="5c5c75d92a90-im-bot",
        )
        assert result["ok"] is True
        assert result["channel"] == "openclaw-weixin"

        call = wechat_bridge_backend.calls[-1]
        assert call["method"] == "POST"
        assert call["path"] == "/wechat"
        payload = call["kwargs"]["json"]
        assert "alerts" in payload
        alert = payload["alerts"][0]
        assert alert["annotations"]["summary"] == "你好，雪莉"
        assert alert["labels"]["target"] == "o9cq804L_KWMLwn6nzTphaGmXn1c@im.wechat"
        assert alert["labels"]["account"] == "5c5c75d92a90-im-bot"
        assert alert["labels"]["severity"] == "info"

    @pytest.mark.asyncio
    async def test_send_wechat_uses_config_defaults(
        self,
        client: OpenClawClient,
        wechat_bridge_backend: FakeBackend,
    ) -> None:
        """省略账号/目标时应使用配置默认值。"""
        wechat_bridge_backend.add_response("POST", "/wechat", 200, {"status": "sent"})
        result = await client.send_wechat_message(message="测试默认参数")
        assert result["ok"] is True

        call = wechat_bridge_backend.calls[-1]
        payload = call["kwargs"]["json"]
        alert = payload["alerts"][0]
        assert alert["labels"]["account"] == "5c5c75d92a90-im-bot"
        assert alert["labels"]["target"] == "o9cq804L_KWMLwn6nzTphaGmXn1c@im.wechat"

    @pytest.mark.asyncio
    async def test_send_wechat_failure(
        self,
        client: OpenClawClient,
        wechat_bridge_backend: FakeBackend,
    ) -> None:
        """wechat-bridge 返回错误时应包装为统一错误结构。"""
        wechat_bridge_backend.add_response("POST", "/wechat", 500, {"detail": "internal error"})
        result = await client.send_wechat_message(message="失败测试")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_WECHAT_BRIDGE_ERROR"

    @pytest.mark.asyncio
    async def test_send_wechat_empty_message(
        self,
        client: OpenClawClient,
        wechat_bridge_backend: FakeBackend,
    ) -> None:
        """空消息应直接返回参数错误，不调用后端。"""
        result = await client.send_wechat_message(message="   ")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"
        assert wechat_bridge_backend.calls == []


class TestMultimodalChat:
    """多模态 Nemotron 调用测试。"""

    @pytest.fixture
    def chat_ok(self, llm_backend: FakeBackend) -> None:
        """注册一个成功的 chat completion 响应。"""
        llm_backend.add_response(
            "POST",
            "/chat/completions",
            200,
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "图中有一只猫。",
                        }
                    }
                ]
            },
        )

    @pytest.mark.asyncio
    async def test_vision_chat(
        self,
        multimodal_client: OpenClawClient,
        llm_backend: FakeBackend,
        chat_ok: None,
    ) -> None:
        """vision_chat 应构造 OpenAI 兼容请求并解析响应。"""
        result = await multimodal_client.vision_chat(
            prompt="这张图里有什么？",
            image_base64_or_url="iVBORw0KGgo=",
        )
        assert result["ok"] is True
        assert result["content"] == "图中有一只猫。"
        assert result["model"] == "qwen3.6-uncensored"

        call = llm_backend.calls[-1]
        assert call["method"] == "POST"
        assert call["path"] == "/chat/completions"
        payload = call["kwargs"]["json"]
        assert payload["model"] == "qwen3.6-uncensored"
        assert payload["messages"][0]["role"] == "user"
        content = payload["messages"][0]["content"]
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")

    @pytest.mark.asyncio
    async def test_vision_chat_with_url(
        self,
        multimodal_client: OpenClawClient,
        llm_backend: FakeBackend,
        chat_ok: None,
    ) -> None:
        """vision_chat 应透传 HTTP URL。"""
        result = await multimodal_client.vision_chat(
            prompt="描述图片",
            image_base64_or_url="https://example.com/img.png",
        )
        assert result["ok"] is True

        call = llm_backend.calls[-1]
        payload = call["kwargs"]["json"]
        content = payload["messages"][0]["content"]
        assert content[1]["image_url"]["url"] == "https://example.com/img.png"

    @pytest.mark.asyncio
    async def test_vision_chat_rejects_empty_prompt(
        self,
        multimodal_client: OpenClawClient,
    ) -> None:
        """空 prompt 应返回参数错误。"""
        result = await multimodal_client.vision_chat(prompt="", image_base64_or_url="x")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    @pytest.mark.asyncio
    async def test_audio_chat(
        self,
        multimodal_client: OpenClawClient,
        llm_backend: FakeBackend,
        chat_ok: None,
    ) -> None:
        """audio_chat 应构造 input_audio 请求。"""
        result = await multimodal_client.audio_chat(
            prompt="这段音频在说什么？",
            audio_base64="YXVkaW8=",
            format_="mp3",
        )
        assert result["ok"] is True

        call = llm_backend.calls[-1]
        payload = call["kwargs"]["json"]
        content = payload["messages"][0]["content"]
        assert content[1]["type"] == "input_audio"
        assert content[1]["input_audio"]["format"] == "mp3"

    @pytest.mark.asyncio
    async def test_video_chat_with_frames(
        self,
        multimodal_client: OpenClawClient,
        llm_backend: FakeBackend,
        chat_ok: None,
    ) -> None:
        """video_chat 传入 frames 时应使用关键帧序列。"""
        result = await multimodal_client.video_chat(
            prompt="视频里发生了什么？",
            video_base64_or_url="ignored",
            frames=["data:image/png;base64,abc", "data:image/png;base64,def"],
        )
        assert result["ok"] is True

        call = llm_backend.calls[-1]
        payload = call["kwargs"]["json"]
        content = payload["messages"][0]["content"]
        assert len(content) == 3  # text + 2 frames
        assert content[1]["type"] == "image_url"
        assert content[2]["image_url"]["url"] == "data:image/png;base64,def"

    @pytest.mark.asyncio
    async def test_chat_completion_llm_error(
        self,
        multimodal_client: OpenClawClient,
        llm_backend: FakeBackend,
    ) -> None:
        """LLM 返回非 200 时应包装错误。"""
        llm_backend.add_response(
            "POST",
            "/chat/completions",
            500,
            {"error": "internal error"},
        )
        result = await multimodal_client.vision_chat(
            prompt="测试",
            image_base64_or_url="x",
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "E_LLM_ERROR"
        assert result["status_code"] == 500

    @pytest.mark.asyncio
    async def test_chat_completion_timeout(
        self,
        multimodal_client: OpenClawClient,
        llm_backend: FakeBackend,
    ) -> None:
        """LLM 超时或连接失败时应返回 E_LLM_UNAVAILABLE。"""

        async def raise_timeout(*args: Any, **kwargs: Any) -> Any:
            raise TimeoutError("connection timeout")

        llm_backend.request = raise_timeout  # type: ignore[assignment]
        result = await multimodal_client.audio_chat(
            prompt="测试",
            audio_base64="x",
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "E_LLM_UNAVAILABLE"
