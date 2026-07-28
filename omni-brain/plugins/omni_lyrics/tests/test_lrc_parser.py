"""LRC 格式解析器测试（M18 TDD red → green）。

覆盖：
- 标准 LRC ``[mm:ss.xx]歌词`` 解析
- 多时间轴同一行 ``[00:01.00][00:15.00]重复歌词``
- 逐字歌词（增强 LRC）``[mm:ss.xx]字[mm:ss.xx]字``
- 翻译歌词（双语）原始行 + 翻译行配对
- 元数据标签 ``[ti:][ar:][al:][by:]``
- 纯文本容错（无时间轴 → 单行 time_s=0.0）
- 空字符串 / None → 空列表
- LyricsLine 结构：``{time_s, text, translation, words}``
- 时间戳格式兼容 ``[mm:ss]`` / ``[mm:ss.xx]`` / ``[mm:ss.xxx]``
"""

from __future__ import annotations

import pytest

from omni_lyrics.lrc_parser import LrcParser, LyricsLine, LrcMetadata, Word


class TestLrcParserEmptyAndPlainText:
    """空输入与纯文本容错。"""

    def test_parse_none_returns_empty_list(self) -> None:
        """None 输入返回空列表。"""
        assert LrcParser.parse(None) == []

    def test_parse_empty_string_returns_empty_list(self) -> None:
        """空字符串返回空列表。"""
        assert LrcParser.parse("") == []

    def test_parse_whitespace_only_returns_empty_list(self) -> None:
        """纯空白字符串返回空列表。"""
        assert LrcParser.parse("   \n  \t ") == []

    def test_parse_plain_text_returns_single_line_at_zero(self) -> None:
        """纯文本（无时间轴）容错为单行 time_s=0.0。"""
        text = "这是一首没有时间轴的歌词"
        result = LrcParser.parse(text)
        assert len(result) == 1
        assert result[0].time_s == pytest.approx(0.0)
        assert result[0].text == text
        assert result[0].translation is None
        assert result[0].words is None

    def test_parse_plain_text_multiline_returns_multiple_lines(self) -> None:
        """多行纯文本（无时间轴）每行一条，time_s=0.0。"""
        text = "第一行\n第二行\n第三行"
        result = LrcParser.parse(text)
        assert len(result) == 3
        for line in result:
            assert line.time_s == pytest.approx(0.0)
        assert result[0].text == "第一行"
        assert result[2].text == "第三行"


class TestLrcParserStandardFormat:
    """标准 LRC ``[mm:ss.xx]歌词`` 解析。"""

    def test_parse_single_line(self) -> None:
        """单行带时间轴的歌词。"""
        result = LrcParser.parse("[00:01.50]故事的小黄花")
        assert len(result) == 1
        assert result[0].time_s == pytest.approx(1.5)
        assert result[0].text == "故事的小黄花"

    def test_parse_multiple_lines_sorted_by_time(self) -> None:
        """多行歌词按时间升序排序。"""
        text = "[00:05.00]第二行\n[00:01.00]第一行\n[00:10.00]第三行"
        result = LrcParser.parse(text)
        assert len(result) == 3
        assert result[0].time_s == pytest.approx(1.0)
        assert result[0].text == "第一行"
        assert result[1].time_s == pytest.approx(5.0)
        assert result[1].text == "第二行"
        assert result[2].time_s == pytest.approx(10.0)
        assert result[2].text == "第三行"

    def test_parse_mm_ss_format_without_fraction(self) -> None:
        """``[mm:ss]`` 格式（无小数部分）。"""
        result = LrcParser.parse("[01:30]一分半")
        assert len(result) == 1
        assert result[0].time_s == pytest.approx(90.0)

    def test_parse_mm_ss_xxx_three_digit_fraction(self) -> None:
        """``[mm:ss.xxx]`` 三位小数毫秒格式。"""
        result = LrcParser.parse("[00:01.500]半秒后")
        assert len(result) == 1
        assert result[0].time_s == pytest.approx(1.5)

    def test_parse_hour_format_hmm_ss(self) -> None:
        """``[h:mm:ss]`` 小时格式（长歌曲）。"""
        result = LrcParser.parse("[01:00:30]一小时半后")
        assert len(result) == 1
        assert result[0].time_s == pytest.approx(3630.0)

    def test_parse_empty_lyrics_line(self) -> None:
        """空行歌词（纯间奏）：``[00:05.00]`` 后无文本。"""
        result = LrcParser.parse("[00:05.00]")
        assert len(result) == 1
        assert result[0].time_s == pytest.approx(5.0)
        assert result[0].text == ""


class TestLrcParserMultiTimestamp:
    """多时间轴同一行 ``[00:01.00][00:15.00]重复歌词``。"""

    def test_parse_multi_timestamp_expands_to_multiple_lines(self) -> None:
        """同一行多时间轴展开为多条 LyricsLine。"""
        text = "[00:01.00][00:15.00]重复歌词"
        result = LrcParser.parse(text)
        assert len(result) == 2
        assert result[0].time_s == pytest.approx(1.0)
        assert result[0].text == "重复歌词"
        assert result[1].time_s == pytest.approx(15.0)
        assert result[1].text == "重复歌词"

    def test_parse_multi_timestamp_three_times(self) -> None:
        """三个时间轴展开为三行。"""
        text = "[00:01.00][00:10.00][00:20.00]副歌"
        result = LrcParser.parse(text)
        assert len(result) == 3
        times = [line.time_s for line in result]
        assert times == [1.0, 10.0, 20.0]


class TestLrcParserWordByWord:
    """逐字歌词（增强 LRC）``[mm:ss.xx]字[mm:ss.xx]字``。"""

    def test_parse_word_by_word_line(self) -> None:
        """逐字歌词行解析出 words 列表。"""
        text = "[00:01.00]故[00:01.50]事[00:02.00]的[00:02.50]小[00:03.00]黄[00:03.50]花"
        result = LrcParser.parse(text)
        assert len(result) == 1
        line = result[0]
        assert line.time_s == pytest.approx(1.0)
        assert line.text == "故事的小黄花"
        assert line.words is not None
        assert len(line.words) == 6
        assert line.words[0].text == "故"
        assert line.words[0].time_s == pytest.approx(1.0)
        assert line.words[1].text == "事"
        assert line.words[1].time_s == pytest.approx(1.5)
        assert line.words[5].text == "花"
        assert line.words[5].time_s == pytest.approx(3.5)

    def test_word_by_word_with_empty_text_segment_skipped(self) -> None:
        """逐字歌词中空文本段被跳过（不产生空 word）。"""
        text = "[00:01.00]故[00:02.00]事"
        result = LrcParser.parse(text)
        assert len(result) == 1
        assert result[0].words is not None
        assert len(result[0].words) == 2

    def test_mixed_word_by_word_and_regular_lines(self) -> None:
        """逐字行与普通行混合解析。"""
        text = "[00:01.00]普通行\n[00:05.00]逐[00:05.50]字"
        result = LrcParser.parse(text)
        assert len(result) == 2
        assert result[0].text == "普通行"
        assert result[0].words is None
        assert result[1].text == "逐字"
        assert result[1].words is not None
        assert len(result[1].words) == 2


class TestLrcParserTranslation:
    """翻译歌词（双语）：原始行 + 翻译行配对。"""

    def test_parse_translation_pairs_by_time(self) -> None:
        """相同时间轴的原始行与翻译行配对。"""
        text = (
            "[00:01.00]Hello World\n"
            "[00:01.00]你好 世界\n"
            "[00:05.00]Goodbye\n"
            "[00:05.00]再见"
        )
        result = LrcParser.parse(text)
        # 按时间配对后应为 2 个时间点，每个时间点原始行 + 翻译
        # 配对策略：同时间的多行中，第一个为原文，第二个为翻译
        assert len(result) == 2
        assert result[0].time_s == pytest.approx(1.0)
        assert result[0].text == "Hello World"
        assert result[0].translation == "你好 世界"
        assert result[1].time_s == pytest.approx(5.0)
        assert result[1].text == "Goodbye"
        assert result[1].translation == "再见"

    def test_parse_translation_no_pair_keeps_original(self) -> None:
        """没有对应翻译的原始行 translation 为 None。"""
        text = "[00:01.00]只有原文\n[00:05.00]另一行"
        result = LrcParser.parse(text)
        assert len(result) == 2
        assert result[0].translation is None
        assert result[1].translation is None


class TestLrcParserMetadata:
    """元数据标签 ``[ti:][ar:][al:][by:]``。"""

    def test_parse_metadata_extracted(self) -> None:
        """元数据标签被解析到 metadata，不进 LyricsLine 列表。"""
        text = (
            "[ti:晴天]\n"
            "[ar:周杰伦]\n"
            "[al:叶惠美]\n"
            "[by:制作人]\n"
            "[00:01.00]故事的小黄花"
        )
        result = LrcParser.parse(text)
        assert len(result) == 1
        assert result[0].time_s == pytest.approx(1.0)
        assert result[0].text == "故事的小黄花"

    def test_parse_metadata_via_parse_with_metadata(self) -> None:
        """parse_with_metadata 返回 (lines, metadata)。"""
        text = (
            "[ti:晴天]\n"
            "[ar:周杰伦]\n"
            "[al:叶惠美]\n"
            "[by:制作人]\n"
            "[00:01.00]故事的小黄花"
        )
        lines, meta = LrcParser.parse_with_metadata(text)
        assert len(lines) == 1
        assert meta.title == "晴天"
        assert meta.artist == "周杰伦"
        assert meta.album == "叶惠美"
        assert meta.by == "制作人"

    def test_parse_metadata_missing_fields_none(self) -> None:
        """缺失的元数据字段为 None。"""
        text = "[ti:只有标题]\n[00:01.00]歌词"
        lines, meta = LrcParser.parse_with_metadata(text)
        assert meta.title == "只有标题"
        assert meta.artist is None
        assert meta.album is None
        assert meta.by is None

    def test_parse_metadata_empty_when_no_tags(self) -> None:
        """无元数据标签时返回全 None 的 metadata。"""
        text = "[00:01.00]歌词"
        lines, meta = LrcParser.parse_with_metadata(text)
        assert meta.title is None
        assert meta.artist is None
        assert meta.album is None
        assert meta.by is None


class TestLyricsLineDataclass:
    """LyricsLine / Word 数据结构。"""

    def test_lyrics_line_to_dict(self) -> None:
        """LyricsLine 可序列化为 dict。"""
        line = LyricsLine(time_s=1.5, text="歌词", translation=None, words=None)
        d = line.to_dict()
        assert d["time_s"] == pytest.approx(1.5)
        assert d["text"] == "歌词"
        assert d["translation"] is None
        assert d["words"] is None

    def test_lyrics_line_to_dict_with_words(self) -> None:
        """带 words 的 LyricsLine 序列化。"""
        words = [Word(time_s=1.0, text="歌"), Word(time_s=1.5, text="词")]
        line = LyricsLine(time_s=1.0, text="歌词", translation="lyrics", words=words)
        d = line.to_dict()
        assert d["translation"] == "lyrics"
        assert len(d["words"]) == 2
        assert d["words"][0]["text"] == "歌"
        assert d["words"][1]["text"] == "词"

    def test_word_to_dict(self) -> None:
        """Word 可序列化为 dict。"""
        word = Word(time_s=2.5, text="字")
        d = word.to_dict()
        assert d["time_s"] == pytest.approx(2.5)
        assert d["text"] == "字"
