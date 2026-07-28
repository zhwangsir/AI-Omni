"""omni_music library.scanner 增强扫描器测试（M19.3）。

TDD 测试先行：覆盖 LibraryScanner 的扫描、增量更新、封面/歌词提取、写入 SQLite。
全部用 fake file_scanner / metadata_reader / cover_extractor 注入，零依赖
（不装 mutagen、不碰真实音频文件）。
"""

from __future__ import annotations

import os
import sys
import time
import types
from pathlib import Path

import pytest

from omni_music.library.db import MusicLibraryDB
from omni_music.library.scanner import LibraryScanner, _extract_bytes


# ---------------------------------------------------------------------------
# Fake 依赖
# ---------------------------------------------------------------------------


class FakeFileScanner:
    """假文件扫描器：返回预置文件列表。"""

    def __init__(self, files: list[str]) -> None:
        self._files = files
        self.call_count: int = 0

    def scan(self, root: str) -> list[str]:
        self.call_count += 1
        return list(self._files)


class FakeMetadataReader:
    """假元数据读取器：返回预置元数据 + 封面 + 歌词。"""

    def __init__(self, metadata: dict[str, dict]) -> None:
        self._meta = metadata
        self.call_count: int = 0

    def read(self, path: str) -> dict:
        self.call_count += 1
        return self._meta.get(
            path,
            {"title": None, "artist": None, "album": None, "duration": 0},
        )


class FakeCoverExtractor:
    """假封面提取器：返回预置封面字节，记录调用。"""

    def __init__(self, covers: dict[str, bytes] | None = None) -> None:
        self._covers = covers or {}
        self.call_count: int = 0
        self.extracted_paths: list[str] = []

    def extract(self, path: str, song_id: str, mtime: float) -> str | None:
        self.call_count += 1
        self.extracted_paths.append(path)
        if path in self._covers:
            return f"/fake/covers/{song_id}.jpg"
        return None


class FakeFileStat:
    """假文件 stat：返回预置 mtime / size。"""

    def __init__(self, stats: dict[str, tuple[float, int]]) -> None:
        self._stats = stats

    def stat(self, path: str) -> tuple[float, int]:
        return self._stats.get(path, (1000.0, 1024))


# ---------------------------------------------------------------------------
# 辅助工厂
# ---------------------------------------------------------------------------


def _make_scanner(
    files: list[str],
    metadata: dict[str, dict] | None = None,
    covers: dict[str, bytes] | None = None,
    stats: dict[str, tuple[float, int]] | None = None,
    db_path: str = ":memory:",
) -> tuple[LibraryScanner, FakeFileScanner, FakeMetadataReader, FakeCoverExtractor, FakeFileStat, MusicLibraryDB]:
    """构造带 fake 依赖的 LibraryScanner + 独立 DB。"""
    fs = FakeFileScanner(files)
    mr = FakeMetadataReader(metadata or {})
    ce = FakeCoverExtractor(covers)
    fst = FakeFileStat(stats or {})
    db = MusicLibraryDB(db_path)
    db.init_schema()
    scanner = LibraryScanner(
        root_dir="/fake/music",
        file_scanner=fs,
        metadata_reader=mr,
        cover_extractor=ce,
        file_stat=fst,
        db=db,
    )
    return scanner, fs, mr, ce, fst, db


# ===========================================================================
# scan
# ===========================================================================
class TestScan:
    def test_scan_writes_songs_to_db(self, tmp_path: Path) -> None:
        """扫描后歌曲写入 SQLite。"""
        files = ["/fake/music/a.mp3", "/fake/music/b.mp3"]
        meta = {
            "/fake/music/a.mp3": {"title": "晴天", "artist": "周杰伦", "album": "叶惠美", "duration": 269},
            "/fake/music/b.mp3": {"title": "稻香", "artist": "周杰伦", "album": "魔杰座", "duration": 223},
        }
        scanner, *_ = _make_scanner(files, meta, db_path=str(tmp_path / "lib.db"))
        result = scanner.scan()
        assert result["scanned"] == 2
        assert result["added"] == 2
        all_songs = scanner._db.get_all_songs()
        assert len(all_songs) == 2
        titles = {s["title"] for s in all_songs}
        assert titles == {"晴天", "稻香"}

    def test_scan_extracts_cover(self, tmp_path: Path) -> None:
        """扫描时提取封面图。"""
        files = ["/fake/music/a.mp3"]
        meta = {"/fake/music/a.mp3": {"title": "晴天", "artist": "周杰伦", "duration": 269}}
        covers = {"/fake/music/a.mp3": b"\xff\xd8\xff\xe0fakejpeg"}
        scanner, _, _, ce, _, _ = _make_scanner(
            files, meta, covers, db_path=str(tmp_path / "lib.db")
        )
        scanner.scan()
        assert ce.call_count == 1
        song = scanner._db.get_all_songs()[0]
        assert song["cover_path"] is not None
        assert song["cover_path"].endswith(".jpg")

    def test_scan_reads_lyrics_path(self, tmp_path: Path) -> None:
        """扫描时记录歌词文件路径（元数据提供 lyrics_path）。"""
        files = ["/fake/music/a.mp3"]
        meta = {
            "/fake/music/a.mp3": {
                "title": "晴天",
                "artist": "周杰伦",
                "duration": 269,
                "lyrics_path": "/fake/music/a.lrc",
            }
        }
        scanner, *_ = _make_scanner(files, meta, db_path=str(tmp_path / "lib.db"))
        scanner.scan()
        song = scanner._db.get_all_songs()[0]
        assert song["lyrics_path"] == "/fake/music/a.lrc"

    def test_scan_falls_back_to_filename_when_no_metadata(self, tmp_path: Path) -> None:
        """元数据缺失时用文件名推断 title。"""
        files = ["/fake/music/未知歌曲.mp3"]
        scanner, *_ = _make_scanner(files, {}, db_path=str(tmp_path / "lib.db"))
        scanner.scan()
        song = scanner._db.get_all_songs()[0]
        assert song["title"] == "未知歌曲"
        assert song["artist"] is None

    def test_scan_records_file_mtime_and_size(self, tmp_path: Path) -> None:
        """扫描记录 file_mtime / file_size。"""
        files = ["/fake/music/a.mp3"]
        stats = {"/fake/music/a.mp3": (12345.0, 9999)}
        scanner, *_ = _make_scanner(
            files, stats=stats, db_path=str(tmp_path / "lib.db")
        )
        scanner.scan()
        song = scanner._db.get_all_songs()[0]
        assert song["file_mtime"] == 12345.0
        assert song["file_size"] == 9999

    def test_scan_sets_last_scan_at(self, tmp_path: Path) -> None:
        """扫描后更新 last_scan_at。"""
        files = ["/fake/music/a.mp3"]
        scanner, *_ = _make_scanner(files, db_path=str(tmp_path / "lib.db"))
        before = scanner._db.get_status()["last_scan_at"]
        assert before is None
        scanner.scan()
        after = scanner._db.get_status()["last_scan_at"]
        assert after is not None and after > 0


# ===========================================================================
# 增量扫描
# ===========================================================================
class TestIncrementalScan:
    def test_rescan_same_mtime_skips(self, tmp_path: Path) -> None:
        """同 mtime 重复扫描不重新提取封面（upsert 跳过）。"""
        files = ["/fake/music/a.mp3"]
        meta = {"/fake/music/a.mp3": {"title": "晴天", "duration": 269}}
        covers = {"/fake/music/a.mp3": b"fake"}
        scanner, _, _, ce, _, _ = _make_scanner(
            files, meta, covers, db_path=str(tmp_path / "lib.db")
        )
        scanner.scan()
        assert ce.call_count == 1
        # 重新扫描：mtime 不变，不应重复提取
        scanner.scan()
        assert ce.call_count == 1

    def test_rescan_new_mtime_re_extracts_cover(self, tmp_path: Path) -> None:
        """mtime 变化时重新提取封面。"""
        files = ["/fake/music/a.mp3"]
        meta = {"/fake/music/a.mp3": {"title": "晴天", "duration": 269}}
        covers = {"/fake/music/a.mp3": b"fake"}
        stats = {"/fake/music/a.mp3": (1000.0, 1024)}
        scanner, _, _, ce, fst, _ = _make_scanner(
            files, meta, covers, stats, db_path=str(tmp_path / "lib.db")
        )
        scanner.scan()
        assert ce.call_count == 1
        # mtime 变化
        fst._stats["/fake/music/a.mp3"] = (2000.0, 1024)
        scanner.scan()
        assert ce.call_count == 2

    def test_rescan_new_file_added(self, tmp_path: Path) -> None:
        """第二次扫描新增文件。"""
        fs = FakeFileScanner(["/fake/music/a.mp3"])
        mr = FakeMetadataReader({"/fake/music/a.mp3": {"title": "A", "duration": 100}})
        ce = FakeCoverExtractor()
        fst = FakeFileStat({"/fake/music/a.mp3": (1000.0, 100)})
        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        scanner = LibraryScanner(
            root_dir="/fake/music",
            file_scanner=fs, metadata_reader=mr, cover_extractor=ce, file_stat=fst, db=db,
        )
        scanner.scan()
        assert len(db.get_all_songs()) == 1
        # 新增文件
        fs._files.append("/fake/music/b.mp3")
        mr._meta["/fake/music/b.mp3"] = {"title": "B", "duration": 200}
        fst._stats["/fake/music/b.mp3"] = (1000.0, 200)
        result = scanner.scan()
        assert result["added"] == 1
        assert len(db.get_all_songs()) == 2


# ===========================================================================
# 默认依赖（mutagen 惰性导入）
# ===========================================================================
class TestDefaultDeps:
    def test_default_metadata_reader_uses_mutagen(self, tmp_path: Path) -> None:
        """未注入 metadata_reader 时用内置 mutagen reader（惰性导入）。"""
        scanner = LibraryScanner(root_dir="/fake/music", db=MusicLibraryDB(tmp_path / "lib.db"))
        # 内置 reader 应可调用；mutagen 缺失时返回空元数据（不抛错）
        meta = scanner._read_metadata("/nonexistent.mp3")
        assert "title" in meta
        assert "duration" in meta

    def test_default_cover_extractor(self, tmp_path: Path) -> None:
        """未注入 cover_extractor 时用内置提取器（mutagen 缺失返回 None）。"""
        scanner = LibraryScanner(root_dir="/fake/music", db=MusicLibraryDB(tmp_path / "lib.db"))
        cover = scanner._extract_cover("/nonexistent.mp3", "sid", 1000.0)
        # 文件不存在 / mutagen 缺失均返回 None（不抛错）
        assert cover is None

    def test_default_file_stat(self, tmp_path: Path) -> None:
        """未注入 file_stat 时用 os.stat。"""
        scanner = LibraryScanner(root_dir="/fake/music", db=MusicLibraryDB(tmp_path / "lib.db"))
        # 用本测试文件验证 os.stat 路径
        mtime, size = scanner._stat_file(__file__)
        assert mtime > 0
        assert size > 0


# ===========================================================================
# 扫描结果统计
# ===========================================================================
class TestScanResult:
    def test_scan_result_has_counts(self, tmp_path: Path) -> None:
        """scan 返回 dict 含 scanned / added / updated / skipped。"""
        files = ["/fake/music/a.mp3", "/fake/music/b.mp3"]
        scanner, *_ = _make_scanner(files, db_path=str(tmp_path / "lib.db"))
        result = scanner.scan()
        assert "scanned" in result
        assert "added" in result
        assert "updated" in result
        assert "skipped" in result
        assert result["scanned"] == 2
        assert result["added"] == 2
        assert result["updated"] == 0
        assert result["skipped"] == 0

    def test_scan_result_skipped_on_rescan(self, tmp_path: Path) -> None:
        """重复扫描 skipped 计数。"""
        files = ["/fake/music/a.mp3"]
        scanner, *_ = _make_scanner(files, db_path=str(tmp_path / "lib.db"))
        scanner.scan()
        result = scanner.scan()
        assert result["skipped"] == 1
        assert result["added"] == 0


# ===========================================================================
# 空目录 / 不存在目录
# ===========================================================================
class TestEdgeCases:
    def test_scan_empty_dir(self, tmp_path: Path) -> None:
        """空目录扫描返回零计数。"""
        scanner, *_ = _make_scanner([], db_path=str(tmp_path / "lib.db"))
        result = scanner.scan()
        assert result["scanned"] == 0
        assert result["added"] == 0

    def test_scan_handles_metadata_read_error(self, tmp_path: Path) -> None:
        """metadata_reader 抛异常时跳过该文件不崩。"""
        files = ["/fake/music/a.mp3", "/fake/music/b.mp3"]

        class BrokenReader:
            def __init__(self):
                self.count = 0

            def read(self, path: str) -> dict:
                self.count += 1
                if path == "/fake/music/a.mp3":
                    raise RuntimeError("读取失败")
                return {"title": "B", "duration": 100}

        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        scanner = LibraryScanner(
            root_dir="/fake/music",
            file_scanner=FakeFileScanner(files),
            metadata_reader=BrokenReader(),
            cover_extractor=FakeCoverExtractor(),
            file_stat=FakeFileStat({}),
            db=db,
        )
        result = scanner.scan()
        # a 失败跳过，b 成功
        assert result["scanned"] == 2
        assert result["added"] == 1
        assert result["errors"] == 1


# ===========================================================================
# 内置 _scan_dir（real os.walk 文件系统扫描）
# ===========================================================================
class TestScanDir:
    """内置 _scan_dir 文件系统扫描（覆盖 lines 99-108）。"""

    def test_scan_dir_finds_all_supported_extensions(self, tmp_path: Path) -> None:
        """_scan_dir 递归扫描并按 SUPPORTED_EXTENSIONS 过滤非音频文件。"""
        from omni_music.sources.local import SUPPORTED_EXTENSIONS

        # 创建全部支持的扩展名文件
        for ext in SUPPORTED_EXTENSIONS:
            (tmp_path / f"track{ext}").write_bytes(b"")
        # 创建非音频文件
        (tmp_path / "readme.txt").write_text("x")
        (tmp_path / "cover.jpg").write_bytes(b"")
        (tmp_path / "notes.md").write_text("x")
        (tmp_path / "data.json").write_text("{}")

        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        scanner = LibraryScanner(root_dir=str(tmp_path), db=db)
        files = scanner._scan_dir(str(tmp_path))

        # 全部支持扩展名命中，非音频过滤掉
        assert len(files) == len(SUPPORTED_EXTENSIONS)
        for f in files:
            assert f.lower().endswith(SUPPORTED_EXTENSIONS)
        basenames = {os.path.basename(f) for f in files}
        assert "readme.txt" not in basenames
        assert "cover.jpg" not in basenames
        assert "notes.md" not in basenames

    def test_scan_dir_recursive_traverses_subdirectories(self, tmp_path: Path) -> None:
        """_scan_dir 递归遍历嵌套子目录。"""
        sub = tmp_path / "album1" / "disc2"
        sub.mkdir(parents=True)
        (tmp_path / "top.mp3").write_bytes(b"")
        (tmp_path / "album1" / "middle.flac").write_bytes(b"")
        (sub / "deep.m4a").write_bytes(b"")
        (sub / "lyrics.lrc").write_text("[00:00.00]x")

        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        scanner = LibraryScanner(root_dir=str(tmp_path), db=db)
        files = scanner._scan_dir(str(tmp_path))

        names = {os.path.basename(f) for f in files}
        assert names == {"top.mp3", "middle.flac", "deep.m4a"}
        # .lrc 非音频扩展名，被过滤
        assert "lyrics.lrc" not in names

    def test_scan_dir_nonexistent_root_returns_empty(self, tmp_path: Path) -> None:
        """_scan_dir 对不存在的目录返回空列表（不抛错）。"""
        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        scanner = LibraryScanner(root_dir=str(tmp_path), db=db)
        files = scanner._scan_dir(str(tmp_path / "does" / "not" / "exist"))
        assert files == []

    def test_scan_dir_extension_match_is_case_insensitive(self, tmp_path: Path) -> None:
        """_scan_dir 扩展名匹配大小写不敏感（fname.lower().endswith）。"""
        (tmp_path / "A.MP3").write_bytes(b"")
        (tmp_path / "B.Flac").write_bytes(b"")
        (tmp_path / "C.OGG").write_bytes(b"")

        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        scanner = LibraryScanner(root_dir=str(tmp_path), db=db)
        files = scanner._scan_dir(str(tmp_path))
        assert len(files) == 3


# ===========================================================================
# _read_metadata（mutagen 可用路径，覆盖 lines 127-161）
# ===========================================================================
class TestReadMetadataWithMutagen:
    """_read_metadata 在 mutagen 可用时的元数据提取（覆盖 lines 127-161）。"""

    @pytest.fixture
    def fake_mutagen(self, monkeypatch) -> types.ModuleType:
        """注入 fake mutagen 模块到 sys.modules，测试后自动还原。"""
        module = types.ModuleType("mutagen")
        module.File = lambda path: None  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "mutagen", module)
        return module

    @staticmethod
    def _scanner(tmp_path: Path) -> LibraryScanner:
        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        return LibraryScanner(root_dir="/fake", db=db)

    def test_extracts_title_artist_album_and_duration(self, fake_mutagen, tmp_path):
        """从 mutagen info.length 提取时长，从 tags 提取 title/artist/album。"""
        class FakeInfo:
            length = 269.7
        class FakeAudio:
            info = FakeInfo()
            tags = {"title": ["晴天"], "artist": ["周杰伦"], "album": ["叶惠美"]}

        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]
        meta = self._scanner(tmp_path)._read_metadata("/fake/song.mp3")
        assert meta["title"] == "晴天"
        assert meta["artist"] == "周杰伦"
        assert meta["album"] == "叶惠美"
        assert meta["duration"] == 269  # int(float(269.7))

    def test_extracts_embedded_lyrics_to_embedded_uri(self, fake_mutagen, tmp_path):
        """含 USLT 标签时 lyrics_path 记为 embedded://path 标记。"""
        class FakeAudio:
            info = None
            tags = {"USLT": ["[00:00.00]歌词内容"]}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]
        meta = self._scanner(tmp_path)._read_metadata("/fake/song.mp3")
        assert meta["lyrics_path"] == "embedded:///fake/song.mp3"

    def test_extracts_lyrics_from_vorbis_lyrics_key(self, fake_mutagen, tmp_path):
        """Vorbis LYRICS 标签也能提取为 embedded 歌词。"""
        class FakeAudio:
            info = None
            tags = {"LYRICS": ["歌词"]}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]
        meta = self._scanner(tmp_path)._read_metadata("/fake/song.mp3")
        assert meta["lyrics_path"] == "embedded:///fake/song.mp3"

    def test_extracts_lyrics_from_mp4_lyr_key(self, fake_mutagen, tmp_path):
        """MP4 ©lyr 标签也能提取为 embedded 歌词。"""
        class FakeAudio:
            info = None
            tags = {"\xa9lyr": ["MP4歌词"]}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]
        meta = self._scanner(tmp_path)._read_metadata("/fake/song.mp3")
        assert meta["lyrics_path"] == "embedded:///fake/song.mp3"

    def test_returns_empty_when_mutagen_file_returns_none(self, fake_mutagen, tmp_path):
        """mutagen.File 返回 None（不支持的格式）时返回空元数据。"""
        fake_mutagen.File = lambda path: None  # type: ignore[attr-defined]
        meta = self._scanner(tmp_path)._read_metadata("/fake/song.mp3")
        assert meta == {
            "title": None, "artist": None, "album": None,
            "duration": 0, "lyrics_path": None,
        }

    def test_returns_empty_on_mutagen_file_exception(self, fake_mutagen, tmp_path):
        """mutagen.File 抛异常（文件损坏）时降级返回空元数据。"""
        def raise_runtime(path):
            raise RuntimeError("corrupt file")
        fake_mutagen.File = raise_runtime  # type: ignore[attr-defined]
        meta = self._scanner(tmp_path)._read_metadata("/fake/song.mp3")
        assert meta["title"] is None
        assert meta["duration"] == 0
        assert meta["lyrics_path"] is None

    def test_handles_id3v2_key_names(self, fake_mutagen, tmp_path):
        """支持 ID3v2 键名 TIT2/TPE1/TALB。"""
        class FakeAudio:
            info = type("I", (), {"length": 100.0})()
            tags = {"TIT2": ["ID3标题"], "TPE1": ["ID3艺术家"], "TALB": ["ID3专辑"]}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]
        meta = self._scanner(tmp_path)._read_metadata("/fake/song.mp3")
        assert meta["title"] == "ID3标题"
        assert meta["artist"] == "ID3艺术家"
        assert meta["album"] == "ID3专辑"

    def test_handles_mp4_key_names(self, fake_mutagen, tmp_path):
        """支持 MP4 键名 ©nam/©ART/©alb。"""
        class FakeAudio:
            info = type("I", (), {"length": 200.0})()
            tags = {
                "\xa9nam": ["MP4标题"],
                "\xa9ART": ["MP4艺术家"],
                "\xa9alb": ["MP4专辑"],
            }
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]
        meta = self._scanner(tmp_path)._read_metadata("/fake/song.mp3")
        assert meta["title"] == "MP4标题"
        assert meta["artist"] == "MP4艺术家"
        assert meta["album"] == "MP4专辑"

    def test_handles_scalar_tag_values(self, fake_mutagen, tmp_path):
        """标签值为标量字符串（非 list）时也能提取。"""
        class FakeAudio:
            info = type("I", (), {"length": 50.0})()
            tags = {"title": "标量标题", "artist": "标量艺术家"}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]
        meta = self._scanner(tmp_path)._read_metadata("/fake/song.mp3")
        assert meta["title"] == "标量标题"
        assert meta["artist"] == "标量艺术家"

    def test_skips_empty_list_tag_value(self, fake_mutagen, tmp_path):
        """标签值为空 list 时跳过该键，返回 None。"""
        class FakeAudio:
            info = type("I", (), {"length": 0.0})()
            tags = {"title": []}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]
        meta = self._scanner(tmp_path)._read_metadata("/fake/song.mp3")
        assert meta["title"] is None

    def test_invalid_duration_string_falls_back_to_zero(self, fake_mutagen, tmp_path):
        """info.length 为非数字字符串时 float() 抛 ValueError，duration 降级为 0。"""
        class FakeInfo:
            length = "not-a-number"
        class FakeAudio:
            info = FakeInfo()
            tags = {}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]
        meta = self._scanner(tmp_path)._read_metadata("/fake/song.mp3")
        assert meta["duration"] == 0

    def test_none_info_yields_zero_duration(self, fake_mutagen, tmp_path):
        """audio.info 为 None 时跳过时长提取，duration 保持 0。"""
        class FakeAudio:
            info = None
            tags = {"title": ["x"]}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]
        meta = self._scanner(tmp_path)._read_metadata("/fake/song.mp3")
        assert meta["duration"] == 0
        assert meta["title"] == "x"

    def test_first_key_match_wins(self, fake_mutagen, tmp_path):
        """多个候选键同时存在时，按 _first 的候选顺序取首个非空。"""
        class FakeAudio:
            info = None
            tags = {"title": ["Vorbis标题"], "TIT2": ["ID3标题"]}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]
        meta = self._scanner(tmp_path)._read_metadata("/fake/song.mp3")
        # 候选顺序 ("title", "TIT2", ...) → title 先命中
        assert meta["title"] == "Vorbis标题"


# ===========================================================================
# _extract_cover（mutagen 可用路径 + mtime 缓存，覆盖 lines 179-225）
# ===========================================================================
class TestExtractCover:
    """_extract_cover 封面提取（fake mutagen + real fs，覆盖 lines 179-225）。"""

    @pytest.fixture
    def fake_mutagen(self, monkeypatch) -> types.ModuleType:
        """注入 fake mutagen 模块。"""
        module = types.ModuleType("mutagen")
        module.File = lambda path: None  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "mutagen", module)
        return module

    @staticmethod
    def _scanner(tmp_path: Path, covers_dir: Path) -> LibraryScanner:
        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        return LibraryScanner(root_dir="/fake", db=db, covers_dir=covers_dir)

    def test_extracts_apic_bytes_and_writes_jpg(self, fake_mutagen, tmp_path):
        """从 ID3 APIC: 标签提取 bytes 封面，写入 covers_dir/<song_id>.jpg。"""
        cover_data = b"\xff\xd8\xff\xe0fakejpeg"
        class FakeAudio:
            tags = {"APIC:": cover_data}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]

        covers_dir = tmp_path / "covers"
        scanner = self._scanner(tmp_path, covers_dir)
        result = scanner._extract_cover("/fake/song.mp3", "sid1", 1000.0)

        assert result is not None
        assert result.endswith("sid1.jpg")
        assert (covers_dir / "sid1.jpg").read_bytes() == cover_data
        # mtime 标记文件正确写入
        assert (covers_dir / "sid1.mtime").read_text(encoding="utf-8").strip() == "1000.0"

    def test_skips_extraction_when_mtime_matches(self, fake_mutagen, tmp_path):
        """封面已存在且 mtime 标记匹配时直接返回旧路径，不调用 mutagen。"""
        covers_dir = tmp_path / "covers"
        covers_dir.mkdir(parents=True)
        existing = b"existing jpeg"
        (covers_dir / "sid.jpg").write_bytes(existing)
        (covers_dir / "sid.mtime").write_text("1000.0", encoding="utf-8")

        call_count = [0]
        def fail_if_called(path):
            call_count[0] += 1
            raise AssertionError("mutagen.File 不应被调用")
        fake_mutagen.File = fail_if_called  # type: ignore[attr-defined]

        scanner = self._scanner(tmp_path, covers_dir)
        result = scanner._extract_cover("/fake/song.mp3", "sid", 1000.0)

        assert result == str(covers_dir / "sid.jpg")
        assert call_count[0] == 0
        # 旧封面未被覆盖
        assert (covers_dir / "sid.jpg").read_bytes() == existing

    def test_re_extracts_when_mtime_changed(self, fake_mutagen, tmp_path):
        """mtime 变化时重新提取封面，覆盖旧文件 + 更新标记。"""
        covers_dir = tmp_path / "covers"
        covers_dir.mkdir(parents=True)
        (covers_dir / "sid.jpg").write_bytes(b"old cover")
        (covers_dir / "sid.mtime").write_text("1000.0", encoding="utf-8")

        new_cover = b"new cover data"
        class FakeAudio:
            tags = {"APIC:": new_cover}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]

        scanner = self._scanner(tmp_path, covers_dir)
        result = scanner._extract_cover("/fake/song.mp3", "sid", 2000.0)

        assert result is not None
        assert (covers_dir / "sid.jpg").read_bytes() == new_cover
        assert (covers_dir / "sid.mtime").read_text(encoding="utf-8").strip() == "2000.0"

    def test_re_extracts_when_mtime_marker_corrupted(self, fake_mutagen, tmp_path):
        """mtime 标记文件内容非数字（float 抛 ValueError）时重新提取。"""
        covers_dir = tmp_path / "covers"
        covers_dir.mkdir(parents=True)
        (covers_dir / "sid.jpg").write_bytes(b"old")
        (covers_dir / "sid.mtime").write_text("corrupted", encoding="utf-8")

        new_cover = b"new cover"
        class FakeAudio:
            tags = {"APIC:": new_cover}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]

        scanner = self._scanner(tmp_path, covers_dir)
        result = scanner._extract_cover("/fake/song.mp3", "sid", 2000.0)

        assert result is not None
        assert (covers_dir / "sid.jpg").read_bytes() == new_cover
        assert (covers_dir / "sid.mtime").read_text(encoding="utf-8").strip() == "2000.0"

    def test_extracts_from_apic_list_picks_first_valid(self, fake_mutagen, tmp_path):
        """APIC 标签值为 list 时遍历，跳过无效项取首个有效封面。"""
        class FakeAPIC:
            def __init__(self, data: bytes | None) -> None:
                self.data = data
        cover_data = b"\xff\xd8fake"
        class FakeAudio:
            tags = {"APIC:": [FakeAPIC(None), FakeAPIC(cover_data), FakeAPIC(b"unused")]}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]

        covers_dir = tmp_path / "covers"
        scanner = self._scanner(tmp_path, covers_dir)
        result = scanner._extract_cover("/fake/song.mp3", "sid", 1000.0)

        assert result is not None
        assert (covers_dir / "sid.jpg").read_bytes() == cover_data

    def test_extracts_from_mp4_covr_tag(self, fake_mutagen, tmp_path):
        """从 MP4 covr 标签提取封面。"""
        cover_data = b"mp4cover"
        class FakeAudio:
            tags = {"covr": cover_data}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]

        covers_dir = tmp_path / "covers"
        scanner = self._scanner(tmp_path, covers_dir)
        result = scanner._extract_cover("/fake/song.mp3", "sid", 1000.0)

        assert result is not None
        assert (covers_dir / "sid.jpg").read_bytes() == cover_data

    def test_extracts_from_flac_pictures_attribute(self, fake_mutagen, tmp_path):
        """无 APIC/covr 标签时从 audio.pictures 列表属性提取封面（FLAC 路径）。

        mutagen FLAC 对象的 pictures 是 list 属性（非方法），代码用
        ``getattr(audio, "pictures")`` 直接取属性迭代。
        """
        cover_data = b"flaccover"
        class FakePic:
            data = cover_data
        class FakeAudio:
            tags = []
            pictures = [FakePic()]  # list 属性，模拟 mutagen FLAC
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]

        covers_dir = tmp_path / "covers"
        scanner = self._scanner(tmp_path, covers_dir)
        result = scanner._extract_cover("/fake/song.mp3", "sid", 1000.0)

        assert result is not None
        assert (covers_dir / "sid.jpg").read_bytes() == cover_data

    def test_returns_none_when_no_cover_anywhere(self, fake_mutagen, tmp_path):
        """无 APIC/covr 标签且 pictures 属性为空列表时返回 None。"""
        class FakeAudio:
            tags = {}
            pictures = []  # 空列表属性
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]

        scanner = self._scanner(tmp_path, tmp_path / "covers")
        result = scanner._extract_cover("/fake/song.mp3", "sid", 1000.0)
        assert result is None

    def test_returns_none_when_mutagen_file_raises(self, fake_mutagen, tmp_path):
        """mutagen.File 抛异常时返回 None。"""
        def raise_runtime(path):
            raise RuntimeError("read fail")
        fake_mutagen.File = raise_runtime  # type: ignore[attr-defined]

        scanner = self._scanner(tmp_path, tmp_path / "covers")
        result = scanner._extract_cover("/fake/song.mp3", "sid", 1000.0)
        assert result is None

    def test_returns_none_when_audio_is_none(self, fake_mutagen, tmp_path):
        """mutagen.File 返回 None 时返回 None。"""
        fake_mutagen.File = lambda path: None  # type: ignore[attr-defined]

        scanner = self._scanner(tmp_path, tmp_path / "covers")
        result = scanner._extract_cover("/fake/song.mp3", "sid", 1000.0)
        assert result is None

    def test_returns_none_on_write_oserror(self, fake_mutagen, tmp_path):
        """写封面时 OSError（covers_dir 路径是文件而非目录）返回 None。"""
        cover_data = b"cover"
        class FakeAudio:
            tags = {"APIC:": cover_data}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]

        # covers_dir 创建为文件（非目录），mkdir(exist_ok=True) 会抛 FileExistsError
        covers_dir = tmp_path / "covers"
        covers_dir.write_text("not a dir")

        scanner = self._scanner(tmp_path, covers_dir)
        result = scanner._extract_cover("/fake/song.mp3", "sid", 1000.0)
        assert result is None

    def test_apic_key_without_colon_also_works(self, fake_mutagen, tmp_path):
        """APIC（无冒号）键名也能命中封面提取。"""
        cover_data = b"cover"
        class FakeAudio:
            tags = {"APIC": cover_data}
        fake_mutagen.File = lambda path: FakeAudio()  # type: ignore[attr-defined]

        covers_dir = tmp_path / "covers"
        scanner = self._scanner(tmp_path, covers_dir)
        result = scanner._extract_cover("/fake/song.mp3", "sid", 1000.0)

        assert result is not None
        assert (covers_dir / "sid.jpg").read_bytes() == cover_data


# ===========================================================================
# _stat_file（OSError 路径，覆盖 lines 232-233）
# ===========================================================================
class TestStatFile:
    """_stat_file 文件 stat 读取（覆盖 lines 232-233 OSError 降级）。"""

    def test_returns_zero_tuple_for_nonexistent_path(self, tmp_path: Path) -> None:
        """os.stat 对不存在的路径抛 FileNotFoundError（OSError 子类），降级返回 (0.0, 0)。"""
        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        scanner = LibraryScanner(root_dir="/fake", db=db)
        mtime, size = scanner._stat_file(str(tmp_path / "nonexistent_file"))
        assert mtime == 0.0
        assert size == 0

    def test_returns_real_stat_for_existing_file(self, tmp_path: Path) -> None:
        """存在的文件返回真实 mtime / size。"""
        f = tmp_path / "real.mp3"
        f.write_bytes(b"hello world")
        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        scanner = LibraryScanner(root_dir="/fake", db=db)
        mtime, size = scanner._stat_file(str(f))
        assert mtime > 0
        assert size == 11


# ===========================================================================
# _extract_bytes 模块级辅助函数（覆盖 lines 314-320）
# ===========================================================================
class TestExtractBytes:
    """_extract_bytes 从 mutagen 标签值提取封面字节（覆盖 lines 314-320）。"""

    def test_bytes_input_returned_as_bytes(self) -> None:
        """bytes 输入直接返回。"""
        assert _extract_bytes(b"\xff\xd8\xff\xe0") == b"\xff\xd8\xff\xe0"

    def test_bytearray_input_converted_to_bytes(self) -> None:
        """bytearray 输入转为 bytes 返回。"""
        result = _extract_bytes(bytearray(b"abc"))
        assert result == b"abc"
        assert isinstance(result, bytes)

    def test_object_with_bytes_data_attribute(self) -> None:
        """带 .data 属性（bytes）的对象提取 data。"""
        class FakeAPIC:
            data = b"coverdata"
        assert _extract_bytes(FakeAPIC()) == b"coverdata"

    def test_object_with_bytearray_data_attribute(self) -> None:
        """带 .data 属性（bytearray）的对象转为 bytes 返回。"""
        class FakeObj:
            data = bytearray(b"xy")
        result = _extract_bytes(FakeObj())
        assert result == b"xy"
        assert isinstance(result, bytes)

    def test_object_without_data_attribute_returns_none(self) -> None:
        """无 .data 属性的对象返回 None。"""
        class NoData:
            pass
        assert _extract_bytes(NoData()) is None

    def test_object_with_none_data_returns_none(self) -> None:
        """ .data 为 None 时返回 None。"""
        class FakeObj:
            data = None
        assert _extract_bytes(FakeObj()) is None

    def test_string_input_returns_none(self) -> None:
        """字符串（非 bytes）且无 .data 返回 None。"""
        assert _extract_bytes("not bytes") is None

    def test_integer_input_returns_none(self) -> None:
        """整数（非 bytes）且无 .data 返回 None。"""
        assert _extract_bytes(42) is None


# ===========================================================================
# scan() 默认依赖集成（覆盖 lines 247 / 260 / 271 / 277）
# ===========================================================================
class TestScanWithDefaultDeps:
    """scan() 无注入依赖时走内置默认实现（覆盖 lines 247 / 260 / 271 / 277）。"""

    def test_scan_uses_builtin_scan_dir_and_os_stat(self, tmp_path: Path) -> None:
        """无 file_scanner / file_stat 注入时走 _scan_dir + os.stat 真实路径。

        mutagen 缺失，_read_metadata 降级返回空元数据，title 用文件名推断。
        """
        (tmp_path / "track1.mp3").write_bytes(b"")
        (tmp_path / "track2.flac").write_bytes(b"")

        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        scanner = LibraryScanner(
            root_dir=str(tmp_path),
            db=db,
            covers_dir=tmp_path / "covers",
        )
        result = scanner.scan()

        assert result["scanned"] == 2
        assert result["added"] == 2
        assert result["errors"] == 0
        songs = db.get_all_songs()
        assert len(songs) == 2
        # mutagen 缺失 → title 兜底为文件名去扩展名
        titles = {s["title"] for s in songs}
        assert titles == {"track1", "track2"}
        # file_mtime / file_size 来自 os.stat（真实空文件）
        for s in songs:
            assert s["file_mtime"] > 0
            assert s["file_size"] == 0
            # 无 mutagen → 无封面
            assert s["cover_path"] is None

    def test_scan_uses_builtin_metadata_and_cover_with_mutagen(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """无 metadata_reader / cover_extractor 注入且 mutagen 可用时走内置读取 + 提取。"""
        cover_data = b"\xff\xd8\xff\xe0fakejpeg"
        class FakeInfo:
            length = 200.0
        class FakeAudio:
            info = FakeInfo()
            tags = {
                "title": ["标题"],
                "artist": ["艺术家"],
                "album": ["专辑"],
                "APIC:": cover_data,
            }
        module = types.ModuleType("mutagen")
        module.File = lambda path: FakeAudio()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "mutagen", module)

        (tmp_path / "song.mp3").write_bytes(b"")

        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        covers_dir = tmp_path / "covers"
        scanner = LibraryScanner(
            root_dir=str(tmp_path),
            db=db,
            covers_dir=covers_dir,
        )
        result = scanner.scan()

        assert result["added"] == 1
        song = db.get_all_songs()[0]
        assert song["title"] == "标题"
        assert song["artist"] == "艺术家"
        assert song["album"] == "专辑"
        assert song["duration_s"] == 200
        assert song["cover_path"] is not None
        # 封面文件实际写入磁盘
        assert (covers_dir / f"{song['id']}.jpg").read_bytes() == cover_data

    def test_scan_default_deps_filters_unsupported_files(self, tmp_path: Path) -> None:
        """默认 _scan_dir 过滤非音频文件（不写入 DB）。"""
        (tmp_path / "a.mp3").write_bytes(b"")
        (tmp_path / "readme.txt").write_text("x")
        (tmp_path / "cover.jpg").write_bytes(b"")

        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        scanner = LibraryScanner(
            root_dir=str(tmp_path),
            db=db,
            covers_dir=tmp_path / "covers",
        )
        result = scanner.scan()
        assert result["scanned"] == 1
        assert result["added"] == 1
        assert len(db.get_all_songs()) == 1

    def test_scan_default_deps_records_updated_count_on_mtime_change(
        self, tmp_path: Path
    ) -> None:
        """默认依赖下重扫 + mtime 变化时 updated 计数 +1。"""
        f = tmp_path / "a.mp3"
        f.write_bytes(b"original")

        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        scanner = LibraryScanner(
            root_dir=str(tmp_path),
            db=db,
            covers_dir=tmp_path / "covers",
        )
        first = scanner.scan()
        assert first["added"] == 1
        assert first["updated"] == 0

        # 修改文件 → mtime 变化
        time.sleep(0.05)
        f.write_bytes(b"changed content")
        second = scanner.scan()
        assert second["added"] == 0
        assert second["updated"] == 1
        assert second["skipped"] == 0
        # DB 中 file_size 更新
        song = db.get_all_songs()[0]
        assert song["file_size"] == len(b"changed content")
