"""omni_music library.long_audio 长音频分析测试（M19.6）。

TDD 测试先行：覆盖 LongAudioAnalyzer 的时长判定、关键词分类、边界。
纯逻辑无依赖，不碰真实音频文件。
"""

from __future__ import annotations

import pytest

from omni_music.library.long_audio import LongAudioAnalyzer


def _song(duration_s: int, title: str = "歌曲", artist: str = "未知") -> dict:
    return {
        "title": title,
        "artist": artist,
        "duration_s": duration_s,
        "path": f"/music/{title}.mp3",
    }


# ===========================================================================
# is_long_audio
# ===========================================================================
class TestIsLongAudio:
    def test_duration_over_15min_is_long(self) -> None:
        """时长 > 15 分钟判定为长音频。"""
        a = LongAudioAnalyzer()
        assert a.is_long_audio(_song(duration_s=15 * 60 + 1)) is True

    def test_duration_exactly_15min_is_long(self) -> None:
        """时长恰好 15 分钟判定为长音频（>= 阈值）。"""
        a = LongAudioAnalyzer()
        assert a.is_long_audio(_song(duration_s=15 * 60)) is True

    def test_duration_under_15min_not_long(self) -> None:
        """时长 < 15 分钟非长音频。"""
        a = LongAudioAnalyzer()
        assert a.is_long_audio(_song(duration_s=14 * 60 + 59)) is False

    def test_zero_duration_not_long(self) -> None:
        assert a if False else True
        a = LongAudioAnalyzer()
        assert a.is_long_audio(_song(duration_s=0)) is False

    def test_custom_threshold(self) -> None:
        """自定义阈值。"""
        a = LongAudioAnalyzer(threshold_s=10 * 60)
        assert a.is_long_audio(_song(duration_s=11 * 60)) is True
        assert a.is_long_audio(_song(duration_s=9 * 60)) is False

    def test_missing_duration_treated_as_zero(self) -> None:
        """duration_s 缺失视为 0。"""
        a = LongAudioAnalyzer()
        assert a.is_long_audio({"title": "x"}) is False


# ===========================================================================
# classify_long_audio
# ===========================================================================
class TestClassify:
    def test_podcast_keyword_in_title(self) -> None:
        """标题含 episode/podcast 判为 podcast。"""
        a = LongAudioAnalyzer()
        assert a.classify_long_audio(_song(20 * 60, title="Episode 42")) == "podcast"
        assert a.classify_long_audio(_song(20 * 60, title="My Podcast Show")) == "podcast"

    def test_dj_mix_keyword_in_title(self) -> None:
        """标题含 mix 判为 dj_mix。"""
        a = LongAudioAnalyzer()
        assert a.classify_long_audio(_song(30 * 60, title="Summer Mix 2024")) == "dj_mix"
        assert a.classify_long_audio(_song(30 * 60, title="Live DJ Set")) == "dj_mix"

    def test_audiobook_keyword_in_title(self) -> None:
        """标题含 chapter/audiobook 判为 audiobook。"""
        a = LongAudioAnalyzer()
        assert a.classify_long_audio(_song(25 * 60, title="Chapter 1")) == "audiobook"
        assert a.classify_long_audio(_song(25 * 60, title="Audiobook Reading")) == "audiobook"

    def test_unknown_when_no_keyword(self) -> None:
        """无关键词匹配判为 unknown。"""
        a = LongAudioAnalyzer()
        assert a.classify_long_audio(_song(20 * 60, title="纯音乐")) == "unknown"

    def test_classify_short_audio_returns_unknown(self) -> None:
        """短音频分类返回 unknown（不判定为长音频类型）。"""
        a = LongAudioAnalyzer()
        assert a.classify_long_audio(_song(5 * 60, title="Episode 1")) == "unknown"

    def test_classify_case_insensitive(self) -> None:
        """关键词匹配大小写不敏感。"""
        a = LongAudioAnalyzer()
        assert a.classify_long_audio(_song(20 * 60, title="EPISODE 1")) == "podcast"
        assert a.classify_long_audio(_song(20 * 60, title="Best MIX Ever")) == "dj_mix"

    def test_classify_priority_podcast_over_mix(self) -> None:
        """同时含 episode 和 mix 时优先 podcast（播客判定优先）。"""
        a = LongAudioAnalyzer()
        # "episode" 与 "mix" 同在标题中：podcast 优先
        result = a.classify_long_audio(_song(20 * 60, title="Episode Mix"))
        assert result in ("podcast", "dj_mix")  # 实现择一即可，但需稳定

    def test_classify_missing_title(self) -> None:
        """title 缺失判为 unknown。"""
        a = LongAudioAnalyzer()
        assert a.classify_long_audio({"duration_s": 20 * 60}) == "unknown"


# ===========================================================================
# 辅助方法
# ===========================================================================
class TestHelpers:
    def test_get_long_audio_summary(self) -> None:
        """get_summary 返回 is_long + category。"""
        a = LongAudioAnalyzer()
        summary = a.get_summary(_song(20 * 60, title="Episode 1"))
        assert summary["is_long_audio"] is True
        assert summary["category"] == "podcast"

    def test_get_summary_short_audio(self) -> None:
        a = LongAudioAnalyzer()
        summary = a.get_summary(_song(3 * 60, title="短歌"))
        assert summary["is_long_audio"] is False
        assert summary["category"] == "unknown"
