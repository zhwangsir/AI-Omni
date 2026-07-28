"""纯 Python 能量 VAD：替代 silero-vad 本地模型，零第三方依赖。

按帧计算 PCM16 的 RMS（均方根）能量并与阈值比较，逐帧无状态；
静音时长累积由上层（VoicePipeline / _record_utterance）负责。
"""

from __future__ import annotations

import array
import math

from .base import VADBackend

#: 满幅 RMS 归一化分母（PCM16 峰值）
_PCM16_FULL_SCALE = 32768.0

#: 阈值映射系数：config 的 vad_threshold ∈ [0, 1] 乘以本系数得到归一化 RMS 截止值。
#: 0.5（默认）→ 0.02，对应一般环境底噪与正常说话能量的分界。
_THRESHOLD_SCALE = 0.04


class EnergyVAD(VADBackend):
    """基于 RMS 能量的语音活动检测。

    ``threshold`` 与既有 config ``vad_threshold`` 同语义（[0, 1]，越大越不敏感）；
    帧过短（< 2 字节）或全零帧直接判静音。
    """

    def __init__(self, threshold: float = 0.5, sample_rate: int = 16000) -> None:
        self._cutoff = threshold * _THRESHOLD_SCALE
        self._sample_rate = sample_rate

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        if len(frame) < 2:
            return False
        # 截断到偶数字节，避免 array 解包残字
        samples = array.array("h")
        samples.frombytes(frame[: len(frame) - (len(frame) % 2)])
        if not samples:
            return False
        rms = math.sqrt(sum(s * s for s in samples) / len(samples)) / _PCM16_FULL_SCALE
        return rms >= self._cutoff
