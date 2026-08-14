"""IndexTTS2 后端单元测试：multipart 构造、WAV 解码与错误处理。"""

from __future__ import annotations

import io
import wave
from typing import Any
from unittest.mock import patch

import pytest

from omni_voice.backends.indextts2_tts import IndexTTS2
from omni_voice.errors import VoiceBackendError


def _make_wav(pcm: bytes, sample_rate: int = 22050) -> bytes:
    """构造有效 RIFF/WAV 字节（单声道 16-bit）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def _fake_urlopen_factory(wav_bytes: bytes, status: int = 200):
    """返回一个模拟 urllib.request.urlopen 的工厂。"""

    def fake_urlopen(request: Any, **kwargs: Any):
        class _Response:
            def read(self) -> bytes:
                return wav_bytes

            def __enter__(self):
                return self

            def __exit__(self, *args: Any) -> None:
                pass

        return _Response()

    return fake_urlopen


class TestIndexTTS2Synthesize:
    """正常合成路径。"""

    def test_empty_text_returns_empty(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200")
        assert tts.synthesize("") == b""
        assert tts.synthesize("   ") == b""

    def test_synthesize_decodes_wav_and_updates_sample_rate(self):
        pcm = b"\x01\x02" * 100
        wav = _make_wav(pcm, sample_rate=24000)
        tts = IndexTTS2(endpoint="http://tts.local:9200", voice="xiaoyi", speed=1.2)

        with patch("urllib.request.urlopen", _fake_urlopen_factory(wav)):
            result = tts.synthesize("你好")

        assert result == pcm
        assert tts.sample_rate == 24000

    def test_multipart_body_maps_voice_to_language(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200", voice="zh")
        body, boundary = tts._multipart_body("你好雪莉")
        text = body.decode("utf-8")
        assert f'"text"\r\n\r\n你好雪莉' in text
        assert f'"language"\r\n\r\nzh' in text
        assert f'"emo_alpha"\r\n\r\n0.8' in text
        assert text.startswith(f"--{boundary}")
        assert text.endswith(f"--{boundary}--\r\n")

    def test_multipart_body_includes_ref_audio_bytes(self):
        ref = b"RIFF" + b"\x00" * 20
        tts = IndexTTS2(endpoint="http://tts.local:9200", voice="zh", ref_audio=ref)
        body, boundary = tts._multipart_body("你好")
        assert b'name="ref_audio"; filename="ref.wav"' in body
        assert ref in body

    def test_multipart_body_includes_ref_audio_from_file(self, tmp_path):
        ref_path = tmp_path / "ref.wav"
        ref_path.write_bytes(b"fake wav bytes")
        tts = IndexTTS2(endpoint="http://tts.local:9200", voice="zh", ref_audio=str(ref_path))
        body, boundary = tts._multipart_body("你好")
        assert b"fake wav bytes" in body

    def test_ref_audio_missing_file_is_gracefully_ignored(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200", voice="zh", ref_audio="/nonexistent/ref.wav")
        body, boundary = tts._multipart_body("你好")
        assert b"ref_audio" not in body

    def test_emo_text_is_included_when_set(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200", voice="zh", emo_text="高兴")
        body, boundary = tts._multipart_body("你好")
        assert f'"emo_text"\r\n\r\n高兴' in body.decode("utf-8")

    def test_endpoint_trailing_slash_is_stripped(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200/")
        assert tts.endpoint == "http://tts.local:9200"


class TestIndexTTS2Errors:
    """错误路径。"""

    def test_invalid_wav_raises_voice_backend_error(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200")

        with patch("urllib.request.urlopen", _fake_urlopen_factory(b"not a wav")):
            with pytest.raises(VoiceBackendError, match="非 WAV"):
                tts.synthesize("你好")

    def test_http_error_raises_voice_backend_error(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200")

        def raise_http_error(*args: Any, **kwargs: Any):
            import urllib.error

            raise urllib.error.HTTPError(
                url="http://tts.local:9200/tts",
                code=500,
                msg="Internal Server Error",
                hdrs={},  # type: ignore[arg-type]
                fp=None,  # type: ignore[arg-type]
            )

        with patch("urllib.request.urlopen", raise_http_error):
            with pytest.raises(VoiceBackendError, match="HTTP 500"):
                tts.synthesize("你好")

    def test_url_error_raises_voice_backend_error(self):
        tts = IndexTTS2(endpoint="http://tts.local:9200")

        def raise_url_error(*args: Any, **kwargs: Any):
            import urllib.error

            raise urllib.error.URLError("connection refused")

        with patch("urllib.request.urlopen", raise_url_error):
            with pytest.raises(VoiceBackendError, match="不可达"):
                tts.synthesize("你好")
