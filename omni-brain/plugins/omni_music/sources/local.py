"""omni_music 本地音乐源（M17.6）。

扫描本地文件系统音频文件，构造 :class:`Song` 列表。无需扫码登录。

依赖 ``mutagen`` 读取音频元数据，但通过惰性导入保证 ``mutagen`` 缺失时降级为
文件名推断（CLAUDE.md §三 重型依赖惰性导入且可缺省）。

通过 ``file_scanner`` + ``metadata_reader`` 依赖注入支持测试 fake
（CLAUDE.md §三 测试零依赖：不碰真实音频硬件、不装 mutagen）。

合规说明（D17.4）：仅扫描用户自有本地文件，不涉及任何破解付费内容。仅个人学习用途。
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from omni_music.models import MusicSourceEnum, Song
from omni_music.sources.base import MusicSource


# 支持的音频扩展名
SUPPORTED_EXTENSIONS: tuple[str, ...] = (".mp3", ".flac", ".m4a", ".wav", ".ogg", ".opus")


class LocalMusicSource(MusicSource):
    """本地音乐源：扫描本地文件系统音频文件构造 :class:`Song` 列表。

    无需扫码登录（``login_qr`` / ``check_login_status`` 返回固定值）。
    通过 ``file_scanner`` + ``metadata_reader`` 依赖注入支持测试 fake。

    用法::

        # 运行时（依赖 mutagen，惰性导入）
        source = LocalMusicSource(root_dir="~/Music")
        songs = source.scan()
        results = source.search("周杰伦", limit=20)

        # 测试时（fake 注入，零依赖）
        source = LocalMusicSource(
            root_dir="/fake/music",
            file_scanner=FakeFileScanner([...]),
            metadata_reader=FakeMetadataReader({...}),
        )
    """

    # 类属性：本地源枚举
    source: MusicSourceEnum = MusicSourceEnum.LOCAL

    def __init__(
        self,
        root_dir: str = "~/.ai-omni/music",
        file_scanner: Any = None,
        metadata_reader: Any = None,
    ) -> None:
        """构造本地音乐源。

        :param root_dir: 扫描根目录，支持 ``~`` 展开（``os.path.expanduser``）
        :param file_scanner: 文件扫描器，需实现 ``scan(root) -> list[str]``；
            ``None`` 时用内置 :meth:`_scan_dir`（递归 ``os.walk``）
        :param metadata_reader: 元数据读取器，需实现 ``read(path) -> dict``；
            ``None`` 时惰性用 ``mutagen``（缺失则降级为文件名推断）
        """
        self.root_dir: str = os.path.expanduser(root_dir)
        self._file_scanner = file_scanner
        self._metadata_reader = metadata_reader
        # 内部缓存：首次扫描后填充，后续 search/get_* 直接复用
        self._songs_cache: list[Song] | None = None

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    def _scan_dir(self, root: str) -> list[str]:
        """内置文件扫描器：递归扫描 root 下所有支持的音频文件。

        :param root: 扫描根目录
        :return: 音频文件绝对路径列表（按 ``os.walk`` 顺序）
        """
        files: list[str] = []
        if not os.path.isdir(root):
            return files
        for dirpath, _dirs, filenames in os.walk(root):
            for fname in filenames:
                if fname.lower().endswith(SUPPORTED_EXTENSIONS):
                    files.append(os.path.join(dirpath, fname))
        return files

    def _read_metadata(self, path: str) -> dict[str, Any]:
        """读取音频文件元数据。

        优先用注入的 ``metadata_reader``；否则惰性用 ``mutagen``
        （CLAUDE.md §三）。``mutagen`` 缺失或读取失败时返回空元数据，
        由 :meth:`_build_song` 兜底降级为文件名推断。

        :param path: 音频文件路径
        :return: 元数据 dict，含 ``title`` / ``artist`` / ``album`` / ``duration`` 键
        """
        if self._metadata_reader is not None:
            return self._metadata_reader.read(path)

        empty: dict[str, Any] = {
            "title": None,
            "artist": None,
            "album": None,
            "duration": 0,
        }
        # 惰性导入 mutagen（CLAUDE.md §三：模块顶层禁止 import mutagen）
        try:
            from mutagen import File as MutagenFile
        except ImportError:
            # mutagen 缺失，降级用文件名（由 _build_song 兜底）
            return empty

        try:
            audio = MutagenFile(path)
        except Exception:
            # 读取失败（文件损坏/格式不支持），降级
            return empty
        if audio is None:
            return empty

        # 时长（秒）
        duration = 0
        info = getattr(audio, "info", None)
        if info is not None and hasattr(info, "length"):
            try:
                duration = int(float(info.length))
            except (TypeError, ValueError):
                duration = 0

        # 标签字段：不同格式键名不同（ID3: TIT2/TPE1/TALB；Vorbis: title/artist/album；
        # MP4: ©nam/©ART/©alb），统一尝试
        tags = getattr(audio, "tags", None) or {}

        def _first(keys: tuple[str, ...]) -> str | None:
            """从 tags 中按候选键名取首个非空值。"""
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

        return {
            "title": title,
            "artist": artist,
            "album": album,
            "duration": duration,
        }

    def _read_lyrics_file(self, audio_path: str) -> str | None:
        """读取与音频同名的 ``.lrc`` 歌词文件。

        :param audio_path: 音频文件路径
        :return: 歌词文本；无 ``.lrc`` 文件或读取失败返回 None
        """
        lrc_path = os.path.splitext(audio_path)[0] + ".lrc"
        if not os.path.isfile(lrc_path):
            return None
        try:
            with open(lrc_path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def _build_song(self, path: str) -> Song:
        """从单个音频文件构造 :class:`Song` 实例。

        元数据缺失时降级：``name`` 用文件名去扩展名、``artists`` 用
        ``["未知艺术家"]``、``album`` 用 ``"未知专辑"``、``duration_s`` 用 0。

        :param path: 音频文件路径
        :return: :class:`Song` 实例（``id``=md5(path)[:12]，``url``=``file://path``）
        """
        meta = self._read_metadata(path)

        # name: 优先元数据 title，否则文件名去扩展名
        title = meta.get("title")
        if title:
            name = title
        else:
            name = os.path.splitext(os.path.basename(path))[0]

        # artists: 元数据 artist 非空则单元素列表，否则占位
        artist_raw = meta.get("artist")
        if artist_raw:
            artists: list[str] = [artist_raw]
        else:
            artists = ["未知艺术家"]

        # album: 元数据 album 非空则用，否则占位
        album = meta.get("album") or "未知专辑"

        # duration_s: 容错转换
        try:
            duration_s = int(meta.get("duration") or 0)
        except (TypeError, ValueError):
            duration_s = 0

        # id: 文件路径 md5 前 12 位（同源内唯一）
        song_id = hashlib.md5(path.encode()).hexdigest()[:12]
        # url: file:// 协议
        url = f"file://{path}"
        # lyrics: 同名 .lrc 文件
        lyrics = self._read_lyrics_file(path)

        return Song(
            id=song_id,
            name=name,
            artists=artists,
            album=album,
            duration_s=duration_s,
            url=url,
            lyrics=lyrics,
            cover_url=None,  # 本地源无 URL 封面
            source=MusicSourceEnum.LOCAL,
        )

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def scan(self) -> list[Song]:
        """递归扫描 ``root_dir`` 下所有音频文件，构造 :class:`Song` 列表并缓存。

        :return: :class:`Song` 列表（扫描后写入 :attr:`_songs_cache`）
        """
        if self._file_scanner is not None:
            files = self._file_scanner.scan(self.root_dir)
        else:
            files = self._scan_dir(self.root_dir)

        songs = [self._build_song(p) for p in files]
        self._songs_cache = songs
        return songs

    def search(self, keyword: str, limit: int = 20) -> list[Song]:
        """按 keyword 过滤缓存歌曲。

        匹配规则：``name`` / ``artists`` / ``album`` 任一包含 keyword
        （大小写不敏感）。空 keyword 返回全部（受 ``limit`` 截断）。
        若未扫描则先 :meth:`scan`。

        :param keyword: 搜索关键词
        :param limit: 返回上限
        :return: 匹配的 :class:`Song` 列表
        """
        if self._songs_cache is None:
            self.scan()
        cache = self._songs_cache
        assert cache is not None  # scan 后必非 None

        if not keyword:
            matched = list(cache)
        else:
            kw_lower = keyword.lower()
            matched = [
                s
                for s in cache
                if kw_lower in s.name.lower()
                or any(kw_lower in a.lower() for a in s.artists)
                or (s.album is not None and kw_lower in s.album.lower())
            ]
        return matched[:limit]

    def get_song_url(self, song_id: str, quality: str = "standard") -> str | None:
        """从缓存中查找歌曲 URL。

        ``quality`` 本地源忽略（始终返回原始文件 URL）。

        :param song_id: 歌曲 ID
        :param quality: 音质（本地源忽略）
        :return: ``file://`` URL；未扫描或未找到返回 None
        """
        if self._songs_cache is None:
            return None
        for song in self._songs_cache:
            if song.id == song_id:
                return song.url
        return None

    def get_lyrics(self, song_id: str) -> str | None:
        """从缓存中查找歌曲歌词。

        :param song_id: 歌曲 ID
        :return: 歌词文本；未扫描、未找到或无歌词返回 None
        """
        if self._songs_cache is None:
            return None
        for song in self._songs_cache:
            if song.id == song_id:
                return song.lyrics
        return None

    def get_song_detail(self, song_id: str) -> Song | None:
        """从缓存中查找歌曲详情。

        :param song_id: 歌曲 ID
        :return: :class:`Song` 实例；未扫描或未找到返回 None
        """
        if self._songs_cache is None:
            return None
        for song in self._songs_cache:
            if song.id == song_id:
                return song
        return None

    def login_qr(self) -> dict[str, str]:
        """本地源不支持登录，返回固定占位值。

        :return: ``{"key": "local", "qr_url": ""}``
        """
        return {"key": "local", "qr_url": ""}

    def check_login_status(self, key: str) -> str:
        """本地源无需登录，直接返回 ``confirmed``。

        :param key: :meth:`login_qr` 返回的 key（本地源忽略）
        :return: ``"confirmed"``
        """
        return "confirmed"

    def get_cookies_on_confirmed(self) -> dict[str, str] | None:
        """本地源无 cookie，返回 None。

        :return: None
        """
        return None
