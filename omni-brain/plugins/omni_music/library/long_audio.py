"""omni_music 长音频分析（M19.6）。

识别播客 / DJ mix / 有声书等长音频内容，前端可据此切换视觉模式
（M21 节奏粒子 vs 静态背景）。

判定规则（启发式）：
- ``is_long_audio``：``duration_s >= 15 分钟``（900 秒，可配置阈值）
- ``classify_long_audio``：基于时长 + 标题关键词
  - ``podcast``   ：标题含 ``episode`` / ``podcast`` / ``part``
  - ``dj_mix``    ：标题含 ``mix`` / ``dj set`` / ``live set``
  - ``audiobook`` ：标题含 ``chapter`` / ``audiobook`` / ``book``
  - ``unknown``   ：无匹配或短音频

纯逻辑无依赖，便于单测。

合规说明（D19.1）：仅分析用户自有本地文件元数据，不涉及任何破解。仅个人学习用途。
"""

from __future__ import annotations

from typing import Any

__all__ = ["LongAudioAnalyzer", "DEFAULT_LONG_AUDIO_THRESHOLD_S"]

DEFAULT_LONG_AUDIO_THRESHOLD_S = 15 * 60  # 15 分钟


class LongAudioAnalyzer:
    """长音频分析器：按时长 + 标题关键词启发式分类。

    :param threshold_s: 长音频阈值（秒），默认 900（15 分钟）
    """

    # 关键词 → 分类（按优先级排序：podcast > dj_mix > audiobook）
    _KEYWORD_MAP: list[tuple[tuple[str, ...], str]] = [
        (("episode", "podcast", "part"), "podcast"),
        (("mix", "dj set", "live set", "dj set"), "dj_mix"),
        (("chapter", "audiobook", "book"), "audiobook"),
    ]

    def __init__(self, threshold_s: int = DEFAULT_LONG_AUDIO_THRESHOLD_S) -> None:
        self.threshold_s: int = int(threshold_s)

    def is_long_audio(self, song_data: dict[str, Any]) -> bool:
        """判断是否为长音频（``duration_s >= threshold_s``）。

        :param song_data: 歌曲 dict，含 ``duration_s``（缺失视为 0）
        :return: 时长达到阈值返回 True
        """
        try:
            duration = int(song_data.get("duration_s") or 0)
        except (TypeError, ValueError):
            duration = 0
        return duration >= self.threshold_s

    def classify_long_audio(self, song_data: dict[str, Any]) -> str:
        """对长音频分类；短音频返回 ``unknown``。

        :param song_data: 歌曲 dict，含 ``title`` / ``duration_s``
        :return: ``"podcast"`` / ``"dj_mix"`` / ``"audiobook"`` / ``"unknown"``
        """
        if not self.is_long_audio(song_data):
            return "unknown"
        title = str(song_data.get("title") or "").lower()
        if not title:
            return "unknown"
        for keywords, category in self._KEYWORD_MAP:
            for kw in keywords:
                if kw in title:
                    return category
        return "unknown"

    def get_summary(self, song_data: dict[str, Any]) -> dict[str, Any]:
        """返回长音频分析摘要。

        :param song_data: 歌曲 dict
        :return: ``{"is_long_audio": bool, "category": str}``
        """
        return {
            "is_long_audio": self.is_long_audio(song_data),
            "category": self.classify_long_audio(song_data),
        }
