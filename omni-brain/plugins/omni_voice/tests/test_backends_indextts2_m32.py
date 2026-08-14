"""IndexTTS2 后端 M32.30 扩展测试：风格预设、采样参数透传、长文本分段合成。"""

from __future__ import annotations

import io
import wave
from typing import Any
from unittest.mock import patch

import pytest

from omni_voice.backends.indextts2_tts import IndexTTS2
from omni_voice.tts_styles import TTS_STYLES


def _make_wav(pcm: bytes, sample_rate: int = 22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, wav_bytes: bytes):
        self._wav = wav_bytes

    def read(self) -> bytes:
        return self._wav

    def __enter__(self):
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class TestStyleIntegration:
    """style 预设自动填充 emo_text / emo_alpha / 采样参数。"""

    def test_style_fills_emo_text_and_alpha(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200", style="calm")
        body, _ = tts._multipart_body("你好")
        text = body.decode("utf-8")
        assert TTS_STYLES["calm"].emo_text in text
        assert f'"emo_alpha"\r\n\r\n{TTS_STYLES["calm"].emo_alpha}' in text

    def test_explicit_emo_text_overrides_style(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200", style="calm", emo_text="自定义情感")
        body, _ = tts._multipart_body("你好")
        text = body.decode("utf-8")
        assert '"emo_text"\r\n\r\n自定义情感' in text
        assert TTS_STYLES["calm"].emo_text not in text

    def test_explicit_emo_alpha_overrides_style(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200", style="serious", emo_alpha=0.95)
        body, _ = tts._multipart_body("你好")
        assert '"emo_alpha"\r\n\r\n0.95' in body.decode("utf-8")

    def test_serious_style_uses_own_alpha(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200", style="serious")
        body, _ = tts._multipart_body("你好")
        text = body.decode("utf-8")
        assert TTS_STYLES["serious"].emo_text in text
        assert f'"emo_alpha"\r\n\r\n{TTS_STYLES["serious"].emo_alpha}' in text

    def test_no_style_no_emo_text_keeps_legacy_behavior(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200")
        body, _ = tts._multipart_body("你好")
        assert b"emo_text" not in body

    def test_unknown_style_raises(self):
        with pytest.raises(ValueError, match="未知 TTS 风格"):
            IndexTTS2(endpoint="http://tts.local:9200", style="angry")


class TestSamplingParams:
    """top_p / temperature 透传（服务端未升级时 FastAPI 静默忽略，安全）。"""

    def test_style_defaults_top_p_temperature(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200", style="calm")
        body, _ = tts._multipart_body("你好")
        text = body.decode("utf-8")
        assert '"top_p"\r\n\r\n0.75' in text
        assert '"temperature"\r\n\r\n0.65' in text

    def test_explicit_sampling_params_override_style(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200", style="calm", top_p=0.9, temperature=0.8)
        body, _ = tts._multipart_body("你好")
        text = body.decode("utf-8")
        assert '"top_p"\r\n\r\n0.9' in text
        assert '"temperature"\r\n\r\n0.8' in text

    def test_sampling_params_present_without_style(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200")
        body, _ = tts._multipart_body("你好")
        text = body.decode("utf-8")
        assert '"top_p"\r\n\r\n0.75' in text
        assert '"temperature"\r\n\r\n0.65' in text


class TestSegmentedSynthesis:
    """长文本按 ≤70 字分段，逐段合成后拼接 PCM。"""

    def _urlopen_recorder(self, pcm_per_call: bytes, sample_rate: int = 22050):
        calls: list[str] = []

        def fake_urlopen(request: Any, **kwargs: Any):
            body = request.data.decode("utf-8", errors="replace")
            # 提取 multipart 中的 text 字段
            marker = 'name="text"\r\n\r\n'
            start = body.index(marker) + len(marker)
            end = body.index("\r\n", start)
            calls.append(body[start:end])
            return _FakeResponse(_make_wav(pcm_per_call, sample_rate))

        return calls, fake_urlopen

    def test_short_text_single_request(self):
        calls, fake = self._urlopen_recorder(b"\x01\x02" * 50)
        tts = IndexTTS2(endpoint="http://tts.local:9200")
        with patch("urllib.request.urlopen", fake):
            result = tts.synthesize("短句。")
        assert len(calls) == 1
        assert calls[0] == "短句。"
        assert result == b"\x01\x02" * 50

    def test_long_text_segmented_and_concatenated(self):
        calls, fake = self._urlopen_recorder(b"\x03\x04" * 50)
        tts = IndexTTS2(endpoint="http://tts.local:9200")
        text = "第一段话。" * 20 + "第二段话。" * 20  # 200 字 → 多段
        with patch("urllib.request.urlopen", fake):
            result = tts.synthesize(text)
        assert len(calls) >= 2
        assert all(len(c) <= 70 for c in calls)
        assert result == b"\x03\x04" * 50 * len(calls)

    def test_segment_sample_rate_from_last_wav(self):
        calls, fake = self._urlopen_recorder(b"\x00\x00" * 10, sample_rate=24000)
        tts = IndexTTS2(endpoint="http://tts.local:9200")
        text = "字" * 150
        with patch("urllib.request.urlopen", fake):
            tts.synthesize(text)
        assert tts.sample_rate == 24000

    def test_segmentation_respects_custom_max_len(self):
        calls, fake = self._urlopen_recorder(b"\x00\x00" * 10)
        tts = IndexTTS2(endpoint="http://tts.local:9200", max_segment_len=30)
        text = "这是测试句子。" * 10  # 70 字
        with patch("urllib.request.urlopen", fake):
            tts.synthesize(text)
        assert len(calls) >= 3
        assert all(len(c) <= 30 for c in calls)

    def test_empty_text_no_request(self):
        calls, fake = self._urlopen_recorder(b"\x00\x00" * 10)
        tts = IndexTTS2(endpoint="http://tts.local:9200")
        with patch("urllib.request.urlopen", fake):
            assert tts.synthesize("") == b""
        assert calls == []
