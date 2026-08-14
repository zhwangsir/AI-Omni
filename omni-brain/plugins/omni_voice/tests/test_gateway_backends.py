"""OpenClaw 网关后端（OpenAIASR / OpenAITTS / EnergyVAD）单元测试。

全部通过 monkeypatch urllib 伪造网关响应，不访问真实网络；
EnergyVAD 为纯 Python，直接构造 PCM16 帧验证能量判定。
"""

from __future__ import annotations

import io
import json
import struct
import urllib.error

import pytest

from omni_voice.backends.energy_vad import _ENERGY_SAMPLE_STRIDE, EnergyVAD
from omni_voice.backends.indextts2_tts import IndexTTS2
from omni_voice.backends.openai_asr import OpenAIASR, _wrap_wav
from omni_voice.backends.openai_tts import OPENAI_PCM_SAMPLE_RATE, OpenAITTS
from omni_voice.errors import VoiceBackendError


# ---------------------------------------------------------------------------
# 工具：伪造 urlopen
# ---------------------------------------------------------------------------
class _FakeResponse:
    """模拟 urllib.request.urlopen 返回的上下文管理器响应。"""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _patch_urlopen(monkeypatch, *, body: bytes = b"", capture: dict | None = None):
    """替换 urllib.request.urlopen，捕获请求并返回伪造响应。"""

    def _fake_urlopen(request, timeout=None):
        if capture is not None:
            capture["url"] = request.full_url
            capture["headers"] = dict(request.header_items())
            capture["body"] = request.data
            capture["timeout"] = timeout
        return _FakeResponse(body)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)


# ---------------------------------------------------------------------------
# _wrap_wav
# ---------------------------------------------------------------------------
class TestWrapWav:
    def test_header_structure(self):
        pcm = b"\x01\x02" * 100  # 200 字节 PCM16
        wav = _wrap_wav(pcm, 16000)
        assert wav[:4] == b"RIFF"
        assert wav[8:12] == b"WAVE"
        assert wav[12:16] == b"fmt "
        # 采样率 16000 写在 fmt chunk 偏移 24 处（小端）
        assert struct.unpack("<I", wav[24:28])[0] == 16000
        # data chunk 长度 = 原始 pcm 长度
        assert struct.unpack("<I", wav[40:44])[0] == len(pcm)
        assert wav[44:] == pcm

    def test_total_size_field(self):
        pcm = b"\x00" * 1000
        wav = _wrap_wav(pcm, 16000)
        # RIFF size = 36 + data_len
        assert struct.unpack("<I", wav[4:8])[0] == 36 + len(pcm)
        assert len(wav) == 44 + len(pcm)


# ---------------------------------------------------------------------------
# OpenAIASR
# ---------------------------------------------------------------------------
class TestOpenAIASR:
    def test_transcribe_happy_path(self, monkeypatch):
        capture: dict = {}
        _patch_urlopen(monkeypatch, body=json.dumps({"text": "你好世界"}).encode(), capture=capture)
        asr = OpenAIASR(endpoint="http://gw:18789/v1", model="whisper-1")
        pcm = b"\x00\x01" * 512
        assert asr.transcribe(pcm, 16000) == "你好世界"
        # 请求打到网关 /audio/transcriptions
        assert capture["url"] == "http://gw:18789/v1/audio/transcriptions"
        # multipart 体内包含模型名与 WAV 头
        assert b"whisper-1" in capture["body"]
        assert b"RIFF" in capture["body"]
        assert "multipart/form-data" in capture["headers"].get("Content-type", "")

    def test_transcribe_empty_pcm_returns_empty(self, monkeypatch):
        asr = OpenAIASR(endpoint="http://gw:18789/v1")
        # 空音频不应发请求
        assert asr.transcribe(b"", 16000) == ""

    def test_transcribe_with_language(self, monkeypatch):
        capture: dict = {}
        _patch_urlopen(monkeypatch, body=b'{"text": "hello"}', capture=capture)
        asr = OpenAIASR(endpoint="http://gw:18789/v1")
        assert asr.transcribe(b"\x00\x01" * 100, 16000, language="zh") == "hello"
        assert b"zh" in capture["body"]

    def test_transcribe_with_prompt(self, monkeypatch):
        """M32.29：prompt（initial_prompt 识别偏置）随 multipart 上传。

        用于把「雪莉」等唤醒词上下文注入 faster-whisper，降低同音误识别。
        """
        capture: dict = {}
        _patch_urlopen(monkeypatch, body=json.dumps({"text": "雪莉"}).encode(), capture=capture)
        asr = OpenAIASR(endpoint="http://gw:18789/v1", prompt="语音助手名叫雪莉")
        assert asr.transcribe(b"\x00\x01" * 100, 16000) == "雪莉"
        assert b'name="prompt"' in capture["body"]
        assert "语音助手名叫雪莉".encode("utf-8") in capture["body"]

    def test_transcribe_without_prompt_omits_field(self, monkeypatch):
        """缺省 prompt=None：multipart 不含 prompt 字段（向后兼容）。"""
        capture: dict = {}
        _patch_urlopen(monkeypatch, body=b'{"text": "x"}', capture=capture)
        asr = OpenAIASR(endpoint="http://gw:18789/v1")
        asr.transcribe(b"\x00\x01" * 100, 16000)
        assert b'name="prompt"' not in capture["body"]

    def test_transcribe_api_key_header(self, monkeypatch):
        capture: dict = {}
        _patch_urlopen(monkeypatch, body=b'{"text": "x"}', capture=capture)
        asr = OpenAIASR(endpoint="http://gw:18789/v1", api_key="sk-test")
        asr.transcribe(b"\x00\x01" * 100, 16000)
        assert capture["headers"].get("Authorization") == "Bearer sk-test"

    def test_http_error_mapped(self, monkeypatch):
        def _raise(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 500, "err", {}, io.BytesIO(b""))

        monkeypatch.setattr("urllib.request.urlopen", _raise)
        asr = OpenAIASR(endpoint="http://gw:18789/v1")
        with pytest.raises(VoiceBackendError, match="HTTP 500"):
            asr.transcribe(b"\x00\x01" * 100, 16000)

    def test_network_error_mapped(self, monkeypatch):
        def _raise(request, timeout=None):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", _raise)
        asr = OpenAIASR(endpoint="http://gw:18789/v1")
        with pytest.raises(VoiceBackendError, match="网关不可达"):
            asr.transcribe(b"\x00\x01" * 100, 16000)

    def test_non_json_response_mapped(self, monkeypatch):
        _patch_urlopen(monkeypatch, body=b"<html>bad gateway</html>")
        asr = OpenAIASR(endpoint="http://gw:18789/v1")
        with pytest.raises(VoiceBackendError, match="非 JSON"):
            asr.transcribe(b"\x00\x01" * 100, 16000)

    def test_missing_text_field_mapped(self, monkeypatch):
        _patch_urlopen(monkeypatch, body=b'{"unexpected": 1}')
        asr = OpenAIASR(endpoint="http://gw:18789/v1")
        with pytest.raises(VoiceBackendError, match="结构异常"):
            asr.transcribe(b"\x00\x01" * 100, 16000)


# ---------------------------------------------------------------------------
# OpenAITTS
# ---------------------------------------------------------------------------
class TestOpenAITTS:
    def test_synthesize_happy_path(self, monkeypatch):
        capture: dict = {}
        pcm_out = b"\x11\x22" * 2400
        _patch_urlopen(monkeypatch, body=pcm_out, capture=capture)
        tts = OpenAITTS(endpoint="http://gw:18789/v1", voice="alloy")
        assert tts.synthesize("你好") == pcm_out
        assert capture["url"] == "http://gw:18789/v1/audio/speech"
        payload = json.loads(capture["body"].decode("utf-8"))
        assert payload["voice"] == "alloy"
        assert payload["input"] == "你好"
        assert payload["response_format"] == "pcm"

    def test_synthesize_empty_text_returns_empty(self):
        tts = OpenAITTS(endpoint="http://gw:18789/v1")
        assert tts.synthesize("   ") == b""

    def test_sample_rate_exposed_for_player(self):
        tts = OpenAITTS(endpoint="http://gw:18789/v1")
        assert tts.sample_rate == OPENAI_PCM_SAMPLE_RATE == 24000

    def test_api_key_header(self, monkeypatch):
        capture: dict = {}
        _patch_urlopen(monkeypatch, body=b"\x00" * 10, capture=capture)
        tts = OpenAITTS(endpoint="http://gw:18789/v1", api_key="sk-test")
        tts.synthesize("hi")
        assert capture["headers"].get("Authorization") == "Bearer sk-test"

    def test_http_error_mapped(self, monkeypatch):
        def _raise(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 404, "err", {}, io.BytesIO(b""))

        monkeypatch.setattr("urllib.request.urlopen", _raise)
        tts = OpenAITTS(endpoint="http://gw:18789/v1")
        with pytest.raises(VoiceBackendError, match="HTTP 404"):
            tts.synthesize("你好")

    def test_network_error_mapped(self, monkeypatch):
        def _raise(request, timeout=None):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", _raise)
        tts = OpenAITTS(endpoint="http://gw:18789/v1")
        with pytest.raises(VoiceBackendError, match="网关不可达"):
            tts.synthesize("你好")


# ---------------------------------------------------------------------------
# EnergyVAD
# ---------------------------------------------------------------------------
def _pcm_frame(amplitude: int, samples: int = 512) -> bytes:
    """生成恒定振幅的 PCM16 帧。"""
    return struct.pack(f"<{samples}h", *([amplitude] * samples))


class TestEnergyVAD:
    def test_silence_frame_is_not_speech(self):
        vad = EnergyVAD(threshold=0.5)
        assert vad.is_speech(_pcm_frame(0), 16000) is False

    def test_low_noise_below_cutoff(self):
        # 默认 threshold=0.5 → cutoff = 0.02 * 32768 ≈ 655 RMS
        vad = EnergyVAD(threshold=0.5)
        assert vad.is_speech(_pcm_frame(100), 16000) is False

    def test_loud_frame_is_speech(self):
        vad = EnergyVAD(threshold=0.5)
        assert vad.is_speech(_pcm_frame(5000), 16000) is True

    def test_higher_threshold_less_sensitive(self):
        vad = EnergyVAD(threshold=0.9)
        # 0.9 * 0.04 * 32768 ≈ 1179 RMS cutoff；振幅 1000 不应触发
        assert vad.is_speech(_pcm_frame(1000), 16000) is False
        # 默认 0.5 阈值下同样振幅应触发
        assert EnergyVAD(threshold=0.5).is_speech(_pcm_frame(1000), 16000) is True

    def test_short_frame_is_not_speech(self):
        vad = EnergyVAD()
        assert vad.is_speech(b"\x01", 16000) is False
        assert vad.is_speech(b"", 16000) is False

    def test_odd_byte_frame_truncated(self):
        vad = EnergyVAD(threshold=0.5)
        frame = _pcm_frame(5000, 512) + b"\xff"  # 奇数字节，截断后仍应判语音
        assert vad.is_speech(frame, 16000) is True

    # ------------------------------------------------------------------
    # M34.3 快路径：零 array 分配 + 降采样平方域比较
    # ------------------------------------------------------------------
    def test_fast_path_does_not_allocate_array(self, monkeypatch):
        """M34.3：is_speech 快路径不再走 array.array 逐帧分配。

        把 array.array 替换为抛错桩——旧实现每帧 frombytes 必炸，
        新实现（memoryview 零拷贝视图）完全绕开，判定不受影响。
        """
        import array as array_mod

        def _boom(*args, **kwargs):
            raise AssertionError("快路径禁止 array.array 分配")

        monkeypatch.setattr(array_mod, "array", _boom)
        vad = EnergyVAD(threshold=0.5)
        assert vad.is_speech(_pcm_frame(5000), 16000) is True
        assert vad.is_speech(_pcm_frame(0), 16000) is False

    def test_speech_band_sine_survives_stride(self):
        """M34.3 抗混叠回归锁：语音频段正弦在降采样快路径下不得漏检。

        stride 降采样对宽带语音能量估计无损，但纯音在等效 Nyquist 附近
        可能混叠到直流（stride=4 的 2kHz Nyquist 曾让 2kHz 正弦在过零
        相位整帧漏检）。stride=2 等效 Nyquist 4kHz，语音频段代表频点
        440Hz/1kHz/2kHz 必须稳定判语音。
        """
        import math as _math

        for freq in (440, 1000, 2000):
            samples = [
                int(5000 * _math.sin(2 * _math.pi * freq * i / 16000)) for i in range(512)
            ]
            frame = struct.pack(f"<{len(samples)}h", *samples)
            assert EnergyVAD(threshold=0.5).is_speech(frame, 16000) is True, (
                f"{freq}Hz 正弦漏检"
            )

    def test_decision_matches_reference_formula(self):
        """M34.3：快路径判定与参考 RMS 公式（同一子采样集 + sqrt）逐帧等价。

        固定种子生成随机噪声帧 + 边界振幅帧，参考实现取与快路径相同的
        stride 子采样集、走 sqrt 域旧公式——判定必须完全一致，验证
        「平方域比较 ⟺ sqrt 域比较」的数学等价性。
        （降采样估计是无偏的但单次实现有统计涨落，不能与全采样参考逐帧
        比对；降采样本身的语音保真由抗混叠测试单独锁定。）
        """
        import math as _math
        import random

        def _reference_is_speech(frame: bytes, cutoff: float) -> bool:
            """参考公式：同一 stride 子采样集上的 sqrt 域 RMS / 满幅 >= cutoff。"""
            even = frame[: len(frame) & ~1]
            n = len(even) // 2
            if n == 0:
                return False
            samples = struct.unpack(f"<{n}h", even)[::_ENERGY_SAMPLE_STRIDE]
            if not samples:
                return False
            rms = _math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768.0
            return rms >= cutoff

        vad = EnergyVAD(threshold=0.5)
        cutoff = 0.5 * 0.04
        rng = random.Random(20260806)
        frames: list[bytes] = []
        # 边界附近振幅（cutoff*FS ≈ 655）
        for amp in (0, 100, 600, 640, 655, 670, 700, 1000, 5000, 30000):
            frames.append(_pcm_frame(amp))
        # 随机噪声帧（含低至无能量段）
        for _ in range(300):
            peak = rng.choice([50, 300, 660, 1200, 8000, 20000])
            frames.append(
                struct.pack("<512h", *[rng.randint(-peak, peak) for _ in range(512)])
            )
        for frame in frames:
            assert vad.is_speech(frame, 16000) is _reference_is_speech(frame, cutoff)


# ---------------------------------------------------------------------------
# IndexTTS2
# ---------------------------------------------------------------------------
def _make_wav(pcm: bytes, sample_rate: int = 22050, channels: int = 1) -> bytes:
    """构造标准 RIFF/WAV 字节（PCM16 单声道）。"""
    import wave
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


class TestIndexTTS2:
    def test_synthesize_happy_path(self, monkeypatch):
        capture: dict = {}
        pcm = b"\x01\x02" * 1024
        body = _make_wav(pcm, sample_rate=22050)
        _patch_urlopen(monkeypatch, body=body, capture=capture)

        tts = IndexTTS2(endpoint="http://tts:9200", voice="zh")
        assert tts.synthesize("你好") == pcm
        assert capture["url"] == "http://tts:9200/tts"
        assert b"Content-Disposition: form-data; name=\"text\"" in capture["body"]
        assert "你好".encode("utf-8") in capture["body"]
        assert b'Content-Disposition: form-data; name="language"' in capture["body"]
        assert b"zh\r\n" in capture["body"]
        assert tts.sample_rate == 22050

    def test_synthesize_empty_text_returns_empty(self):
        tts = IndexTTS2(endpoint="http://tts:9200")
        assert tts.synthesize("   ") == b""

    def test_synthesize_non_wav_response_mapped(self, monkeypatch):
        _patch_urlopen(monkeypatch, body=b"not wav")
        tts = IndexTTS2(endpoint="http://tts:9200")
        with pytest.raises(VoiceBackendError, match="非 WAV"):
            tts.synthesize("你好")

    def test_http_error_mapped(self, monkeypatch):
        def _raise(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 503, "err", {}, io.BytesIO(b""))

        monkeypatch.setattr("urllib.request.urlopen", _raise)
        tts = IndexTTS2(endpoint="http://tts:9200")
        with pytest.raises(VoiceBackendError, match="HTTP 503"):
            tts.synthesize("你好")

    def test_network_error_mapped(self, monkeypatch):
        def _raise(request, timeout=None):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", _raise)
        tts = IndexTTS2(endpoint="http://tts:9200")
        with pytest.raises(VoiceBackendError, match="服务不可达"):
            tts.synthesize("你好")
