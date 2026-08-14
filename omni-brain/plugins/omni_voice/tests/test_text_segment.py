"""text_segment 长文本分段测试（M32.30：IndexTTS2 输入规范 ≤70 字/段）。"""

from __future__ import annotations

import pytest

from omni_voice.text_segment import DEFAULT_MAX_LEN, segment_text


class TestShortText:
    def test_empty_returns_empty(self):
        assert segment_text("") == []
        assert segment_text("   ") == []

    def test_short_text_single_segment(self):
        assert segment_text("你好，雪莉。") == ["你好，雪莉。"]

    def test_exactly_max_len_single_segment(self):
        text = "啊" * DEFAULT_MAX_LEN
        assert segment_text(text) == [text]


class TestSentenceSplit:
    def test_splits_on_sentence_endings(self):
        text = "第一句。第二句！第三句？"
        # 每句 4 字，max_len=7 → 两两合并不下，各自成段
        segments = segment_text(text, max_len=7)
        assert segments == ["第一句。", "第二句！", "第三句？"]

    def test_merges_short_sentences_within_limit(self):
        text = "今天天气不错。我们去散步吧。你觉得呢？"
        segments = segment_text(text, max_len=70)
        assert segments == ["今天天气不错。我们去散步吧。你觉得呢？"]

    def test_flush_pending_before_overflow(self):
        # 两句各 40 字，max 70：合并不下 → 各成一段
        s1 = "甲" * 39 + "。"
        s2 = "乙" * 39 + "。"
        segments = segment_text(s1 + s2, max_len=70)
        assert segments == [s1, s2]


class TestLongSentenceFallback:
    def test_long_sentence_splits_on_comma(self):
        # 单句 90 字含逗号：逗号处切，每段 ≤70
        part1 = "子" * 40
        part2 = "丑" * 40
        text = part1 + "，" + part2 + "。"
        segments = segment_text(text, max_len=70)
        assert len(segments) == 2
        assert segments[0] == part1 + "，"
        assert segments[1] == part2 + "。"
        assert all(len(s) <= 70 for s in segments)

    def test_hard_cut_when_no_punctuation(self):
        text = "无标点" * 40  # 120 字
        segments = segment_text(text, max_len=70)
        assert len(segments) == 2
        assert "".join(segments) == text
        assert all(len(s) <= 70 for s in segments)

    def test_hard_cut_preserves_order(self):
        text = "字" * 150
        segments = segment_text(text, max_len=70)
        assert [len(s) for s in segments] == [70, 70, 10]


class TestEdgeCases:
    def test_ellipsis_is_sentence_ending(self):
        text = "他沉默了……没有人知道答案。"
        segments = segment_text(text, max_len=10)
        assert segments == ["他沉默了……", "没有人知道答案。"]

    def test_mixed_punctuation_kept(self):
        text = "真的吗？是的！就这样。"
        segments = segment_text(text, max_len=70)
        assert segments == [text]

    def test_whitespace_stripped_per_segment(self):
        text = "  第一句。  第二句。  "
        segments = segment_text(text, max_len=70)
        assert segments == ["第一句。 第二句。"] or segments == ["第一句。第二句。"]

    def test_invalid_max_len_raises(self):
        with pytest.raises(ValueError):
            segment_text("你好", max_len=0)

    def test_concat_roundtrip_no_content_loss(self):
        text = "我本来以为，那些事情，早就已经结束了。人是没有办法违抗时间的洪流的。"
        segments = segment_text(text, max_len=20)
        # 拼接（去除分段间隙空白）后内容不丢字
        joined = "".join(segments)
        for ch in "我本来以为那些事情早就已经结束了人是没有办法违抗时间的洪流的":
            assert ch in joined
