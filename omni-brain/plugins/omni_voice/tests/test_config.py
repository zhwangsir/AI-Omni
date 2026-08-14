"""VoiceConfig 单元测试：默认值、from_dict、from_env、from_yaml 与非法值校验。"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from omni_sdk.identity import get_identity

from omni_voice.config import (
    RUNTIME_SETTABLE,
    VoiceConfig,
    _default_ref_audio,
    parse_simple_yaml,
)


class TestDefaults:
    """默认配置值与派生属性。"""

    def test_default_values(self):
        cfg = VoiceConfig()
        assert cfg.sample_rate == 16000
        assert cfg.channels == 1
        assert cfg.frame_ms == 32
        assert cfg.wake_word == "雪莉"
        assert cfg.wake_threshold == 0.5
        assert cfg.vad_threshold == 0.5
        assert cfg.vad_silence_ms == 1200
        assert cfg.max_record_s == 30.0
        assert cfg.asr_model == "whisper-1"
        assert cfg.tts_backend == "indextts2"
        assert cfg.tts_voice == "zh"
        assert cfg.tts_speed == pytest.approx(1.0)
        assert cfg.llm_endpoint == "http://192.168.71.109:52415/v1"
        assert cfg.asr_endpoint == "http://192.168.71.127:9210/v1"
        assert cfg.tts_endpoint == "http://192.168.71.127:9200"
        assert cfg.llm_model == "mlx-community/GLM-5.2-fp8"
        assert cfg.system_prompt
        assert cfg.wake_response == "我在"

    def test_default_wake_word_matches_identity(self):
        """M25：默认唤醒词必须与 omni_sdk identity 保持一致，避免前端/配置展示漂移。"""
        cfg = VoiceConfig()
        identity = get_identity()
        assert cfg.wake_word == identity.wake_aliases[0]
        assert cfg.wake_word in identity.wake_aliases

    def test_default_asr_prompt_contains_wake_word(self):
        """M32.29：默认 ASR 识别偏置注入唤醒词上下文，降低同音误识别（雪莉→Siri）。"""
        cfg = VoiceConfig()
        identity = get_identity()
        assert identity.display_name in cfg.asr_prompt
        assert identity.english_name in cfg.asr_prompt

    def test_asr_prompt_overridable(self):
        """asr_prompt 可通过 from_dict 覆盖；置空则关闭识别偏置。"""
        cfg = VoiceConfig.from_dict({"asr_prompt": "自定义上下文"})
        assert cfg.asr_prompt == "自定义上下文"
        assert VoiceConfig.from_dict({"asr_prompt": ""}).asr_prompt == ""

    def test_frame_bytes(self):
        # 16000Hz * 32ms * 2 字节(PCM16) * 1 声道 = 1024
        assert VoiceConfig().frame_bytes == 1024

    def test_summary_contains_all_fields(self):
        summary = VoiceConfig().summary()
        assert summary["sample_rate"] == 16000
        assert summary["llm_model"] == "mlx-community/GLM-5.2-fp8"
        assert "system_prompt" in summary
        assert "wake_response" in summary


class TestFromDict:
    def test_partial_dict(self):
        cfg = VoiceConfig.from_dict({"sample_rate": 8000, "wake_word": "hi_omni"})
        assert cfg.sample_rate == 8000
        assert cfg.wake_word == "hi_omni"
        assert cfg.channels == 1  # 其余保持默认

    def test_string_numbers_coerced(self):
        cfg = VoiceConfig.from_dict({"sample_rate": "16000", "wake_threshold": "0.7"})
        assert cfg.sample_rate == 16000
        assert cfg.wake_threshold == pytest.approx(0.7)

    def test_unknown_key_raises(self):
        with pytest.raises(ValueError, match="未知配置项"):
            VoiceConfig.from_dict({"not_a_field": 1})

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError, match="sample_rate"):
            VoiceConfig.from_dict({"sample_rate": -1})


class TestFromEnv:
    def test_env_override(self):
        env = {
            "OMNI_VOICE_SAMPLE_RATE": "24000",
            "OMNI_VOICE_WAKE_THRESHOLD": "0.9",
            "OMNI_VOICE_LLM_MODEL": "qwen-local",
        }
        cfg = VoiceConfig.from_env(environ=env)
        assert cfg.sample_rate == 24000
        assert cfg.wake_threshold == pytest.approx(0.9)
        assert cfg.llm_model == "qwen-local"
        assert cfg.frame_ms == 32  # 未覆盖的保持默认

    def test_env_ignores_unrelated(self):
        cfg = VoiceConfig.from_env(environ={"PATH": "/usr/bin", "OTHER_X": "1"})
        assert cfg.sample_rate == 16000

    def test_env_override_endpoints(self):
        env = {
            "OMNI_VOICE_LLM_ENDPOINT": "http://llm.local:8000/v1",
            "OMNI_VOICE_ASR_ENDPOINT": "http://asr.local:9210/v1",
            "OMNI_VOICE_TTS_ENDPOINT": "http://tts.local:9200",
        }
        cfg = VoiceConfig.from_env(environ=env)
        assert cfg.llm_endpoint == "http://llm.local:8000/v1"
        assert cfg.asr_endpoint == "http://asr.local:9210/v1"
        assert cfg.tts_endpoint == "http://tts.local:9200"

    def test_env_invalid_raises(self):
        with pytest.raises(ValueError):
            VoiceConfig.from_env(environ={"OMNI_VOICE_VAD_SILENCE_MS": "-5"})

    def test_env_over_base(self):
        base = VoiceConfig.from_dict({"sample_rate": 8000})
        cfg = VoiceConfig.from_env(environ={"OMNI_VOICE_FRAME_MS": "20"}, base=base)
        assert cfg.sample_rate == 8000  # base 保留
        assert cfg.frame_ms == 20  # env 覆盖


class TestFromYaml:
    def test_from_yaml_file(self, tmp_path):
        path = tmp_path / "voice.yaml"
        path.write_text(
            "sample_rate: 22050\n"
            "wake_word: hey_local\n"
            "wake_threshold: 0.65\n",
            encoding="utf-8",
        )
        cfg = VoiceConfig.from_yaml(path)
        assert cfg.sample_rate == 22050
        assert cfg.wake_word == "hey_local"
        assert cfg.wake_threshold == pytest.approx(0.65)

    def test_from_yaml_json_fallback(self, tmp_path):
        # JSON 是 YAML 子集，降级路径也应能解析
        path = tmp_path / "voice.json"
        path.write_text('{"sample_rate": 8000}', encoding="utf-8")
        assert VoiceConfig.from_yaml(path).sample_rate == 8000


class TestValidation:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"sample_rate": 0},
            {"sample_rate": -16000},
            {"channels": 0},
            {"frame_ms": 0},
            {"wake_threshold": 1.5},
            {"wake_threshold": -0.1},
            {"vad_threshold": 2.0},
            {"vad_silence_ms": -1},
            {"max_record_s": 0},
            {"wake_word": "  "},
            {"asr_model": ""},
            {"tts_backend": "invalid"},
            {"tts_backend": ""},
            {"tts_speed": 0},
            {"tts_speed": -1},
            {"tts_voice": ""},
            {"llm_model": ""},
            {"llm_endpoint": ""},
            {"asr_endpoint": ""},
            {"tts_endpoint": ""},
        ],
    )
    def test_invalid_values_raise(self, kwargs):
        with pytest.raises(ValueError):
            VoiceConfig(**kwargs)


class TestTtsMuted:
    """M6.3：tts_muted —— OpenTalking 独家发声模式下 omni_voice 本地静音的开关。"""

    def test_default_is_false(self):
        assert VoiceConfig().tts_muted is False

    def test_from_dict_bool_passthrough(self):
        assert VoiceConfig.from_dict({"tts_muted": True}).tts_muted is True
        assert VoiceConfig.from_dict({"tts_muted": False}).tts_muted is False

    @pytest.mark.parametrize("text", ["true", "True", "1", "yes", "on"])
    def test_from_dict_truthy_strings_coerced(self, text):
        assert VoiceConfig.from_dict({"tts_muted": text}).tts_muted is True

    @pytest.mark.parametrize("text", ["false", "False", "0", "no", "off"])
    def test_from_dict_falsy_strings_coerced(self, text):
        assert VoiceConfig.from_dict({"tts_muted": text}).tts_muted is False

    def test_from_dict_invalid_bool_raises(self):
        with pytest.raises(ValueError, match="tts_muted"):
            VoiceConfig.from_dict({"tts_muted": "maybe"})

    def test_from_env_override(self):
        cfg = VoiceConfig.from_env(environ={"OMNI_VOICE_TTS_MUTED": "true"})
        assert cfg.tts_muted is True

    def test_summary_contains_tts_muted(self):
        assert VoiceConfig().summary()["tts_muted"] is False

    def test_runtime_settable(self):
        """voice_config set 复用既有工具即可调整（不新增 tool）。"""
        assert "tts_muted" in RUNTIME_SETTABLE


class TestTtsRefAudio:
    """M32.15：IndexTTS2 参考音频配置。"""

    def test_default_is_default_path(self):
        assert VoiceConfig().tts_ref_audio == _default_ref_audio()

    def test_default_ref_audio_points_to_default_wav(self):
        """M32.21：默认参考音频必须指向 default.wav，而不是其他候选文件。"""
        path = Path(_default_ref_audio())
        assert path.name == "default.wav"

    def test_default_ref_audio_exists_and_valid_wav(self):
        """M32.18：默认参考音频必须存在且为合法单声道 WAV。

        缺失或损坏会导致运行时降级为服务默认音色，用户听感接近系统 TTS。
        """
        path = Path(_default_ref_audio())
        assert path.exists(), f"默认参考音频缺失: {path}"
        with wave.open(str(path), "rb") as wav:
            assert wav.getnchannels() == 1
            assert wav.getframerate() > 0
            assert wav.getnframes() > 0

    def test_from_dict_path_passthrough(self):
        cfg = VoiceConfig.from_dict({"tts_ref_audio": "/tmp/ref.wav"})
        assert cfg.tts_ref_audio == "/tmp/ref.wav"

    def test_summary_contains_tts_ref_audio(self):
        assert "tts_ref_audio" in VoiceConfig().summary()

    def test_runtime_settable(self):
        """voice_config set 复用既有工具即可调整（不新增 tool）。"""
        assert "tts_ref_audio" in RUNTIME_SETTABLE


class TestTtsEmoText:
    """M32.16：IndexTTS2 情感/风格提示文本配置。"""

    def test_default_is_empty_for_neutral_voice(self):
        """M32.19：默认情感文本为空，日常对话不做额外情感渲染。"""
        assert VoiceConfig().tts_emo_text == ""

    def test_from_dict_passthrough(self):
        cfg = VoiceConfig.from_dict({"tts_emo_text": "活泼可爱"})
        assert cfg.tts_emo_text == "活泼可爱"

    def test_haibara_emotion_preserved(self):
        """M32.19：灰原哀风格情感提示仍可通过配置启用。"""
        emo = "清冷温柔，略带忧伤，像灰原哀，少女音色，语速自然，咬字清晰"
        cfg = VoiceConfig.from_dict({"tts_emo_text": emo})
        assert cfg.tts_emo_text == emo

    def test_empty_string_allowed(self):
        cfg = VoiceConfig.from_dict({"tts_emo_text": ""})
        assert cfg.tts_emo_text == ""

    def test_summary_contains_tts_emo_text(self):
        assert "tts_emo_text" in VoiceConfig().summary()

    def test_runtime_settable(self):
        assert "tts_emo_text" in RUNTIME_SETTABLE


class TestTtsEmoAlpha:
    """M32.17：IndexTTS2 情感强度配置。"""

    def test_default_is_095(self):
        assert VoiceConfig().tts_emo_alpha == pytest.approx(0.95)

    def test_from_dict_coerced(self):
        cfg = VoiceConfig.from_dict({"tts_emo_alpha": "0.9"})
        assert cfg.tts_emo_alpha == pytest.approx(0.9)

    def test_summary_contains_tts_emo_alpha(self):
        assert "tts_emo_alpha" in VoiceConfig().summary()

    def test_runtime_settable(self):
        assert "tts_emo_alpha" in RUNTIME_SETTABLE


class TestParseSimpleYaml:
    """无 PyYAML 时的降级解析器。"""

    def test_scalars(self):
        data = parse_simple_yaml(
            "name: omni_voice\n"
            "version: 0.1.0\n"
            "count: 3\n"
            "ratio: 0.5\n"
            "# 注释行\n"
            "\n"
        )
        assert data["name"] == "omni_voice"
        assert data["version"] == "0.1.0"
        assert data["count"] == 3
        assert data["ratio"] == pytest.approx(0.5)

    def test_list(self):
        data = parse_simple_yaml("provides_tools:\n  - voice_status\n  - voice_speak\n")
        assert data["provides_tools"] == ["voice_status", "voice_speak"]
