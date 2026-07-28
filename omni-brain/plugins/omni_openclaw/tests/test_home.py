"""omni_openclaw 智能家居/Home Assistant 桥接测试。"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from omni_openclaw.config import OpenClawConfig
from omni_openclaw.home import (
    SPEAKER_SAY_SCRIPT,
    VOICE_MODE_ENTITY,
    HomeAssistantClient,
)


class FakeBackend:
    """内存中的 fake HA backend，用于测试。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: dict[tuple[str, str], tuple[int, Any]] = {}

    def add_response(self, method: str, path: str, status: int, body: Any) -> None:
        """注册对 method+path 的响应。"""
        self.responses[(method.upper(), path)] = (status, body)

    async def request(self, method: str, path: str, **kwargs: Any) -> tuple[int, Any]:
        """模拟 HTTP 请求。"""
        self.calls.append({"method": method.upper(), "path": path, "kwargs": kwargs})
        status, body = self.responses.get(
            (method.upper(), path),
            (404, {"error": "not found"}),
        )
        return status, body


@pytest.fixture
def fake_backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def client(fake_backend: FakeBackend) -> HomeAssistantClient:
    return HomeAssistantClient(
        config=OpenClawConfig(
            ha_endpoint="http://ha.test",
            ha_token="test-token",
        ),
        backend=fake_backend,
    )


class TestControlLight:
    """灯光控制测试。"""

    @pytest.mark.asyncio
    async def test_turn_on(self, client: HomeAssistantClient, fake_backend: FakeBackend) -> None:
        """开灯应调用 light/turn_on 并携带 entity_id。"""
        fake_backend.add_response("POST", "/api/services/light/turn_on", 200, [])
        result = await client.control_light("light.living_room", on=True)
        assert result["ok"] is True

        call = fake_backend.calls[-1]
        assert call["method"] == "POST"
        assert call["path"] == "/api/services/light/turn_on"
        assert call["kwargs"]["json"] == {"entity_id": "light.living_room"}
        assert call["kwargs"]["headers"]["Authorization"] == "Bearer test-token"
        assert call["kwargs"]["headers"]["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_turn_on_with_options(self, client: HomeAssistantClient, fake_backend: FakeBackend) -> None:
        """开灯附带亮度与色温时应正确构造请求体。"""
        fake_backend.add_response("POST", "/api/services/light/turn_on", 200, [])
        result = await client.control_light(
            "light.bedroom",
            on=True,
            brightness=180,
            color_temp=350,
        )
        assert result["ok"] is True

        call = fake_backend.calls[-1]
        assert call["kwargs"]["json"] == {
            "entity_id": "light.bedroom",
            "brightness": 180,
            "color_temp": 350,
        }

    @pytest.mark.asyncio
    async def test_turn_off(self, client: HomeAssistantClient, fake_backend: FakeBackend) -> None:
        """关灯应调用 light/turn_off。"""
        fake_backend.add_response("POST", "/api/services/light/turn_off", 200, [])
        result = await client.control_light("light.living_room", on=False)
        assert result["ok"] is True

        call = fake_backend.calls[-1]
        assert call["path"] == "/api/services/light/turn_off"
        assert call["kwargs"]["json"] == {"entity_id": "light.living_room"}

    @pytest.mark.asyncio
    async def test_empty_entity_id(self, client: HomeAssistantClient) -> None:
        """空 entity_id 应返回参数错误。"""
        result = await client.control_light("", on=True)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    @pytest.mark.asyncio
    async def test_service_error(self, client: HomeAssistantClient, fake_backend: FakeBackend) -> None:
        """HA 返回非 200 时应包装为 E_HA_SERVICE_ERROR。"""
        fake_backend.add_response(
            "POST",
            "/api/services/light/turn_on",
            500,
            {"error": "internal"},
        )
        result = await client.control_light("light.living_room", on=True)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_HA_SERVICE_ERROR"
        assert result["error"]["status_code"] == 500


class TestControlFan:
    """风扇控制测试。"""

    @pytest.mark.asyncio
    async def test_turn_on_with_speed(
        self,
        client: HomeAssistantClient,
        fake_backend: FakeBackend,
    ) -> None:
        """开风扇并指定风速。"""
        fake_backend.add_response("POST", "/api/services/fan/turn_on", 200, [])
        result = await client.control_fan("fan.bedroom", on=True, speed="medium")
        assert result["ok"] is True

        call = fake_backend.calls[-1]
        assert call["path"] == "/api/services/fan/turn_on"
        assert call["kwargs"]["json"] == {
            "entity_id": "fan.bedroom",
            "speed": "medium",
        }

    @pytest.mark.asyncio
    async def test_turn_off(self, client: HomeAssistantClient, fake_backend: FakeBackend) -> None:
        """关风扇应调用 fan/turn_off。"""
        fake_backend.add_response("POST", "/api/services/fan/turn_off", 200, [])
        result = await client.control_fan("fan.bedroom", on=False)
        assert result["ok"] is True

        call = fake_backend.calls[-1]
        assert call["path"] == "/api/services/fan/turn_off"

    @pytest.mark.asyncio
    async def test_empty_entity_id(self, client: HomeAssistantClient) -> None:
        """空 entity_id 应返回参数错误。"""
        result = await client.control_fan("   ", on=True)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"


class TestControlAirPurifier:
    """空气净化器控制测试。"""

    @pytest.mark.asyncio
    async def test_turn_on_with_mode(
        self,
        client: HomeAssistantClient,
        fake_backend: FakeBackend,
    ) -> None:
        """开启空气净化器并指定模式。"""
        fake_backend.add_response("POST", "/api/services/fan/turn_on", 200, [])
        result = await client.control_air_purifier(
            "fan.purifier",
            on=True,
            mode="auto",
        )
        assert result["ok"] is True

        call = fake_backend.calls[-1]
        assert call["path"] == "/api/services/fan/turn_on"
        assert call["kwargs"]["json"] == {
            "entity_id": "fan.purifier",
            "mode": "auto",
        }

    @pytest.mark.asyncio
    async def test_turn_off(self, client: HomeAssistantClient, fake_backend: FakeBackend) -> None:
        """关闭空气净化器应调用 fan/turn_off。"""
        fake_backend.add_response("POST", "/api/services/fan/turn_off", 200, [])
        result = await client.control_air_purifier("fan.purifier", on=False)
        assert result["ok"] is True

        call = fake_backend.calls[-1]
        assert call["path"] == "/api/services/fan/turn_off"

    @pytest.mark.asyncio
    async def test_empty_entity_id(self, client: HomeAssistantClient) -> None:
        """空 entity_id 应返回参数错误。"""
        result = await client.control_air_purifier("", on=True)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"


class TestSpeaker:
    """扬声器语音模式与播报测试。"""

    @pytest.mark.asyncio
    async def test_voice_on(self, client: HomeAssistantClient, fake_backend: FakeBackend) -> None:
        """开启语音模式应调用 input_boolean/turn_on。"""
        fake_backend.add_response(
            "POST",
            "/api/services/input_boolean/turn_on",
            200,
            [],
        )
        result = await client.speaker_voice_on()
        assert result["ok"] is True

        call = fake_backend.calls[-1]
        assert call["path"] == "/api/services/input_boolean/turn_on"
        assert call["kwargs"]["json"] == {"entity_id": VOICE_MODE_ENTITY}

    @pytest.mark.asyncio
    async def test_voice_off(self, client: HomeAssistantClient, fake_backend: FakeBackend) -> None:
        """关闭语音模式应调用 input_boolean/turn_off。"""
        fake_backend.add_response(
            "POST",
            "/api/services/input_boolean/turn_off",
            200,
            [],
        )
        result = await client.speaker_voice_off()
        assert result["ok"] is True

        call = fake_backend.calls[-1]
        assert call["path"] == "/api/services/input_boolean/turn_off"
        assert call["kwargs"]["json"] == {"entity_id": VOICE_MODE_ENTITY}

    @pytest.mark.asyncio
    async def test_say_success(self, client: HomeAssistantClient, fake_backend: FakeBackend) -> None:
        """speaker_say 应优先调用 tts/speak。"""
        fake_backend.add_response("POST", "/api/services/tts/speak", 200, [])
        result = await client.speaker_say("你好，世界")
        assert result["ok"] is True

        call = fake_backend.calls[-1]
        assert call["path"] == "/api/services/tts/speak"
        assert call["kwargs"]["json"] == {"message": "你好，世界"}

    @pytest.mark.asyncio
    async def test_say_fallback_to_script(
        self,
        client: HomeAssistantClient,
        fake_backend: FakeBackend,
    ) -> None:
        """tts/speak 不可用时回退到 script/turn_on。"""
        fake_backend.add_response(
            "POST",
            "/api/services/tts/speak",
            404,
            {"error": "not found"},
        )
        fake_backend.add_response(
            "POST",
            "/api/services/script/turn_on",
            200,
            [],
        )
        result = await client.speaker_say("回退播报")
        assert result["ok"] is True

        calls = fake_backend.calls
        assert calls[-2]["path"] == "/api/services/tts/speak"
        assert calls[-1]["path"] == "/api/services/script/turn_on"
        assert calls[-1]["kwargs"]["json"] == {
            "entity_id": SPEAKER_SAY_SCRIPT,
            "variables": {"message": "回退播报"},
        }

    @pytest.mark.asyncio
    async def test_say_fallback_for_400_and_501(
        self,
        client: HomeAssistantClient,
        fake_backend: FakeBackend,
    ) -> None:
        """400 与 501 状态码也应触发脚本回退。"""
        fake_backend.add_response(
            "POST",
            "/api/services/tts/speak",
            501,
            {"error": "not implemented"},
        )
        fake_backend.add_response(
            "POST",
            "/api/services/script/turn_on",
            200,
            [],
        )
        result = await client.speaker_say("501 fallback")
        assert result["ok"] is True
        assert fake_backend.calls[-1]["path"] == "/api/services/script/turn_on"

    @pytest.mark.asyncio
    async def test_say_tts_error(self, client: HomeAssistantClient, fake_backend: FakeBackend) -> None:
        """tts/speak 返回非回退错误码时应失败。"""
        fake_backend.add_response(
            "POST",
            "/api/services/tts/speak",
            500,
            {"error": "internal"},
        )
        result = await client.speaker_say("失败测试")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_HA_TTS_ERROR"

    @pytest.mark.asyncio
    async def test_say_empty_text(self, client: HomeAssistantClient) -> None:
        """空 text 应返回参数错误。"""
        result = await client.speaker_say("")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"


class TestErrors:
    """异常与错误处理测试。"""

    @pytest.mark.asyncio
    async def test_timeout(self, client: HomeAssistantClient, fake_backend: FakeBackend) -> None:
        """后端抛 TimeoutError 时应返回 E_HA_UNAVAILABLE。"""

        async def raise_timeout(*args: Any, **kwargs: Any) -> Any:
            raise TimeoutError("connection timeout")

        fake_backend.request = raise_timeout  # type: ignore[assignment]
        result = await client.control_light("light.x", on=True)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_HA_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_generic_exception(self, client: HomeAssistantClient, fake_backend: FakeBackend) -> None:
        """后端抛其他异常时应返回 E_HA_ERROR。"""

        async def raise_exc(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

        fake_backend.request = raise_exc  # type: ignore[assignment]
        result = await client.control_air_purifier("fan.x", on=True)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_HA_ERROR"

    @pytest.mark.asyncio
    async def test_speaker_say_timeout(self, client: HomeAssistantClient, fake_backend: FakeBackend) -> None:
        """tts/speak 请求超时时应返回 E_HA_UNAVAILABLE。"""

        async def raise_timeout(*args: Any, **kwargs: Any) -> Any:
            raise TimeoutError("connection timeout")

        fake_backend.request = raise_timeout  # type: ignore[assignment]
        result = await client.speaker_say("超时测试")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_HA_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_speaker_say_generic_exception(
        self,
        client: HomeAssistantClient,
        fake_backend: FakeBackend,
    ) -> None:
        """tts/speak 抛非超时异常时应返回 E_HA_ERROR。"""

        async def raise_exc(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

        fake_backend.request = raise_exc  # type: ignore[assignment]
        result = await client.speaker_say("异常测试")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_HA_ERROR"


class TestLifecycle:
    """生命周期与真实 backend 构造测试。"""

    @pytest.mark.asyncio
    async def test_close_releases_owned_backend(self) -> None:
        """close 应释放默认创建的 backend。"""
        client = HomeAssistantClient(
            config=OpenClawConfig(ha_endpoint="http://ha.test"),
        )
        client._backend = MagicMock()
        client._backend.close = AsyncMock()
        await client.close()
        client._backend.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_skips_injected_backend(self, client: HomeAssistantClient) -> None:
        """注入的 backend 不应被 close 释放。"""
        client._backend = MagicMock()
        client._backend.close = AsyncMock()
        await client.close()
        client._backend.close.assert_not_awaited()

    @patch("omni_openclaw.home.HttpxBackend")
    def test_default_backend_uses_ha_endpoint(self, mock_backend: MagicMock) -> None:
        """未注入 backend 时应以 HA endpoint 构造 HttpxBackend。"""
        HomeAssistantClient(
            config=OpenClawConfig(
                ha_endpoint="http://ha.example.com:8123",
                timeout_s=7.0,
            ),
        )
        mock_backend.assert_called_once()
        call_args = mock_backend.call_args
        cfg = call_args.args[0]
        assert cfg.gateway == "http://ha.example.com:8123"
        assert cfg.timeout_s == 7.0
