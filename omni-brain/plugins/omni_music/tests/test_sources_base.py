"""omni_music MusicSource 抽象基类 + FakeMusicSource 测试（M17.2）。

覆盖：
- MusicSource 是 ABC，不能直接实例化
- 抽象方法清单（search/get_song_url/get_lyrics/get_song_detail/login_qr/check_login_status）
- FakeMusicSource 行为：内置固定数据、记录调用计数
- 错误路径：未知 song_id 返回 None / 默认 url
"""

from __future__ import annotations

import pytest

from omni_music.models import MusicSourceEnum, Song
from omni_music.sources.base import FakeMusicSource, MusicSource


class TestMusicSourceABC:
    def test_music_source_is_abstract(self) -> None:
        """MusicSource 是 ABC，不能直接实例化。"""
        with pytest.raises(TypeError):
            MusicSource()  # type: ignore[abstract]

    def test_music_source_has_abstract_methods(self) -> None:
        """MusicSource 声明 6 个抽象方法。"""
        abstract_methods = MusicSource.__abstractmethods__
        for name in (
            "search",
            "get_song_url",
            "get_lyrics",
            "get_song_detail",
            "login_qr",
            "check_login_status",
        ):
            assert name in abstract_methods, f"缺少抽象方法 {name}"

    def test_music_source_source_property_exists(self) -> None:
        """MusicSource 子类需提供 source 属性（MusicSourceEnum）。"""
        fake = FakeMusicSource()
        assert hasattr(fake, "source")
        assert isinstance(fake.source, MusicSourceEnum)


class TestFakeMusicSourceSearch:
    def test_search_returns_songs(self) -> None:
        """search 返回内置固定 Song 列表。"""
        fake = FakeMusicSource()
        results = fake.search("晴天", limit=10)
        assert isinstance(results, list)
        assert len(results) > 0
        assert all(isinstance(s, Song) for s in results)

    def test_search_keyword_filter(self) -> None:
        """search 按 keyword 过滤内置歌曲名。"""
        fake = FakeMusicSource()
        # 内置至少有一首含"晴天"的歌
        results = fake.search("晴天", limit=10)
        assert any("晴天" in s.name for s in results)

    def test_search_limit_respected(self) -> None:
        """search 截断到 limit 条。"""
        fake = FakeMusicSource()
        results = fake.search("", limit=1)
        assert len(results) <= 1

    def test_search_increments_call_count(self) -> None:
        """search 调用计数累加（供测试断言）。"""
        fake = FakeMusicSource()
        assert fake.search_call_count == 0
        fake.search("a", limit=5)
        assert fake.search_call_count == 1
        fake.search("b", limit=5)
        assert fake.search_call_count == 2

    def test_search_empty_keyword_returns_all(self) -> None:
        """空 keyword 返回全部内置歌曲（受 limit 截断）。"""
        fake = FakeMusicSource()
        results = fake.search("", limit=100)
        assert len(results) == len(fake.songs)


class TestFakeMusicSourceGetSongUrl:
    def test_get_song_url_returns_url(self) -> None:
        """已知 song_id 返回 URL 字符串。"""
        fake = FakeMusicSource()
        first_id = fake.songs[0].id
        url = fake.get_song_url(first_id)
        assert isinstance(url, str)
        assert url  # 非空

    def test_get_song_url_unknown_returns_none(self) -> None:
        """未知 song_id 返回 None。"""
        fake = FakeMusicSource()
        url = fake.get_song_url("non_existent_id")
        assert url is None

    def test_get_song_url_quality_param_accepted(self) -> None:
        """get_song_url 接受 quality 参数（默认 standard）。"""
        fake = FakeMusicSource()
        first_id = fake.songs[0].id
        # 不同音质都应返回非 None URL
        url_std = fake.get_song_url(first_id, quality="standard")
        url_hq = fake.get_song_url(first_id, quality="hires")
        assert url_std is not None
        assert url_hq is not None


class TestFakeMusicSourceGetLyrics:
    def test_get_lyrics_returns_str(self) -> None:
        """已知 song_id 返回歌词字符串。"""
        fake = FakeMusicSource()
        # 内置至少一首带歌词的歌
        first_with_lyrics = next(s for s in fake.songs if s.lyrics)
        lyrics = fake.get_lyrics(first_with_lyrics.id)
        assert isinstance(lyrics, str)
        assert lyrics

    def test_get_lyrics_no_lyrics_returns_none(self) -> None:
        """歌曲没有歌词时返回 None。"""
        fake = FakeMusicSource()
        # M32.23：next 不带默认值——fake 内置数据一旦丢失无歌词歌曲，
        # StopIteration 让测试立刻失败（回归信号），而非 pytest.skip 静默跳过。
        first_without_lyrics = next(s for s in fake.songs if not s.lyrics)
        lyrics = fake.get_lyrics(first_without_lyrics.id)
        assert lyrics is None

    def test_get_lyrics_unknown_returns_none(self) -> None:
        """未知 song_id 返回 None。"""
        fake = FakeMusicSource()
        assert fake.get_lyrics("ghost_id") is None


class TestFakeMusicSourceGetSongDetail:
    def test_get_song_detail_returns_song(self) -> None:
        """已知 song_id 返回 Song 实例。"""
        fake = FakeMusicSource()
        first = fake.songs[0]
        detail = fake.get_song_detail(first.id)
        assert detail is not None
        assert isinstance(detail, Song)
        assert detail.id == first.id

    def test_get_song_detail_unknown_returns_none(self) -> None:
        """未知 song_id 返回 None。"""
        fake = FakeMusicSource()
        assert fake.get_song_detail("ghost_id") is None


class TestFakeMusicSourceLoginQR:
    def test_login_qr_returns_key_and_url(self) -> None:
        """login_qr 返回 dict 含 key 与 qr_url。"""
        fake = FakeMusicSource()
        result = fake.login_qr()
        assert isinstance(result, dict)
        assert "key" in result and result["key"]
        assert "qr_url" in result and result["qr_url"]

    def test_login_qr_increments_count(self) -> None:
        """login_qr 调用计数累加。"""
        fake = FakeMusicSource()
        assert fake.login_qr_call_count == 0
        fake.login_qr()
        assert fake.login_qr_call_count == 1


class TestFakeMusicSourceCheckLoginStatus:
    def test_check_login_status_returns_str(self) -> None:
        """check_login_status 返回状态字符串。"""
        fake = FakeMusicSource()
        status = fake.check_login_status("any_key")
        assert status in ("waiting", "scanned", "confirmed", "expired")

    def test_check_login_status_unknown_key_returns_waiting(self) -> None:
        """未知 key 默认返回 waiting。"""
        fake = FakeMusicSource()
        assert fake.check_login_status("ghost_key") == "waiting"

    def test_check_login_status_transitions(self) -> None:
        """FakeMusicSource 状态机：waiting → scanned → confirmed。"""
        fake = FakeMusicSource()
        key = fake.login_qr()["key"]
        # 第一次轮询：waiting
        assert fake.check_login_status(key) == "waiting"
        # 第二次轮询：scanned
        assert fake.check_login_status(key) == "scanned"
        # 第三次轮询：confirmed
        assert fake.check_login_status(key) == "confirmed"
        # 第四次轮询：保持 confirmed
        assert fake.check_login_status(key) == "confirmed"


class TestFakeMusicSourceBuiltinSongs:
    def test_builtin_songs_non_empty(self) -> None:
        """FakeMusicSource 内置至少 3 首歌曲。"""
        fake = FakeMusicSource()
        assert len(fake.songs) >= 3

    def test_builtin_songs_source_is_netease(self) -> None:
        """FakeMusicSource 内置歌曲 source 默认为 netease。"""
        fake = FakeMusicSource()
        for song in fake.songs:
            assert song.source is MusicSourceEnum.NETEASE

    def test_fake_source_attribute(self) -> None:
        """FakeMusicSource.source == NETEASE。"""
        fake = FakeMusicSource()
        assert fake.source is MusicSourceEnum.NETEASE
