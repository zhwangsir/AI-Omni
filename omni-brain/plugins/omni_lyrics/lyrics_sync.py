"""歌词同步逻辑（M18.4）。

提供 ``LyricsSync`` 类，根据当前播放时间定位应显示的歌词行与逐字高亮：

- :meth:`find_current_line`：返回当前应显示的行索引（0-based）
- :meth:`find_current_word`：逐字歌词当前字索引（非逐字行返回 None）
- :meth:`compute_offset`：行内偏移（用于渐变效果）
- :meth:`set_offset` / :meth:`get_offset`：全局用户偏移（正数提前，负数延后）

边界处理：
- 空列表 → ``find_current_line`` 返回 -1
- ``time=0`` 或负时间 → 返回第一行（索引 0）
- 时间超过最后一行 → 返回最后一行
- 未排序输入也能正确工作（按时间值查找，返回原始索引）

纯逻辑，无外部依赖。
"""

from __future__ import annotations

from typing import Any

from omni_lyrics.lrc_parser import LyricsLine


class LyricsSync:
    """歌词同步器：根据播放时间定位当前行/字。

    :ivar _offset_s: 用户全局偏移（秒）；正数提前，负数延后
    """

    def __init__(self, offset_s: float = 0.0) -> None:
        """构造同步器，初始偏移 0.0。

        :param offset_s: 初始用户偏移（秒）
        """
        self._offset_s: float = float(offset_s)

    def set_offset(self, offset_s: float) -> None:
        """设置用户全局偏移量。

        正数提前（歌词提前显示），负数延后。

        :param offset_s: 偏移秒数
        """
        self._offset_s = float(offset_s)

    def get_offset(self) -> float:
        """返回当前用户偏移量。"""
        return self._offset_s

    def _effective_time(self, current_time_s: float) -> float:
        """应用用户偏移后的有效时间。"""
        return float(current_time_s) + self._offset_s

    def find_current_line(
        self, parsed: list[LyricsLine], current_time_s: float
    ) -> int:
        """返回当前应显示的行索引。

        查找最大的 ``time_s <= current_time_s + offset`` 的行索引；
        若 current_time 小于所有行时间，返回 0（第一行）；
        空列表返回 -1。

        :param parsed: 解析后的歌词行列表（无需预排序）
        :param current_time_s: 当前播放时间（秒）
        :return: 行索引（0-based）；空列表返回 -1
        """
        if not parsed:
            return -1
        eff_time = self._effective_time(current_time_s)
        # 查找最大的 time_s <= eff_time 的行；相同时间取第一个（用 > 严格大于保持首个）
        best_idx = -1
        best_time = float("-inf")
        for idx, line in enumerate(parsed):
            if line.time_s <= eff_time and line.time_s > best_time:
                best_time = line.time_s
                best_idx = idx
        # 若没有已开始的行（所有 time_s > eff_time），返回 0（第一行）
        if best_idx == -1:
            return 0
        return best_idx

    def find_current_word(
        self, line: LyricsLine, current_time_s: float
    ) -> int | None:
        """逐字歌词当前字索引。

        :param line: 歌词行（需含 ``words`` 列表）
        :param current_time_s: 当前播放时间（秒）
        :return: 字索引（0-based）；非逐字行或空 words 返回 None
        """
        if line.words is None or len(line.words) == 0:
            return None
        eff_time = self._effective_time(current_time_s)
        best_idx = -1
        best_time = float("-inf")
        for idx, word in enumerate(line.words):
            if word.time_s <= eff_time and word.time_s > best_time:
                best_time = word.time_s
                best_idx = idx
        if best_idx == -1:
            return 0
        return best_idx

    def compute_offset(self, line_time: float, current_time: float) -> float:
        """计算行内偏移（用于渐变效果）。

        返回 ``current_time - line_time``：正值表示已过秒数，负值表示未到。

        :param line_time: 行起始时间（秒）
        :param current_time: 当前播放时间（秒）
        :return: 偏移秒数（current - line）
        """
        return float(current_time) - float(line_time)
