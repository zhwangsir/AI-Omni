"""omni_openclaw 工具注册与 handler 测试。"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from omni_openclaw.tools import (
    _handle_audio_chat,
    _handle_chat,
    _handle_health,
    _handle_send_wechat,
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
        """所有 tool handler 必须返回 JSON 字符串。"""
        from omni_openclaw.tools import register

        register(ctx)
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
        """在已有事件循环内调用同步 handler 不应抛 RuntimeError。"""

        async def _inner() -> None:
            result = _handle_chat({"prompt": "你好", "level": "L1"})
            parsed = json.loads(result)
            assert parsed["ok"] is True

        with patch("omni_openclaw.tools.AicgPipeline") as mock_aicg:
            mock_aicg.return_value.chat = AsyncMock(
                return_value={"ok": True, "content": "hi"}
            )
            asyncio.run(_inner())
