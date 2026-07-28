"""Fake 后端行为测试：可编程队列、默认值、调用记录。"""

from __future__ import annotations

import pytest

from omni_voice.backends.base import ASRBackend, TTSBackend, VADBackend, WakeWordBackend
from omni_voice.backends.fakes import (
    FakeASR,
    FakePlayer,
    FakeTTS,
    FakeVAD,
    FakeWakeWord,
)
from omni_voice.errors import VoiceError


class TestFakeVAD:
    def test_is_backend(self):
        assert isinstance(FakeVAD(), VADBackend)

    def test_scripted_results_then_default(self):
        vad = FakeVAD(results=[True, False], default=True)
        assert vad.is_speech(b"\x00", 16000) is True
        assert vad.is_speech(b"\x00", 16000) is False
        assert vad.is_speech(b"\x00", 16000) is True  # 队列耗尽回默认值

    def test_default_is_false(self):
        assert FakeVAD().is_speech(b"\x00", 16000) is False

    def test_calls_counted(self):
        vad = FakeVAD()
        vad.is_speech(b"\x00", 16000)
        vad.is_speech(b"\x00", 16000)
        assert vad.calls == 2


class TestFakeASR:
    def test_is_backend(self):
        assert isinstance(FakeASR(), ASRBackend)

    def test_transcript_queue(self):
        asr = FakeASR(transcripts=["第一句", "第二句"])
        assert asr.transcribe(b"pcm", 16000) == "第一句"
        assert asr.transcribe(b"pcm", 16000) == "第二句"
        assert asr.transcribe(b"pcm", 16000) == ""  # 耗尽后默认空文本

    def test_calls_recorded(self):
        asr = FakeASR()
        asr.transcribe(b"\x00\x01", 16000, language="zh")
        assert asr.calls == [(2, 16000, "zh")]

    def test_error_raised_once(self):
        asr = FakeASR(transcripts=["ok"], error=VoiceError("asr 故障"))
        with pytest.raises(VoiceError, match="asr 故障"):
            asr.transcribe(b"pcm", 16000)
        assert asr.transcribe(b"pcm", 16000) == "ok"  # 第二次恢复正常


class TestFakeTTS:
    def test_is_backend(self):
        assert isinstance(FakeTTS(), TTSBackend)

    def test_synthesize_records_and_returns_pcm(self):
        tts = FakeTTS(pcm_bytes=100)
        pcm = tts.synthesize("你好")
        assert isinstance(pcm, bytes)
        assert len(pcm) == 100
        assert tts.texts == ["你好"]
        assert tts.synthesized.is_set()

    def test_multiple_texts_appended(self):
        tts = FakeTTS()
        tts.synthesize("一")
        tts.synthesize("二")
        assert tts.texts == ["一", "二"]


class TestFakeWakeWord:
    def test_is_backend(self):
        assert isinstance(FakeWakeWord(), WakeWordBackend)

    def test_confidence_sequence(self):
        wake = FakeWakeWord(confidences=[0.1, 0.9])
        assert wake.detect(b"f") == 0.1
        assert wake.detect(b"f") == 0.9
        assert wake.detect(b"f") == 0.0  # 耗尽后默认 0
        assert wake.calls == 3


class TestFakePlayer:
    def test_play_records(self):
        player = FakePlayer()
        player.play(b"pcm-data", 16000)
        assert player.played == [(b"pcm-data", 16000)]
        assert player.played_event.is_set()
