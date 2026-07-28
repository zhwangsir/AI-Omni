"""音频采集与播放抽象。

- :class:`AudioSource`        ：帧源抽象（start/stop/read_frame）
- :class:`FakeAudioSource`    ：脚本化帧源（测试与演示用）
- :class:`SounddeviceSource`  ：真实麦克风采集（惰性导入 sounddevice）
- :class:`SounddevicePlayer`  ：真实扬声器播放（惰性导入 sounddevice）

帧格式统一为 PCM16 字节，帧长由 VoiceConfig.frame_bytes 决定。
"""

from __future__ import annotations

import logging
import queue as queue_mod
from abc import ABC, abstractmethod
from collections import deque

from .errors import VoiceBackendError

logger = logging.getLogger(__name__)


class AudioSource(ABC):
    """音频帧源抽象。"""

    @abstractmethod
    def start(self) -> None:
        """打开采集设备/资源。"""

    @abstractmethod
    def stop(self) -> None:
        """关闭采集设备/资源（需幂等）。"""

    @abstractmethod
    def read_frame(self) -> bytes:
        """读取一帧 PCM16 数据；返回 b"" 表示暂无数据。"""


class FakeAudioSource(AudioSource):
    """脚本化帧源：按序弹出预设帧，耗尽后返回静音帧（或 b""）。"""

    def __init__(
        self,
        frames: list[bytes] | None = None,
        frame_bytes: int = 960,
        silence_after: bool = True,
    ):
        self._frames: deque[bytes] = deque(frames or [])
        self.frame_bytes = frame_bytes
        self.silence_after = silence_after
        self.started = False
        self.frames_read = 0

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def read_frame(self) -> bytes:
        self.frames_read += 1
        if self._frames:
            return self._frames.popleft()
        if self.silence_after:
            return b"\x00" * self.frame_bytes
        return b""


class SounddeviceSource(AudioSource):
    """基于 sounddevice 的麦克风帧源（惰性导入，缺依赖抛 VoiceBackendError）。"""

    def __init__(self, sample_rate: int = 16000, channels: int = 1, frame_ms: int = 30, device=None):
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise VoiceBackendError(
                "音频采集需要 sounddevice，请安装：pip install sounddevice"
            ) from exc
        self._sd = sd
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_ms = frame_ms
        self.device = device
        self._stream = None
        self._queue: deque[bytes] = deque()

    def start(self) -> None:  # pragma: no cover（需要音频硬件）
        self._raw: queue_mod.Queue[bytes] = queue_mod.Queue()
        blocksize = self.sample_rate * self.frame_ms // 1000

        def _callback(indata, frames, time_info, status):
            if status:
                logger.warning("sounddevice status: %s", status)
            self._raw.put(indata.tobytes())

        self._stream = self._sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=blocksize,
            device=self.device,
            callback=_callback,
        )
        self._stream.start()
        logger.info(
            "sounddevice 输入流已启动: sr=%d, channels=%d, blocksize=%d, device=%s",
            self.sample_rate, self.channels, blocksize, self.device,
        )

    def read_frame(self) -> bytes:  # pragma: no cover（需要音频硬件）
        try:
            return self._raw.get(timeout=1.0)
        except queue_mod.Empty:
            logger.warning("音频输入超时：1秒未收到麦克风数据，检查麦克风权限与设备")
            return b""

    def stop(self) -> None:  # pragma: no cover（需要音频硬件）
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class SounddevicePlayer:
    """基于 sounddevice 的 PCM16 播放器（惰性导入，缺依赖抛 VoiceBackendError）。

    满足 pipeline.PlayerProtocol 的鸭子类型：``play(pcm, sample_rate)``。
    """

    def __init__(self, sample_rate: int = 16000):
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise VoiceBackendError(
                "音频播放需要 sounddevice，请安装：pip install sounddevice"
            ) from exc
        self._sd = sd
        self.sample_rate = sample_rate

    def play(self, pcm: bytes, sample_rate: int) -> None:  # pragma: no cover（需要音频硬件）
        import numpy as np

        audio = np.frombuffer(pcm, dtype=np.int16)
        self._sd.play(audio, samplerate=sample_rate, blocking=True)

    def stop(self) -> None:  # pragma: no cover（需要音频硬件）
        """中止当前播放（M7.5 打断）：阻塞中的 play 调用随即返回。"""
        self._sd.stop()
