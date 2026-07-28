"""语音后端抽象基类。

约定音频格式统一为 PCM16（小端有符号 16 位）字节流；
所有方法同步阻塞，由上层（VoicePipeline）在线程中调度。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class VADBackend(ABC):
    """语音活动检测：判断单帧是否包含语音。"""

    @abstractmethod
    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        """返回该帧是否为语音帧。"""


class ASRBackend(ABC):
    """自动语音识别：把一段 PCM16 音频转写为文本。"""

    @abstractmethod
    def transcribe(self, pcm: bytes, sample_rate: int, language: str | None = None) -> str:
        """转写整段音频，返回文本（可能为空字符串）。"""


class TTSBackend(ABC):
    """文本转语音：合成结果为 PCM16 字节流。"""

    @abstractmethod
    def synthesize(self, text: str) -> bytes:
        """把文本合成为 PCM16 音频字节。"""


class WakeWordBackend(ABC):
    """唤醒词检测：对单帧返回置信度。"""

    #: True 表示该后端仅做语音活动检测，需要上层用 ASR 校验热词；
    #: False 表示该后端自身已精确匹配唤醒词（如专用模型），无需二次校验。
    requires_hotword_check: bool = False

    @abstractmethod
    def detect(self, frame: bytes) -> float:
        """返回 [0, 1] 的唤醒置信度。"""

    def reset(self) -> None:
        """重置唤醒状态（回到可检测状态）。默认空实现。"""
