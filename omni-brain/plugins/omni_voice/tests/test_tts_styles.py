"""tts_styles 情感风格预设测试（M32.30 灰原哀·台配声线调优 v2）。"""

from __future__ import annotations

import pytest

from omni_voice.tts_styles import DEFAULT_STYLE, TTS_STYLES, TTSStyle, get_style

STYLE_NAMES = {"calm", "sad", "teasing", "serious", "gentle"}


class TestStyleRegistry:
    """五个场景预设齐备且字段合法。"""

    def test_five_styles_registered(self):
        assert set(TTS_STYLES) == STYLE_NAMES

    def test_default_style_is_calm(self):
        assert DEFAULT_STYLE == "calm"
        assert TTS_STYLES[DEFAULT_STYLE].label == "日常冷静款"

    @pytest.mark.parametrize("name", list(STYLE_NAMES))
    def test_style_fields_valid(self, name: str):
        style = TTS_STYLES[name]
        assert style.name == name
        assert style.label  # 中文名非空
        assert len(style.emo_text) >= 20  # 提示词足够具体（语速+情绪+气质+细节+句尾）
        assert 0.0 < style.emo_alpha <= 1.0
        assert 0.0 < style.top_p <= 1.0
        assert 0.0 < style.temperature <= 1.0
        assert style.description

    def test_styles_are_frozen(self):
        style = TTS_STYLES["calm"]
        with pytest.raises(AttributeError):
            style.emo_alpha = 0.1  # type: ignore[misc]


class TestPromptContent:
    """提示词内容贴合指南：含台配特征，不含角色名（音色由参考音频决定）。"""

    @pytest.mark.parametrize("name", list(STYLE_NAMES))
    def test_prompt_excludes_character_name(self, name: str):
        assert "灰原哀" not in TTS_STYLES[name].emo_text

    @pytest.mark.parametrize("name", list(STYLE_NAMES))
    def test_prompt_contains_taiwanese_dna(self, name: str):
        """所有提示词必须含台配女配音员核心咬字特征。"""
        text = TTS_STYLES[name].emo_text
        assert "台湾" in text
        assert "咬字清晰" in text

    def test_calm_prompt_matches_guide(self):
        text = TTS_STYLES["calm"].emo_text
        assert "语速中等偏缓" in text
        assert "疏离感" in text
        assert "句尾轻收不上扬" in text

    def test_sad_prompt_matches_guide(self):
        text = TTS_STYLES["sad"].emo_text
        assert "语速放慢" in text
        assert "忧伤" in text
        assert "克制隐忍" in text

    def test_teasing_prompt_matches_guide(self):
        text = TTS_STYLES["teasing"].emo_text
        assert "吐槽" in text
        assert "情绪不张扬" in text

    def test_serious_prompt_matches_guide(self):
        text = TTS_STYLES["serious"].emo_text
        assert "严肃冷静" in text
        assert "压迫感藏在平静" in text

    def test_gentle_prompt_matches_guide(self):
        text = TTS_STYLES["gentle"].emo_text
        assert "温柔" in text
        assert "不甜腻" in text or "嘴硬心软" in text


class TestGetStyle:
    def test_known_name_returns_style(self):
        style = get_style("serious")
        assert isinstance(style, TTSStyle)
        assert style.name == "serious"

    def test_unknown_name_raises_with_valid_list(self):
        with pytest.raises(ValueError, match="未知 TTS 风格"):
            get_style("angry")
        try:
            get_style("angry")
        except ValueError as exc:
            message = str(exc)
            for valid in STYLE_NAMES:
                assert valid in message

    def test_empty_name_raises(self):
        with pytest.raises(ValueError):
            get_style("")


class TestGuideParameters:
    """基准参数：calm/gentle 使用默认 top_p=0.75/temp=0.65，其他风格按场景微调。"""

    def test_calm_uses_default_params(self):
        style = TTS_STYLES["calm"]
        assert style.top_p == pytest.approx(0.75)
        assert style.temperature == pytest.approx(0.65)

    def test_emotion_intensity_per_style(self):
        assert TTS_STYLES["calm"].emo_alpha == pytest.approx(0.65)
        assert TTS_STYLES["sad"].emo_alpha == pytest.approx(0.75)
        assert TTS_STYLES["teasing"].emo_alpha == pytest.approx(0.7)
        assert TTS_STYLES["serious"].emo_alpha == pytest.approx(0.8)
        assert TTS_STYLES["gentle"].emo_alpha == pytest.approx(0.7)

    def test_sad_uses_lower_temperature(self):
        """忧伤场景降温度求稳定。"""
        assert TTS_STYLES["sad"].temperature < TTS_STYLES["calm"].temperature
        assert TTS_STYLES["sad"].top_p == pytest.approx(0.7)

    def test_teasing_uses_higher_temperature(self):
        """吐槽场景升温度增自然感。"""
        assert TTS_STYLES["teasing"].temperature > TTS_STYLES["calm"].temperature
        assert TTS_STYLES["teasing"].top_p == pytest.approx(0.8)

    def test_serious_uses_lowest_temperature(self):
        """警告场景最收敛。"""
        assert TTS_STYLES["serious"].temperature == pytest.approx(0.55)
        assert TTS_STYLES["serious"].top_p == pytest.approx(0.7)
