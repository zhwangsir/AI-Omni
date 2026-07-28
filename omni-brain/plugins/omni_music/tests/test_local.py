"""omni_music LocalMusicSource 测试（M17.6）。

覆盖：
- scan() 递归扫描、扩展名过滤、元数据读取、.lrc 歌词、mutagen 缺失降级
- search() 按 name/artist/album 匹配、空 keyword、limit 截断、缓存复用
- get_song_url / get_lyrics / get_song_detail 查找与未找到路径
- login_qr / check_login_status / get_cookies_on_confirmed 固定返回值
- root_dir ~ 展开
- Song.source == MusicSourceEnum.LOCAL

测试零依赖（CLAUDE.md §三）：用 FakeFileScanner + FakeMetadataReader 注入，
不碰真实音频硬件、不装 mutagen、不下载模型。
"""

from __future__ import annotations

import hashlib
import os
import sys

import pytest

from omni_music.models import MusicSourceEnum, Song
from omni_music.sources.local import LocalMusicSource


# ---------------------------------------------------------------------------
# Fake 依赖（CLAUDE.md §三 测试零依赖）
# ---------------------------------------------------------------------------


class FakeFileScanner:
    """假文件扫描器：按 root 前缀过滤预置文件列表，记录调用次数。"""

    def __init__(self, files: list[str]) -> None:
        self._files = files
        self.scan_call_count: int = 0
        self.received_root: str | None = None

    def scan(self, root: str) -> list[str]:
        """返回以 root 开头的预置文件；记录调用次数与收到的 root。"""
        self.scan_call_count += 1
        self.received_root = root
        return [f for f in self._files if f.startswith(root)]


class FakeMetadataReader:
    """假元数据读取器：按 path 返回预置 dict，缺失则返回空元数据。"""

    def __init__(self, metadata: dict[str, dict] | None = None) -> None:
        self._meta = metadata or {}
        self.read_call_count: int = 0

    def read(self, path: str) -> dict:
        """返回 path 对应的元数据 dict；未预置返回空元数据。"""
        self.read_call_count += 1
        return self._meta.get(
            path,
            {"title": None, "artist": None, "album": None, "duration": 0},
        )


# ---------------------------------------------------------------------------
# 辅助工厂
# ---------------------------------------------------------------------------


def _make_source(
    files: list[str],
    metadata: dict[str, dict] | None = None,
    root_dir: str = "/fake/music",
) -> tuple[LocalMusicSource, FakeFileScanner, FakeMetadataReader]:
    """构造带 fake 依赖的 LocalMusicSource，返回 (source, scanner, reader)。"""
    scanner = FakeFileScanner(files)
    reader = FakeMetadataReader(metadata or {})
    source = LocalMusicSource(
        root_dir=root_dir,
        file_scanner=scanner,
        metadata_reader=reader,
    )
    return source, scanner, reader


# ---------------------------------------------------------------------------
# scan() 测试
# ---------------------------------------------------------------------------


class TestScan:
    def test_scan_returns_song_list(self) -> None:
        """scan 成功返回 Song 列表，断言 id/name/artists/album/url/cover。"""
        files = ["/fake/music/song1.mp3", "/fake/music/song2.flac"]
        meta = {
            "/fake/music/song1.mp3": {
                "title": "晴天",
                "artist": "周杰伦",
                "album": "叶惠美",
                "duration": 269,
            },
            "/fake/music/song2.flac": {
                "title": "稻香",
                "artist": "周杰伦",
                "album": "魔杰座",
                "duration": 223,
            },
        }
        source, _, _ = _make_source(files, meta)
        songs = source.scan()

        assert len(songs) == 2
        s1 = songs[0]
        # id = md5(path)[:12]
        expected_id = hashlib.md5(b"/fake/music/song1.mp3").hexdigest()[:12]
        assert s1.id == expected_id
        assert s1.name == "晴天"
        assert s1.artists == ["周杰伦"]
        assert s1.album == "叶惠美"
        assert s1.duration_s == 269
        assert s1.url == "file:///fake/music/song1.mp3"
        assert s1.cover_url is None
        assert s1.source is MusicSourceEnum.LOCAL

    def test_scan_ignores_non_audio_extensions(self, tmp_path: pytest.Path) -> None:
        """scan 忽略非音频扩展名（.txt/.jpg 不入列）。"""
        (tmp_path / "song.mp3").write_text("")
        (tmp_path / "notes.txt").write_text("")
        (tmp_path / "cover.jpg").write_text("")
        (tmp_path / "readme.md").write_text("")

        source = LocalMusicSource(
            root_dir=str(tmp_path),
            file_scanner=None,  # 用内置 _scan_dir
            metadata_reader=FakeMetadataReader({}),
        )
        songs = source.scan()
        assert len(songs) == 1
        assert songs[0].name == "song"

    def test_scan_recurses_subdirectories(self, tmp_path: pytest.Path) -> None:
        """scan 递归扫描子目录。"""
        sub = tmp_path / "subdir"
        sub.mkdir()
        deep = sub / "nested"
        deep.mkdir()
        (deep / "deep.mp3").write_text("")
        (sub / "mid.flac").write_text("")
        (tmp_path / "top.m4a").write_text("")

        source = LocalMusicSource(
            root_dir=str(tmp_path),
            file_scanner=None,
            metadata_reader=FakeMetadataReader({}),
        )
        songs = source.scan()
        names = {s.name for s in songs}
        assert names == {"deep", "mid", "top"}

    def test_scan_reads_lrc_file(self, tmp_path: pytest.Path) -> None:
        """scan 读取与音频同名的 .lrc 歌词文件。"""
        (tmp_path / "song.mp3").write_text("")
        (tmp_path / "song.lrc").write_text("[00:00] 故事的小黄花")

        source = LocalMusicSource(
            root_dir=str(tmp_path),
            file_scanner=None,
            metadata_reader=FakeMetadataReader({}),
        )
        songs = source.scan()
        assert len(songs) == 1
        assert songs[0].lyrics == "[00:00] 故事的小黄花"

    def test_scan_no_lrc_returns_none_lyrics(self, tmp_path: pytest.Path) -> None:
        """scan 无 .lrc 文件时 lyrics 为 None。"""
        (tmp_path / "song.mp3").write_text("")

        source = LocalMusicSource(
            root_dir=str(tmp_path),
            file_scanner=None,
            metadata_reader=FakeMetadataReader({}),
        )
        songs = source.scan()
        assert len(songs) == 1
        assert songs[0].lyrics is None

    def test_scan_mutagen_missing_degrades_to_filename(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """mutagen 缺失时降级用文件名推断元数据。"""
        # 强制 mutagen 不可导入（无论是否实际安装）
        monkeypatch.setitem(sys.modules, "mutagen", None)

        scanner = FakeFileScanner(["/fake/music/song1.mp3"])
        source = LocalMusicSource(
            root_dir="/fake/music",
            file_scanner=scanner,
            metadata_reader=None,  # 触发 mutagen 路径
        )
        songs = source.scan()
        assert len(songs) == 1
        s = songs[0]
        # 降级：name=文件名去扩展名、artists=["未知艺术家"]、album="未知专辑"
        assert s.name == "song1"
        assert s.artists == ["未知艺术家"]
        assert s.album == "未知专辑"
        assert s.duration_s == 0

    def test_scan_uses_mutagen_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """metadata_reader 为 None 且 mutagen 可用时，用 mutagen 读取元数据。"""

        class FakeAudio:
            class info:
                length = 269.5

            tags = {"title": ["晴天"], "artist": ["周杰伦"], "album": ["叶惠美"]}

        class FakeMutagenModule:
            @staticmethod
            def File(path: str) -> object:
                return FakeAudio() if "song1" in path else None

        monkeypatch.setitem(sys.modules, "mutagen", FakeMutagenModule)

        scanner = FakeFileScanner(
            ["/fake/music/song1.mp3", "/fake/music/song2.mp3"]
        )
        source = LocalMusicSource(
            root_dir="/fake/music",
            file_scanner=scanner,
            metadata_reader=None,
        )
        songs = source.scan()
        assert len(songs) == 2
        # song1: mutagen 返回有效元数据
        s1 = songs[0]
        assert s1.name == "晴天"
        assert s1.artists == ["周杰伦"]
        assert s1.album == "叶惠美"
        assert s1.duration_s == 269
        # song2: mutagen 返回 None，降级用文件名
        s2 = songs[1]
        assert s2.name == "song2"
        assert s2.artists == ["未知艺术家"]
        assert s2.album == "未知专辑"

    def test_scan_writes_cache(self) -> None:
        """scan 后写入 _songs_cache。"""
        source, _, _ = _make_source(["/fake/music/song1.mp3"])
        assert source._songs_cache is None
        source.scan()
        assert source._songs_cache is not None
        assert len(source._songs_cache) == 1

    def test_scan_empty_dir_returns_empty_list(self, tmp_path: pytest.Path) -> None:
        """scan 空目录返回空列表。"""
        source = LocalMusicSource(
            root_dir=str(tmp_path),
            file_scanner=None,
            metadata_reader=FakeMetadataReader({}),
        )
        songs = source.scan()
        assert songs == []

    def test_scan_nonexistent_dir_returns_empty_list(self) -> None:
        """scan 不存在的目录返回空列表（不抛异常）。"""
        source = LocalMusicSource(
            root_dir="/nonexistent/path/xyz",
            file_scanner=None,
            metadata_reader=FakeMetadataReader({}),
        )
        songs = source.scan()
        assert songs == []


# ---------------------------------------------------------------------------
# search() 测试
# ---------------------------------------------------------------------------


class TestSearch:
    def _scanned_source(self) -> LocalMusicSource:
        """构造已扫描的 source，含 3 首预置歌曲。"""
        files = [
            "/fake/music/qingtian.mp3",
            "/fake/music/daoxiang.mp3",
            "/fake/music/qilixiang.mp3",
        ]
        meta = {
            "/fake/music/qingtian.mp3": {
                "title": "晴天",
                "artist": "周杰伦",
                "album": "叶惠美",
                "duration": 269,
            },
            "/fake/music/daoxiang.mp3": {
                "title": "稻香",
                "artist": "周杰伦",
                "album": "魔杰座",
                "duration": 223,
            },
            "/fake/music/qilixiang.mp3": {
                "title": "七里香",
                "artist": "周杰伦",
                "album": "七里香",
                "duration": 299,
            },
        }
        source, _, _ = _make_source(files, meta)
        source.scan()
        return source

    def test_search_by_name_case_insensitive(self) -> None:
        """search 按 name 匹配（大小写不敏感）。"""
        source = self._scanned_source()
        # 中文不区分大小写，用英文歌名测试大小写
        files_en = ["/fake/music/sunny.mp3"]
        meta_en = {
            "/fake/music/sunny.mp3": {
                "title": "Sunny Day",
                "artist": "Jay",
                "album": "Album",
                "duration": 100,
            }
        }
        src_en, _, _ = _make_source(files_en, meta_en)
        src_en.scan()
        results = src_en.search("sunny", limit=10)
        assert len(results) == 1
        assert results[0].name == "Sunny Day"
        # 大写关键词也能匹配
        results_upper = src_en.search("SUNNY", limit=10)
        assert len(results_upper) == 1

    def test_search_by_artist(self) -> None:
        """search 按 artist 匹配。"""
        source = self._scanned_source()
        results = source.search("周杰伦", limit=10)
        assert len(results) == 3

    def test_search_by_album(self) -> None:
        """search 按 album 匹配。"""
        source = self._scanned_source()
        results = source.search("叶惠美", limit=10)
        assert len(results) == 1
        assert results[0].name == "晴天"

    def test_search_empty_keyword_returns_all(self) -> None:
        """空 keyword 返回全部（受 limit 截断）。"""
        source = self._scanned_source()
        results = source.search("", limit=100)
        assert len(results) == 3

    def test_search_limit_truncation(self) -> None:
        """search 截断到 limit 条。"""
        source = self._scanned_source()
        results = source.search("周杰伦", limit=2)
        assert len(results) == 2

    def test_search_auto_scans_if_cache_none(self) -> None:
        """未扫描时 search 自动触发 scan。"""
        files = ["/fake/music/song1.mp3"]
        meta = {
            "/fake/music/song1.mp3": {
                "title": "test",
                "artist": "a",
                "album": "b",
                "duration": 1,
            }
        }
        source, scanner, _ = _make_source(files, meta)
        assert source._songs_cache is None
        results = source.search("test", limit=10)
        assert len(results) == 1
        assert scanner.scan_call_count == 1

    def test_search_uses_cache_no_rescan(self) -> None:
        """第二次 search 不重新扫描（缓存复用）。"""
        source, scanner, _ = _make_source(
            ["/fake/music/song1.mp3"],
            {
                "/fake/music/song1.mp3": {
                    "title": "test",
                    "artist": "a",
                    "album": "b",
                    "duration": 1,
                }
            },
        )
        source.search("test", limit=10)
        source.search("test", limit=10)
        source.search("", limit=10)
        assert scanner.scan_call_count == 1

    def test_search_no_match_returns_empty(self) -> None:
        """search 无匹配返回空列表。"""
        source = self._scanned_source()
        results = source.search("不存在的歌曲名xyz", limit=10)
        assert results == []


# ---------------------------------------------------------------------------
# get_song_url() 测试
# ---------------------------------------------------------------------------


class TestGetSongUrl:
    def test_get_song_url_found(self) -> None:
        """get_song_url 找到返回 file:// URL。"""
        files = ["/fake/music/song1.mp3"]
        source, _, _ = _make_source(files)
        source.scan()
        songs = source._songs_cache
        assert songs is not None
        song_id = songs[0].id
        url = source.get_song_url(song_id)
        assert url == "file:///fake/music/song1.mp3"

    def test_get_song_url_not_found(self) -> None:
        """get_song_url 未找到返回 None。"""
        source, _, _ = _make_source(["/fake/music/song1.mp3"])
        source.scan()
        assert source.get_song_url("non_existent_id") is None

    def test_get_song_url_cache_none_returns_none(self) -> None:
        """未扫描时 get_song_url 返回 None。"""
        source, _, _ = _make_source(["/fake/music/song1.mp3"])
        assert source.get_song_url("any_id") is None

    def test_get_song_url_quality_ignored(self) -> None:
        """quality 参数本地源忽略，始终返回原始 URL。"""
        files = ["/fake/music/song1.mp3"]
        source, _, _ = _make_source(files)
        source.scan()
        songs = source._songs_cache
        assert songs is not None
        song_id = songs[0].id
        url_std = source.get_song_url(song_id, quality="standard")
        url_hires = source.get_song_url(song_id, quality="hires")
        assert url_std == url_hires
        assert url_std == "file:///fake/music/song1.mp3"


# ---------------------------------------------------------------------------
# get_lyrics() 测试
# ---------------------------------------------------------------------------


class TestGetLyrics:
    def test_get_lyrics_found(self, tmp_path: pytest.Path) -> None:
        """get_lyrics 找到返回歌词。"""
        (tmp_path / "song.mp3").write_text("")
        (tmp_path / "song.lrc").write_text("[00:00] 歌词内容")

        source = LocalMusicSource(
            root_dir=str(tmp_path),
            file_scanner=None,
            metadata_reader=FakeMetadataReader({}),
        )
        source.scan()
        songs = source._songs_cache
        assert songs is not None
        song_id = songs[0].id
        lyrics = source.get_lyrics(song_id)
        assert lyrics == "[00:00] 歌词内容"

    def test_get_lyrics_none_returns_none(self, tmp_path: pytest.Path) -> None:
        """get_lyrics 歌曲无歌词返回 None。"""
        (tmp_path / "song.mp3").write_text("")

        source = LocalMusicSource(
            root_dir=str(tmp_path),
            file_scanner=None,
            metadata_reader=FakeMetadataReader({}),
        )
        source.scan()
        songs = source._songs_cache
        assert songs is not None
        song_id = songs[0].id
        assert source.get_lyrics(song_id) is None

    def test_get_lyrics_not_found(self) -> None:
        """get_lyrics 未找到返回 None。"""
        source, _, _ = _make_source(["/fake/music/song1.mp3"])
        source.scan()
        assert source.get_lyrics("ghost_id") is None


# ---------------------------------------------------------------------------
# get_song_detail() 测试
# ---------------------------------------------------------------------------


class TestGetSongDetail:
    def test_get_song_detail_found(self) -> None:
        """get_song_detail 找到返回 Song。"""
        files = ["/fake/music/song1.mp3"]
        source, _, _ = _make_source(files)
        source.scan()
        songs = source._songs_cache
        assert songs is not None
        song_id = songs[0].id
        detail = source.get_song_detail(song_id)
        assert detail is not None
        assert isinstance(detail, Song)
        assert detail.id == song_id
        assert detail.name == "song1"  # FakeMetadataReader 返回空 → 文件名

    def test_get_song_detail_not_found(self) -> None:
        """get_song_detail 未找到返回 None。"""
        source, _, _ = _make_source(["/fake/music/song1.mp3"])
        source.scan()
        assert source.get_song_detail("ghost_id") is None


# ---------------------------------------------------------------------------
# login / cookies 测试
# ---------------------------------------------------------------------------


class TestLoginAndCookies:
    def test_login_qr_returns_fixed_value(self) -> None:
        """login_qr 返回 {"key": "local", "qr_url": ""}。"""
        source = LocalMusicSource()
        result = source.login_qr()
        assert result == {"key": "local", "qr_url": ""}

    def test_check_login_status_returns_confirmed(self) -> None:
        """check_login_status 返回 "confirmed"。"""
        source = LocalMusicSource()
        assert source.check_login_status("any_key") == "confirmed"
        # 本地源 key 参数忽略，任何 key 都返回 confirmed
        assert source.check_login_status("local") == "confirmed"
        assert source.check_login_status("") == "confirmed"

    def test_get_cookies_on_confirmed_returns_none(self) -> None:
        """get_cookies_on_confirmed 返回 None（本地源无 cookie）。"""
        source = LocalMusicSource()
        assert source.get_cookies_on_confirmed() is None


# ---------------------------------------------------------------------------
# source 属性 / root_dir 展开测试
# ---------------------------------------------------------------------------


class TestSourceAttribute:
    def test_source_is_local(self) -> None:
        """LocalMusicSource.source == MusicSourceEnum.LOCAL。"""
        source = LocalMusicSource()
        assert source.source is MusicSourceEnum.LOCAL

    def test_scanned_song_source_is_local(self) -> None:
        """扫描出的 Song.source 字段为 MusicSourceEnum.LOCAL。"""
        source, _, _ = _make_source(["/fake/music/song1.mp3"])
        songs = source.scan()
        for song in songs:
            assert song.source is MusicSourceEnum.LOCAL


class TestRootDirExpansion:
    def test_root_dir_expands_tilde(self) -> None:
        """root_dir 中的 ~ 展开为用户家目录。"""
        scanner = FakeFileScanner([])
        source = LocalMusicSource(root_dir="~/music", file_scanner=scanner)
        expected = os.path.expanduser("~/music")
        assert source.root_dir == expected
        # 触发 scan，验证 scanner 收到展开后的路径
        source.scan()
        assert scanner.received_root == expected

    def test_root_dir_no_tilde_unchanged(self) -> None:
        """root_dir 不含 ~ 时保持原样。"""
        source = LocalMusicSource(root_dir="/abs/path")
        assert source.root_dir == "/abs/path"

    def test_default_root_dir(self) -> None:
        """默认 root_dir 为 ~/.ai-omni/music（展开后）。"""
        source = LocalMusicSource()
        assert source.root_dir == os.path.expanduser("~/.ai-omni/music")
