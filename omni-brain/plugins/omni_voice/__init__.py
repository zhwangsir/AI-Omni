"""omni_voice：语音交互插件（唤醒 → VAD → ASR → LLM Agent → TTS）。

对外暴露两个入口：
- ``register(ctx)``：Hermes/WeBrain 旧式插件契约（向后兼容，不破坏既有 307 个测试）
- ``VoicePlugin``：M15 ``OmniPlugin`` 子类，经 ``omni_sdk.compat.RegisterCompatPlugin``
  包装 ``register(ctx)``，``on_load(ctx)`` 调用 ``register`` 把 voice_* 工具注册到
  ``ctx.tool_registry``。迁移期两条入口并存（AGENTS.md §7 / CLAUDE.md §2.1）。

ASR/TTS/LLM 统一走 OpenClaw 网关 OpenAI 兼容端点（AGENTS.md §四），
本地仅保留纯 Python 能量 VAD；音频采集/播放（sounddevice）仍惰性导入可缺省，
import 本包不会拉入任何第三方库。
"""

from __future__ import annotations

from typing import Any

from omni_sdk.compat import RegisterCompatPlugin

__all__ = ["register", "VoicePlugin"]


def register(ctx) -> None:
    """Hermes/WeBrain 插件入口：把全部 voice_* tools 注册到插件上下文。"""
    from .tools import register as _register

    _register(ctx)


class VoicePlugin(RegisterCompatPlugin):
    """omni_voice 的 ``OmniPlugin`` 适配子类。

    经 :class:`RegisterCompatPlugin` 包装现有 ``register(ctx)`` 函数：
    ``on_load(ctx)`` 构造 legacy ctx 适配器并调用 ``register(adapter)``，
    使 7 个 voice_* 工具注册到 ``ctx.tool_registry``、事件总线接入运行时。
    保留 ``register(ctx)`` 入口向后兼容（M15 迁移期不破坏既有测试）。
    """

    name: str = "omni_voice"
    version: str = "0.1.0"
    description: str = "本地语音交互 MVP 插件 - 唤醒/VAD/ASR/LLM Agent/TTS 管道"
    emoji: str = "🎙️"

    def __init__(self) -> None:
        super().__init__(register_func=register)
