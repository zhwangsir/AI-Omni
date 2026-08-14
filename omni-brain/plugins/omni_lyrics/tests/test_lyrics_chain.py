"""歌词来源优先级链测试（M18.3 TDD red → green）。

覆盖 ``LyricsChain.fetch(song)``：
- 本地 .lrc 文件优先（LocalMusicSource 已有 ``_read_lyrics_file`` / ``get_lyrics``）
- 音频文件内嵌歌词（mutagen USLT/SYNCEDLYRICS，惰性导入 + fake 注入）
- 在线 API（复用 omni_music 各源的 ``get_lyrics(song_id)``）
- 纯文本兜底（无时间轴）
- 每个来源失败（异常/None）自动降级到下一级
- 全部失败返回 ``{lyrics: None, source: "none", parsed: []}``

全部使用 fake MusicSource / fake 嵌入歌词读取器，零网络/零硬件依赖。
``mutagen`` 缺失时测试也必须全绿（惰性导入 + 依赖注入）。
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from omni_lyrics.lyrics_chain import LyricsChain, LyricsResult, MutagenEmbeddedReader
from omni_music.models import MusicSourceEnum, Song
from omni_music.sources.base import FakeMusicSource


def _make_song(
    song_id: str = "s1",
    name: str = "晴天",
    lyrics: str | None = None,
    source: MusicSourceEnum = MusicSourceEnum.NETEASE,
) -> Song:
    """构造测试用 Song。"""
    return Song(
        id=song_id,
        name=name,
        source=source,
        artists=["周杰伦"],
        album="叶惠美",
        duration_s=240,
        url=f"file:///fake/{song_id}.mp3",
        lyrics=lyrics,
        cover_url=None,
    )


class _FakeEmbeddedReader:
    """fake 嵌入歌词读取器（模拟 mutagen 读取 USLT/SYNCEDLYRICS）。

    按 ``song_id`` → 歌词文本 映射返回；未配置返回 None。
    """

    def __init__(self, lyrics_map: dict[str, str | None] | None = None) -> None:
        self.lyrics_map = lyrics_map or {}
        self.call_count = 0

    def read(self, song: Song) -> str | None:
        """按 song.id 查嵌入歌词；模拟 mutagen 读取。"""
        self.call_count += 1
        return self.lyrics_map.get(song.id)


class _FailingSource(FakeMusicSource):
    """所有方法都抛异常的 fake 源（测试降级链）。"""

    def get_lyrics(self, song_id: str) -> str | None:
        raise RuntimeError("源故障")

    def get_song_detail(self, song_id: str) -> Song | None:
        raise RuntimeError("源故障")


class _NoneLyricsSource(FakeMusicSource):
    """get_lyrics 始终返回 None 的 fake 源。"""

    def get_lyrics(self, song_id: str) -> str | None:
        return None


class TestLyricsResultDataclass:
    """LyricsResult 数据结构。"""

    def test_lyrics_result_to_dict(self) -> None:
        """LyricsResult 可序列化为 dict。"""
        result = LyricsResult(lyrics="歌词文本", source="local_file", parsed=[])
        d = result.to_dict()
        assert d["lyrics"] == "歌词文本"
        assert d["source"] == "local_file"
        assert d["parsed"] == []

    def test_lyrics_result_to_dict_with_parsed(self) -> None:
        """带 parsed 行的 LyricsResult 序列化。"""
        from omni_lyrics.lrc_parser import LyricsLine

        parsed = [LyricsLine(time_s=1.0, text="第一行")]
        result = LyricsResult(lyrics="[00:01.00]第一行", source="local_file", parsed=parsed)
        d = result.to_dict()
        assert len(d["parsed"]) == 1
        assert d["parsed"][0]["text"] == "第一行"

    def test_lyrics_result_none_lyrics(self) -> None:
        """lyrics=None 的 LyricsResult。"""
        result = LyricsResult(lyrics=None, source="none", parsed=[])
        assert result.lyrics is None
        assert result.source == "none"


class TestLyricsChainLocalFile:
    """本地 .lrc 文件优先级最高。"""

    def test_fetch_prefers_song_lyrics_field(self) -> None:
        """Song.lyrics 字段（本地源 _read_lyrics_file 填充）优先返回。"""
        lrc = "[00:01.00]故事的小黄花\n[00:05.00]从出生那年就飘着"
        song = _make_song(lyrics=lrc)
        chain = LyricsChain(sources=[FakeMusicSource()])
        result = chain.fetch(song)
        assert result.lyrics == lrc
        assert result.source == "local_file"
        assert len(result.parsed) == 2
        assert result.parsed[0].text == "故事的小黄花"

    def test_fetch_song_lyrics_none_falls_through(self) -> None:
        """Song.lyrics 为 None 时降级到下一级（在线源）。"""
        song = _make_song(lyrics=None)
        # FakeMusicSource 内置歌曲 lyrics 不为空，但 song.id 不在内置列表 → get_lyrics 返回 None
        online = FakeMusicSource()
        # 让 online.get_lyrics 返回在线歌词
        online.songs[0].lyrics = "[00:02.00]在线歌词"
        online.songs[0].id = song.id
        chain = LyricsChain(sources=[online])
        result = chain.fetch(song)
        assert result.lyrics is not None
        assert result.source == "online"
        assert "在线歌词" in result.lyrics


class TestLyricsChainEmbedded:
    """音频文件内嵌歌词（mutagen USLT/SYNCEDLYRICS）。"""

    def test_fetch_embedded_lyrics_when_song_lyrics_none(self) -> None:
        """Song.lyrics=None 且无在线源时，从嵌入歌词读取。"""
        embedded_lrc = "[00:03.00]嵌入歌词"
        song = _make_song(lyrics=None)
        reader = _FakeEmbeddedReader({song.id: embedded_lrc})
        chain = LyricsChain(sources=[], embedded_reader=reader)
        result = chain.fetch(song)
        assert result.lyrics == embedded_lrc
        assert result.source == "embedded"
        assert reader.call_count == 1

    def test_fetch_embedded_skipped_when_song_lyrics_present(self) -> None:
        """Song.lyrics 存在时不读嵌入歌词（优先级）。"""
        song = _make_song(lyrics="[00:01.00]本地")
        reader = _FakeEmbeddedReader({song.id: "[00:02.00]嵌入"})
        chain = LyricsChain(sources=[], embedded_reader=reader)
        result = chain.fetch(song)
        assert result.source == "local_file"
        assert reader.call_count == 0

    def test_fetch_embedded_reader_returns_none_falls_through(self) -> None:
        """嵌入读取器返回 None 时降级。"""
        song = _make_song(lyrics=None)
        reader = _FakeEmbeddedReader({song.id: None})
        chain = LyricsChain(sources=[], embedded_reader=reader)
        result = chain.fetch(song)
        assert result.lyrics is None
        # 无在线源 + 无嵌入 → 纯文本兜底（无）→ none
        assert result.source == "none"

    def test_fetch_embedded_reader_exception_falls_through(self) -> None:
        """嵌入读取器抛异常时降级，不拖垮链。"""
        song = _make_song(lyrics=None)

        class _FailingReader:
            def read(self, song: Song) -> str | None:
                raise OSError("mutagen 读取失败")

        chain = LyricsChain(sources=[], embedded_reader=_FailingReader())
        result = chain.fetch(song)
        assert result.lyrics is None
        assert result.source == "none"

    def test_fetch_no_embedded_reader_skips_embedded(self) -> None:
        """未注入 embedded_reader 时跳过嵌入歌词来源。"""
        song = _make_song(lyrics=None)
        chain = LyricsChain(sources=[])
        result = chain.fetch(song)
        assert result.lyrics is None
        assert result.source == "none"


class TestLyricsChainOnline:
    """在线 API（omni_music 各源的 get_lyrics）。"""

    def test_fetch_online_when_local_and_embedded_none(self) -> None:
        """本地 + 嵌入均无歌词时，从在线源获取。"""
        song = _make_song(lyrics=None)
        online = FakeMusicSource()
        online.songs[0].id = song.id
        online.songs[0].lyrics = "[00:10.00]在线歌词"
        chain = LyricsChain(sources=[online])
        result = chain.fetch(song)
        assert result.lyrics == "[00:10.00]在线歌词"
        assert result.source == "online"

    def test_fetch_online_multiple_sources_tries_in_order(self) -> None:
        """多个在线源按顺序尝试，第一个成功的胜出。"""
        song = _make_song(lyrics=None)
        # 第一个源无歌词，第二个有
        source1 = _NoneLyricsSource()
        source2 = FakeMusicSource()
        source2.songs[0].id = song.id
        source2.songs[0].lyrics = "[00:01.00]第二源歌词"
        chain = LyricsChain(sources=[source1, source2])
        result = chain.fetch(song)
        assert result.lyrics == "[00:01.00]第二源歌词"
        assert result.source == "online"

    def test_fetch_online_source_exception_falls_through(self) -> None:
        """在线源抛异常时降级到下一源。"""
        song = _make_song(lyrics=None)
        failing = _FailingSource()
        # failing 的内置歌曲 id 不匹配，get_song_detail 也会抛异常
        online = FakeMusicSource()
        online.songs[0].id = song.id
        online.songs[0].lyrics = "[00:01.00]兜底歌词"
        chain = LyricsChain(sources=[failing, online])
        result = chain.fetch(song)
        assert result.lyrics == "[00:01.00]兜底歌词"
        assert result.source == "online"

    def test_fetch_online_all_sources_fail_falls_to_none(self) -> None:
        """所有在线源都失败时降级到 none。"""
        song = _make_song(lyrics=None)
        failing = _FailingSource()
        chain = LyricsChain(sources=[failing])
        result = chain.fetch(song)
        assert result.lyrics is None
        assert result.source == "none"


class TestLyricsChainPlainTextFallback:
    """纯文本兜底（无时间轴）。"""

    def test_fetch_plain_text_lyrics_parsed_as_single_line(self) -> None:
        """纯文本歌词（无 [time]）被解析为 time_s=0.0 的单行。"""
        plain = "这是一首没有时间轴的纯歌词"
        song = _make_song(lyrics=plain)
        chain = LyricsChain(sources=[])
        result = chain.fetch(song)
        assert result.source == "local_file"
        assert len(result.parsed) == 1
        assert result.parsed[0].time_s == pytest.approx(0.0)
        assert result.parsed[0].text == plain


class TestLyricsChainPriority:
    """优先级链整体顺序：local_file > embedded > online > none。"""

    def test_priority_local_file_beats_embedded_and_online(self) -> None:
        """本地歌词文件优先于嵌入与在线。"""
        song = _make_song(lyrics="[00:01.00]本地")
        reader = _FakeEmbeddedReader({song.id: "[00:02.00]嵌入"})
        online = FakeMusicSource()
        online.songs[0].id = song.id
        online.songs[0].lyrics = "[00:03.00]在线"
        chain = LyricsChain(sources=[online], embedded_reader=reader)
        result = chain.fetch(song)
        assert result.source == "local_file"
        assert "本地" in result.lyrics

    def test_priority_embedded_beats_online(self) -> None:
        """嵌入歌词优先于在线。"""
        song = _make_song(lyrics=None)
        reader = _FakeEmbeddedReader({song.id: "[00:02.00]嵌入"})
        online = FakeMusicSource()
        online.songs[0].id = song.id
        online.songs[0].lyrics = "[00:03.00]在线"
        chain = LyricsChain(sources=[online], embedded_reader=reader)
        result = chain.fetch(song)
        assert result.source == "embedded"
        assert "嵌入" in result.lyrics

    def test_all_fail_returns_none_source(self) -> None:
        """全部来源失败返回 source=none。"""
        song = _make_song(lyrics=None)
        chain = LyricsChain(sources=[_NoneLyricsSource()])
        result = chain.fetch(song)
        assert result.lyrics is None
        assert result.source == "none"
        assert result.parsed == []


# ---------------------------------------------------------------------------
# MutagenEmbeddedReader（M32.26 覆盖率提升：fake mutagen 模块注入，零依赖）
# ---------------------------------------------------------------------------
def _fake_mutagen(file_func: Any) -> ModuleType:
    """构造 fake mutagen 模块：``File`` 属性为给定的假函数。"""
    mod = ModuleType("mutagen")
    mod.File = file_func
    return mod


def _fake_audio(tags: dict[str, Any] | None) -> SimpleNamespace:
    """构造带 .tags 的假 audio 对象。"""
    return SimpleNamespace(tags=tags)


class TestMutagenEmbeddedReader:
    """MutagenEmbeddedReader.read 全分支（lyrics_chain.py 91-120 行）。"""

    def test_non_file_url_returns_none(self) -> None:
        """url 非 file:// 协议直接返回 None（不触发 mutagen）。"""
        song = _make_song(lyrics=None)
        song.url = "https://example.com/x.mp3"
        assert MutagenEmbeddedReader().read(song) is None

    def test_url_not_str_returns_none(self) -> None:
        """url 缺失（None）直接返回 None。"""
        song = _make_song(lyrics=None)
        song.url = None
        assert MutagenEmbeddedReader().read(song) is None

    def test_mutagen_import_error_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """mutagen 缺失（sys.modules 中为 None → ImportError）返回 None。"""
        monkeypatch.setitem(sys.modules, "mutagen", None)
        song = _make_song(lyrics=None)
        assert MutagenEmbeddedReader().read(song) is None

    def test_mutagen_file_raises_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MutagenFile 抛异常（文件损坏/格式不支持）返回 None。"""

        def _boom(path: str) -> Any:
            raise RuntimeError("无法解析音频")

        monkeypatch.setitem(sys.modules, "mutagen", _fake_mutagen(_boom))
        song = _make_song(lyrics=None)
        assert MutagenEmbeddedReader().read(song) is None

    def test_mutagen_file_returns_none_audio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MutagenFile 返回 None（不支持的格式）返回 None。"""
        monkeypatch.setitem(sys.modules, "mutagen", _fake_mutagen(lambda path: None))
        song = _make_song(lyrics=None)
        assert MutagenEmbeddedReader().read(song) is None

    def test_tags_none_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """audio.tags 为 None → 视为空标签，返回 None。"""
        monkeypatch.setitem(
            sys.modules, "mutagen", _fake_mutagen(lambda path: _fake_audio(None))
        )
        song = _make_song(lyrics=None)
        assert MutagenEmbeddedReader().read(song) is None

    @pytest.mark.parametrize(
        "key", ["SYNCEDLYRICS", "lyrics", "USLT", "USLT::eng", "©lyr"]
    )
    def test_each_tag_key_hit_returns_text(
        self, key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """五个候选 tag key 各自命中（list 值取 [0]）。"""
        monkeypatch.setitem(
            sys.modules,
            "mutagen",
            _fake_mutagen(lambda path: _fake_audio({key: ["[00:01.00]内嵌歌词"]})),
        )
        song = _make_song(lyrics=None)
        assert MutagenEmbeddedReader().read(song) == "[00:01.00]内嵌歌词"

    def test_non_list_value_str_conversion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """tag 值非 list（如 USLT 对象/字符串）→ str(val) 返回。"""
        monkeypatch.setitem(
            sys.modules,
            "mutagen",
            _fake_mutagen(lambda path: _fake_audio({"USLT": "纯文本内嵌歌词"})),
        )
        song = _make_song(lyrics=None)
        assert MutagenEmbeddedReader().read(song) == "纯文本内嵌歌词"

    def test_empty_list_value_continues_to_next_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空 list 值跳过（continue），继续匹配后续 key。"""
        monkeypatch.setitem(
            sys.modules,
            "mutagen",
            _fake_mutagen(
                lambda path: _fake_audio(
                    {"SYNCEDLYRICS": [], "lyrics": ["[00:02.00]次优命中"]}
                )
            ),
        )
        song = _make_song(lyrics=None)
        assert MutagenEmbeddedReader().read(song) == "[00:02.00]次优命中"

    def test_blank_text_skipped_to_next_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """text 全空白跳过，继续匹配后续 key。"""
        monkeypatch.setitem(
            sys.modules,
            "mutagen",
            _fake_mutagen(
                lambda path: _fake_audio(
                    {"SYNCEDLYRICS": ["   \n  "], "USLT": ["真实歌词"]}
                )
            ),
        )
        song = _make_song(lyrics=None)
        assert MutagenEmbeddedReader().read(song) == "真实歌词"

    def test_no_candidate_key_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """tags 无任何候选 key → 返回 None。"""
        monkeypatch.setitem(
            sys.modules,
            "mutagen",
            _fake_mutagen(lambda path: _fake_audio({"TIT2": ["标题"]})),
        )
        song = _make_song(lyrics=None)
        assert MutagenEmbeddedReader().read(song) is None

    def test_fetch_with_real_mutagen_reader_integration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """经 LyricsChain.fetch 集成：fake mutagen 注入后来源为 embedded。"""
        monkeypatch.setitem(
            sys.modules,
            "mutagen",
            _fake_mutagen(
                lambda path: _fake_audio({"SYNCEDLYRICS": ["[00:03.00]集成歌词"]})
            ),
        )
        song = _make_song(lyrics=None)
        chain = LyricsChain(sources=[], embedded_reader=MutagenEmbeddedReader())
        result = chain.fetch(song)
        assert result.lyrics == "[00:03.00]集成歌词"
        assert result.source == "embedded"
        assert result.parsed[0].text == "集成歌词"


class TestParseNone:
    """LyricsChain._parse(None) 边界（lyrics_chain.py 152 行）。"""

    def test_parse_none_returns_empty_list(self) -> None:
        assert LyricsChain._parse(None) == []


class TestTryOnlineSongIdNotStr:
    """_try_online 的 song.id 非 str 分支（lyrics_chain.py 176 行）。"""

    def test_song_id_not_str_skips_online(self) -> None:
        """song.id=123（非 str）→ 在线源整体跳过，get_lyrics 不被调用。"""
        song = _make_song(song_id=123, lyrics=None)  # type: ignore[arg-type]

        class _RecordingSource:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def get_lyrics(self, song_id: str) -> str | None:
                self.calls.append(song_id)
                return "[00:01.00]在线"

        source = _RecordingSource()
        chain = LyricsChain(sources=[source])
        result = chain.fetch(song)
        assert result.lyrics is None
        assert result.source == "none"
        assert source.calls == []
