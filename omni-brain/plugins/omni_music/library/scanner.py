"""omni_music 本地音乐库增强扫描器（M19.3）。

复用 :class:`LocalMusicSource` 的扫描逻辑 + mutagen 元数据读取，
额外提取封面图（APIC / cover art）与内嵌歌词（USLT / SYNCEDLYRICS），
扫描结果写入 SQLite（:class:`MusicLibraryDB.upsert_song`）。

增量扫描：对比 ``file_mtime``，仅更新变化的文件（封面按 mtime 判断是否重新提取）。

支持 MP3 ID3v2 / FLAC Vorbis / M4A MP4 / OGG Vorbis（mutagen 统一接口）。
mutagen 惰性导入（CLAUDE.md §三），缺失时降级为文件名推断。
依赖注入 ``file_scanner`` / ``metadata_reader`` / ``cover_extractor`` / ``file_stat`` 便于测试。

封面存储到 ``~/.ai-omni/music/covers/<song_id>.jpg``（按 file_mtime 判断是否需要重新提取）。

合规说明（D19.1）：仅扫描用户自有本地文件，不涉及任何破解付费内容。仅个人学习用途。
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

from omni_music.library.db import MusicLibraryDB, default_db_path

__all__ = ["LibraryScanner", "default_covers_dir"]

logger = logging.getLogger(__name__)


def default_covers_dir() -> Path:
    """取默认封面存储目录 ``~/.ai-omni/music/covers``。"""
    return Path.home() / ".ai-omni" / "music" / "covers"


class LibraryScanner:
    """本地音乐库增强扫描器：扫描文件 → 读元数据 → 提取封面/歌词 → 写 SQLite。

    用法::

        # 运行时（依赖 mutagen，惰性导入）
        scanner = LibraryScanner(root_dir="~/Music")
        result = scanner.scan()
        # result = {"scanned": 10, "added": 8, "updated": 2, "skipped": 0, "errors": 0}

        # 测试时（fake 注入，零依赖）
        scanner = LibraryScanner(
            root_dir="/fake",
            file_scanner=FakeFileScanner([...]),
            metadata_reader=FakeMetadataReader({...}),
            cover_extractor=FakeCoverExtractor(),
            file_stat=FakeFileStat({...}),
            db=MusicLibraryDB(":memory:"),
        )

    :param root_dir: 扫描根目录，支持 ``~`` 展开
    :param file_scanner: 文件扫描器，需实现 ``scan(root) -> list[str]``；
        ``None`` 时用内置 ``_scan_dir``（递归 ``os.walk``）
    :param metadata_reader: 元数据读取器，需实现 ``read(path) -> dict``；
        ``None`` 时惰性用 mutagen（缺失则降级为文件名推断）
    :param cover_extractor: 封面提取器，需实现
        ``extract(path, song_id, mtime) -> str | None``；``None`` 时用内置提取器
    :param file_stat: 文件 stat 读取器，需实现 ``stat(path) -> (mtime, size)``；
        ``None`` 时用 ``os.stat``
    :param db: :class:`MusicLibraryDB` 实例；``None`` 时用 :meth:`MusicLibraryDB.from_env`
    """

    def __init__(
        self,
        root_dir: str = "~/.ai-omni/music",
        file_scanner: Any = None,
        metadata_reader: Any = None,
        cover_extractor: Any = None,
        file_stat: Any = None,
        db: MusicLibraryDB | None = None,
        covers_dir: str | Path | None = None,
    ) -> None:
        """构造扫描器。"""
        self.root_dir: str = os.path.expanduser(root_dir)
        self._file_scanner = file_scanner
        self._metadata_reader = metadata_reader
        self._cover_extractor = cover_extractor
        self._file_stat = file_stat
        self._db: MusicLibraryDB = db if db is not None else MusicLibraryDB.from_env()
        self._covers_dir: Path = (
            Path(os.path.expanduser(str(covers_dir)))
            if covers_dir is not None
            else default_covers_dir()
        )

    # ------------------------------------------------------------------
    # 内置默认实现（mutagen 惰性导入）
    # ------------------------------------------------------------------
    def _scan_dir(self, root: str) -> list[str]:
        """内置文件扫描器：递归扫描 root 下所有支持的音频文件。"""
        # 复用 LocalMusicSource 的扩展名清单
        from omni_music.sources.local import SUPPORTED_EXTENSIONS

        files: list[str] = []
        if not os.path.isdir(root):
            return files
        for dirpath, _dirs, filenames in os.walk(root):
            for fname in filenames:
                if fname.lower().endswith(SUPPORTED_EXTENSIONS):
                    files.append(os.path.join(dirpath, fname))
        return files

    def _read_metadata(self, path: str) -> dict[str, Any]:
        """读取音频元数据（惰性用 mutagen，缺失/失败返回空元数据）。

        与 :meth:`LocalMusicSource._read_metadata` 类似，额外提取
        ``lyrics_path``（内嵌歌词写到临时文件或直接记 path）。
        """
        empty: dict[str, Any] = {
            "title": None,
            "artist": None,
            "album": None,
            "duration": 0,
            "lyrics_path": None,
        }
        try:
            from mutagen import File as MutagenFile
        except ImportError:
            return empty
        try:
            audio = MutagenFile(path)
        except Exception:  # noqa: BLE001 - 读取失败降级
            return empty
        if audio is None:
            return empty
        duration = 0
        info = getattr(audio, "info", None)
        if info is not None and hasattr(info, "length"):
            try:
                duration = int(float(info.length))
            except (TypeError, ValueError):
                duration = 0
        tags = getattr(audio, "tags", None) or {}

        def _first(keys: tuple[str, ...]) -> str | None:
            for k in keys:
                if k in tags:
                    val = tags[k]
                    if isinstance(val, list) and val:
                        return str(val[0])
                    if val:
                        return str(val)
            return None

        title = _first(("title", "TIT2", "TITLE", "\xa9nam"))
        artist = _first(("artist", "TPE1", "ARTIST", "\xa9ART"))
        album = _first(("album", "TALB", "ALBUM", "\xa9alb"))
        # 内嵌歌词：USLT（ID3）/ LYRICS（Vorbis）/ ©lyr（MP4）
        lyrics = _first(("USLT", "LYRICS", "UNSYNCEDLYRICS", "SYNCEDLYRICS", "\xa9lyr"))
        lyrics_path = None
        if lyrics:
            # 内嵌歌词不写文件，但记一个标记 path 便于前端识别
            lyrics_path = f"embedded://{path}"
        return {
            "title": title,
            "artist": artist,
            "album": album,
            "duration": duration,
            "lyrics_path": lyrics_path,
        }

    def _extract_cover(self, path: str, song_id: str, mtime: float) -> str | None:
        """提取封面图到 ``covers_dir/<song_id>.jpg``；无封面或失败返回 None。

        按 mtime 判断是否需要重新提取：已存在且 mtime 相同则跳过。
        mutagen 缺失或文件无封面返回 None。
        """
        cover_path = self._covers_dir / f"{song_id}.jpg"
        # mtime 标记文件：covers_dir/<song_id>.mtime
        mtime_marker = self._covers_dir / f"{song_id}.mtime"
        if cover_path.exists() and mtime_marker.exists():
            try:
                old_mtime = float(mtime_marker.read_text(encoding="utf-8").strip())
                if old_mtime == mtime:
                    return str(cover_path)
            except (OSError, ValueError):
                pass
        # 提取封面
        try:
            from mutagen import File as MutagenFile
        except ImportError:
            return None
        try:
            audio = MutagenFile(path)
        except Exception:  # noqa: BLE001
            return None
        if audio is None:
            return None
        tags = getattr(audio, "tags", None) or []
        cover_data: bytes | None = None
        # ID3 APIC / MP4 covr / FLAC picture
        for key in ("APIC:", "APIC", "covr", "\xa9ART"):
            if key in tags:
                val = tags[key]
                if isinstance(val, list):
                    for item in val:
                        cover_data = _extract_bytes(item)
                        if cover_data:
                            break
                else:
                    cover_data = _extract_bytes(val)
                if cover_data:
                    break
        # FLAC pictures 属性
        if cover_data is None and hasattr(audio, "pictures"):
            for pic in getattr(audio, "pictures") or []:
                if getattr(pic, "data", None):
                    cover_data = pic.data
                    break
        if cover_data is None:
            return None
        try:
            self._covers_dir.mkdir(parents=True, exist_ok=True)
            cover_path.write_bytes(cover_data)
            mtime_marker.write_text(str(mtime), encoding="utf-8")
            return str(cover_path)
        except OSError:
            return None

    def _stat_file(self, path: str) -> tuple[float, int]:
        """取文件 mtime / size（默认 os.stat）。"""
        try:
            st = os.stat(path)
            return float(st.st_mtime), int(st.st_size)
        except OSError:
            return 0.0, 0

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------
    def scan(self) -> dict[str, int]:
        """扫描 ``root_dir``，写入 SQLite，返回统计。

        :return: dict，含 ``scanned`` / ``added`` / ``updated`` / ``skipped`` / ``errors``
        """
        # 取文件列表
        if self._file_scanner is not None:
            files = self._file_scanner.scan(self.root_dir)
        else:
            files = self._scan_dir(self.root_dir)
        added = 0
        updated = 0
        skipped = 0
        errors = 0
        from omni_music.library.db import MusicLibraryDB as _DB  # noqa: F401 - 类型提示

        for path in files:
            try:
                # 取 mtime / size
                if self._file_stat is not None:
                    mtime, size = self._file_stat.stat(path)
                else:
                    mtime, size = self._stat_file(path)
                # 检查是否已存在且 mtime 未变（增量跳过）
                song_id = self._db._make_song_id(path)
                existing = self._db.get_song(song_id)
                if existing is not None and existing["file_mtime"] == mtime:
                    skipped += 1
                    continue
                # 读元数据
                if self._metadata_reader is not None:
                    meta = self._metadata_reader.read(path)
                else:
                    meta = self._read_metadata(path)
                # 提取封面
                cover_path: str | None = None
                if self._cover_extractor is not None:
                    cover_path = self._cover_extractor.extract(path, song_id, mtime)
                else:
                    cover_path = self._extract_cover(path, song_id, mtime)
                # title 兜底：文件名去扩展名
                title = meta.get("title") or os.path.splitext(os.path.basename(path))[0]
                song_data = {
                    "id": song_id,
                    "path": path,
                    "title": title,
                    "artist": meta.get("artist"),
                    "album": meta.get("album"),
                    "duration_s": int(meta.get("duration") or 0),
                    "cover_path": cover_path,
                    "lyrics_path": meta.get("lyrics_path"),
                    "source": "local",
                    "file_mtime": mtime,
                    "file_size": size,
                }
                self._db.upsert_song(song_data)
                if existing is not None:
                    updated += 1
                else:
                    added += 1
            except Exception:  # noqa: BLE001 - 单文件失败不崩
                errors += 1
                logger.debug("scanner 扫描文件失败: %s", path, exc_info=True)
        # 更新 last_scan_at
        self._db.set_last_scan_at()
        return {
            "scanned": len(files),
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }


def _extract_bytes(item: Any) -> bytes | None:
    """从 mutagen 标签值中提取封面字节（兼容 APIC / MP4 covr / bytes）。"""
    if isinstance(item, (bytes, bytearray)):
        return bytes(item)
    # APIC 对象有 .data 属性
    data = getattr(item, "data", None)
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    return None
