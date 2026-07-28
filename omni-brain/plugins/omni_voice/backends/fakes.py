"""可编程 fake 后端：供单元/集成测试与 CLI ``--fake`` 演示使用。

每个 fake 都支持「脚本化队列 + 队列耗尽后的默认值」，
并记录调用信息供断言；不依赖任何音频硬件、模型或网络。
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any

from .base import ASRBackend, TTSBackend, VADBackend, WakeWordBackend


class FakeVAD(VADBackend):
    """按预设序列返回 is_speech 结果，耗尽后返回 ``default``。"""

    def __init__(self, results: list[bool] | None = None, default: bool = False):
        self._results: deque[bool] = deque(results or [])
        self.default = default
        self.calls = 0

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        self.calls += 1
        if self._results:
            return self._results.popleft()
        return self.default


class FakeASR(ASRBackend):
    """按预设队列返回转写文本，耗尽后返回空字符串。

    ``error`` 非空时首次调用抛出该异常（仅一次），用于测试异常恢复。
    """

    def __init__(self, transcripts: list[str] | None = None, error: Exception | None = None):
        self._queue: deque[str] = deque(transcripts or [])
        self.error = error
        self.calls: list[tuple[int, int, str | None]] = []

    def transcribe(self, pcm: bytes, sample_rate: int, language: str | None = None) -> str:
        self.calls.append((len(pcm), sample_rate, language))
        if self.error is not None:
            error, self.error = self.error, None
            raise error
        if self._queue:
            return self._queue.popleft()
        return ""


class FakeTTS(TTSBackend):
    """记录收到的文本，返回固定长度的静音 PCM16 字节。"""

    def __init__(self, pcm_bytes: int = 3200):
        self.pcm_bytes = pcm_bytes
        self.texts: list[str] = []
        #: 首次合成后置位，供测试/演示同步等待
        self.synthesized = threading.Event()

    def synthesize(self, text: str) -> bytes:
        self.texts.append(text)
        self.synthesized.set()
        return b"\x00" * self.pcm_bytes


class FakeWakeWord(WakeWordBackend):
    """按预设序列返回唤醒置信度，耗尽后返回 ``default``。"""

    def __init__(self, confidences: list[float] | None = None, default: float = 0.0):
        self._queue: deque[float] = deque(confidences or [])
        self.default = default
        self.calls = 0
        self.resets = 0

    def detect(self, frame: bytes) -> float:
        self.calls += 1
        if self._queue:
            return self._queue.popleft()
        return self.default

    def reset(self) -> None:
        self.resets += 1


class FakePlayer:
    """播放器 fake：记录播放内容，满足 pipeline.PlayerProtocol 的鸭子类型。"""

    def __init__(self):
        self.played: list[tuple[bytes, int]] = []
        #: 首次播放后置位，供测试/演示同步等待
        self.played_event = threading.Event()
        #: M7.5：stop() 调用次数（打断消费断言用）
        self.stop_calls = 0

    def play(self, pcm: bytes, sample_rate: int) -> None:
        self.played.append((pcm, sample_rate))
        self.played_event.set()

    def stop(self) -> None:
        self.stop_calls += 1


def fake_components(**overrides: Any) -> dict[str, Any]:
    """便捷工厂：返回一整套 fake 组件（可用关键字覆盖任意一个）。"""
    components: dict[str, Any] = {
        "vad": FakeVAD(),
        "asr": FakeASR(),
        "tts": FakeTTS(),
        "wake": FakeWakeWord(),
        "player": FakePlayer(),
    }
    components.update(overrides)
    return components
