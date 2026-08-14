"""omni_openclaw 工具注册与 handler 测试。"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from omni_openclaw.tools import (
    _handle_audio_chat,
    _handle_chat,
    _handle_control_air_purifier,
    _handle_control_fan,
    _handle_control_light,
    _handle_device_lookup,
    _handle_generate_image,
    _handle_health,
    _handle_send_wechat,
    _handle_speaker_say,
    _handle_text_to_speech,
    _handle_video_chat,
    _handle_vision_chat,
)


class FakeContext:
    """模拟 Hermes/WeBrain 插件上下文。"""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []

    def register_tool(
        self,
        name: str,
        description: str,
        emoji: str,
        schema: dict[str, Any],
        handler_func: Any,
    ) -> None:
        self.tools.append(
            {
                "name": name,
                "description": description,
                "emoji": emoji,
                "schema": schema,
                "handler": handler_func,
            }
        )


@pytest.fixture
def ctx() -> FakeContext:
    return FakeContext()


class TestRegister:
    """工具注册测试。"""

    def test_registers_openclaw_tools(self, ctx: FakeContext) -> None:
        """应注册 openclaw_* 系列工具。"""
        from omni_openclaw.tools import register

        register(ctx)
        names = {t["name"] for t in ctx.tools}
        assert "openclaw_health" in names
        assert "openclaw_send_wechat" in names
        assert "openclaw_vision_chat" in names
        assert "openclaw_audio_chat" in names
        assert "openclaw_video_chat" in names

    def test_tool_returns_json(self, ctx: FakeContext) -> None:
        """所有 tool handler 必须返回 JSON 字符串。

        M32.23：无必填参数的 handler（speaker_voice_on/off、cluster_health）
        空参调用也会真实发起网络请求——必须打桩 HomeAssistantClient 与
        ClusterChecker，禁止测试触碰真实集群 / HA。
        """
        from omni_openclaw.tools import register

        register(ctx)

        fake_ha = MagicMock()
        fake_ha.return_value.speaker_voice_on = AsyncMock(return_value={"ok": True})
        fake_ha.return_value.speaker_voice_off = AsyncMock(return_value={"ok": True})
        fake_ha.return_value.close = AsyncMock()

        fake_checker = MagicMock()
        fake_checker.return_value.health_check = AsyncMock(return_value={"ok": True})
        fake_checker.return_value.close = AsyncMock()

        with (
            patch("omni_openclaw.tools.HomeAssistantClient", fake_ha),
            patch("omni_openclaw.tools.ClusterChecker", fake_checker),
        ):
            for tool in ctx.tools:
                result = tool["handler"]({})
                assert isinstance(result, str)
                parsed = json.loads(result)
                assert "ok" in parsed


class TestHealthHandler:
    """openclaw_health handler 测试。"""

    def test_health_handler(self) -> None:
        """handler 应返回标准 JSON 结构。"""
        result = _handle_health({})
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert parsed["gateway"] == "http://192.168.71.86:18789"


class TestSendWeChatHandler:
    """openclaw_send_wechat handler 测试。"""

    def test_send_wechat_handler_validates_message(self) -> None:
        """缺少 message 参数应返回参数错误。"""
        result = _handle_send_wechat({})
        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["error"]["code"] == "E_INVALID_PARAMS"


class TestVisionChatHandler:
    """openclaw_vision_chat handler 测试。"""

    def test_validates_prompt(self) -> None:
        """缺少 prompt 应返回参数错误。"""
        result = _handle_vision_chat({"image": "x"})
        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["error"]["code"] == "E_INVALID_PARAMS"

    def test_validates_image(self) -> None:
        """缺少 image 应返回参数错误。"""
        result = _handle_vision_chat({"prompt": "x"})
        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["error"]["code"] == "E_INVALID_PARAMS"

    def test_returns_json(self) -> None:
        """正常调用应返回 JSON 结构。"""
        result = _handle_vision_chat(
            {
                "prompt": "描述图片",
                "image": "data:image/png;base64,abc",
            }
        )
        parsed = json.loads(result)
        assert "ok" in parsed


class TestAudioChatHandler:
    """openclaw_audio_chat handler 测试。"""

    def test_validates_prompt(self) -> None:
        """缺少 prompt 应返回参数错误。"""
        result = _handle_audio_chat({"audio": "x"})
        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["error"]["code"] == "E_INVALID_PARAMS"

    def test_validates_audio(self) -> None:
        """缺少 audio 应返回参数错误。"""
        result = _handle_audio_chat({"prompt": "x"})
        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["error"]["code"] == "E_INVALID_PARAMS"


class TestVideoChatHandler:
    """openclaw_video_chat handler 测试。"""

    def test_validates_prompt(self) -> None:
        """缺少 prompt 应返回参数错误。"""
        result = _handle_video_chat({"video": "x"})
        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["error"]["code"] == "E_INVALID_PARAMS"

    def test_validates_video(self) -> None:
        """缺少 video 应返回参数错误。"""
        result = _handle_video_chat({"prompt": "x"})
        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["error"]["code"] == "E_INVALID_PARAMS"

    def test_validates_frames_type(self) -> None:
        """frames 非数组应返回参数错误。"""
        result = _handle_video_chat(
            {"prompt": "x", "video": "x", "frames": "not-a-list"}
        )
        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["error"]["code"] == "E_INVALID_PARAMS"



class TestRunAsync:
    """_run_async 在已有事件循环中也能正确运行。"""

    def test_chat_handler_inside_running_loop(self) -> None:
        """在已有事件循环内调用同步 handler 不应抛 RuntimeError。

        M32.23：handler 改用 _run_with 后会在同一事件循环 await pipeline.close()，
        mock 必须提供 async close，否则 TypeError: 'MagicMock' object can't be awaited。
        """

        async def _inner() -> None:
            result = _handle_chat({"prompt": "你好", "level": "L1"})
            parsed = json.loads(result)
            assert parsed["ok"] is True

        with patch("omni_openclaw.tools.AicgPipeline") as mock_aicg:
            mock_aicg.return_value.chat = AsyncMock(
                return_value={"ok": True, "content": "hi"}
            )
            mock_aicg.return_value.close = AsyncMock()
            asyncio.run(_inner())

    def test_run_with_closes_resource(self) -> None:
        """_run_with 必须在协程结束后关闭资源（M32.23 资源泄漏回归）。

        回归背景：此前工具 handler 用 _run_async 直接运行协程，构造的
        client/pipeline 从不 close，长驻进程每次工具调用泄漏一个 httpx
        连接池。
        """
        from omni_openclaw.tools import _run_with

        class FakeResource:
            def __init__(self) -> None:
                self.closed = False

            async def close(self) -> None:
                self.closed = True

        async def _work() -> str:
            return "done"

        resource = FakeResource()
        result = _run_with(resource, _work())
        assert result == "done"
        assert resource.closed is True

    def test_run_with_closes_resource_on_error(self) -> None:
        """协程抛异常时资源也必须关闭（finally 语义）。"""
        from omni_openclaw.tools import _run_with

        class FakeResource:
            def __init__(self) -> None:
                self.closed = False

            async def close(self) -> None:
                self.closed = True

        async def _boom() -> str:
            raise RuntimeError("simulated failure")

        resource = FakeResource()
        with pytest.raises(RuntimeError, match="simulated failure"):
            _run_with(resource, _boom())
        assert resource.closed is True


# ---------------------------------------------------------------------------
# M32.26：handler happy path 覆盖（fake 客户端注入，零网络）
# ---------------------------------------------------------------------------
class _FakeResourceBase:
    """fake 客户端基类：记录 config / 方法调用，async close 置 closed 标志。"""

    def __init__(self, config: Any) -> None:
        self.config = config
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeOpenClawClient(_FakeResourceBase):
    """fake OpenClawClient：last 记录最近实例便于断言。"""

    last: "_FakeOpenClawClient | None" = None

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        _FakeOpenClawClient.last = self

    async def send_wechat_message(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("send_wechat_message", kwargs))
        return {"ok": True, "sent": kwargs}

    async def audio_chat(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("audio_chat", kwargs))
        return {"ok": True, "text": "音频理解结果"}

    async def video_chat(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("video_chat", kwargs))
        return {"ok": True, "text": "视频理解结果"}


class _FakeHomeAssistantClient(_FakeResourceBase):
    """fake HomeAssistantClient。"""

    last: "_FakeHomeAssistantClient | None" = None

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        _FakeHomeAssistantClient.last = self

    async def control_light(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("control_light", kwargs))
        return {"ok": True, "light": kwargs}

    async def control_fan(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("control_fan", kwargs))
        return {"ok": True, "fan": kwargs}

    async def control_air_purifier(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("control_air_purifier", kwargs))
        return {"ok": True, "air_purifier": kwargs}

    async def speaker_say(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("speaker_say", kwargs))
        return {"ok": True, "say": kwargs}


class _FakeAicgPipeline(_FakeResourceBase):
    """fake AicgPipeline。"""

    last: "_FakeAicgPipeline | None" = None

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        _FakeAicgPipeline.last = self

    async def generate_image(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("generate_image", kwargs))
        return {"ok": True, "image": kwargs}

    async def text_to_speech(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("text_to_speech", kwargs))
        return {"ok": True, "speech": kwargs}


class _FakeClusterChecker:
    """fake ClusterChecker：device_lookup 为同步方法（与真实实现一致）。"""

    last: "_FakeClusterChecker | None" = None

    def __init__(self, config: Any) -> None:
        self.config = config
        self.queries: list[str] = []
        _FakeClusterChecker.last = self

    def device_lookup(self, query: str) -> dict[str, Any]:
        self.queries.append(query)
        return {"ok": True, "results": [query]}


class TestSendWeChatDeprecated:
    """_handle_send_wechat 弃用行为（M38 起由 omni_wechat 直连 iLink 替代）。"""

    def test_send_wechat_returns_deprecated(self) -> None:
        """合法入参返回 E_DEPRECATED 并指向 wechat_send。"""
        result = json.loads(
            _handle_send_wechat(
                {"message": "你好", "target": "user1", "account": "bot1"}
            )
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "E_DEPRECATED"
        assert "wechat_send" in result["error"]["message"]
        assert result["error"]["replacement"] == "wechat_send"

    def test_send_wechat_default_target_and_account(self) -> None:
        """缺省 target/account 同样返回 E_DEPRECATED。"""
        result = json.loads(_handle_send_wechat({"message": "默认目标"}))
        assert result["ok"] is False
        assert result["error"]["code"] == "E_DEPRECATED"


class TestAudioChatHappyPath:
    """_handle_audio_chat happy path（tools.py 234-244 行）。"""

    def test_audio_chat_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("omni_openclaw.tools.OpenClawClient", _FakeOpenClawClient)
        result = json.loads(
            _handle_audio_chat(
                {"prompt": "这段音频说了什么", "audio": "QUJD", "format": "mp3"}
            )
        )
        assert result["ok"] is True
        assert result["text"] == "音频理解结果"
        client = _FakeOpenClawClient.last
        assert client is not None
        assert client.calls == [
            (
                "audio_chat",
                {"prompt": "这段音频说了什么", "audio_base64": "QUJD", "format_": "mp3"},
            )
        ]
        assert client.closed is True

    def test_audio_chat_default_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("omni_openclaw.tools.OpenClawClient", _FakeOpenClawClient)
        result = json.loads(_handle_audio_chat({"prompt": "听", "audio": "QUJD"}))
        assert result["ok"] is True
        client = _FakeOpenClawClient.last
        assert client is not None
        _, kwargs = client.calls[0]
        assert kwargs["format_"] == "wav"


class TestVideoChatHappyPath:
    """_handle_video_chat happy path（tools.py 270-278 行）。"""

    def test_video_chat_success_with_frames(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("omni_openclaw.tools.OpenClawClient", _FakeOpenClawClient)
        frames = ["data:image/png;base64,f1", "data:image/png;base64,f2"]
        result = json.loads(
            _handle_video_chat(
                {"prompt": "视频内容", "video": "https://v", "frames": frames}
            )
        )
        assert result["ok"] is True
        client = _FakeOpenClawClient.last
        assert client is not None
        assert client.calls == [
            (
                "video_chat",
                {"prompt": "视频内容", "video_base64_or_url": "https://v", "frames": frames},
            )
        ]
        assert client.closed is True

    def test_video_chat_without_frames(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("omni_openclaw.tools.OpenClawClient", _FakeOpenClawClient)
        result = json.loads(_handle_video_chat({"prompt": "看", "video": "https://v"}))
        assert result["ok"] is True
        client = _FakeOpenClawClient.last
        assert client is not None
        _, kwargs = client.calls[0]
        assert kwargs["frames"] is None


class TestControlLightHandler:
    """_handle_control_light（tools.py 481-498 行）。"""

    def test_control_light_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "omni_openclaw.tools.HomeAssistantClient", _FakeHomeAssistantClient
        )
        result = json.loads(
            _handle_control_light(
                {
                    "entity_id": "light.living_room",
                    "on": True,
                    "brightness": 128,
                    "color_temp": 300,
                }
            )
        )
        assert result["ok"] is True
        client = _FakeHomeAssistantClient.last
        assert client is not None
        assert client.calls == [
            (
                "control_light",
                {
                    "entity_id": "light.living_room",
                    "on": True,
                    "brightness": 128,
                    "color_temp": 300,
                },
            )
        ]
        assert client.closed is True

    def test_control_light_validates_entity_id(self) -> None:
        result = json.loads(_handle_control_light({"on": True}))
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    def test_control_light_validates_on_is_bool(self) -> None:
        """on 非布尔（如字符串 "yes"）→ E_INVALID_PARAMS，不构造客户端。"""
        result = json.loads(
            _handle_control_light({"entity_id": "light.x", "on": "yes"})
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"
        assert "布尔" in result["error"]["message"]


class TestControlFanHandler:
    """_handle_control_fan（tools.py 510-526 行）。"""

    def test_control_fan_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "omni_openclaw.tools.HomeAssistantClient", _FakeHomeAssistantClient
        )
        result = json.loads(
            _handle_control_fan(
                {"entity_id": "fan.bedroom", "on": True, "speed": "high"}
            )
        )
        assert result["ok"] is True
        client = _FakeHomeAssistantClient.last
        assert client is not None
        assert client.calls == [
            (
                "control_fan",
                {"entity_id": "fan.bedroom", "on": True, "speed": "high"},
            )
        ]
        assert client.closed is True

    def test_control_fan_validates_entity_id(self) -> None:
        result = json.loads(_handle_control_fan({"on": False}))
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    def test_control_fan_validates_on_is_bool(self) -> None:
        result = json.loads(_handle_control_fan({"entity_id": "fan.x", "on": 1}))
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"
        assert "布尔" in result["error"]["message"]


class TestControlAirPurifierHandler:
    """_handle_control_air_purifier（tools.py 538-554 行）。"""

    def test_control_air_purifier_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "omni_openclaw.tools.HomeAssistantClient", _FakeHomeAssistantClient
        )
        result = json.loads(
            _handle_control_air_purifier(
                {"entity_id": "air_purifier.room", "on": False, "mode": "auto"}
            )
        )
        assert result["ok"] is True
        client = _FakeHomeAssistantClient.last
        assert client is not None
        assert client.calls == [
            (
                "control_air_purifier",
                {"entity_id": "air_purifier.room", "on": False, "mode": "auto"},
            )
        ]
        assert client.closed is True

    def test_control_air_purifier_validates_entity_id(self) -> None:
        result = json.loads(_handle_control_air_purifier({"on": True}))
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    def test_control_air_purifier_validates_on_is_bool(self) -> None:
        result = json.loads(
            _handle_control_air_purifier({"entity_id": "air_purifier.x", "on": "on"})
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"
        assert "布尔" in result["error"]["message"]


class TestSpeakerSayHappyPath:
    """_handle_speaker_say happy path（tools.py 582-585 行）。"""

    def test_speaker_say_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "omni_openclaw.tools.HomeAssistantClient", _FakeHomeAssistantClient
        )
        result = json.loads(_handle_speaker_say({"text": "请注意安全"}))
        assert result["ok"] is True
        client = _FakeHomeAssistantClient.last
        assert client is not None
        assert client.calls == [("speaker_say", {"text": "请注意安全"})]
        assert client.closed is True

    def test_speaker_say_validates_text(self) -> None:
        result = json.loads(_handle_speaker_say({}))
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"


class TestDeviceLookupHappyPath:
    """_handle_device_lookup happy path（tools.py 605-608 行，同步调用）。"""

    def test_device_lookup_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("omni_openclaw.tools.ClusterChecker", _FakeClusterChecker)
        result = json.loads(_handle_device_lookup({"query": "spark01"}))
        assert result["ok"] is True
        assert result["results"] == ["spark01"]
        checker = _FakeClusterChecker.last
        assert checker is not None
        assert checker.queries == ["spark01"]

    def test_device_lookup_validates_query(self) -> None:
        result = json.loads(_handle_device_lookup({}))
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"


class TestGenerateImageHappyPath:
    """_handle_generate_image happy path（tools.py 644-654 行）。"""

    def test_generate_image_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("omni_openclaw.tools.AicgPipeline", _FakeAicgPipeline)
        result = json.loads(
            _handle_generate_image({"prompt": "一只猫", "width": 512, "height": 768})
        )
        assert result["ok"] is True
        pipeline = _FakeAicgPipeline.last
        assert pipeline is not None
        assert pipeline.calls == [
            ("generate_image", {"prompt": "一只猫", "width": 512, "height": 768})
        ]
        assert pipeline.closed is True

    def test_generate_image_default_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("omni_openclaw.tools.AicgPipeline", _FakeAicgPipeline)
        result = json.loads(_handle_generate_image({"prompt": "一只猫"}))
        assert result["ok"] is True
        pipeline = _FakeAicgPipeline.last
        assert pipeline is not None
        _, kwargs = pipeline.calls[0]
        assert kwargs["width"] == 1024
        assert kwargs["height"] == 1024


class TestTextToSpeechHappyPath:
    """_handle_text_to_speech happy path（tools.py 666-675 行）。"""

    def test_text_to_speech_success_with_output_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("omni_openclaw.tools.AicgPipeline", _FakeAicgPipeline)
        result = json.loads(
            _handle_text_to_speech({"text": "你好世界", "output_path": "/tmp/out.wav"})
        )
        assert result["ok"] is True
        pipeline = _FakeAicgPipeline.last
        assert pipeline is not None
        assert pipeline.calls == [
            ("text_to_speech", {"text": "你好世界", "output_path": "/tmp/out.wav"})
        ]
        assert pipeline.closed is True

    def test_text_to_speech_default_output_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("omni_openclaw.tools.AicgPipeline", _FakeAicgPipeline)
        result = json.loads(_handle_text_to_speech({"text": "你好"}))
        assert result["ok"] is True
        pipeline = _FakeAicgPipeline.last
        assert pipeline is not None
        _, kwargs = pipeline.calls[0]
        assert kwargs["output_path"] is None
