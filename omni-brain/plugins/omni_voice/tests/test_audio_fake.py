"""FakeAudioSource 行为测试。"""

from __future__ import annotations

from omni_voice.audio import AudioSource, FakeAudioSource


def test_is_audio_source():
    assert isinstance(FakeAudioSource(), AudioSource)


def test_scripted_frames_in_order():
    source = FakeAudioSource(frames=[b"f1", b"f2"], frame_bytes=4, silence_after=False)
    source.start()
    assert source.read_frame() == b"f1"
    assert source.read_frame() == b"f2"


def test_silence_after_exhausted():
    source = FakeAudioSource(frames=[b"f1"], frame_bytes=4, silence_after=True)
    source.read_frame()
    assert source.read_frame() == b"\x00" * 4
    assert source.read_frame() == b"\x00" * 4


def test_empty_after_exhausted_when_no_silence():
    source = FakeAudioSource(frames=[], silence_after=False)
    assert source.read_frame() == b""


def test_start_stop_flags_and_count():
    source = FakeAudioSource(frames=[b"x"])
    assert source.started is False
    source.start()
    assert source.started is True
    source.read_frame()
    source.read_frame()
    assert source.frames_read == 2
    source.stop()
    assert source.started is False
