"""omni_music library.db SQLite 音乐库索引测试（M19.2）。

TDD 测试先行：覆盖 MusicLibraryDB 的全部方法。
全部用 ``:memory:`` 或 ``tmp_path`` 数据库，不污染用户家目录（~/.ai-omni/music/library.db）。
FTS5 全文搜索、歌单管理、播放历史、上下文管理器协议、增量 upsert（按 path + mtime）。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from omni_music.library.db import MusicLibraryDB


def _song(
    path: str = "/music/a.mp3",
    title: str = "晴天",
    artist: str = "周杰伦",
    album: str = "叶惠美",
    duration_s: int = 269,
    mtime: float = 1000.0,
    size: int = 1024,
    source: str = "local",
    cover: str | None = None,
    lyrics: str | None = None,
) -> dict:
    """构造一份测试用 song_data dict。"""
    return {
        "path": path,
        "title": title,
        "artist": artist,
        "album": album,
        "duration_s": duration_s,
        "cover_path": cover,
        "lyrics_path": lyrics,
        "source": source,
        "file_mtime": mtime,
        "file_size": size,
    }


# ===========================================================================
# schema 初始化
# ===========================================================================
class TestInitSchema:
    def test_init_schema_creates_tables(self, tmp_path: Path) -> None:
        """init_schema 后 songs/playlists/playlist_songs/play_history 表存在。"""
        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        rows = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r[0] for r in rows}
        assert "songs" in names
        assert "playlists" in names
        assert "playlist_songs" in names
        assert "play_history" in names
        db.close()

    def test_init_schema_creates_fts5(self, tmp_path: Path) -> None:
        """init_schema 后 songs_fts FTS5 虚拟表存在。"""
        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        rows = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='songs_fts'"
        ).fetchall()
        assert len(rows) == 1
        db.close()

    def test_init_schema_idempotent(self, tmp_path: Path) -> None:
        """init_schema 可重复调用不报错（IF NOT EXISTS）。"""
        db = MusicLibraryDB(tmp_path / "lib.db")
        db.init_schema()
        db.init_schema()
        db.close()


# ===========================================================================
# upsert_song
# ===========================================================================
class TestUpsertSong:
    def test_upsert_inserts_new_song(self, tmp_path: Path) -> None:
        """首次 upsert 插入新歌，返回 song_id。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            sid = db.upsert_song(_song(path="/music/a.mp3"))
            assert isinstance(sid, str) and len(sid) > 0
            got = db.get_song(sid)
            assert got is not None
            assert got["title"] == "晴天"
            assert got["path"] == "/music/a.mp3"

    def test_upsert_same_path_same_mtime_no_update(self, tmp_path: Path) -> None:
        """同 path 同 mtime 重复 upsert 不更新（added_at 不变）。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            sid1 = db.upsert_song(_song(path="/music/a.mp3", mtime=1000.0))
            row1 = db.get_song(sid1)
            sid2 = db.upsert_song(_song(path="/music/a.mp3", mtime=1000.0))
            assert sid1 == sid2
            row2 = db.get_song(sid2)
            assert row1["added_at"] == row2["added_at"]

    def test_upsert_same_path_new_mtime_updates(self, tmp_path: Path) -> None:
        """同 path 但 mtime 变化时更新元数据。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            sid = db.upsert_song(
                _song(path="/music/a.mp3", title="旧标题", mtime=1000.0)
            )
            sid2 = db.upsert_song(
                _song(path="/music/a.mp3", title="新标题", mtime=2000.0)
            )
            assert sid == sid2
            got = db.get_song(sid)
            assert got["title"] == "新标题"
            assert got["file_mtime"] == 2000.0

    def test_upsert_different_paths_different_ids(self, tmp_path: Path) -> None:
        """不同 path 生成不同 song_id。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            sid1 = db.upsert_song(_song(path="/music/a.mp3"))
            sid2 = db.upsert_song(_song(path="/music/b.mp3"))
            assert sid1 != sid2

    def test_upsert_fts_synced(self, tmp_path: Path) -> None:
        """upsert 后 FTS 表可搜到 title。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            db.upsert_song(_song(path="/music/a.mp3", title="七里香"))
            results = db.search("七里香")
            assert len(results) == 1
            assert results[0]["title"] == "七里香"


# ===========================================================================
# remove_song
# ===========================================================================
class TestRemoveSong:
    def test_remove_song_returns_true(self, tmp_path: Path) -> None:
        """删除已存在歌曲返回 True。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            sid = db.upsert_song(_song(path="/music/a.mp3"))
            assert db.remove_song(sid) is True
            assert db.get_song(sid) is None

    def test_remove_nonexistent_returns_false(self, tmp_path: Path) -> None:
        """删除不存在歌曲返回 False。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            assert db.remove_song("nonexistent_id") is False

    def test_remove_song_cleans_fts(self, tmp_path: Path) -> None:
        """删除歌曲后 FTS 也搜不到。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            sid = db.upsert_song(_song(path="/music/a.mp3", title="晴天"))
            db.remove_song(sid)
            assert db.search("晴天") == []

    def test_remove_song_cleans_playlist_entries(self, tmp_path: Path) -> None:
        """删除歌曲后歌单中的关联记录也清除（级联）。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            sid = db.upsert_song(_song(path="/music/a.mp3"))
            pid = db.create_playlist("my")
            db.add_to_playlist(pid, sid)
            db.remove_song(sid)
            assert db.get_playlist_songs(pid) == []


# ===========================================================================
# search (FTS5)
# ===========================================================================
class TestSearch:
    def test_search_by_title(self, tmp_path: Path) -> None:
        """按标题搜索。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            db.upsert_song(_song(path="/a.mp3", title="晴天", artist="周杰伦"))
            db.upsert_song(_song(path="/b.mp3", title="稻香", artist="周杰伦"))
            results = db.search("晴天")
            assert len(results) == 1
            assert results[0]["title"] == "晴天"

    def test_search_by_artist(self, tmp_path: Path) -> None:
        """按艺术家搜索（FTS 覆盖 artist 列）。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            db.upsert_song(_song(path="/a.mp3", title="晴天", artist="周杰伦"))
            db.upsert_song(_song(path="/b.mp3", title="稻香", artist="周杰伦"))
            db.upsert_song(_song(path="/c.mp3", title="七里香", artist="费玉清"))
            results = db.search("周杰伦")
            assert len(results) == 2

    def test_search_by_album(self, tmp_path: Path) -> None:
        """按专辑搜索。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            db.upsert_song(_song(path="/a.mp3", title="晴天", album="叶惠美"))
            db.upsert_song(_song(path="/b.mp3", title="稻香", album="魔杰座"))
            results = db.search("叶惠美")
            assert len(results) == 1

    def test_search_limit(self, tmp_path: Path) -> None:
        """limit 截断结果。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            for i in range(5):
                db.upsert_song(
                    _song(path=f"/a{i}.mp3", title=f"晴天{i}", artist="周杰伦")
                )
            results = db.search("周杰伦", limit=3)
            assert len(results) == 3

    def test_search_no_match_returns_empty(self, tmp_path: Path) -> None:
        """无匹配返回空列表。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            db.upsert_song(_song(path="/a.mp3", title="晴天"))
            assert db.search("不存在的歌") == []

    def test_search_empty_query_returns_all(self, tmp_path: Path) -> None:
        """空 query 返回全部（受 limit 截断）。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            db.upsert_song(_song(path="/a.mp3", title="晴天"))
            db.upsert_song(_song(path="/b.mp3", title="稻香"))
            results = db.search("", limit=10)
            assert len(results) == 2


# ===========================================================================
# get_song / get_all_songs
# ===========================================================================
class TestGetSongs:
    def test_get_song_returns_dict(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            sid = db.upsert_song(_song(path="/a.mp3", title="晴天"))
            got = db.get_song(sid)
            assert got is not None
            assert got["id"] == sid
            assert got["title"] == "晴天"
            assert got["path"] == "/a.mp3"

    def test_get_song_nonexistent_returns_none(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            assert db.get_song("nope") is None

    def test_get_all_songs(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            db.upsert_song(_song(path="/a.mp3", title="晴天"))
            db.upsert_song(_song(path="/b.mp3", title="稻香"))
            all_songs = db.get_all_songs()
            assert len(all_songs) == 2
            titles = {s["title"] for s in all_songs}
            assert titles == {"晴天", "稻香"}

    def test_get_all_songs_empty(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            assert db.get_all_songs() == []


# ===========================================================================
# 播放列表
# ===========================================================================
class TestPlaylist:
    def test_create_playlist_returns_id(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            pid = db.create_playlist("我的歌单")
            assert isinstance(pid, int) and pid > 0

    def test_create_playlist_different_names_different_ids(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            p1 = db.create_playlist("a")
            p2 = db.create_playlist("b")
            assert p1 != p2

    def test_add_to_playlist(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            sid = db.upsert_song(_song(path="/a.mp3"))
            pid = db.create_playlist("my")
            db.add_to_playlist(pid, sid)
            songs = db.get_playlist_songs(pid)
            assert len(songs) == 1
            assert songs[0]["id"] == sid

    def test_add_to_playlist_with_position(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            s1 = db.upsert_song(_song(path="/a.mp3", title="A"))
            s2 = db.upsert_song(_song(path="/b.mp3", title="B"))
            pid = db.create_playlist("my")
            db.add_to_playlist(pid, s1)
            db.add_to_playlist(pid, s2, position=0)
            songs = db.get_playlist_songs(pid)
            assert songs[0]["id"] == s2
            assert songs[1]["id"] == s1

    def test_add_to_playlist_duplicate_song_idempotent(self, tmp_path: Path) -> None:
        """同首歌重复加入歌单不重复（按 song_id 去重）。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            sid = db.upsert_song(_song(path="/a.mp3"))
            pid = db.create_playlist("my")
            db.add_to_playlist(pid, sid)
            db.add_to_playlist(pid, sid)
            assert len(db.get_playlist_songs(pid)) == 1

    def test_remove_from_playlist(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            s1 = db.upsert_song(_song(path="/a.mp3"))
            s2 = db.upsert_song(_song(path="/b.mp3"))
            pid = db.create_playlist("my")
            db.add_to_playlist(pid, s1)
            db.add_to_playlist(pid, s2)
            db.remove_from_playlist(pid, s1)
            songs = db.get_playlist_songs(pid)
            assert len(songs) == 1
            assert songs[0]["id"] == s2

    def test_remove_from_playlist_nonexistent_idempotent(self, tmp_path: Path) -> None:
        """从歌单移除不存在的歌曲静默成功。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            pid = db.create_playlist("my")
            db.remove_from_playlist(pid, "nope")  # 不报错

    def test_get_playlist_songs_empty(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            pid = db.create_playlist("my")
            assert db.get_playlist_songs(pid) == []

    def test_get_playlist_songs_ordered_by_position(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            s1 = db.upsert_song(_song(path="/a.mp3", title="A"))
            s2 = db.upsert_song(_song(path="/b.mp3", title="B"))
            s3 = db.upsert_song(_song(path="/c.mp3", title="C"))
            pid = db.create_playlist("my")
            db.add_to_playlist(pid, s3)
            db.add_to_playlist(pid, s1, position=0)
            db.add_to_playlist(pid, s2, position=1)
            songs = db.get_playlist_songs(pid)
            assert [s["id"] for s in songs] == [s1, s2, s3]


# ===========================================================================
# 播放历史
# ===========================================================================
class TestHistory:
    def test_add_to_history(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            sid = db.upsert_song(_song(path="/a.mp3"))
            db.add_to_history(sid)
            hist = db.get_history()
            assert len(hist) == 1
            assert hist[0]["song_id"] == sid

    def test_get_history_limit(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            for i in range(5):
                sid = db.upsert_song(_song(path=f"/a{i}.mp3", title=f"T{i}"))
                db.add_to_history(sid)
            assert len(db.get_history(limit=3)) == 3

    def test_get_history_ordered_recent_first(self, tmp_path: Path) -> None:
        """历史按时间倒序（最近优先）。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            s1 = db.upsert_song(_song(path="/a.mp3", title="A"))
            s2 = db.upsert_song(_song(path="/b.mp3", title="B"))
            db.add_to_history(s1)
            time.sleep(0.01)
            db.add_to_history(s2)
            hist = db.get_history()
            assert hist[0]["song_id"] == s2
            assert hist[1]["song_id"] == s1

    def test_get_history_empty(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            assert db.get_history() == []


# ===========================================================================
# 上下文管理器 + 环境变量
# ===========================================================================
class TestContextManager:
    def test_context_manager_commits_and_closes(self, tmp_path: Path) -> None:
        """with 块退出后数据已 commit，可重新打开读到。"""
        path = tmp_path / "lib.db"
        with MusicLibraryDB(path) as db:
            db.init_schema()
            db.upsert_song(_song(path="/a.mp3", title="晴天"))
        # 重新打开，数据应持久化
        with MusicLibraryDB(path) as db2:
            db2.init_schema()
            results = db2.search("晴天")
            assert len(results) == 1

    def test_context_manager_auto_init_schema(self, tmp_path: Path) -> None:
        """with 进入时自动 init_schema，无需显式调用。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            # 不调 init_schema 也能 upsert
            sid = db.upsert_song(_song(path="/a.mp3"))
            assert db.get_song(sid) is not None


class TestEnvOverride:
    def test_env_overrides_db_path(self, tmp_path: Path, monkeypatch) -> None:
        """env AI_OMNI_MUSIC_DB 覆盖默认路径。"""
        custom = tmp_path / "custom" / "lib.db"
        monkeypatch.setenv("AI_OMNI_MUSIC_DB", str(custom))
        db = MusicLibraryDB.from_env()
        assert str(db.db_path) == str(custom)
        db.close()

    def test_from_env_default_when_unset(self, tmp_path: Path, monkeypatch) -> None:
        """env 未设置时用默认 ~/.ai-omni/music/library.db。"""
        monkeypatch.delenv("AI_OMNI_MUSIC_DB", raising=False)
        db = MusicLibraryDB.from_env()
        assert "music" in str(db.db_path)
        assert str(db.db_path).endswith("library.db")
        db.close()


# ===========================================================================
# 库状态
# ===========================================================================
class TestLibraryStatus:
    def test_get_status_empty(self, tmp_path: Path) -> None:
        """空库 status 返回 song_count=0。"""
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            status = db.get_status()
            assert status["song_count"] == 0
            assert status["playlist_count"] == 0
            assert "last_scan_at" in status

    def test_get_status_with_data(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            db.upsert_song(_song(path="/a.mp3"))
            db.upsert_song(_song(path="/b.mp3"))
            db.create_playlist("my")
            status = db.get_status()
            assert status["song_count"] == 2
            assert status["playlist_count"] == 1

    def test_set_last_scan_at(self, tmp_path: Path) -> None:
        with MusicLibraryDB(tmp_path / "lib.db") as db:
            db.init_schema()
            db.set_last_scan_at(12345.0)
            status = db.get_status()
            assert status["last_scan_at"] == 12345.0
