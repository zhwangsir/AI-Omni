"""M32.30 配置接入测试：tts_style 字段、校验、装配传参。"""

from __future__ import annotations

from typing import Any

import pytest

from omni_voice import tools
from omni_voice.config import RUNTIME_SETTABLE, VoiceConfig


@pytest.fixture()
def fresh_runtime():
    """每个测试前重置运行时单例，结束后回收管道线程。"""
    rt = tools._reset_runtime()
    yield rt
    if rt.pipeline is not None:
        rt.pipeline.stop()
        rt.pipeline = None


class TestTTSStyleConfig:
    """tts_style 配置字段（M32.30：默认日常冷静款）。"""

    def test_default_style_is_calm(self):
        assert VoiceConfig().tts_style == "calm"

    def test_style_in_runtime_settable(self):
        assert "tts_style" in RUNTIME_SETTABLE

    def test_from_dict_accepts_valid_style(self):
        cfg = VoiceConfig.from_dict({"tts_style": "serious"})
        assert cfg.tts_style == "serious"

    def test_invalid_style_rejected(self):
        with pytest.raises(ValueError, match="tts_style"):
            VoiceConfig.from_dict({"tts_style": "angry"})

    def test_empty_style_rejected(self):
        with pytest.raises(ValueError):
            VoiceConfig.from_dict({"tts_style": ""})


class TestAssemblyStyleWiring:
    """tools._build_real_components 装配 style（M32.30）。"""

    def _capture_indextts2(self, monkeypatch, captured: dict[str, Any]) -> None:
        class _FakeIndexTTS2:
            def __init__(self, endpoint: str, **kwargs: Any):
                captured["endpoint"] = endpoint
                captured.update(kwargs)

        class _FakePlayer:
            def __init__(self, sample_rate: int):
                pass

        monkeypatch.setattr("omni_voice.backends.indextts2_tts.IndexTTS2", _FakeIndexTTS2)
        monkeypatch.setattr("omni_voice.audio.SounddevicePlayer", _FakePlayer)
        monkeypatch.setattr("omni_voice.audio.SounddeviceSource", object)

    def test_style_passed_to_backend(self, fresh_runtime, monkeypatch):
        captured: dict[str, Any] = {}
        self._capture_indextts2(monkeypatch, captured)
        tools._build_real_components(fresh_runtime.config)
        assert captured["style"] == "calm"

    def test_explicit_emo_text_uses_config_alpha(self, fresh_runtime, monkeypatch):
        """显式 emo_text 时：emo_alpha 用配置值（覆盖 style 强度）。"""
        captured: dict[str, Any] = {}
        self._capture_indextts2(monkeypatch, captured)
        rt = fresh_runtime
        rt.config = VoiceConfig.from_dict({"tts_emo_text": "自定义情感", "tts_emo_alpha": "0.9"})
        tools._build_real_components(rt.config)
        assert captured["emo_text"] == "自定义情感"
        assert captured["emo_alpha"] == 0.9

    def test_default_uses_style_alpha(self, fresh_runtime, monkeypatch):
        """默认（未显式 emo_text）：emo_alpha 传 None，由 style 预设决定强度。"""
        captured: dict[str, Any] = {}
        self._capture_indextts2(monkeypatch, captured)
        tools._build_real_components(fresh_runtime.config)
        assert captured["emo_text"] is None
        assert captured["emo_alpha"] is None

    def test_custom_style_passed(self, fresh_runtime, monkeypatch):
        captured: dict[str, Any] = {}
        self._capture_indextts2(monkeypatch, captured)
        rt = fresh_runtime
        rt.config = VoiceConfig.from_dict({"tts_style": "teasing"})
        tools._build_real_components(rt.config)
        assert captured["style"] == "teasing"
