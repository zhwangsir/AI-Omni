"""omni_music 本地音乐库 SQLite 索引（M19.2）。

使用 Python 标准库 ``sqlite3``（无需额外依赖）+ FTS5 全文搜索。

表结构：

- ``songs``           ：id(PK) / path / title / artist / album / duration_s /
                       cover_path / lyrics_path / source / file_mtime /
                       file_size / added_at
- ``playlists``       ：id(PK) / name / created_at / updated_at
- ``playlist_songs``  ：playlist_id / song_id / position（联合主键）
- ``play_history``    ：id(PK) / song_id / played_at
- ``songs_fts``       ：FTS5 虚拟表（title / artist / album），经触发器与 songs 同步
- ``library_meta``    ：key(PK) / value，存 last_scan_at 等元信息

上下文管理器协议（``with MusicLibraryDB(path) as db:``）自动 init_schema +
commit + close。``upsert_song`` 按 path 去重，file_mtime 变化时更新。

测试用 ``:memory:`` 或 ``tmp_path`` 数据库，不污染用户家目录。
默认路径 ``~/.ai-omni/music/library.db``，env ``AI_OMNI_MUSIC_DB`` 可覆盖。

合规说明（D19.1）：本模块仅管理用户自有本地音乐元数据索引，不涉及任何破解。
仅个人学习用途。
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

__all__ = ["MusicLibraryDB", "default_db_path"]


def default_db_path() -> Path:
    """取默认数据库路径 ``~/.ai-omni/music/library.db``。

    :return: ``Path.home() / ".ai-omni" / "music" / "library.db"``
    """
    return Path.home() / ".ai-omni" / "music" / "library.db"


class MusicLibraryDB:
    """SQLite 音乐库索引：FTS5 全文搜索 + 歌单 + 播放历史。

    用法::

        # 上下文管理器（推荐，自动 init_schema + commit + close）
        with MusicLibraryDB("~/.ai-omni/music/library.db") as db:
            db.upsert_song({...})
            results = db.search("周杰伦")

        # 手动管理
        db = MusicLibraryDB(":memory:")
        db.init_schema()
        ...
        db.close()

    :param db_path: 数据库文件路径；``:memory:`` 为内存库（测试用）
    """

    def __init__(self, db_path: str | Path) -> None:
        """构造数据库实例（不立即连接，``init_schema`` / 上下文管理器进入时才连接）。

        :param db_path: 数据库文件路径；支持 ``~`` 展开；``:memory:`` 为内存库
        """
        path_str = str(db_path)
        if path_str != ":memory:":
            path_str = os.path.expanduser(path_str)
        self.db_path: Path | str = Path(path_str) if path_str != ":memory:" else ":memory:"
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # 连接与 schema
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        """建立连接（懒构造）；父目录不存在时自动创建。"""
        if self._conn is not None:
            return self._conn
        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path))
        else:
            conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # 开启外键约束（级联删除）
        conn.execute("PRAGMA foreign_keys = ON")
        self._conn = conn
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        """当前连接（懒构造）。"""
        return self._connect()

    def init_schema(self) -> None:
        """建表 + FTS5 虚拟表 + 触发器（IF NOT EXISTS，幂等）。

        songs_fts 经触发器与 songs 同步：INSERT/UPDATE/DELETE 自动镜像。
        """
        conn = self._connect()
        cur = conn.cursor()
        # songs 主表
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS songs (
                id           TEXT PRIMARY KEY,
                path         TEXT NOT NULL UNIQUE,
                title        TEXT,
                artist       TEXT,
                album        TEXT,
                duration_s   INTEGER NOT NULL DEFAULT 0,
                cover_path   TEXT,
                lyrics_path  TEXT,
                source       TEXT NOT NULL DEFAULT 'local',
                file_mtime   REAL NOT NULL DEFAULT 0,
                file_size    INTEGER NOT NULL DEFAULT 0,
                added_at     REAL NOT NULL DEFAULT 0
            )
            """
        )
        # playlists 歌单表
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS playlists (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            )
            """
        )
        # playlist_songs 关联表（联合主键 + 级联删除）
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS playlist_songs (
                playlist_id  INTEGER NOT NULL,
                song_id      TEXT NOT NULL,
                position     INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (playlist_id, song_id),
                FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
                FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE
            )
            """
        )
        # play_history 播放历史
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS play_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                song_id    TEXT NOT NULL,
                played_at  REAL NOT NULL,
                FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE
            )
            """
        )
        # library_meta 元信息（last_scan_at 等）
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS library_meta (
                key    TEXT PRIMARY KEY,
                value  TEXT
            )
            """
        )
        # FTS5 全文搜索虚拟表（title / artist / album）
        # 注意：不使用 content=''（contentless），否则触发器 INSERT 的值为 NULL。
        # song_id UNINDEXED 表示该列不参与索引但可读取，用于 JOIN 回 songs 主表。
        cur.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS songs_fts USING fts5(
                song_id UNINDEXED,
                title,
                artist,
                album
            )
            """
        )
        # 触发器：songs 变更同步到 songs_fts
        cur.execute(
            """
            CREATE TRIGGER IF NOT EXISTS songs_ai AFTER INSERT ON songs BEGIN
                INSERT INTO songs_fts(song_id, title, artist, album)
                VALUES (new.id, new.title, new.artist, new.album);
            END
            """
        )
        cur.execute(
            """
            CREATE TRIGGER IF NOT EXISTS songs_ad AFTER DELETE ON songs BEGIN
                DELETE FROM songs_fts WHERE song_id = old.id;
            END
            """
        )
        cur.execute(
            """
            CREATE TRIGGER IF NOT EXISTS songs_au AFTER UPDATE ON songs BEGIN
                DELETE FROM songs_fts WHERE song_id = old.id;
                INSERT INTO songs_fts(song_id, title, artist, album)
                VALUES (new.id, new.title, new.artist, new.album);
            END
            """
        )
        conn.commit()

    # ------------------------------------------------------------------
    # songs CRUD
    # ------------------------------------------------------------------
    @staticmethod
    def _make_song_id(path: str) -> str:
        """由文件路径生成 song_id（md5 前 12 位，与 LocalMusicSource 一致）。"""
        return hashlib.md5(path.encode("utf-8")).hexdigest()[:12]

    def upsert_song(self, song_data: dict[str, Any]) -> str:
        """插入或更新歌曲（按 path 去重，file_mtime 变化时更新）。

        :param song_data: 歌曲 dict，必含 ``path``；可选 ``id`` / ``title`` /
            ``artist`` / ``album`` / ``duration_s`` / ``cover_path`` /
            ``lyrics_path`` / ``source`` / ``file_mtime`` / ``file_size``
        :return: song_id（``song_data["id"]`` 或由 path 生成）
        """
        conn = self._connect()
        path = song_data["path"]
        song_id = song_data.get("id") or self._make_song_id(path)
        mtime = float(song_data.get("file_mtime", 0))
        # 检查是否已存在且 mtime 未变
        row = conn.execute(
            "SELECT id, file_mtime, added_at FROM songs WHERE path = ?", (path,)
        ).fetchone()
        if row is not None and row["file_mtime"] == mtime:
            # mtime 未变，不更新（保留 added_at）
            return row["id"]
        if row is not None:
            # mtime 变化，更新（保留 added_at）
            added_at = row["added_at"]
            conn.execute(
                """
                UPDATE songs SET id=?, title=?, artist=?, album=?, duration_s=?,
                    cover_path=?, lyrics_path=?, source=?, file_mtime=?, file_size=?,
                    added_at=?
                WHERE path=?
                """,
                (
                    song_id,
                    song_data.get("title"),
                    song_data.get("artist"),
                    song_data.get("album"),
                    int(song_data.get("duration_s", 0)),
                    song_data.get("cover_path"),
                    song_data.get("lyrics_path"),
                    song_data.get("source", "local"),
                    mtime,
                    int(song_data.get("file_size", 0)),
                    added_at,
                    path,
                ),
            )
            conn.commit()
            return song_id
        # 新插入
        added_at = time.time()
        conn.execute(
            """
            INSERT INTO songs (id, path, title, artist, album, duration_s,
                cover_path, lyrics_path, source, file_mtime, file_size, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                song_id,
                path,
                song_data.get("title"),
                song_data.get("artist"),
                song_data.get("album"),
                int(song_data.get("duration_s", 0)),
                song_data.get("cover_path"),
                song_data.get("lyrics_path"),
                song_data.get("source", "local"),
                mtime,
                int(song_data.get("file_size", 0)),
                added_at,
            ),
        )
        conn.commit()
        return song_id

    def remove_song(self, song_id: str) -> bool:
        """删除歌曲（级联清理 playlist_songs / play_history / songs_fts）。

        :param song_id: 歌曲 ID
        :return: 实际删除返回 True，不存在返回 False
        """
        conn = self._connect()
        cur = conn.execute("DELETE FROM songs WHERE id = ?", (song_id,))
        conn.commit()
        return cur.rowcount > 0

    def get_song(self, song_id: str) -> dict[str, Any] | None:
        """按 ID 查询单曲。

        :param song_id: 歌曲 ID
        :return: 歌曲 dict；不存在返回 None
        """
        conn = self._connect()
        row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
        return dict(row) if row is not None else None

    def get_all_songs(self) -> list[dict[str, Any]]:
        """返回全部歌曲（按 added_at 倒序）。"""
        conn = self._connect()
        rows = conn.execute("SELECT * FROM songs ORDER BY added_at DESC").fetchall()
        return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """FTS5 全文搜索（title / artist / album）。

        空 query 返回全部（受 limit 截断，按 added_at 倒序）。
        FTS5 查询语法：空格分词，``*`` 前缀匹配。

        :param query: 搜索关键词
        :param limit: 返回上限
        :return: 匹配的歌曲 dict 列表
        """
        conn = self._connect()
        if not query.strip():
            rows = conn.execute(
                "SELECT * FROM songs ORDER BY added_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        # FTS5 MATCH：用引号包裹避免特殊字符被当语法
        # 转义双引号后用 "..." 做短语匹配
        escaped = query.replace('"', '""')
        fts_query = f'"{escaped}"'
        try:
            rows = conn.execute(
                """
                SELECT s.* FROM songs s
                JOIN songs_fts f ON s.id = f.song_id
                WHERE songs_fts MATCH ?
                ORDER BY s.added_at DESC
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            # FTS 查询语法错误（如纯特殊字符），降级 LIKE
            like = f"%{query}%"
            rows = conn.execute(
                """
                SELECT * FROM songs
                WHERE title LIKE ? OR artist LIKE ? OR album LIKE ?
                ORDER BY added_at DESC LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # playlists
    # ------------------------------------------------------------------
    def create_playlist(self, name: str) -> int:
        """创建歌单，返回自增 ID。"""
        conn = self._connect()
        now = time.time()
        cur = conn.execute(
            "INSERT INTO playlists (name, created_at, updated_at) VALUES (?, ?, ?)",
            (name, now, now),
        )
        conn.commit()
        return int(cur.lastrowid)

    def add_to_playlist(
        self, playlist_id: int, song_id: str, position: int | None = None
    ) -> None:
        """添加歌曲到歌单（按 song_id 去重；指定 position 时插入到该位置）。

        :param playlist_id: 歌单 ID
        :param song_id: 歌曲 ID
        :param position: 插入位置；None 时追加到末尾
        """
        conn = self._connect()
        # 已存在则幂等返回
        existing = conn.execute(
            "SELECT position FROM playlist_songs WHERE playlist_id=? AND song_id=?",
            (playlist_id, song_id),
        ).fetchone()
        if existing is not None:
            return
        if position is None:
            # 追加到末尾：取当前最大 position + 1
            row = conn.execute(
                "SELECT COALESCE(MAX(position), -1) AS max_pos FROM playlist_songs WHERE playlist_id=?",
                (playlist_id,),
            ).fetchone()
            position = int(row["max_pos"]) + 1
        else:
            # 把 >= position 的后移一位
            conn.execute(
                "UPDATE playlist_songs SET position = position + 1 WHERE playlist_id=? AND position >= ?",
                (playlist_id, position),
            )
        conn.execute(
            "INSERT INTO playlist_songs (playlist_id, song_id, position) VALUES (?, ?, ?)",
            (playlist_id, song_id, position),
        )
        conn.execute(
            "UPDATE playlists SET updated_at = ? WHERE id = ?", (time.time(), playlist_id)
        )
        conn.commit()

    def remove_from_playlist(self, playlist_id: int, song_id: str) -> None:
        """从歌单移除歌曲（幂等）。"""
        conn = self._connect()
        conn.execute(
            "DELETE FROM playlist_songs WHERE playlist_id=? AND song_id=?",
            (playlist_id, song_id),
        )
        conn.execute(
            "UPDATE playlists SET updated_at = ? WHERE id = ?", (time.time(), playlist_id)
        )
        conn.commit()

    def get_playlist_songs(self, playlist_id: int) -> list[dict[str, Any]]:
        """返回歌单内歌曲（按 position 升序，JOIN songs 取完整元数据）。"""
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT s.*, ps.position FROM songs s
            JOIN playlist_songs ps ON s.id = ps.song_id
            WHERE ps.playlist_id = ?
            ORDER BY ps.position ASC
            """,
            (playlist_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_playlists(self) -> list[dict[str, Any]]:
        """返回全部歌单（按 updated_at 倒序）。"""
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT p.*, (
                SELECT COUNT(*) FROM playlist_songs ps WHERE ps.playlist_id = p.id
            ) AS song_count
            FROM playlists p ORDER BY p.updated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # play_history
    # ------------------------------------------------------------------
    def add_to_history(self, song_id: str) -> None:
        """记录一次播放（played_at = 当前时间戳）。"""
        conn = self._connect()
        conn.execute(
            "INSERT INTO play_history (song_id, played_at) VALUES (?, ?)",
            (song_id, time.time()),
        )
        conn.commit()

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """返回播放历史（按 played_at 倒序，最近优先）。"""
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT h.id, h.song_id, h.played_at, s.title, s.artist, s.album, s.path
            FROM play_history h
            LEFT JOIN songs s ON h.song_id = s.id
            ORDER BY h.played_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 库状态 / 元信息
    # ------------------------------------------------------------------
    def get_status(self) -> dict[str, Any]:
        """返回库状态：song_count / playlist_count / last_scan_at。"""
        conn = self._connect()
        song_count = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        playlist_count = conn.execute("SELECT COUNT(*) FROM playlists").fetchone()[0]
        row = conn.execute(
            "SELECT value FROM library_meta WHERE key = 'last_scan_at'"
        ).fetchone()
        last_scan_at = float(row["value"]) if row is not None else None
        return {
            "song_count": int(song_count),
            "playlist_count": int(playlist_count),
            "last_scan_at": last_scan_at,
        }

    def set_last_scan_at(self, ts: float | None = None) -> None:
        """记录最近一次扫描时间戳（默认当前时间）。"""
        conn = self._connect()
        ts = ts if ts is not None else time.time()
        conn.execute(
            "INSERT INTO library_meta (key, value) VALUES ('last_scan_at', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(ts),),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # 上下文管理器
    # ------------------------------------------------------------------
    def __enter__(self) -> MusicLibraryDB:
        self._connect()
        self.init_schema()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """关闭连接（幂等）。"""
        if self._conn is not None:
            try:
                self._conn.commit()
            except sqlite3.Error:
                pass
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # 工厂方法
    # ------------------------------------------------------------------
    @classmethod
    def from_env(cls) -> MusicLibraryDB:
        """按 env ``AI_OMNI_MUSIC_DB`` 构造实例；未设置用默认路径。"""
        env = os.environ.get("AI_OMNI_MUSIC_DB")
        if env:
            return cls(env)
        return cls(default_db_path())
