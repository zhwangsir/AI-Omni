"""LRC 格式解析器（M18.2）。

解析标准 LRC / 增强 LRC（逐字）/ 双语翻译歌词，返回结构化 ``LyricsLine`` 列表。

支持特性：
- 标准 LRC：``[mm:ss.xx]歌词文本``
- 多时间轴同一行：``[00:01.00][00:15.00]重复歌词`` → 展开为多条
- 逐字歌词（增强 LRC）：``[mm:ss.xx]字[mm:ss.xx]字`` → ``words`` 列表
- 翻译歌词（双语）：同时间轴的原始行 + 翻译行配对
- 元数据标签：``[ti:标题][ar:艺人][al:专辑][by:制作]``
- 时间格式：``[mm:ss]`` / ``[mm:ss.xx]`` / ``[mm:ss.xxx]`` / ``[h:mm:ss]``
- 纯文本（无时间轴）容错：每行返回 ``time_s=0.0``
- 空字符串 / None 返回空列表

纯文本解析，无外部依赖，无网络/硬件依赖。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class Word:
    """逐字歌词的单个字片段。

    :ivar time_s: 该字起始时间（秒）
    :ivar text: 字文本
    """

    time_s: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的 dict。"""
        return {"time_s": self.time_s, "text": self.text}


@dataclass
class LyricsLine:
    """单行歌词。

    :ivar time_s: 行起始时间（秒）
    :ivar text: 行文本（逐字行时为各 word 文本拼接）
    :ivar translation: 翻译文本；无翻译为 None
    :ivar words: 逐字歌词的字片段列表；非逐字行为 None
    """

    time_s: float
    text: str
    translation: str | None = None
    words: list[Word] | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的 dict。"""
        return {
            "time_s": self.time_s,
            "text": self.text,
            "translation": self.translation,
            "words": [w.to_dict() for w in self.words] if self.words is not None else None,
        }


@dataclass
class LrcMetadata:
    """LRC 元数据。

    :ivar title: 标题（``[ti:]``）
    :ivar artist: 艺人（``[ar:]``）
    :ivar album: 专辑（``[al:]``）
    :ivar by: 制作人（``[by:]``）
    """

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    by: str | None = None


# ---------------------------------------------------------------------------
# 正则
# ---------------------------------------------------------------------------
# 时间戳：[mm:ss] / [mm:ss.xx] / [mm:ss.xxx] / [h:mm:ss] / [h:mm:ss.xx]
_TIMESTAMP_RE = re.compile(r"\[(\d+:\d+(?::\d+)?(?:\.\d+)?)\]")
# 元数据标签：[ti:xxx] / [ar:xxx] / [al:xxx] / [by:xxx]
_METADATA_RE = re.compile(r"\[(ti|ar|al|by):([^\]]*)\]")


# ---------------------------------------------------------------------------
# 解析器
# ---------------------------------------------------------------------------
class LrcParser:
    """LRC 格式解析器（无状态，全部为类方法/静态方法）。"""

    @staticmethod
    def _parse_timestamp(ts: str) -> float:
        """解析时间戳字符串为秒数。

        支持格式：``mm:ss`` / ``mm:ss.xx`` / ``mm:ss.xxx`` / ``h:mm:ss`` / ``h:mm:ss.xx``

        :param ts: 时间戳字符串（如 ``01:30.50``）
        :return: 秒数（浮点）
        """
        parts = ts.split(":")
        try:
            if len(parts) == 2:
                # mm:ss[.xx]
                mm = int(parts[0])
                ss = float(parts[1])
                return mm * 60 + ss
            elif len(parts) == 3:
                # h:mm:ss[.xx]
                h = int(parts[0])
                mm = int(parts[1])
                ss = float(parts[2])
                return h * 3600 + mm * 60 + ss
        except (ValueError, IndexError):
            return 0.0
        return 0.0

    @staticmethod
    def _extract_leading_timestamps(line: str) -> tuple[list[float], str]:
        """提取行首连续的 ``[time]`` 时间戳，返回时间列表与剩余文本。

        连续的 ``[time]``（中间无其他字符）视为多时间轴；
        遇到非 ``[time]`` 字符即停止。

        :param line: 单行文本
        :return: (时间列表, 剩余文本)
        """
        times: list[float] = []
        pos = 0
        while pos < len(line):
            m = _TIMESTAMP_RE.match(line, pos)
            if m is None:
                break
            times.append(LrcParser._parse_timestamp(m.group(1)))
            pos = m.end()
        return times, line[pos:]

    @staticmethod
    def _parse_word_by_word(remaining: str, line_time: float) -> tuple[str, list[Word]]:
        """解析逐字歌词剩余文本为 (完整文本, words 列表)。

        :param remaining: 行首时间戳之后的文本，形如 ``故[00:01.50]事[00:02.00]的``
        :param line_time: 行起始时间（首个时间戳）
        :return: (完整文本, words 列表)
        """
        words: list[Word] = []
        full_text_parts: list[str] = []
        # remaining 形如 "故[00:01.50]事[00:02.00]的"
        # 第一个 word 的 time = line_time，text = leading text before next [time]
        current_time = line_time
        # 按 [time] 切分
        pos = 0
        segments: list[tuple[float, str]] = []
        # 先取 remaining 开头到第一个 [time] 的文本
        first_match = _TIMESTAMP_RE.search(remaining, 0)
        if first_match is None:
            # 无后续时间戳，整段是一个 word
            text = remaining.strip()
            if text:
                segments.append((line_time, text))
        else:
            # 第一段文本（line_time 对应）
            first_text = remaining[: first_match.start()]
            if first_text.strip():
                segments.append((line_time, first_text))
            # 后续 [time]text 段
            last_pos = first_match.start()
            for m in _TIMESTAMP_RE.finditer(remaining, last_pos):
                t = LrcParser._parse_timestamp(m.group(1))
                # 取该 [time] 到下一个 [time] 之间的文本
                start = m.end()
                next_m = _TIMESTAMP_RE.search(remaining, start)
                end = next_m.start() if next_m is not None else len(remaining)
                seg_text = remaining[start:end]
                if seg_text.strip():
                    segments.append((t, seg_text))

        for t, text in segments:
            clean = text.strip()
            if clean:
                words.append(Word(time_s=t, text=clean))
                full_text_parts.append(clean)

        return "".join(full_text_parts), words

    @staticmethod
    def _pair_translations(
        lines: list[LyricsLine], plain_text_indices: set[int]
    ) -> list[LyricsLine]:
        """按时间轴配对翻译行。

        同一 ``time_s`` 的多行（且非逐字行、非纯文本行）中，第一行作为原文，
        第二行作为翻译。配对后只保留第一行（设置 ``translation``），其余同时间行被丢弃。
        逐字行（``words is not None``）与纯文本行（无时间轴）不参与翻译配对。

        :param lines: 已解析的行列表
        :param plain_text_indices: 纯文本行（无时间轴）的索引集合，跳过配对
        :return: 配对后的行列表（保持时间升序）
        """
        # 按时间分组索引
        time_to_indices: dict[float, list[int]] = {}
        for idx, line in enumerate(lines):
            # 逐字行 / 纯文本行不参与翻译配对
            if line.words is not None or idx in plain_text_indices:
                continue
            time_to_indices.setdefault(line.time_s, []).append(idx)

        # 标记需要丢弃的索引 + 设置 translation
        drop_indices: set[int] = set()
        for time_s, indices in time_to_indices.items():
            if len(indices) < 2:
                continue
            # 第一行设 translation = 第二行 text；其余丢弃
            first_idx = indices[0]
            second_idx = indices[1]
            lines[first_idx].translation = lines[second_idx].text
            # 第二行及之后全部丢弃
            for idx in indices[1:]:
                drop_indices.add(idx)

        return [line for idx, line in enumerate(lines) if idx not in drop_indices]

    @staticmethod
    def parse(text: str | None) -> list[LyricsLine]:
        """解析 LRC 文本为 ``LyricsLine`` 列表（不含元数据）。

        :param text: LRC 文本
        :return: 按时间升序排序的行列表；空输入返回空列表
        """
        lines, _meta = LrcParser.parse_with_metadata(text)
        return lines

    @staticmethod
    def parse_with_metadata(text: str | None) -> tuple[list[LyricsLine], LrcMetadata]:
        """解析 LRC 文本为 (行列表, 元数据)。

        :param text: LRC 文本
        :return: (按时间升序排序的行列表, 元数据)
        """
        if text is None or not text.strip():
            return [], LrcMetadata()

        meta = LrcMetadata()
        raw_lines: list[str] = text.splitlines()

        # 1. 提取元数据 + 收集歌词行
        lyric_lines: list[str] = []
        for raw in raw_lines:
            stripped = raw.strip()
            if not stripped:
                continue
            # 元数据标签
            m = _METADATA_RE.match(stripped)
            if m is not None:
                tag, value = m.group(1), m.group(2).strip()
                if tag == "ti":
                    meta.title = value
                elif tag == "ar":
                    meta.artist = value
                elif tag == "al":
                    meta.album = value
                elif tag == "by":
                    meta.by = value
                continue
            lyric_lines.append(stripped)

        # 2. 解析每行（保持原始顺序，记录纯文本行索引）
        result: list[LyricsLine] = []
        plain_text_indices: set[int] = set()
        for line in lyric_lines:
            leading_times, remaining = LrcParser._extract_leading_timestamps(line)

            if not leading_times:
                # 无时间轴：纯文本行，time_s=0.0（不参与翻译配对）
                plain_text_indices.add(len(result))
                result.append(LyricsLine(time_s=0.0, text=line, translation=None, words=None))
                continue

            # 检查 remaining 是否含 [time]（逐字歌词）
            has_interspersed = _TIMESTAMP_RE.search(remaining) is not None

            if has_interspersed:
                # 逐字歌词：用首个时间戳作为行时间
                line_time = leading_times[0]
                full_text, words = LrcParser._parse_word_by_word(remaining, line_time)
                result.append(
                    LyricsLine(
                        time_s=line_time,
                        text=full_text,
                        translation=None,
                        words=words if words else None,
                    )
                )
            else:
                # 多时间轴展开 / 单行
                for t in leading_times:
                    result.append(
                        LyricsLine(
                            time_s=t,
                            text=remaining,
                            translation=None,
                            words=None,
                        )
                    )

        # 3. 配对翻译（必须在排序前完成，plain_text_indices 基于原始索引）
        result = LrcParser._pair_translations(result, plain_text_indices)

        # 4. 按时间升序排序（稳定排序，保持同时间行的原始顺序）
        result.sort(key=lambda x: x.time_s)

        return result, meta
