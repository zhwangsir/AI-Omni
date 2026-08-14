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


class TestHangoverTolerance:
    """hangover 容忍：语音段内允许短暂能量凹陷（如「雪莉」双音节间）不清零。"""

    def test_short_dip_within_hangover_does_not_reset(self):
        # 3 语音 → 2 帧凹陷（hangover=3 容忍内）→ 再 2 语音：凑满 5 帧触发
        wake = VADWakeWord(
            vad=FakeVAD(results=[True] * 3 + [False] * 2 + [True] * 3),
            speech_frames=5,
            hangover_frames=3,
            startup_grace_s=0.0,
        )
        results = [wake.detect(_LOUD) for _ in range(8)]
        # 3+2=5 帧语音在第 7 帧凑满 → 当帧触发，第 8 帧因已触发静默
        assert results == [0.0] * 6 + [1.0, 0.0]

    def test_dip_longer_than_hangover_resets(self):
        # 3 语音 → 4 帧凹陷（超出 hangover=3）→ 再 2 语音：计数清零，不触发
        wake = VADWakeWord(
            vad=FakeVAD(results=[True] * 3 + [False] * 4 + [True] * 2),
            speech_frames=5,
            hangover_frames=3,
            startup_grace_s=0.0,
        )
        results = [wake.detect(_LOUD) for _ in range(9)]
        assert 1.0 not in results

    def test_hangover_default_zero_keeps_strict_consecutive(self):
        # 默认 hangover=0：1 帧凹陷即清零（向后兼容旧语义）
        wake = VADWakeWord(
            vad=FakeVAD(results=[True] * 4 + [False] + [True] * 4),
            speech_frames=5,
            startup_grace_s=0.0,
        )
        results = [wake.detect(_LOUD) for _ in range(9)]
        assert 1.0 not in results

    def test_hangover_budget_restored_on_speech(self):
        # 每段凹陷独立计数：凹陷 2 帧 → 语音恢复预算 → 再凹陷 2 帧仍容忍
        wake = VADWakeWord(
            vad=FakeVAD(
                results=[True] * 2 + [False] * 2 + [True] * 2 + [False] * 2 + [True]
            ),
            speech_frames=5,
            hangover_frames=2,
            startup_grace_s=0.0,
        )
        results = [wake.detect(_LOUD) for _ in range(9)]
        assert results[-1] == 1.0

    def test_reset_restores_hangover_budget(self):
        wake = VADWakeWord(
            vad=FakeVAD(default=True),
            speech_frames=3,
            hangover_frames=2,
            cooldown_ms=0,
            startup_grace_s=0.0,
        )
        assert [wake.detect(_LOUD) for _ in range(3)][-1] == 1.0
        wake.reset()
        # reset 后重新累计：hangover 预算应已恢复
        assert [wake.detect(_LOUD) for _ in range(3)][-1] == 1.0


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


class _BrokenVAD(FakeVAD):
    """is_speech 永远抛错的 VAD fake。"""

    def is_speech(self, frame, sample_rate):
        raise RuntimeError("vad broken")


class _FlakyVAD(FakeVAD):
    """可开关故障的 VAD fake：broken=True 时 is_speech 抛错。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.broken = False

    def is_speech(self, frame, sample_rate):
        if self.broken:
            raise RuntimeError("vad broken")
        return super().is_speech(frame, sample_rate)


class _BufferedVAD(FakeVAD):
    """带内部滑窗缓冲（_buf/_warm）的 VAD fake，模拟滑窗型 VAD 包装器。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._buf = bytearray(b"\x01\x02")
        self._warm = True


class TestGracePeriodFaultTolerance:
    """启动稳定期边界：帧窗内 VAD 异常容错、时间窗兜底抑制。"""

    def test_grace_period_vad_exception_swallowed(self):
        """稳定期帧窗内 VAD 抛错被吞（保持 VAD 热身的调用不拖垮检测），仍返回 0.0。"""
        wake = VADWakeWord(vad=_BrokenVAD(), speech_frames=2, startup_grace_s=1.5)
        # grace_frames = 1500ms / 32ms = 46，前几帧都在帧窗稳定期内
        for _ in range(3):
            assert wake.detect(_LOUD) == 0.0

    def test_startup_deadline_suppresses_after_grace_frames(self):
        """帧喂得比实时快：帧窗结束后时间窗（startup_deadline）未到，仍不触发。"""
        wake = VADWakeWord(
            vad=FakeVAD(default=True),
            speech_frames=2,
            startup_grace_s=0.5,  # grace_frames = 15，时间窗 0.5s
        )
        # 瞬间喂 20 帧：前 15 帧走帧窗分支，第 16-20 帧走时间窗分支
        results = [wake.detect(_LOUD) for _ in range(20)]
        assert results == [0.0] * 20


class TestCooldownFaultTolerance:
    def test_cooldown_vad_exception_swallowed(self):
        """冷却期内 VAD 抛错被吞：冷却计数照走，冷却结束后可重新触发。"""
        vad = _FlakyVAD(default=True)
        wake = VADWakeWord(
            vad=vad,
            speech_frames=2,
            cooldown_ms=320,  # 10 帧冷却
            frame_ms=32,
            startup_grace_s=0.0,
        )
        assert [wake.detect(_LOUD) for _ in range(2)][-1] == 1.0
        wake.reset()
        vad.broken = True
        for _ in range(5):
            assert wake.detect(_LOUD) == 0.0  # 冷却期 VAD 故障不抛出
        vad.broken = False
        for _ in range(5):
            assert wake.detect(_LOUD) == 0.0  # 剩余冷却帧递减完毕
        assert [wake.detect(_LOUD) for _ in range(2)][-1] == 1.0  # 冷却后重新触发


class TestResetClearsVadBuffer:
    def test_reset_clears_vad_sliding_window(self):
        """reset 时 VAD 若有内部滑窗（_buf/_warm 鸭子属性），一并清理防止残留误触发。"""
        vad = _BufferedVAD(default=True)
        wake = VADWakeWord(vad=vad, speech_frames=1, startup_grace_s=0.0)
        wake.reset()
        assert vad._buf == bytearray()
        assert vad._warm is False
