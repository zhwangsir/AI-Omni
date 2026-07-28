"""歌词来源优先级链（M18.3）。

按优先级依次尝试获取歌词：
1. 本地 .lrc 文件（``Song.lyrics`` 字段，由 ``LocalMusicSource._read_lyrics_file`` 填充）
2. 音频文件内嵌歌词（mutagen 读取 USLT/SYNCEDLYRICS，惰性导入 + 依赖注入）
3. 在线 API（复用 omni_music 各源的 ``get_lyrics(song_id)``）
4. 纯文本兜底（无时间轴，由 LrcParser 容错为 time_s=0.0）

每个来源失败（异常/None）自动降级到下一级；全部失败返回
``LyricsResult(lyrics=None, source="none", parsed=[])``。

设计要点：
- 接受 ``MusicSource`` 列表（可注入 fake）
- ``embedded_reader`` 可注入（测试零依赖，mutagen 缺失时降级）
- 跨插件复用：不直接 import omni_music 模块内部，仅依赖 ``MusicSource`` 抽象接口
  （鸭子类型 ``get_lyrics(song_id) -> str|None``）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from omni_lyrics.lrc_parser import LrcParser, LyricsLine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 协议（鸭子类型，便于 fake 注入）
# ---------------------------------------------------------------------------
class _MusicSourceLike(Protocol):
    """音乐源最小协议：仅需 ``get_lyrics``。"""

    def get_lyrics(self, song_id: str) -> str | None: ...


class _EmbeddedReaderLike(Protocol):
    """嵌入歌词读取器协议。"""

    def read(self, song: Any) -> str | None: ...


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class LyricsResult:
    """歌词获取结果。

    :ivar lyrics: 原始歌词文本（LRC 或纯文本）；全部失败为 None
    :ivar source: 命中的来源：``local_file`` / ``embedded`` / ``online`` / ``none``
    :ivar parsed: 解析后的 ``LyricsLine`` 列表；无歌词为空列表
    """

    lyrics: str | None
    source: str
    parsed: list[LyricsLine] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的 dict。"""
        return {
            "lyrics": self.lyrics,
            "source": self.source,
            "parsed": [line.to_dict() for line in self.parsed],
        }


# ---------------------------------------------------------------------------
# 默认嵌入歌词读取器（mutagen 惰性导入）
# ---------------------------------------------------------------------------
class MutagenEmbeddedReader:
    """音频文件内嵌歌词读取器（mutagen 惰性导入）。

    读取音频文件的 ``USLT``（非同步歌词）/ ``SYNCEDLYRICS``（同步歌词）标签。
    ``mutagen`` 缺失或读取失败时返回 None（CLAUDE.md §三 惰性导入且可缺省）。

    需 ``Song.url`` 为 ``file://`` 协议本地路径。
    """

    def read(self, song: Any) -> str | None:
        """读取音频文件内嵌歌词。

        :param song: :class:`Song` 实例（需有 ``url`` 属性为 ``file://path``）
        :return: 歌词文本；无内嵌歌词或读取失败返回 None
        """
        url = getattr(song, "url", None)
        if not isinstance(url, str) or not url.startswith("file://"):
            return None
        path = url[len("file://") :]
        # 惰性导入 mutagen（CLAUDE.md §三：模块顶层禁止 import mutagen）
        try:
            from mutagen import File as MutagenFile
        except ImportError:
            return None

        try:
            audio = MutagenFile(path)
        except Exception:  # noqa: BLE001 - 文件损坏/格式不支持
            return None
        if audio is None:
            return None

        tags = getattr(audio, "tags", None) or {}

        # 优先 SYNCEDLYRICS（同步歌词，LRC 格式），其次 USLT（非同步）
        # Vorbis/FLAC: SYNCEDLYRICS, lyrics；ID3: USLT, SYLT；MP4: ©lyr
        for key in ("SYNCEDLYRICS", "lyrics", "USLT", "USLT::eng", "©lyr"):
            if key in tags:
                val = tags[key]
                if isinstance(val, list) and val:
                    text = str(val[0])
                elif val:
                    text = str(val)
                else:
                    continue
                if text.strip():
                    return text
        return None


# ---------------------------------------------------------------------------
# 优先级链
# ---------------------------------------------------------------------------
class LyricsChain:
    """歌词来源优先级链。

    按优先级依次尝试：本地 .lrc 文件 → 嵌入歌词 → 在线 API → 纯文本兜底。

    :param sources: 在线 ``MusicSource`` 列表（按顺序尝试）；空列表跳过在线
    :param embedded_reader: 嵌入歌词读取器；None 跳过嵌入来源
    """

    def __init__(
        self,
        sources: list[_MusicSourceLike] | None = None,
        embedded_reader: _EmbeddedReaderLike | None = None,
    ) -> None:
        """构造优先级链。

        :param sources: 在线音乐源列表（按顺序尝试）
        :param embedded_reader: 嵌入歌词读取器；None 跳过嵌入来源
        """
        self._sources: list[_MusicSourceLike] = list(sources or [])
        self._embedded_reader: _EmbeddedReaderLike | None = embedded_reader

    @staticmethod
    def _parse(lyrics: str | None) -> list[LyricsLine]:
        """解析歌词文本为 LyricsLine 列表；None 返回空列表。"""
        if lyrics is None:
            return []
        return LrcParser.parse(lyrics)

    def _try_local_file(self, song: Any) -> str | None:
        """尝试从 ``Song.lyrics`` 字段读取（本地 .lrc 文件已填充）。"""
        lyrics = getattr(song, "lyrics", None)
        if isinstance(lyrics, str) and lyrics.strip():
            return lyrics
        return None

    def _try_embedded(self, song: Any) -> str | None:
        """尝试从音频文件内嵌标签读取。"""
        if self._embedded_reader is None:
            return None
        try:
            return self._embedded_reader.read(song)
        except Exception as exc:  # noqa: BLE001 - 嵌入读取失败不拖垮链
            logger.debug("嵌入歌词读取失败: %s", exc)
            return None

    def _try_online(self, song: Any) -> str | None:
        """按顺序尝试各在线源的 ``get_lyrics``。"""
        song_id = getattr(song, "id", None)
        if not isinstance(song_id, str):
            return None
        for source in self._sources:
            try:
                lyrics = source.get_lyrics(song_id)
            except Exception as exc:  # noqa: BLE001 - 单源故障降级到下一源
                logger.debug("在线源 %s 获取歌词失败: %s", type(source).__name__, exc)
                continue
            if isinstance(lyrics, str) and lyrics.strip():
                return lyrics
        return None

    def fetch(self, song: Any) -> LyricsResult:
        """按优先级链获取歌词并解析。

        :param song: :class:`Song` 实例（需有 ``lyrics`` / ``id`` / ``url`` 属性）
        :return: :class:`LyricsResult`，含原始文本、来源标识与解析后的行列表
        """
        # 1. 本地 .lrc 文件（Song.lyrics 字段）
        lyrics = self._try_local_file(song)
        if lyrics is not None:
            return LyricsResult(
                lyrics=lyrics, source="local_file", parsed=self._parse(lyrics)
            )

        # 2. 音频文件内嵌歌词
        lyrics = self._try_embedded(song)
        if lyrics is not None:
            return LyricsResult(
                lyrics=lyrics, source="embedded", parsed=self._parse(lyrics)
            )

        # 3. 在线 API
        lyrics = self._try_online(song)
        if lyrics is not None:
            return LyricsResult(
                lyrics=lyrics, source="online", parsed=self._parse(lyrics)
            )

        # 4. 全部失败
        return LyricsResult(lyrics=None, source="none", parsed=[])
