"""基于 VAD 的唤醒词后端：检测到连续语音活动即触发唤醒，由上层做热词校验。"""

from __future__ import annotations

import time

from ..errors import VoiceBackendError
from .base import VADBackend, WakeWordBackend


class VADWakeWord(WakeWordBackend):
    """用 VAD 做语音活动触发的唤醒后端。

    连续语音帧达到 ``speech_frames`` 阈值后返回高置信度；
    触发后需经 ``cooldown_frames`` 帧冷却才能再次触发，避免重复。

    ``hangover_frames``：语音段内容忍的短暂能量凹陷帧数（如「雪莉」双音节
    之间的停顿）。凹陷未超过该预算时连续计数保留；凹陷超预算才清零。
    默认为 0（严格连续，向后兼容）。

    启动时设 ``startup_grace_s`` 秒稳定期（忽略语音），防止麦克风启动
    瞬间的电平脉冲误触发；重置后同样清理 VAD 内部滑窗缓冲。

    仅检测语音活动，需要 pipeline 层通过 ASR 做热词二次校验。
    """

    requires_hotword_check = True

    def __init__(
        self,
        vad: VADBackend,
        sample_rate: int = 16000,
        frame_ms: int = 32,
        speech_frames: int = 15,
        cooldown_ms: int = 3000,
        startup_grace_s: float = 1.5,
        hangover_frames: int = 0,
    ) -> None:
        self._vad = vad
        self._sample_rate = sample_rate
        self._frame_ms = frame_ms
        self._speech_threshold = speech_frames
        self._cooldown_frames = cooldown_ms // frame_ms
        self._hangover_frames = max(0, hangover_frames)
        self._hangover_left = self._hangover_frames
        self._speech_count = 0
        self._cooldown = 0
        self._triggered = False
        self._startup_deadline = time.monotonic() + startup_grace_s
        self._grace_frames = int(startup_grace_s * 1000 / frame_ms)
        self._frame_idx = 0

    def detect(self, frame: bytes) -> float:
        self._frame_idx += 1
        if self._frame_idx <= self._grace_frames:
            try:
                self._vad.is_speech(frame, self._sample_rate)
            except Exception:
                pass
            return 0.0
        if time.monotonic() < self._startup_deadline:
            return 0.0
        if self._cooldown > 0:
            self._cooldown -= 1
            try:
                self._vad.is_speech(frame, self._sample_rate)
            except Exception:
                pass
            return 0.0
        if self._triggered:
            return 0.0
        try:
            is_speech = self._vad.is_speech(frame, self._sample_rate)
        except Exception:
            return 0.0
        if is_speech:
            self._speech_count += 1
            self._hangover_left = self._hangover_frames
            if self._speech_count >= self._speech_threshold:
                self._triggered = True
                self._speech_count = 0
                return 1.0
        elif self._speech_count > 0 and self._hangover_left > 0:
            # 语音段内的短暂凹陷：消耗 hangover 预算，保留连续计数
            self._hangover_left -= 1
        else:
            self._speech_count = 0
            self._hangover_left = self._hangover_frames
        return 0.0

    def reset(self) -> None:
        """重置触发状态（热词校验通过或未通过后调用，准备下一轮检测）。"""
        self._triggered = False
        self._speech_count = 0
        self._hangover_left = self._hangover_frames
        self._cooldown = self._cooldown_frames
        if hasattr(self._vad, "_buf"):
            self._vad._buf = bytearray()
            self._vad._warm = False
