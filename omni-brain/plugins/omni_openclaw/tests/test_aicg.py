"""omni_openclaw AICG 流水线测试。

所有后端均为 fake，不触碰真实模型/ComfyUI/TTS 服务。
"""

from __future__ import annotations

import base64
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from omni_openclaw.aicg import AicgPipeline, HttpxAicgBackend
from omni_openclaw.config import OpenClawConfig


class FakeAicgBackend:
    """内存中的 fake AICG backend，按 endpoint + path 返回响应。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: dict[tuple[str, str, str], tuple[int, Any]] = {}

    def add_response(
        self,
        method: str,
        endpoint: str,
        path: str,
        status: int,
        body: Any,
    ) -> None:
        """注册对 ``method + endpoint + path`` 的响应。"""
        self.responses[(method.upper(), endpoint, path)] = (status, body)

    async def request(
        self,
        method: str,
        endpoint: str,
        path: str,
        **kwargs: Any,
    ) -> tuple[int, Any]:
        """模拟 HTTP 请求。"""
        self.calls.append(
            {
                "method": method.upper(),
                "endpoint": endpoint,
                "path": path,
                "kwargs": kwargs,
            }
        )
        status, body = self.responses.get(
            (method.upper(), endpoint, path),
            (404, {"error": "not found"}),
        )
        return status, body


class _FakeHttpResponse:
    """模拟 httpx Response 的最小接口。"""

    def __init__(
        self,
        status_code: int = 200,
        content_type: str = "application/json",
        json_data: Any = None,
        content: bytes = b"",
        text: str = "",
        json_raises: bool = False,
    ) -> None:
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.content = content
        self.text = text
        self._json_data = json_data
        self._json_raises = json_raises

    def json(self) -> Any:
        """返回预置 JSON 数据；``json_raises`` 时模拟解析失败。"""
        if self._json_raises:
            raise ValueError("invalid json")
        return self._json_data


def _install_fake_httpx(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """向 sys.modules 注入 fake httpx，返回已创建的 AsyncClient 实例列表。"""
    created: list[Any] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.requests: list[dict[str, Any]] = []
            self.responses: list[_FakeHttpResponse] = []
            self.closed = False
            created.append(self)

        async def request(
            self, method: str, url: str, **kwargs: Any
        ) -> _FakeHttpResponse:
            self.requests.append({"method": method, "url": url, "kwargs": kwargs})
            return self.responses.pop(0)

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setitem(
        sys.modules, "httpx", types.SimpleNamespace(AsyncClient=FakeAsyncClient)
    )
    return created


@pytest.fixture
def config() -> OpenClawConfig:
    return OpenClawConfig()


@pytest.fixture
def llm_backend() -> FakeAicgBackend:
    return FakeAicgBackend()


@pytest.fixture
def comfyui_backend() -> FakeAicgBackend:
    return FakeAicgBackend()


@pytest.fixture
def tts_backend() -> FakeAicgBackend:
    return FakeAicgBackend()


@pytest.fixture
def pipeline(
    config: OpenClawConfig,
    llm_backend: FakeAicgBackend,
    comfyui_backend: FakeAicgBackend,
    tts_backend: FakeAicgBackend,
) -> AicgPipeline:
    return AicgPipeline(
        config=config,
        llm_backend=llm_backend,
        comfyui_backend=comfyui_backend,
        tts_backend=tts_backend,
    )


def _chat_ok_body(content: str) -> dict[str, Any]:
    """构造标准 OpenAI 兼容成功响应体。"""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                }
            }
        ]
    }


class TestChat:
    """LLM chat 路由与降级测试。"""

    @pytest.mark.asyncio
    async def test_chat_l1_success(
        self,
        pipeline: AicgPipeline,
        llm_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """L1 成功时应返回 L1 内容。"""
        llm_backend.add_response(
            "POST",
            config.llm_l1_endpoint,
            "/chat/completions",
            200,
            _chat_ok_body("L1 回答"),
        )
        result = await pipeline.chat("你好")
        assert result["ok"] is True
        assert result["content"] == "L1 回答"
        assert result["model"] == config.llm_l1_model

        call = llm_backend.calls[-1]
        payload = call["kwargs"]["json"]
        assert payload["model"] == config.llm_l1_model
        assert payload["messages"] == [{"role": "user", "content": "你好"}]
        assert "temperature" in payload
        assert "max_tokens" in payload

    @pytest.mark.asyncio
    async def test_chat_l4_direct(
        self,
        pipeline: AicgPipeline,
        llm_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """显式 level=L4 时应直接调用 L4。"""
        llm_backend.add_response(
            "POST",
            config.llm_l4_endpoint,
            "/chat/completions",
            200,
            _chat_ok_body("L4 回答"),
        )
        result = await pipeline.chat("你好", level="L4")
        assert result["ok"] is True
        assert result["content"] == "L4 回答"
        assert result["model"] == config.llm_l4_model

        call = llm_backend.calls[-1]
        assert call["endpoint"] == config.llm_l4_endpoint

    @pytest.mark.asyncio
    async def test_chat_l1_failure_fallback_to_l4(
        self,
        pipeline: AicgPipeline,
        llm_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """L1 失败且 nsfw=False 时应降级到 L4。"""
        llm_backend.add_response(
            "POST",
            config.llm_l1_endpoint,
            "/chat/completions",
            500,
            {"error": "internal error"},
        )
        llm_backend.add_response(
            "POST",
            config.llm_l4_endpoint,
            "/chat/completions",
            200,
            _chat_ok_body("L4 兜底"),
        )
        result = await pipeline.chat("你好", level="L1")
        assert result["ok"] is True
        assert result["content"] == "L4 兜底"
        assert result["model"] == config.llm_l4_model
        assert result["fallback_from"] == "L1"

    @pytest.mark.asyncio
    async def test_chat_nsfw_fallback_to_l4(
        self,
        pipeline: AicgPipeline,
        llm_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """nsfw=True 时应降级到 L4。"""
        llm_backend.add_response(
            "POST",
            config.llm_l1_endpoint,
            "/chat/completions",
            200,
            _chat_ok_body("L1 回答"),
        )
        llm_backend.add_response(
            "POST",
            config.llm_l4_endpoint,
            "/chat/completions",
            200,
            _chat_ok_body("L4 回答"),
        )
        result = await pipeline.chat("你好", nsfw=True)
        assert result["ok"] is True
        assert result["content"] == "L4 回答"
        assert result["model"] == config.llm_l4_model
        assert result["nsfw"] is True

    @pytest.mark.asyncio
    async def test_chat_l1_failure_l4_also_fails(
        self,
        pipeline: AicgPipeline,
        llm_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """L1 与 L4 均失败时应返回 L4 错误。"""
        llm_backend.add_response(
            "POST",
            config.llm_l1_endpoint,
            "/chat/completions",
            503,
            {"error": "l1 down"},
        )
        llm_backend.add_response(
            "POST",
            config.llm_l4_endpoint,
            "/chat/completions",
            500,
            {"error": "l4 down"},
        )
        result = await pipeline.chat("你好")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_LLM_ERROR"
        assert result["status_code"] == 500

    @pytest.mark.asyncio
    async def test_chat_empty_prompt_rejected(
        self,
        pipeline: AicgPipeline,
    ) -> None:
        """空 prompt 应返回参数错误。"""
        result = await pipeline.chat("")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    @pytest.mark.asyncio
    async def test_chat_invalid_level_rejected(
        self,
        pipeline: AicgPipeline,
    ) -> None:
        """不支持的 level 应返回参数错误。"""
        result = await pipeline.chat("你好", level="L3")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    @pytest.mark.asyncio
    async def test_chat_kwargs_passed_through(
        self,
        pipeline: AicgPipeline,
        llm_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """temperature、max_tokens、stream 等参数应透传到请求体。"""
        llm_backend.add_response(
            "POST",
            config.llm_l1_endpoint,
            "/chat/completions",
            200,
            _chat_ok_body("ok"),
        )
        result = await pipeline.chat(
            "你好",
            temperature=0.2,
            max_tokens=256,
            stream=True,
            top_p=0.9,
        )
        assert result["ok"] is True
        payload = llm_backend.calls[-1]["kwargs"]["json"]
        assert payload["temperature"] == 0.2
        assert payload["max_tokens"] == 256
        assert payload["stream"] is True
        assert payload["top_p"] == 0.9

    @pytest.mark.asyncio
    async def test_chat_llm_timeout(
        self,
        pipeline: AicgPipeline,
        llm_backend: FakeAicgBackend,
    ) -> None:
        """LLM 超时或连接失败时应返回 E_LLM_UNAVAILABLE。"""

        async def raise_timeout(*args: Any, **kwargs: Any) -> Any:
            raise TimeoutError("connection timeout")

        llm_backend.request = raise_timeout  # type: ignore[assignment]
        result = await pipeline.chat("你好")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_LLM_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_chat_llm_generic_error(
        self,
        pipeline: AicgPipeline,
        llm_backend: FakeAicgBackend,
    ) -> None:
        """LLM 端点抛出非网络类异常时应返回 E_LLM_UNAVAILABLE 并携带错误详情。"""

        async def raise_value_error(*args: Any, **kwargs: Any) -> Any:
            raise ValueError("bad payload")

        llm_backend.request = raise_value_error  # type: ignore[assignment]
        result = await pipeline.chat("你好", level="L4")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_LLM_UNAVAILABLE"
        assert "bad payload" in result["error"]["message"]


class TestGenerateImage:
    """ComfyUI 图像生成测试。"""

    @pytest.mark.asyncio
    async def test_generate_image_default_workflow(
        self,
        pipeline: AicgPipeline,
        comfyui_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """未提供 workflow 时应提交默认工作流。"""
        comfyui_backend.add_response(
            "POST",
            config.comfyui_endpoint,
            "/prompt",
            200,
            {"prompt_id": "uuid-123"},
        )
        result = await pipeline.generate_image("一只猫")
        assert result["ok"] is True
        assert result["prompt_id"] == "uuid-123"
        assert result["status"] == "queued"

        call = comfyui_backend.calls[-1]
        assert call["endpoint"] == config.comfyui_endpoint
        assert call["path"] == "/prompt"
        workflow = call["kwargs"]["json"]["prompt"]
        assert workflow["3"]["class_type"] == "KSampler"
        assert workflow["5"]["class_type"] == "EmptyLatentImage"
        assert workflow["6"]["inputs"]["text"] == "一只猫"
        assert workflow["7"]["class_type"] == "CLIPTextEncode"
        assert workflow["8"]["class_type"] == "SaveImage"

    @pytest.mark.asyncio
    async def test_generate_image_custom_workflow(
        self,
        pipeline: AicgPipeline,
        comfyui_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """提供 workflow 时应直接透传。"""
        comfyui_backend.add_response(
            "POST",
            config.comfyui_endpoint,
            "/prompt",
            200,
            {"prompt_id": "uuid-456"},
        )
        custom: dict[str, Any] = {"custom": "workflow"}
        result = await pipeline.generate_image("测试", workflow=custom)
        assert result["ok"] is True
        assert result["prompt_id"] == "uuid-456"

        payload = comfyui_backend.calls[-1]["kwargs"]["json"]
        assert payload["prompt"] == custom

    @pytest.mark.asyncio
    async def test_generate_image_custom_size(
        self,
        pipeline: AicgPipeline,
        comfyui_backend: FakeAicgBackend,
    ) -> None:
        """width/height 应进入默认 EmptyLatentImage 节点。"""
        comfyui_backend.add_response(
            "POST",
            pipeline.config.comfyui_endpoint,
            "/prompt",
            200,
            {"prompt_id": "uuid-789"},
        )
        result = await pipeline.generate_image("风景", width=512, height=768)
        assert result["ok"] is True

        workflow = comfyui_backend.calls[-1]["kwargs"]["json"]["prompt"]
        assert workflow["5"]["inputs"]["width"] == 512
        assert workflow["5"]["inputs"]["height"] == 768

    @pytest.mark.asyncio
    async def test_generate_image_empty_prompt_rejected(
        self,
        pipeline: AicgPipeline,
    ) -> None:
        """空 prompt 应返回参数错误。"""
        result = await pipeline.generate_image("")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    @pytest.mark.asyncio
    async def test_generate_image_invalid_size_rejected(
        self,
        pipeline: AicgPipeline,
    ) -> None:
        """非法尺寸应返回参数错误。"""
        result = await pipeline.generate_image("x", width=0, height=1024)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    @pytest.mark.asyncio
    async def test_generate_image_comfyui_error(
        self,
        pipeline: AicgPipeline,
        comfyui_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """ComfyUI 非 200 时应包装错误。"""
        comfyui_backend.add_response(
            "POST",
            config.comfyui_endpoint,
            "/prompt",
            500,
            {"error": "queue full"},
        )
        result = await pipeline.generate_image("猫")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_COMFYUI_ERROR"
        assert result["status_code"] == 500

    @pytest.mark.asyncio
    async def test_generate_image_timeout(
        self,
        pipeline: AicgPipeline,
        comfyui_backend: FakeAicgBackend,
    ) -> None:
        """ComfyUI 超时或连接失败时应返回 E_COMFYUI_UNAVAILABLE。"""

        async def raise_timeout(*args: Any, **kwargs: Any) -> Any:
            raise TimeoutError("connection timeout")

        comfyui_backend.request = raise_timeout  # type: ignore[assignment]
        result = await pipeline.generate_image("猫")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_COMFYUI_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_generate_image_generic_error(
        self,
        pipeline: AicgPipeline,
        comfyui_backend: FakeAicgBackend,
    ) -> None:
        """ComfyUI 抛出非网络类异常时应返回 E_COMFYUI_UNAVAILABLE 并携带错误详情。"""

        async def raise_runtime_error(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("queue broken")

        comfyui_backend.request = raise_runtime_error  # type: ignore[assignment]
        result = await pipeline.generate_image("猫")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_COMFYUI_UNAVAILABLE"
        assert "queue broken" in result["error"]["message"]


class TestTextToSpeech:
    """IndexTTS2 语音合成测试。"""

    @pytest.mark.asyncio
    async def test_text_to_speech_returns_base64(
        self,
        pipeline: AicgPipeline,
        tts_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """output_path 为 None 时应返回 base64 音频。"""
        audio_bytes = b"fake-wav-data"
        tts_backend.add_response(
            "POST",
            config.tts_endpoint,
            "/tts",
            200,
            audio_bytes,
        )
        result = await pipeline.text_to_speech("你好")
        assert result["ok"] is True
        assert result["format"] == "wav"
        assert base64.b64decode(result["audio"]) == audio_bytes

        call = tts_backend.calls[-1]
        assert call["endpoint"] == config.tts_endpoint
        assert call["path"] == "/tts"
        assert call["kwargs"]["json"] == {"text": "你好"}

    @pytest.mark.asyncio
    async def test_text_to_speech_saves_file(
        self,
        pipeline: AicgPipeline,
        tts_backend: FakeAicgBackend,
        tmp_path: Path,
    ) -> None:
        """提供 output_path 时应写入文件。"""
        audio_bytes = b"fake-wav-data"
        tts_backend.add_response(
            "POST",
            pipeline.config.tts_endpoint,
            "/tts",
            200,
            audio_bytes,
        )
        output_path = tmp_path / "out.wav"
        result = await pipeline.text_to_speech("你好", output_path=str(output_path))
        assert result["ok"] is True
        assert result["path"] == str(output_path)
        assert output_path.read_bytes() == audio_bytes

    @pytest.mark.asyncio
    async def test_text_to_speech_fallback_to_root(
        self,
        pipeline: AicgPipeline,
        tts_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """/tts 失败时应回退到 / 端点。"""
        audio_bytes = b"fallback-wav-data"
        tts_backend.add_response(
            "POST",
            config.tts_endpoint,
            "/tts",
            404,
            {"error": "not found"},
        )
        tts_backend.add_response(
            "POST",
            config.tts_endpoint,
            "/",
            200,
            audio_bytes,
        )
        result = await pipeline.text_to_speech("你好")
        assert result["ok"] is True
        assert base64.b64decode(result["audio"]) == audio_bytes
        assert tts_backend.calls[0]["path"] == "/tts"
        assert tts_backend.calls[1]["path"] == "/"

    @pytest.mark.asyncio
    async def test_text_to_speech_parses_json_response(
        self,
        pipeline: AicgPipeline,
        tts_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """TTS 返回 JSON 嵌套 base64 音频时应正确解析。"""
        audio_bytes = b"json-wav-data"
        tts_backend.add_response(
            "POST",
            config.tts_endpoint,
            "/tts",
            200,
            {"audio": base64.b64encode(audio_bytes).decode("utf-8")},
        )
        result = await pipeline.text_to_speech("你好")
        assert result["ok"] is True
        assert base64.b64decode(result["audio"]) == audio_bytes

    @pytest.mark.asyncio
    async def test_text_to_speech_empty_text_rejected(
        self,
        pipeline: AicgPipeline,
    ) -> None:
        """空 text 应返回参数错误。"""
        result = await pipeline.text_to_speech("")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    @pytest.mark.asyncio
    async def test_text_to_speech_both_endpoints_fail(
        self,
        pipeline: AicgPipeline,
        tts_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """/tts 与 / 均失败时应返回最后一个错误。"""
        tts_backend.add_response(
            "POST",
            config.tts_endpoint,
            "/tts",
            500,
            {"error": "tts down"},
        )
        tts_backend.add_response(
            "POST",
            config.tts_endpoint,
            "/",
            503,
            {"error": "root down"},
        )
        result = await pipeline.text_to_speech("你好")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_TTS_ERROR"
        assert result["status_code"] == 503

    @pytest.mark.asyncio
    async def test_text_to_speech_invalid_audio_data(
        self,
        pipeline: AicgPipeline,
        tts_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """TTS 返回无法解析的音频数据时应返回错误。"""
        tts_backend.add_response(
            "POST",
            config.tts_endpoint,
            "/tts",
            200,
            {"foo": "bar"},
        )
        tts_backend.add_response(
            "POST",
            config.tts_endpoint,
            "/",
            200,
            {"baz": "qux"},
        )
        result = await pipeline.text_to_speech("你好")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_TTS_INVALID_RESPONSE"

    @pytest.mark.asyncio
    async def test_text_to_speech_timeout(
        self,
        pipeline: AicgPipeline,
        tts_backend: FakeAicgBackend,
    ) -> None:
        """TTS 超时或连接失败时应返回 E_TTS_UNAVAILABLE。"""

        async def raise_timeout(*args: Any, **kwargs: Any) -> Any:
            raise TimeoutError("connection timeout")

        tts_backend.request = raise_timeout  # type: ignore[assignment]
        result = await pipeline.text_to_speech("你好")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_TTS_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_text_to_speech_generic_error(
        self,
        pipeline: AicgPipeline,
        tts_backend: FakeAicgBackend,
    ) -> None:
        """TTS 抛出非网络类异常时应依次尝试两个端点并返回最后错误。"""
        calls: list[Any] = []

        async def raise_value_error(*args: Any, **kwargs: Any) -> Any:
            calls.append(args)
            raise ValueError("synthesis exploded")

        tts_backend.request = raise_value_error  # type: ignore[assignment]
        result = await pipeline.text_to_speech("你好")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_TTS_UNAVAILABLE"
        assert "synthesis exploded" in result["error"]["message"]
        # /tts 与 / 两个端点均应被尝试
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_text_to_speech_str_body_base64(
        self,
        pipeline: AicgPipeline,
        tts_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """TTS 直接返回 base64 字符串时应解码为音频字节。"""
        audio_bytes = b"str-wav-data"
        tts_backend.add_response(
            "POST",
            config.tts_endpoint,
            "/tts",
            200,
            base64.b64encode(audio_bytes).decode("utf-8"),
        )
        result = await pipeline.text_to_speech("你好")
        assert result["ok"] is True
        assert base64.b64decode(result["audio"]) == audio_bytes

    @pytest.mark.asyncio
    async def test_text_to_speech_str_body_not_base64(
        self,
        pipeline: AicgPipeline,
        tts_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """TTS 返回非 base64 字符串时应按 utf-8 原样编码为字节。"""
        tts_backend.add_response(
            "POST",
            config.tts_endpoint,
            "/tts",
            200,
            "plain text!",
        )
        result = await pipeline.text_to_speech("你好")
        assert result["ok"] is True
        assert base64.b64decode(result["audio"]) == b"plain text!"

    @pytest.mark.asyncio
    async def test_text_to_speech_dict_bytes_audio(
        self,
        pipeline: AicgPipeline,
        tts_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """TTS 返回字典且 audio 字段为字节时应直接采用。"""
        audio_bytes = b"\x00\x01raw-bytes"
        tts_backend.add_response(
            "POST",
            config.tts_endpoint,
            "/tts",
            200,
            {"audio": audio_bytes},
        )
        result = await pipeline.text_to_speech("你好")
        assert result["ok"] is True
        assert base64.b64decode(result["audio"]) == audio_bytes

    @pytest.mark.asyncio
    async def test_text_to_speech_dict_str_not_base64(
        self,
        pipeline: AicgPipeline,
        tts_backend: FakeAicgBackend,
        config: OpenClawConfig,
    ) -> None:
        """TTS 返回字典且 audio 字段为非 base64 字符串时应按 utf-8 编码。"""
        tts_backend.add_response(
            "POST",
            config.tts_endpoint,
            "/tts",
            200,
            {"audio": "not base64!!"},
        )
        result = await pipeline.text_to_speech("你好")
        assert result["ok"] is True
        assert base64.b64decode(result["audio"]) == b"not base64!!"


class TestHttpxAicgBackend:
    """真实 HttpxAicgBackend 包装层测试（httpx 已 fake 注入，不触碰网络）。"""

    @pytest.mark.asyncio
    async def test_request_json_response(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """JSON content-type 响应应解析为字典，且 URL 拼接无重复斜杠。"""
        created = _install_fake_httpx(monkeypatch)
        backend = HttpxAicgBackend(timeout_s=7.5)
        created[0].responses.append(
            _FakeHttpResponse(
                status_code=200,
                content_type="application/json; charset=utf-8",
                json_data={"ok": 1},
            )
        )
        status, body = await backend.request(
            "POST", "http://host:9200/", "/tts", json={"text": "x"}
        )
        assert status == 200
        assert body == {"ok": 1}

        client = created[0]
        assert client.kwargs["timeout"] == 7.5
        call = client.requests[-1]
        assert call["method"] == "POST"
        assert call["url"] == "http://host:9200/tts"
        assert call["kwargs"]["json"] == {"text": "x"}

    @pytest.mark.asyncio
    async def test_request_audio_response_returns_bytes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """audio/octet-stream content-type 响应应返回原始字节。"""
        created = _install_fake_httpx(monkeypatch)
        backend = HttpxAicgBackend()
        for content_type in ("audio/wav", "application/octet-stream"):
            created[0].responses.append(
                _FakeHttpResponse(
                    status_code=200,
                    content_type=content_type,
                    content=b"\x00\x01wav",
                )
            )
            status, body = await backend.request("POST", "http://host:9200", "/tts")
            assert status == 200
            assert body == b"\x00\x01wav"

    @pytest.mark.asyncio
    async def test_request_text_response(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """其他 content-type 响应应返回文本。"""
        created = _install_fake_httpx(monkeypatch)
        backend = HttpxAicgBackend()
        created[0].responses.append(
            _FakeHttpResponse(
                status_code=500,
                content_type="text/plain",
                text="Internal Server Error",
            )
        )
        status, body = await backend.request("GET", "http://host:9200", "/health")
        assert status == 500
        assert body == "Internal Server Error"


class TestPipelineLifecycle:
    """流水线生命周期与 backend 管理测试。"""

    @pytest.mark.asyncio
    async def test_close_releases_owned_backends(
        self,
        config: OpenClawConfig,
    ) -> None:
        """close 应释放由流水线自己创建的 backend。"""
        pipeline = AicgPipeline(config=config)
        # 不实际发起网络请求，只验证 close 可正常执行
        await pipeline.close()

    @pytest.mark.asyncio
    async def test_close_ignores_injected_backends(
        self,
        config: OpenClawConfig,
        llm_backend: FakeAicgBackend,
        comfyui_backend: FakeAicgBackend,
        tts_backend: FakeAicgBackend,
    ) -> None:
        """close 不应关闭外部注入的 backend。"""
        pipeline = AicgPipeline(
            config=config,
            llm_backend=llm_backend,
            comfyui_backend=comfyui_backend,
            tts_backend=tts_backend,
        )
        await pipeline.close()
