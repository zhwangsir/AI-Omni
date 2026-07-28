"""omni_lyrics 工具 handler 测试（M18.5 TDD red → green）。

覆盖 5 个 ``lyrics_*`` 工具：
- ``lyrics_get``：获取歌词（参数 song_id, source），返回解析后的 LyricsLine 列表
- ``lyrics_search``：按关键词搜索歌词（复用 music_search 结果）
- ``lyrics_set_offset``：设置用户偏移量（参数 offset_s）
- ``lyrics_upload``：上传/保存歌词到本地 .lrc 文件（参数 song_id, content）
- ``lyrics_get_current``：根据当前播放时间返回当前行+逐字高亮

工具返回 JSON 字符串 ``{"ok": true, "data": ...}`` / ``{"ok": false, "error": {...}}``。
全部使用 FakeMusicSource / fake 嵌入读取器，零网络/零硬件依赖。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from omni_lyrics import tools
from omni_music.models import MusicSourceEnum, Song
from omni_music.sources.base import FakeMusicSource


@pytest.fixture(autouse=True)
def _reset_runtime_each():
    """每个测试前重置 tools._runtime，避免跨测试状态污染。"""
    tools._reset_runtime()
    yield
    tools._reset_runtime()


def _make_fake_source_with_song(
    song_id: str = "s1",
    name: str = "晴天",
    lyrics: str | None = "[00:01.00]故事的小黄花\n[00:05.00]从出生那年就飘着",
) -> FakeMusicSource:
    """构造含指定歌曲的 FakeMusicSource。"""
    source = FakeMusicSource()
    source.songs[0].id = song_id
    source.songs[0].name = name
    source.songs[0].lyrics = lyrics
    return source


class TestToolsRegistry:
    """工具注册表与 register(ctx)。"""

    def test_tools_registered_count(self) -> None:
        """TOOLS 注册表含 5 个 lyrics_* 工具。"""
        names = [t["name"] for t in tools.TOOLS]
        assert len(names) == 5
        assert "lyrics_get" in names
        assert "lyrics_search" in names
        assert "lyrics_set_offset" in names
        assert "lyrics_upload" in names
        assert "lyrics_get_current" in names

    def test_tools_have_schema_and_emoji(self) -> None:
        """每个工具携带 schema / description / emoji / handler_func。"""
        for meta in tools.TOOLS:
            assert meta["description"]
            assert meta["emoji"]
            assert callable(meta["handler_func"])
            assert meta["schema"]["name"] == meta["name"]
            assert meta["schema"]["parameters"]["type"] == "object"

    def test_register_to_legacy_ctx(self) -> None:
        """register(ctx) 把 5 个工具注册到旧式 ctx。"""

        class _LegacyCtx:
            def __init__(self) -> None:
                self.tools: list[dict[str, Any]] = []

            def register_tool(self, **kwargs: Any) -> None:
                self.tools.append(kwargs)

        ctx = _LegacyCtx()
        tools.register(ctx)
        assert len(ctx.tools) == 5
        for t in ctx.tools:
            assert t["name"].startswith("lyrics_")


class TestLyricsGet:
    """``lyrics_get`` 工具。"""

    def test_get_returns_parsed_lines(self) -> None:
        """获取歌词返回解析后的 LyricsLine 列表。"""
        source = _make_fake_source_with_song()
        tools._runtime.source = source
        result = tools.lyrics_get(song_id="s1")
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"]["source"] == "local_file"
        assert len(data["data"]["parsed"]) == 2
        assert data["data"]["parsed"][0]["text"] == "故事的小黄花"

    def test_get_song_not_found_returns_error(self) -> None:
        """未找到歌曲返回 ok:false E_NOT_FOUND。"""
        source = _make_fake_source_with_song()
        tools._runtime.source = source
        result = tools.lyrics_get(song_id="not_exist")
        data = json.loads(result)
        assert data["ok"] is False
        assert data["error"]["code"] == "E_NOT_FOUND"

    def test_get_no_source_returns_backend_unavailable(self) -> None:
        """未配置源返回 E_BACKEND_UNAVAILABLE。"""
        result = tools.lyrics_get(song_id="s1")
        data = json.loads(result)
        assert data["ok"] is False
        assert data["error"]["code"] == "E_BACKEND_UNAVAILABLE"

    def test_get_no_lyrics_returns_none(self) -> None:
        """歌曲无歌词返回 source=none + parsed=[]。"""
        source = _make_fake_source_with_song(lyrics=None)
        tools._runtime.source = source
        result = tools.lyrics_get(song_id="s1")
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"]["source"] == "none"
        assert data["data"]["parsed"] == []
        assert data["data"]["lyrics"] is None

    def test_get_with_source_filter(self) -> None:
        """source 参数指定来源过滤（local_file/online/embedded/none）。"""
        source = _make_fake_source_with_song()
        tools._runtime.source = source
        # 指定 source=local_file，应只从本地获取
        result = tools.lyrics_get(song_id="s1", source="local_file")
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"]["source"] == "local_file"


class TestLyricsSearch:
    """``lyrics_search`` 工具。"""

    def test_search_returns_songs(self) -> None:
        """搜索返回歌曲列表。"""
        source = _make_fake_source_with_song()
        tools._runtime.source = source
        result = tools.lyrics_search(keyword="晴天")
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"]["count"] >= 1
        assert data["data"]["songs"][0]["name"] == "晴天"

    def test_search_no_source_returns_error(self) -> None:
        """未配置源返回 E_BACKEND_UNAVAILABLE。"""
        result = tools.lyrics_search(keyword="晴天")
        data = json.loads(result)
        assert data["ok"] is False
        assert data["error"]["code"] == "E_BACKEND_UNAVAILABLE"

    def test_search_empty_keyword_returns_all(self) -> None:
        """空关键词返回全部歌曲。"""
        source = _make_fake_source_with_song()
        tools._runtime.source = source
        result = tools.lyrics_search(keyword="")
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"]["count"] >= 1


class TestLyricsSetOffset:
    """``lyrics_set_offset`` 工具。"""

    def test_set_offset_positive(self) -> None:
        """设置正偏移。"""
        result = tools.lyrics_set_offset(offset_s=2.5)
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"]["offset_s"] == 2.5
        assert tools._runtime.sync.get_offset() == pytest.approx(2.5)

    def test_set_offset_negative(self) -> None:
        """设置负偏移。"""
        result = tools.lyrics_set_offset(offset_s=-1.0)
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"]["offset_s"] == -1.0

    def test_set_offset_zero(self) -> None:
        """设置 0 偏移。"""
        result = tools.lyrics_set_offset(offset_s=0.0)
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"]["offset_s"] == 0.0

    def test_set_offset_invalid_type_returns_error(self) -> None:
        """非数值偏移返回错误。"""
        result = tools.lyrics_set_offset(offset_s="not a number")  # type: ignore[arg-type]
        data = json.loads(result)
        assert data["ok"] is False


class TestLyricsGetCurrent:
    """``lyrics_get_current`` 工具。"""

    def test_get_current_returns_line_and_word(self) -> None:
        """返回当前行索引 + 逐字高亮。"""
        lrc = "[00:01.00]故[00:01.50]事[00:02.00]的[00:02.50]花\n[00:05.00]第二行"
        source = _make_fake_source_with_song(lyrics=lrc)
        tools._runtime.source = source
        # 先 fetch 歌词到运行时缓存
        tools.lyrics_get(song_id="s1")
        # 1.2s → 第 0 行，第 0 字（故）
        result = tools.lyrics_get_current(song_id="s1", current_time_s=1.2)
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"]["current_line"] == 0
        assert data["data"]["current_word"] == 0
        assert data["data"]["line_text"] == "故事的花"

    def test_get_current_no_lyrics_returns_empty(self) -> None:
        """无歌词返回 current_line=-1。"""
        source = _make_fake_source_with_song(lyrics=None)
        tools._runtime.source = source
        result = tools.lyrics_get_current(song_id="s1", current_time_s=5.0)
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"]["current_line"] == -1

    def test_get_current_song_not_in_cache_fetches_first(self) -> None:
        """运行时无缓存时自动 fetch。"""
        lrc = "[00:01.00]第一行\n[00:05.00]第二行"
        source = _make_fake_source_with_song(lyrics=lrc)
        tools._runtime.source = source
        # 不先调 lyrics_get，直接 get_current
        result = tools.lyrics_get_current(song_id="s1", current_time_s=3.0)
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"]["current_line"] == 0  # 1s 行仍显示

    def test_get_current_regular_line_no_word(self) -> None:
        """非逐字行 current_word=null。"""
        lrc = "[00:01.00]普通行\n[00:05.00]第二行"
        source = _make_fake_source_with_song(lyrics=lrc)
        tools._runtime.source = source
        result = tools.lyrics_get_current(song_id="s1", current_time_s=2.0)
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"]["current_line"] == 0
        assert data["data"]["current_word"] is None

    def test_get_current_with_offset(self) -> None:
        """应用用户偏移后返回当前行。"""
        lrc = "[00:01.00]第一行\n[00:05.00]第二行"
        source = _make_fake_source_with_song(lyrics=lrc)
        tools._runtime.source = source
        tools.lyrics_set_offset(offset_s=3.0)  # 提前 3s
        tools.lyrics_get(song_id="s1")
        # 实际时间 2.0 + 偏移 3.0 = 5.0 → 第二行
        result = tools.lyrics_get_current(song_id="s1", current_time_s=2.0)
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"]["current_line"] == 1


class TestLyricsUpload:
    """``lyrics_upload`` 工具。"""

    def test_upload_writes_lrc_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """上传歌词写入 .lrc 文件。"""
        # 构造本地源歌曲（file:// 路径）
        audio_path = tmp_path / "song.mp3"
        audio_path.write_bytes(b"fake audio")
        song = Song(
            id="s1",
            name="测试",
            source=MusicSourceEnum.LOCAL,
            artists=["艺人"],
            album="专辑",
            duration_s=100,
            url=f"file://{audio_path}",
            lyrics=None,
        )
        source = FakeMusicSource()
        source.songs = [song]
        tools._runtime.source = source

        content = "[00:01.00]上传的歌词\n[00:05.00]第二行"
        result = tools.lyrics_upload(song_id="s1", content=content)
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"]["path"].endswith(".lrc")
        # 验证文件写入
        lrc_path = audio_path.with_suffix(".lrc")
        assert lrc_path.exists()
        assert lrc_path.read_text(encoding="utf-8") == content

    def test_upload_song_not_found_returns_error(self) -> None:
        """未找到歌曲返回 E_NOT_FOUND。"""
        source = _make_fake_source_with_song()
        tools._runtime.source = source
        result = tools.lyrics_upload(song_id="not_exist", content="歌词")
        data = json.loads(result)
        assert data["ok"] is False
        assert data["error"]["code"] == "E_NOT_FOUND"

    def test_upload_non_local_source_returns_error(self) -> None:
        """非本地源歌曲（无 file:// URL）返回 E_INVALID_ARGS。"""
        source = _make_fake_source_with_song()
        # FakeMusicSource 默认 source=NETEASE，url 不是 file://
        tools._runtime.source = source
        result = tools.lyrics_upload(song_id="s1", content="歌词")
        data = json.loads(result)
        assert data["ok"] is False
        # 非 file:// URL 无法写入本地 .lrc
        assert data["error"]["code"] in ("E_INVALID_ARGS", "E_UPLOAD_FAILED")

    def test_upload_no_source_returns_error(self) -> None:
        """未配置源返回 E_BACKEND_UNAVAILABLE。"""
        result = tools.lyrics_upload(song_id="s1", content="歌词")
        data = json.loads(result)
        assert data["ok"] is False
        assert data["error"]["code"] == "E_BACKEND_UNAVAILABLE"

    def test_upload_empty_content_returns_error(self) -> None:
        """空内容返回 E_INVALID_ARGS。"""
        source = _make_fake_source_with_song()
        tools._runtime.source = source
        result = tools.lyrics_upload(song_id="s1", content="")
        data = json.loads(result)
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
