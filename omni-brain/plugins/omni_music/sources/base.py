"""MusicSource 抽象基类 + FakeMusicSource（M17.2）。

所有具体音乐源（网易云/QQ/本地/Spotify）需继承 :class:`MusicSource` 实现 6 个抽象方法。
网络请求（httpx/requests）在子类中惰性导入，``ImportError`` 时返回 ``E_BACKEND_UNAVAILABLE``。

合规说明（D17.4）：本抽象只定义接口契约，不携带任何破解付费内容的逻辑。
仅个人学习用途。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from omni_music.models import MusicSourceEnum, Song


class MusicSource(ABC):
    """音乐源抽象基类。

    子类需覆盖类属性 ``source``（:class:`MusicSourceEnum`）并实现 6 个抽象方法：
    - :meth:`search`：按关键词搜索歌曲
    - :meth:`get_song_url`：获取可播放 URL（VIP 曲目可能返回 None）
    - :meth:`get_lyrics`：获取歌词文本
    - :meth:`get_song_detail`：获取歌曲详情
    - :meth:`login_qr`：发起扫码登录，返回 key + qr_url
    - :meth:`check_login_status`：轮询扫码登录状态
    """

    # 类属性：子类覆盖为对应的 MusicSourceEnum
    source: MusicSourceEnum = MusicSourceEnum.LOCAL

    @abstractmethod
    def search(self, keyword: str, limit: int = 20) -> list[Song]:
        """按关键词搜索歌曲。

        :param keyword: 搜索关键词（歌曲名/歌手名/专辑名）
        :param limit: 返回上限
        :return: 匹配的 :class:`Song` 列表
        """
        ...

    @abstractmethod
    def get_song_url(self, song_id: str, quality: str = "standard") -> str | None:
        """获取可播放 URL。

        :param song_id: 歌曲 ID
        :param quality: 音质，``standard`` / ``hires`` / ``lossless`` 等
        :return: 可播放 URL 字符串；VIP 曲目无权限时返回 None
        """
        ...

    @abstractmethod
    def get_lyrics(self, song_id: str) -> str | None:
        """获取歌词文本（LRC 或纯文本）。

        :param song_id: 歌曲 ID
        :return: 歌词字符串；无歌词返回 None
        """
        ...

    @abstractmethod
    def get_song_detail(self, song_id: str) -> Song | None:
        """获取歌曲详情。

        :param song_id: 歌曲 ID
        :return: :class:`Song` 实例；不存在返回 None
        """
        ...

    @abstractmethod
    def login_qr(self) -> dict[str, str]:
        """发起扫码登录，返回二维码 key 与 URL。

        :return: dict，至少含 ``key``（轮询用）与 ``qr_url``（二维码图片 URL）
        """
        ...

    @abstractmethod
    def check_login_status(self, key: str) -> str:
        """轮询扫码登录状态。

        :param key: :meth:`login_qr` 返回的 key
        :return: 状态字符串，``waiting`` / ``scanned`` / ``confirmed`` / ``expired``
        """
        ...


class FakeMusicSource(MusicSource):
    """测试用 fake 音乐源：内置固定歌曲数据，记录调用计数。

    不发起任何网络请求；扫码登录状态机内置 ``waiting → scanned → confirmed`` 转换。
    测试可通过覆盖类属性 ``fake_login_status_sequence`` / ``fake_cookies_on_confirmed``
    定制行为。

    用法::

        fake = FakeMusicSource()
        songs = fake.search("晴天", limit=5)
        qr = fake.login_qr()
        for _ in range(3):
            status = fake.check_login_status(qr["key"])
            if status == "confirmed":
                break
    """

    source: MusicSourceEnum = MusicSourceEnum.NETEASE

    def __init__(self) -> None:
        """构造 fake 音乐源，预置 3 首固定歌曲。"""
        # 内置固定歌曲数据（3 首，便于测试断言）
        self.songs: list[Song] = [
            Song(
                id="fake_song_1",
                name="晴天",
                artists=["周杰伦"],
                album="叶惠美",
                duration_s=269,
                url="https://fake.example.com/song_1.mp3",
                lyrics="[00:00] 故事的小黄花 从出生那年就飘着",
                cover_url="https://fake.example.com/cover_1.jpg",
                source=MusicSourceEnum.NETEASE,
            ),
            Song(
                id="fake_song_2",
                name="稻香",
                artists=["周杰伦"],
                album="魔杰座",
                duration_s=223,
                url="https://fake.example.com/song_2.mp3",
                lyrics="对这个世界如果你有太多的抱怨",
                cover_url="https://fake.example.com/cover_2.jpg",
                source=MusicSourceEnum.NETEASE,
            ),
            Song(
                id="fake_song_3",
                name="七里香",
                artists=["周杰伦"],
                album="七里香",
                duration_s=299,
                url="https://fake.example.com/song_3.mp3",
                lyrics=None,  # 无歌词（测试 None 路径）
                cover_url="https://fake.example.com/cover_3.jpg",
                source=MusicSourceEnum.NETEASE,
            ),
        ]
        # 调用计数（供测试断言）
        self.search_call_count: int = 0
        self.login_qr_call_count: int = 0
        self.fake_cookies_save_count: int = 0
        # 扫码状态机：可被测试覆盖
        # 默认序列：waiting → scanned → confirmed（之后保持 confirmed）
        self.fake_login_status_sequence: list[str] | None = None
        # confirmed 时返回的 cookie（可被测试覆盖）
        self.fake_cookies_on_confirmed: dict[str, str] | None = None
        # 每个 key 的轮询次数（驱动默认状态机）
        self._poll_counts: dict[str, int] = {}
        # login_qr 返回的 key 累计序号
        self._qr_seq: int = 0

    def search(self, keyword: str, limit: int = 20) -> list[Song]:
        """按 keyword 过滤内置歌曲名；空 keyword 返回全部（受 limit 截断）。"""
        self.search_call_count += 1
        if not keyword:
            matched = list(self.songs)
        else:
            matched = [s for s in self.songs if keyword in s.name]
        return matched[:limit]

    def get_song_url(self, song_id: str, quality: str = "standard") -> str | None:
        """返回内置歌曲的 URL；未知 song_id 返回 None。"""
        for song in self.songs:
            if song.id == song_id:
                return song.url
        return None

    def get_lyrics(self, song_id: str) -> str | None:
        """返回内置歌曲的歌词；无歌词或未知返回 None。"""
        for song in self.songs:
            if song.id == song_id:
                return song.lyrics
        return None

    def get_song_detail(self, song_id: str) -> Song | None:
        """返回内置歌曲详情；未知返回 None。"""
        for song in self.songs:
            if song.id == song_id:
                return song
        return None

    def login_qr(self) -> dict[str, str]:
        """返回递增 key + 固定 qr_url。"""
        self.login_qr_call_count += 1
        self._qr_seq += 1
        key = f"fake_qr_key_{self._qr_seq}"
        # 重置该 key 的轮询计数
        self._poll_counts[key] = 0
        return {
            "key": key,
            "qr_url": f"https://fake.example.com/qr/{key}.png",
        }

    def check_login_status(self, key: str) -> str:
        """按预设序列返回状态；默认 waiting → scanned → confirmed。"""
        # 自定义序列优先
        if self.fake_login_status_sequence is not None:
            idx = self._poll_counts.get(key, 0)
            if idx >= len(self.fake_login_status_sequence):
                # 序列耗尽，返回最后一个状态
                return self.fake_login_status_sequence[-1]
            status = self.fake_login_status_sequence[idx]
            self._poll_counts[key] = idx + 1
            return status
        # 默认状态机：waiting → scanned → confirmed → confirmed...
        count = self._poll_counts.get(key, 0)
        self._poll_counts[key] = count + 1
        if count == 0:
            return "waiting"
        elif count == 1:
            return "scanned"
        else:
            return "confirmed"

    def get_cookies_on_confirmed(self) -> dict[str, str] | None:
        """返回 confirmed 时应保存的 cookie；供 QRLoginFlow 调用。

        每次调用累加 ``fake_cookies_save_count``（便于测试断言保存次数）。
        """
        self.fake_cookies_save_count += 1
        return self.fake_cookies_on_confirmed
