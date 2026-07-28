"""omni_music 数据模型测试（M17.1）。

覆盖 Song / Playlist / Artist / MusicSourceEnum：
- 字段默认值与构造赋值
- dataclasses.field 默认工厂（artists / songs 为 list）
- MusicSourceEnum 成员与值
- Song.to_dict / from_dict 往返序列化
- Playlist.add_song / remove_song
- Artist.song_count 派生属性
"""

from __future__ import annotations

import pytest

from omni_music.models import (
    Artist,
    MusicSourceEnum,
    Playlist,
    Song,
)


class TestMusicSourceEnum:
    def test_enum_members(self) -> None:
        """MusicSourceEnum 含 netease/qqmusic/local/spotify 四个成员。"""
        assert MusicSourceEnum.NETEASE.value == "netease"
        assert MusicSourceEnum.QQMUSIC.value == "qqmusic"
        assert MusicSourceEnum.LOCAL.value == "local"
        assert MusicSourceEnum.SPOTIFY.value == "spotify"

    def test_enum_from_value(self) -> None:
        """通过字符串值构造 MusicSourceEnum。"""
        assert MusicSourceEnum("netease") is MusicSourceEnum.NETEASE
        assert MusicSourceEnum("local") is MusicSourceEnum.LOCAL

    def test_enum_unknown_value_raises(self) -> None:
        """未知源字符串抛 ValueError。"""
        with pytest.raises(ValueError):
            MusicSourceEnum("unknown_source")

    def test_enum_iterable(self) -> None:
        """可遍历所有成员。"""
        members = list(MusicSourceEnum)
        assert len(members) == 4


class TestSong:
    def test_song_basic_fields(self) -> None:
        """Song 含 id/name/artists/album/duration_s/url/lyrics/cover_url/source 字段。"""
        song = Song(
            id="song_1",
            name="晴天",
            artists=["周杰伦"],
            album="叶惠美",
            duration_s=269,
            url="https://example.com/song_1.mp3",
            lyrics="[00:00] 故事的小黄花",
            cover_url="https://example.com/cover_1.jpg",
            source=MusicSourceEnum.NETEASE,
        )
        assert song.id == "song_1"
        assert song.name == "晴天"
        assert song.artists == ["周杰伦"]
        assert song.album == "叶惠美"
        assert song.duration_s == 269
        assert song.url.endswith("song_1.mp3")
        assert song.lyrics.startswith("[00:00]")
        assert song.cover_url.endswith("cover_1.jpg")
        assert song.source is MusicSourceEnum.NETEASE

    def test_song_artists_default_empty_list(self) -> None:
        """artists 默认空 list（dataclasses.field 默认工厂）。"""
        song = Song(id="s", name="x", source=MusicSourceEnum.LOCAL)
        assert song.artists == []

    def test_song_optional_fields_default_none(self) -> None:
        """album/url/lyrics/cover_url 默认 None。"""
        song = Song(id="s", name="x", source=MusicSourceEnum.LOCAL)
        assert song.album is None
        assert song.url is None
        assert song.lyrics is None
        assert song.cover_url is None

    def test_song_duration_default_zero(self) -> None:
        """duration_s 默认 0。"""
        song = Song(id="s", name="x", source=MusicSourceEnum.LOCAL)
        assert song.duration_s == 0

    def test_song_artists_independent_instances(self) -> None:
        """两个 Song 实例的 artists 列表互不影响（field 默认工厂）。"""
        s1 = Song(id="1", name="a", source=MusicSourceEnum.LOCAL)
        s2 = Song(id="2", name="b", source=MusicSourceEnum.LOCAL)
        s1.artists.append("歌手X")
        assert s2.artists == []

    def test_song_to_dict_roundtrip(self) -> None:
        """to_dict / from_dict 往返序列化保持等价。"""
        original = Song(
            id="song_2",
            name="稻香",
            artists=["周杰伦"],
            album="魔杰座",
            duration_s=223,
            url="https://example.com/dao.mp3",
            lyrics="对这个世界如果你有太多的抱怨",
            cover_url="https://example.com/dao.jpg",
            source=MusicSourceEnum.NETEASE,
        )
        d = original.to_dict()
        assert d["id"] == "song_2"
        assert d["source"] == "netease"  # 序列化为字符串值
        restored = Song.from_dict(d)
        assert restored == original

    def test_song_from_dict_missing_optional(self) -> None:
        """from_dict 缺失可选字段时使用默认值。"""
        d = {"id": "s3", "name": "无专辑", "source": "local"}
        song = Song.from_dict(d)
        assert song.id == "s3"
        assert song.artists == []
        assert song.album is None
        assert song.source is MusicSourceEnum.LOCAL

    def test_song_from_dict_invalid_source_raises(self) -> None:
        """from_dict 收到未知 source 字符串抛 ValueError。"""
        d = {"id": "s", "name": "x", "source": "tidal"}
        with pytest.raises(ValueError):
            Song.from_dict(d)

    def test_song_eq_by_id_and_source(self) -> None:
        """Song 相等性按 id + source 判定（同一首歌在不同源视为不同）。"""
        s1 = Song(id="1", name="a", source=MusicSourceEnum.NETEASE)
        s2 = Song(id="1", name="a", source=MusicSourceEnum.NETEASE)
        s3 = Song(id="1", name="a", source=MusicSourceEnum.QQMUSIC)
        assert s1 == s2
        assert s1 != s3


class TestPlaylist:
    def test_playlist_basic_fields(self) -> None:
        """Playlist 含 id/name/songs/cover_url/creator 字段。"""
        playlist = Playlist(
            id="pl_1",
            name="我的歌单",
            cover_url="https://example.com/pl.jpg",
            creator="user_1",
        )
        assert playlist.id == "pl_1"
        assert playlist.name == "我的歌单"
        assert playlist.songs == []
        assert playlist.cover_url.endswith("pl.jpg")
        assert playlist.creator == "user_1"

    def test_playlist_songs_default_empty_list(self) -> None:
        """songs 默认空 list。"""
        pl = Playlist(id="p", name="x")
        assert pl.songs == []

    def test_playlist_optional_fields_default_none(self) -> None:
        """cover_url / creator 默认 None。"""
        pl = Playlist(id="p", name="x")
        assert pl.cover_url is None
        assert pl.creator is None

    def test_playlist_add_song(self) -> None:
        """add_song 追加歌曲到 songs 列表。"""
        pl = Playlist(id="p", name="x")
        song = Song(id="s1", name="a", source=MusicSourceEnum.LOCAL)
        pl.add_song(song)
        assert pl.songs == [song]

    def test_playlist_add_song_dedup(self) -> None:
        """add_song 对相同 id+source 的歌曲去重。"""
        pl = Playlist(id="p", name="x")
        song = Song(id="s1", name="a", source=MusicSourceEnum.LOCAL)
        pl.add_song(song)
        pl.add_song(song)
        assert len(pl.songs) == 1

    def test_playlist_remove_song(self) -> None:
        """remove_song 按 id+source 移除歌曲。"""
        pl = Playlist(id="p", name="x")
        s1 = Song(id="s1", name="a", source=MusicSourceEnum.LOCAL)
        s2 = Song(id="s2", name="b", source=MusicSourceEnum.LOCAL)
        pl.add_song(s1)
        pl.add_song(s2)
        pl.remove_song(s1)
        assert pl.songs == [s2]

    def test_playlist_remove_song_not_found(self) -> None:
        """remove_song 不存在的歌曲不报错（幂等）。"""
        pl = Playlist(id="p", name="x")
        s = Song(id="ghost", name="g", source=MusicSourceEnum.LOCAL)
        pl.remove_song(s)  # 不应抛异常
        assert pl.songs == []

    def test_playlist_song_count(self) -> None:
        """song_count 属性返回歌曲数量。"""
        pl = Playlist(id="p", name="x")
        pl.add_song(Song(id="s1", name="a", source=MusicSourceEnum.LOCAL))
        pl.add_song(Song(id="s2", name="b", source=MusicSourceEnum.LOCAL))
        assert pl.song_count == 2


class TestArtist:
    def test_artist_basic_fields(self) -> None:
        """Artist 含 id/name/cover_url/song_count 字段。"""
        artist = Artist(
            id="artist_1",
            name="周杰伦",
            cover_url="https://example.com/artist.jpg",
            song_count=200,
        )
        assert artist.id == "artist_1"
        assert artist.name == "周杰伦"
        assert artist.cover_url.endswith("artist.jpg")
        assert artist.song_count == 200

    def test_artist_optional_fields_default(self) -> None:
        """cover_url 默认 None；song_count 默认 0。"""
        artist = Artist(id="a", name="x")
        assert artist.cover_url is None
        assert artist.song_count == 0
