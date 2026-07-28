"""VoiceConfig 单元测试：默认值、from_dict、from_env、from_yaml 与非法值校验。"""

from __future__ import annotations

import pytest

from omni_voice.config import RUNTIME_SETTABLE, VoiceConfig, parse_simple_yaml


class TestDefaults:
    """默认配置值与派生属性。"""

    def test_default_values(self):
        cfg = VoiceConfig()
        assert cfg.sample_rate == 16000
        assert cfg.channels == 1
        assert cfg.frame_ms == 32
        assert cfg.wake_word == "hey_omni"
        assert cfg.wake_threshold == 0.5
        assert cfg.vad_threshold == 0.5
        assert cfg.vad_silence_ms == 1200
        assert cfg.max_record_s == 30.0
        assert cfg.asr_model == "whisper-1"
        assert cfg.tts_voice == "alloy"
        assert cfg.llm_endpoint == "http://localhost:18789/v1"
        assert cfg.llm_model == "qwen3.6-uncensored"
        assert cfg.system_prompt
        assert cfg.wake_response == "我在"

    def test_frame_bytes(self):
        # 16000Hz * 32ms * 2 字节(PCM16) * 1 声道 = 1024
        assert VoiceConfig().frame_bytes == 1024

    def test_summary_contains_all_fields(self):
        summary = VoiceConfig().summary()
        assert summary["sample_rate"] == 16000
        assert summary["llm_model"] == "qwen3.6-uncensored"
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
            {"tts_voice": ""},
            {"llm_model": ""},
            {"llm_endpoint": ""},
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
