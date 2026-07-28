"""omni_openclaw 多模态消息构造器测试。"""

from __future__ import annotations

from typing import Any

import pytest

from omni_openclaw.multimodal import (
    build_audio_message,
    build_vision_message,
    build_video_message,
    parse_chat_response,
)


class TestBuildVisionMessage:
    """vision 消息构造测试。"""

    def test_wraps_raw_base64(self) -> None:
        """裸 base64 应自动包装为 data URL。"""
        msg = build_vision_message("描述", "iVBORw0KGgo=")
        url = msg["content"][1]["image_url"]["url"]
        assert url == "data:image/png;base64,iVBORw0KGgo="

    def test_keeps_data_url(self) -> None:
        """已有 data URL 应直接透传。"""
        msg = build_vision_message("描述", "data:image/jpeg;base64,abc")
        url = msg["content"][1]["image_url"]["url"]
        assert url == "data:image/jpeg;base64,abc"

    def test_keeps_http_url(self) -> None:
        """HTTP URL 应直接透传。"""
        msg = build_vision_message("描述", "https://example.com/img.png")
        url = msg["content"][1]["image_url"]["url"]
        assert url == "https://example.com/img.png"

    def test_detail_default_is_auto(self) -> None:
        """默认 detail 为 auto。"""
        msg = build_vision_message("描述", "x")
        assert msg["content"][1]["image_url"]["detail"] == "auto"

    def test_detail_override(self) -> None:
        """可覆盖 detail。"""
        msg = build_vision_message("描述", "x", detail="high")
        assert msg["content"][1]["image_url"]["detail"] == "high"


class TestBuildAudioMessage:
    """audio 消息构造测试。"""

    def test_default_format_is_wav(self) -> None:
        """默认音频格式为 wav。"""
        msg = build_audio_message("转写", "YXVkaW8=")
        audio = msg["content"][1]["input_audio"]
        assert audio["data"] == "YXVkaW8="
        assert audio["format"] == "wav"

    def test_format_override(self) -> None:
        """可覆盖音频格式。"""
        msg = build_audio_message("转写", "YXVkaW8=", format_="mp3")
        assert msg["content"][1]["input_audio"]["format"] == "mp3"


class TestBuildVideoMessage:
    """video 消息构造测试。"""

    def test_wraps_raw_base64(self) -> None:
        """裸 base64 视频应包装为 data URL。"""
        msg = build_video_message("描述", "abc")
        url = msg["content"][1]["image_url"]["url"]
        assert url == "data:video/mp4;base64,abc"

    def test_keeps_http_url(self) -> None:
        """HTTP 视频 URL 应透传。"""
        msg = build_video_message("描述", "https://example.com/vid.mp4")
        url = msg["content"][1]["image_url"]["url"]
        assert url == "https://example.com/vid.mp4"

    def test_uses_frames_when_provided(self) -> None:
        """提供 frames 时优先使用关键帧序列。"""
        msg = build_video_message(
            "描述",
            "ignored",
            frames=["data:image/png;base64,f1", "data:image/png;base64,f2"],
        )
        content = msg["content"]
        assert len(content) == 3
        assert content[1]["image_url"]["url"] == "data:image/png;base64,f1"
        assert content[2]["image_url"]["url"] == "data:image/png;base64,f2"


class TestParseChatResponse:
    """响应解析测试。"""

    def test_extracts_content(self) -> None:
        """正常响应应提取 assistant content。"""
        body: dict[str, Any] = {
            "choices": [{"message": {"role": "assistant", "content": "hello"}}]
        }
        assert parse_chat_response(body) == "hello"

    def test_empty_choices(self) -> None:
        """空 choices 返回空字符串。"""
        assert parse_chat_response({"choices": []}) == ""

    def test_missing_content(self) -> None:
        """缺少 content 返回空字符串。"""
        assert parse_chat_response({"choices": [{"message": {}}]}) == ""

    def test_non_string_content(self) -> None:
        """content 非字符串返回空字符串。"""
        assert parse_chat_response({"choices": [{"message": {"content": 123}}]}) == ""
