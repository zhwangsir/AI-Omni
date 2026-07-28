"""VADWakeWord 单元测试：VAD 触发型唤醒后端（替代 openwakeword 的默认唤醒路径）。

配合 EnergyVAD 或脚本化 FakeVAD 使用，不依赖音频硬件与模型。
"""

from __future__ import annotations

import struct

from omni_voice.backends.energy_vad import EnergyVAD
from omni_voice.backends.fakes import FakeVAD
from omni_voice.backends.vad_wake import VADWakeWord


def _frame(amplitude: int, samples: int = 512) -> bytes:
    return struct.pack(f"<{samples}h", *([amplitude] * samples))


_LOUD = _frame(5000)
_SILENT = _frame(0)


class TestTriggerAfterContinuousSpeech:
    def test_no_trigger_before_speech_threshold(self):
        wake = VADWakeWord(
            vad=FakeVAD(default=True),
            speech_frames=5,
            startup_grace_s=0.0,
        )
        for _ in range(4):
            assert wake.detect(_LOUD) == 0.0

    def test_triggers_after_continuous_speech_frames(self):
        wake = VADWakeWord(
            vad=FakeVAD(default=True),
            speech_frames=5,
            startup_grace_s=0.0,
        )
        results = [wake.detect(_LOUD) for _ in range(5)]
        assert results[-1] == 1.0
        assert results[:-1] == [0.0] * 4

    def test_silence_resets_continuous_count(self):
        # 4 帧语音 → 1 帧静音打断 → 再 4 帧语音：不应触发（speech_frames=5）
        wake = VADWakeWord(
            vad=FakeVAD(results=[True] * 4 + [False] + [True] * 4),
            speech_frames=5,
            startup_grace_s=0.0,
        )
        results = [wake.detect(_LOUD) for _ in range(9)]
        assert 1.0 not in results

    def test_stays_silent_after_trigger_until_reset(self):
        wake = VADWakeWord(
            vad=FakeVAD(default=True),
            speech_frames=3,
            startup_grace_s=0.0,
        )
        assert [wake.detect(_LOUD) for _ in range(3)][-1] == 1.0
        # 触发后未 reset，持续语音也不再触发
        assert wake.detect(_LOUD) == 0.0
        assert wake.detect(_LOUD) == 0.0


class TestResetAndCooldown:
    def test_reset_clears_trigger_and_enters_cooldown(self):
        wake = VADWakeWord(
            vad=FakeVAD(default=True),
            speech_frames=3,
            cooldown_ms=3000,
            frame_ms=32,
            startup_grace_s=0.0,
        )
        assert [wake.detect(_LOUD) for _ in range(3)][-1] == 1.0
        wake.reset()
        # 冷却帧数 = 3000 / 32 = 93 帧，期间不触发
        assert wake.detect(_LOUD) == 0.0

    def test_retrigger_after_cooldown_elapsed(self):
        wake = VADWakeWord(
            vad=FakeVAD(default=True),
            speech_frames=2,
            cooldown_ms=64,  # 2 帧冷却
            frame_ms=32,
            startup_grace_s=0.0,
        )
        assert [wake.detect(_LOUD) for _ in range(2)][-1] == 1.0
        wake.reset()
        assert wake.detect(_LOUD) == 0.0  # 冷却帧 1
        assert wake.detect(_LOUD) == 0.0  # 冷却帧 2
        # 冷却结束后重新累计连续语音
        assert [wake.detect(_LOUD) for _ in range(2)][-1] == 1.0


class TestStartupGrace:
    def test_grace_period_suppresses_detection(self):
        wake = VADWakeWord(
            vad=FakeVAD(default=True),
            speech_frames=2,
            startup_grace_s=10.0,  # 足够长的稳定期
        )
        for _ in range(10):
            assert wake.detect(_LOUD) == 0.0


class TestHotwordContract:
    def test_requires_hotword_check(self):
        """VAD 唤醒只做活动检测，必须由上层 ASR 热词校验（契约断言）。"""
        wake = VADWakeWord(vad=FakeVAD(), startup_grace_s=0.0)
        assert wake.requires_hotword_check is True

    def test_vad_exception_treated_as_silence(self):
        class _BrokenVAD(FakeVAD):
            def is_speech(self, frame, sample_rate):
                raise RuntimeError("vad broken")

        wake = VADWakeWord(vad=_BrokenVAD(), speech_frames=2, startup_grace_s=0.0)
        for _ in range(5):
            assert wake.detect(_LOUD) == 0.0


class TestWithEnergyVAD:
    """与真实 EnergyVAD 组合：能量 VAD 驱动的端到端唤醒行为。"""

    def test_energy_vad_drives_trigger(self):
        wake = VADWakeWord(
            vad=EnergyVAD(threshold=0.5),
            speech_frames=3,
            startup_grace_s=0.0,
        )
        assert [wake.detect(_LOUD) for _ in range(3)][-1] == 1.0

    def test_energy_vad_silence_does_not_trigger(self):
        wake = VADWakeWord(
            vad=EnergyVAD(threshold=0.5),
            speech_frames=3,
            startup_grace_s=0.0,
        )
        for _ in range(10):
            assert wake.detect(_SILENT) == 0.0
