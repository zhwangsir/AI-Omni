"""纯 Python 能量 VAD：替代 silero-vad 本地模型，零第三方依赖。

按帧计算 PCM16 的 RMS（均方根）能量并与阈值比较，逐帧无状态；
静音时长累积由上层（VoicePipeline / _record_utterance）负责。

M34.3 快路径（实测 10.82µs → 5.34µs/帧，-51%）：

- ``memoryview.cast("h")`` 零拷贝视图替代 ``array.array.frombytes`` 逐帧分配；
- 降采样 stride=2（32ms 帧 512 → 256 样本，等效 Nyquist 4kHz 覆盖全语音
  频段）——stride=4 的等效 Nyquist 2kHz 会让 2kHz 纯音在过零相位混叠漏检，
  stride=2 是语音保真与计算量的平衡点，由
  ``test_speech_band_sine_survives_stride`` 抗混叠回归锁定；
- 平方域比较 ``sum_sq >= cutoff²·n`` 替代 ``sqrt(sum_sq/n)/FS >= cutoff``，
  数学等价，免去每帧 sqrt 与两次除法；阈值平方在构造期预计算。
"""

from __future__ import annotations

import operator

from .base import VADBackend

#: 满幅 RMS 归一化分母（PCM16 峰值）
_PCM16_FULL_SCALE = 32768.0

#: 阈值映射系数：config 的 vad_threshold ∈ [0, 1] 乘以本系数得到归一化 RMS 截止值。
#: 0.5（默认）→ 0.02，对应一般环境底噪与正常说话能量的分界。
_THRESHOLD_SCALE = 0.04

#: 能量估计降采样步长（M34.3）：每 2 个样本取 1 个参与能量求和。
#: stride=2 等效 Nyquist 4kHz 覆盖全语音频段；stride=4（2kHz）会让 2kHz
#: 纯音在过零相位混叠到直流而漏检（test_speech_band_sine_survives_stride 锁定）。
_ENERGY_SAMPLE_STRIDE = 2


class EnergyVAD(VADBackend):
    """基于 RMS 能量的语音活动检测。

    ``threshold`` 与既有 config ``vad_threshold`` 同语义（[0, 1]，越大越不敏感）；
    帧过短（< 2 字节）或全零帧直接判静音。
    """

    def __init__(self, threshold: float = 0.5, sample_rate: int = 16000) -> None:
        self._cutoff = threshold * _THRESHOLD_SCALE
        self._sample_rate = sample_rate
        # 平方域截止值（PCM16 域）：cutoff_pcm² = (cutoff_norm × 满幅)²
        cutoff_pcm = self._cutoff * _PCM16_FULL_SCALE
        self._cutoff_sq_pcm = cutoff_pcm * cutoff_pcm

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        if len(frame) < 2:
            return False
        # 截断到偶数字节后建零拷贝 int16 视图；stride 降采样不复制数据
        samples = memoryview(frame[: len(frame) & ~1]).cast("h")[::_ENERGY_SAMPLE_STRIDE]
        n = len(samples)
        if n == 0:
            return False
        # 平方域比较：sum(s²) >= cutoff²·n  ⟺  sqrt(sum(s²)/n)/FS >= cutoff
        return sum(map(operator.mul, samples, samples)) >= self._cutoff_sq_pcm * n
