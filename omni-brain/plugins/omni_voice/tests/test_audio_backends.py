"""SounddeviceSource / SounddevicePlayer 后端测试（M32.26 覆盖率提升）。

测试零依赖：经 ``monkeypatch.setitem(sys.modules, "sounddevice", fake)``
注入 fake 模块，不触碰真实音频硬件；``sys.modules["sounddevice"] = None``
模拟依赖缺失（import 抛 ImportError → VoiceBackendError）。

``start`` / ``read_frame`` / ``stop`` / ``play`` 带 ``# pragma: no cover``
（真实硬件路径），此处用 fake sd 顺便做行为测试，但不删除 pragma 注释。
"""

from __future__ import annotations

import queue as queue_mod
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from omni_voice.audio import SounddevicePlayer, SounddeviceSource
from omni_voice.errors import VoiceBackendError


def _fake_sd_module() -> ModuleType:
    """构造最小 fake sounddevice 模块（InputStream/play/stop 假实现）。"""
    mod = ModuleType("sounddevice")

    class _FakeInputStream:
        """假输入流：记录构造参数，start/stop/close 置标志。"""

        instances: list["_FakeInputStream"] = []

        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.started = False
            self.stopped = False
            self.closed = False
            _FakeInputStream.instances.append(self)

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stopped = True

        def close(self) -> None:
            self.closed = True

    mod.InputStream = _FakeInputStream
    mod.play_calls: list[dict[str, Any]] = []

    def _play(audio: Any, samplerate: int, blocking: bool) -> None:
        mod.play_calls.append(
            {"audio": audio, "samplerate": samplerate, "blocking": blocking}
        )

    mod.play = _play
    mod.stop_calls: list[int] = []

    def _stop() -> None:
        mod.stop_calls.append(1)

    mod.stop = _stop
    return mod


class TestSounddeviceSourceInit:
    """SounddeviceSource 构造器（audio.py 73-85 行）。"""

    def test_init_success_assigns_attributes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """fake sounddevice 注入后构造成功，属性按参数赋值。"""
        fake_sd = _fake_sd_module()
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
        source = SounddeviceSource(sample_rate=8000, channels=2, frame_ms=20, device="mic0")
        assert source._sd is fake_sd
        assert source.sample_rate == 8000
        assert source.channels == 2
        assert source.frame_ms == 20
        assert source.device == "mic0"
        assert source._stream is None

    def test_init_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """默认参数：16000 / 单声道 / 30ms / 默认设备。"""
        fake_sd = _fake_sd_module()
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
        source = SounddeviceSource()
        assert source.sample_rate == 16000
        assert source.channels == 1
        assert source.frame_ms == 30
        assert source.device is None

    def test_init_import_error_raises_voice_backend_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """sounddevice 缺失（sys.modules 中为 None）→ VoiceBackendError。"""
        monkeypatch.setitem(sys.modules, "sounddevice", None)
        with pytest.raises(VoiceBackendError, match="sounddevice"):
            SounddeviceSource()


class TestSounddevicePlayerInit:
    """SounddevicePlayer 构造器（audio.py 131-138 行）。"""

    def test_init_success_assigns_sample_rate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_sd = _fake_sd_module()
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
        player = SounddevicePlayer(sample_rate=22050)
        assert player._sd is fake_sd
        assert player.sample_rate == 22050

    def test_init_default_sample_rate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_sd = _fake_sd_module()
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
        player = SounddevicePlayer()
        assert player.sample_rate == 16000

    def test_init_import_error_raises_voice_backend_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "sounddevice", None)
        with pytest.raises(VoiceBackendError, match="sounddevice"):
            SounddevicePlayer()


class TestSounddeviceSourceBehavior:
    """fake InputStream 下的 start/read_frame/stop 行为（pragma 段，顺带验证）。"""

    def test_start_creates_and_starts_stream(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_sd = _fake_sd_module()
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
        source = SounddeviceSource(sample_rate=16000, channels=1, frame_ms=30)
        source.start()
        assert source._stream is not None
        stream = source._stream
        assert stream.started is True
        assert stream.kwargs["samplerate"] == 16000
        assert stream.kwargs["channels"] == 1
        assert stream.kwargs["blocksize"] == 16000 * 30 // 1000
        source.stop()

    def test_read_frame_returns_callback_bytes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """流回调写入的帧经 read_frame 原样读出。"""
        fake_sd = _fake_sd_module()
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
        source = SounddeviceSource()
        source.start()
        callback = source._stream.kwargs["callback"]
        callback(SimpleNamespace(tobytes=lambda: b"frame-bytes"), 480, None, None)
        assert source.read_frame() == b"frame-bytes"
        source.stop()

    def test_read_frame_timeout_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """队列超时抛 Empty 时返回 b""（用立即抛空的 fake 队列避免真实等待）。"""
        fake_sd = _fake_sd_module()
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
        source = SounddeviceSource()
        source.start()

        class _EmptyQueue:
            def get(self, timeout: float = 0.0) -> bytes:
                raise queue_mod.Empty

        source._raw = _EmptyQueue()
        assert source.read_frame() == b""
        source.stop()

    def test_stop_closes_stream_and_is_idempotent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_sd = _fake_sd_module()
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
        source = SounddeviceSource()
        source.start()
        stream = source._stream
        source.stop()
        assert stream.stopped is True
        assert stream.closed is True
        assert source._stream is None
        source.stop()  # 幂等：不抛

    def test_stop_without_start_is_safe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_sd = _fake_sd_module()
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
        source = SounddeviceSource()
        source.stop()  # _stream 为 None：不抛


class TestSounddevicePlayerBehavior:
    """fake sd 下的 play/stop 行为（pragma 段，顺带验证）。"""

    def test_play_delegates_to_sd_play(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """play 经 numpy 转 int16 后调 sd.play（fake numpy 注入，零依赖）。"""
        fake_sd = _fake_sd_module()
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
        fake_np = ModuleType("numpy")
        fake_np.int16 = "int16"
        fake_np.frombuffer = lambda buf, dtype: ("pcm", bytes(buf), dtype)
        monkeypatch.setitem(sys.modules, "numpy", fake_np)

        player = SounddevicePlayer()
        player.play(b"\x01\x00\x02\x00", sample_rate=8000)
        assert len(fake_sd.play_calls) == 1
        call = fake_sd.play_calls[0]
        assert call["audio"] == ("pcm", b"\x01\x00\x02\x00", "int16")
        assert call["samplerate"] == 8000
        assert call["blocking"] is True

    def test_stop_delegates_to_sd_stop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_sd = _fake_sd_module()
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
        player = SounddevicePlayer()
        player.stop()
        assert fake_sd.stop_calls == [1]
