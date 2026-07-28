"""omni_music 数据模型：Song / Playlist / Artist / MusicSourceEnum（M17.1）。

仅描述音乐元数据，不涉及播放控制（播放由前端 WebAudio 负责，见 D17.1）。
所有模型为可 JSON 序列化的 dataclass，便于工具 handler 返回结构化数据。

合规说明（D17.4）：本模型仅承载免费/试听曲目元数据，不携带任何破解付费内容的信息。
仅个人学习用途。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MusicSourceEnum(Enum):
    """音乐源枚举。

    - NETEASE：网易云音乐（M17.5 实现）
    - QQMUSIC：QQ音乐（M17.7 实现）
    - LOCAL：本地音乐文件（M17.6 实现）
    - SPOTIFY：Spotify（P3 后续，D17.3）
    """

    NETEASE = "netease"
    QQMUSIC = "qqmusic"
    LOCAL = "local"
    SPOTIFY = "spotify"


@dataclass
class Song:
    """单曲元数据。

    :ivar id: 歌曲 ID（在所属源内唯一）
    :ivar name: 歌曲名
    :ivar artists: 艺术家名列表（一首歌可能多艺人）
    :ivar album: 专辑名，可空
    :ivar duration_s: 时长（秒），默认 0
    :ivar url: 可播放 URL，可空（VIP 曲目可能无 URL）
    :ivar lyrics: 歌词文本（LRC 或纯文本），可空
    :ivar cover_url: 封面图 URL，可空
    :ivar source: 所属音乐源（MusicSourceEnum）
    """

    id: str
    name: str
    source: MusicSourceEnum
    artists: list[str] = field(default_factory=list)
    album: str | None = None
    duration_s: int = 0
    url: str | None = None
    lyrics: str | None = None
    cover_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的 dict（source 转字符串值）。

        :return: dict，``source`` 字段为字符串（如 "netease"）
        """
        return {
            "id": self.id,
            "name": self.name,
            "artists": list(self.artists),
            "album": self.album,
            "duration_s": self.duration_s,
            "url": self.url,
            "lyrics": self.lyrics,
            "cover_url": self.cover_url,
            "source": self.source.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Song:
        """从 dict 构造 Song 实例（``source`` 接受字符串或枚举）。

        :param data: 由 :meth:`to_dict` 或外部 JSON 反序列化得到的 dict
        :return: :class:`Song` 实例
        :raises ValueError: ``source`` 字段为未知字符串
        """
        source = data["source"]
        if isinstance(source, str):
            source = MusicSourceEnum(source)
        return cls(
            id=data["id"],
            name=data["name"],
            source=source,
            artists=list(data.get("artists", [])),
            album=data.get("album"),
            duration_s=int(data.get("duration_s", 0)),
            url=data.get("url"),
            lyrics=data.get("lyrics"),
            cover_url=data.get("cover_url"),
        )

    def __eq__(self, other: object) -> bool:
        """相等性按 id + source 判定（同一首歌在不同源视为不同）。"""
        if not isinstance(other, Song):
            return NotImplemented
        return self.id == other.id and self.source is other.source

    def __hash__(self) -> int:
        """与 __eq__ 配套，使 Song 可作为 dict key / set 成员。"""
        return hash((self.id, self.source))


@dataclass
class Playlist:
    """歌单元数据。

    :ivar id: 歌单 ID
    :ivar name: 歌单名
    :ivar songs: 歌曲列表（默认空）
    :ivar cover_url: 歌单封面 URL，可空
    :ivar creator: 创建者标识，可空
    """

    id: str
    name: str
    songs: list[Song] = field(default_factory=list)
    cover_url: str | None = None
    creator: str | None = None

    def add_song(self, song: Song) -> None:
        """追加歌曲到歌单；同 id+source 的歌曲去重。

        :param song: 要追加的 :class:`Song`
        """
        if song in self.songs:
            return
        self.songs.append(song)

    def remove_song(self, song: Song) -> None:
        """按 id+source 移除歌曲；不存在则静默（幂等）。

        :param song: 要移除的 :class:`Song`
        """
        if song in self.songs:
            self.songs.remove(song)

    @property
    def song_count(self) -> int:
        """歌单内歌曲数量。"""
        return len(self.songs)


@dataclass
class Artist:
    """艺术家元数据。

    :ivar id: 艺术家 ID
    :ivar name: 艺术家名
    :ivar cover_url: 艺术家封面 URL，可空
    :ivar song_count: 该艺术家歌曲总数（默认 0）
    """

    id: str
    name: str
    cover_url: str | None = None
    song_count: int = 0
