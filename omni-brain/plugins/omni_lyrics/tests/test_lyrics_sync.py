"""歌词同步逻辑测试（M18.4 TDD red → green）。

覆盖 ``LyricsSync``：
- ``find_current_line(parsed, current_time_s)``：返回当前应显示的行索引
- ``find_current_word(line, current_time_s)``：逐字歌词当前字索引
- ``compute_offset(line_time, current_time)``：行内偏移（渐变效果）
- ``set_offset(offset_s)``：全局偏移（正数提前，负数延后）
- 边界：time=0 → 第一行；time 超过最后一行 → 最后一行；空列表 → -1
- 用户偏移量应用：current_time + offset_s 后再查找
"""

from __future__ import annotations

import pytest

from omni_lyrics.lrc_parser import LyricsLine, Word
from omni_lyrics.lyrics_sync import LyricsSync


def _make_lines() -> list[LyricsLine]:
    """构造 5 行测试歌词（1s / 5s / 10s / 15s / 20s）。"""
    return [
        LyricsLine(time_s=1.0, text="第一行"),
        LyricsLine(time_s=5.0, text="第二行"),
        LyricsLine(time_s=10.0, text="第三行"),
        LyricsLine(time_s=15.0, text="第四行"),
        LyricsLine(time_s=20.0, text="第五行"),
    ]


def _make_word_line() -> LyricsLine:
    """构造逐字歌词行（1.0/1.5/2.0/2.5 四个字）。"""
    words = [
        Word(time_s=1.0, text="故"),
        Word(time_s=1.5, text="事"),
        Word(time_s=2.0, text="的"),
        Word(time_s=2.5, text="花"),
    ]
    return LyricsLine(time_s=1.0, text="故事的花", words=words)


class TestFindCurrentLine:
    """``find_current_line`` 边界与常规。"""

    def test_empty_list_returns_negative_one(self) -> None:
        """空列表返回 -1。"""
        sync = LyricsSync()
        assert sync.find_current_line([], 5.0) == -1

    def test_time_before_first_line_returns_first(self) -> None:
        """time=0（第一行之前）返回第一行索引 0。"""
        sync = LyricsSync()
        lines = _make_lines()
        assert sync.find_current_line(lines, 0.0) == 0

    def test_time_negative_returns_first(self) -> None:
        """负时间返回第一行。"""
        sync = LyricsSync()
        lines = _make_lines()
        assert sync.find_current_line(lines, -5.0) == 0

    def test_time_at_exact_line_start(self) -> None:
        """时间正好等于某行起始时间，返回该行。"""
        sync = LyricsSync()
        lines = _make_lines()
        assert sync.find_current_line(lines, 5.0) == 1
        assert sync.find_current_line(lines, 10.0) == 2

    def test_time_between_lines_returns_previous(self) -> None:
        """时间在两行之间，返回前一行（已显示的行）。"""
        sync = LyricsSync()
        lines = _make_lines()
        assert sync.find_current_line(lines, 7.5) == 1  # 5s 行仍显示
        assert sync.find_current_line(lines, 12.0) == 2  # 10s 行仍显示

    def test_time_after_last_line_returns_last(self) -> None:
        """时间超过最后一行，返回最后一行。"""
        sync = LyricsSync()
        lines = _make_lines()
        assert sync.find_current_line(lines, 100.0) == 4
        assert sync.find_current_line(lines, 999.0) == 4

    def test_single_line_list(self) -> None:
        """单行列表：任何时间都返回 0。"""
        sync = LyricsSync()
        lines = [LyricsLine(time_s=1.0, text="唯一")]
        assert sync.find_current_line(lines, 0.0) == 0
        assert sync.find_current_line(lines, 100.0) == 0


class TestFindCurrentWord:
    """``find_current_word`` 逐字高亮。"""

    def test_line_without_words_returns_none(self) -> None:
        """非逐字行（words=None）返回 None。"""
        sync = LyricsSync()
        line = LyricsLine(time_s=1.0, text="普通行")
        assert sync.find_current_word(line, 1.5) is None

    def test_line_with_empty_words_returns_none(self) -> None:
        """空 words 列表返回 None。"""
        sync = LyricsSync()
        line = LyricsLine(time_s=1.0, text="", words=[])
        assert sync.find_current_word(line, 1.5) is None

    def test_time_at_word_start(self) -> None:
        """时间正好在某字起始，返回该字索引。"""
        sync = LyricsSync()
        line = _make_word_line()
        assert sync.find_current_word(line, 1.0) == 0  # "故"
        assert sync.find_current_word(line, 1.5) == 1  # "事"
        assert sync.find_current_word(line, 2.5) == 3  # "花"

    def test_time_between_words_returns_previous(self) -> None:
        """时间在两字之间，返回前一字索引。"""
        sync = LyricsSync()
        line = _make_word_line()
        assert sync.find_current_word(line, 1.2) == 0  # 仍 "故"
        assert sync.find_current_word(line, 1.8) == 1  # 仍 "事"

    def test_time_before_first_word_returns_first(self) -> None:
        """时间在第一个字之前，返回 0。"""
        sync = LyricsSync()
        line = _make_word_line()
        assert sync.find_current_word(line, 0.5) == 0

    def test_time_after_last_word_returns_last(self) -> None:
        """时间在最后一字之后，返回最后索引。"""
        sync = LyricsSync()
        line = _make_word_line()
        assert sync.find_current_word(line, 100.0) == 3


class TestComputeOffset:
    """``compute_offset`` 行内偏移（渐变效果）。"""

    def test_offset_at_line_start_is_zero(self) -> None:
        """时间正好在行起始，偏移 0。"""
        sync = LyricsSync()
        assert sync.compute_offset(5.0, 5.0) == pytest.approx(0.0)

    def test_offset_positive_after_line_start(self) -> None:
        """时间在行起始之后，返回正偏移（已过秒数）。"""
        sync = LyricsSync()
        assert sync.compute_offset(5.0, 8.0) == pytest.approx(3.0)

    def test_offset_negative_before_line_start(self) -> None:
        """时间在行起始之前，返回负偏移（未到的秒数）。"""
        sync = LyricsSync()
        assert sync.compute_offset(5.0, 3.0) == pytest.approx(-2.0)


class TestUserOffset:
    """``set_offset`` 用户偏移量（正数提前，负数延后）。"""

    def test_positive_offset_advances_time(self) -> None:
        """正偏移（提前）：current=3.0 + offset=2.0 → 实际按 5.0 查找。"""
        sync = LyricsSync()
        sync.set_offset(2.0)
        lines = _make_lines()
        # 无偏移时 3.0 → 第 0 行（1s 行）；+2s 偏移 → 按 5.0 查 → 第 1 行
        assert sync.find_current_line(lines, 3.0) == 1

    def test_negative_offset_delays_time(self) -> None:
        """负偏移（延后）：current=5.0 + offset=-2.0 → 实际按 3.0 查找。"""
        sync = LyricsSync()
        sync.set_offset(-2.0)
        lines = _make_lines()
        # 无偏移时 5.0 → 第 1 行；-2s 偏移 → 按 3.0 查 → 第 0 行
        assert sync.find_current_line(lines, 5.0) == 0

    def test_zero_offset_no_effect(self) -> None:
        """0 偏移无影响。"""
        sync = LyricsSync()
        sync.set_offset(0.0)
        lines = _make_lines()
        assert sync.find_current_line(lines, 5.0) == 1

    def test_offset_affects_find_current_word(self) -> None:
        """用户偏移同样作用于逐字查找。"""
        sync = LyricsSync()
        sync.set_offset(0.5)
        line = _make_word_line()
        # 无偏移时 1.2 → 第 0 字；+0.5s 偏移 → 按 1.7 查 → 第 1 字
        assert sync.find_current_word(line, 1.2) == 1

    def test_get_offset_returns_set_value(self) -> None:
        """``get_offset`` 返回已设置的偏移量。"""
        sync = LyricsSync()
        assert sync.get_offset() == pytest.approx(0.0)
        sync.set_offset(1.5)
        assert sync.get_offset() == pytest.approx(1.5)
        sync.set_offset(-3.0)
        assert sync.get_offset() == pytest.approx(-3.0)


class TestFindCurrentLineEdgeCases:
    """``find_current_line`` 复杂边界。"""

    def test_unsorted_lines_handles_gracefully(self) -> None:
        """未排序的行列表：find_current_line 仍按时间正确返回。

        实现按时间查找最大 time_s <= current 的行，返回原始索引，不依赖输入顺序。
        """
        sync = LyricsSync()
        # 故意乱序
        lines = [
            LyricsLine(time_s=10.0, text="第三"),
            LyricsLine(time_s=1.0, text="第一"),
            LyricsLine(time_s=5.0, text="第二"),
        ]
        assert sync.find_current_line(lines, 3.0) == 1  # time=1.0（idx1）
        assert sync.find_current_line(lines, 7.0) == 2  # time=5.0（idx2）

    def test_duplicate_times_returns_first_match(self) -> None:
        """相同时间的多行：返回第一个匹配（时间相等时取靠前的）。"""
        sync = LyricsSync()
        lines = [
            LyricsLine(time_s=5.0, text="原文"),
            LyricsLine(time_s=5.0, text="翻译"),
        ]
        # 时间正好 5.0 → 返回第 0 行（原文）
        assert sync.find_current_line(lines, 5.0) == 0
