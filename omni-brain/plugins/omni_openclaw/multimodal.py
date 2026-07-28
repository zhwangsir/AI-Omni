"""omni_openclaw 多模态 Nemotron 调用封装。

提供 vision_chat / audio_chat / video_chat 的高层封装，
底层通过 OpenClaw 网关的 OpenAI 兼容 ``/v1/chat/completions`` 调用 Nemotron（L1）。
"""

from __future__ import annotations

from typing import Any


def _build_content_parts(
    prompt: str,
    media_parts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """构造 OpenAI 兼容 messages.content 列表（text + image_url/input_audio）。"""
    return [{"type": "text", "text": prompt}, *media_parts]


def build_vision_message(
    prompt: str,
    image_base64_or_url: str,
    detail: str = "auto",
) -> dict[str, Any]:
    """构造单图 vision 请求消息。

    ``image_base64_or_url`` 支持：
    - HTTP(S) URL：``https://example.com/image.png``
    - Base64 data URL：``data:image/png;base64,...``
    - 裸 base64 字符串：自动包装为 data URL
    """
    url = image_base64_or_url
    if url.startswith("http://") or url.startswith("https://"):
        pass
    elif not url.startswith("data:"):
        url = f"data:image/png;base64,{url}"

    return {
        "role": "user",
        "content": _build_content_parts(
            prompt,
            [{"type": "image_url", "image_url": {"url": url, "detail": detail}}],
        ),
    }


def build_audio_message(
    prompt: str,
    audio_base64: str,
    format_: str = "wav",
) -> dict[str, Any]:
    """构造音频理解请求消息（OpenAI input_audio 格式）。"""
    return {
        "role": "user",
        "content": _build_content_parts(
            prompt,
            [{"type": "input_audio", "input_audio": {"data": audio_base64, "format": format_}}],
        ),
    }


def build_video_message(
    prompt: str,
    video_base64_or_url: str,
    frames: list[str] | None = None,
) -> dict[str, Any]:
    """构造视频理解请求消息。

    优先使用帧序列方式（抽取关键帧以 base64 data URL 传入），
    若后端支持原生视频 URL，也可传入单个 video URL。
    """
    if frames:
        media_parts: list[dict[str, Any]] = [
            {"type": "image_url", "image_url": {"url": frame}} for frame in frames
        ]
        return {
            "role": "user",
            "content": _build_content_parts(prompt, media_parts),
        }

    url = video_base64_or_url
    if url.startswith("http://") or url.startswith("https://"):
        pass
    elif not url.startswith("data:"):
        url = f"data:video/mp4;base64,{url}"

    return {
        "role": "user",
        "content": _build_content_parts(
            prompt,
            [{"type": "image_url", "image_url": {"url": url}}],
        ),
    }


def parse_chat_response(body: dict[str, Any]) -> str:
    """从 OpenAI 兼容 chat completion 响应中提取 assistant 文本。"""
    choices = body.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    return ""
