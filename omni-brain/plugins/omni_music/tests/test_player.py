"""omni_music MusicPlayer 播放控制测试（M17.8）。

覆盖：
- 构造空 player 与初始状态
- 队列管理（set_queue/add_to_queue/add_next/remove_from_queue/clear_queue/get_queue/queue_length）
- 播放控制（play/pause/resume/stop/seek/next/previous/set_repeat_mode/get_repeat_mode）
- 4 种 RepeatMode 切换逻辑（SINGLE/LIST_LOOP/RANDOM/SEQUENCE）
- 状态查询 property
- 与 MusicSource 协作（ensure_song_url/ensure_lyrics/set_source）—— 通过 CountingFakeMusicSource 断言真实调用次数
- 序列化（to_state_dict/from_state_dict 往返一致）
- history 去重相邻 + max_history 截断

D17.1 对齐：Python 侧不播放音频，仅管理元数据+队列+状态；测试零音频依赖。
"""

from __future__ import annotations

import random

import pytest

from omni_music.models import MusicSourceEnum, Song
from omni_music.player import MusicPlayer, PlayerState, RepeatMode
from omni_music.sources.base import FakeMusicSource


class CountingFakeMusicSource(FakeMusicSource):
    """带 url/lyrics 调用计数的 FakeMusicSource 子类（测试专用）。

    继承 FakeMusicSource 全部行为，额外记录 ``get_song_url`` / ``get_lyrics``
    调用次数，便于断言 :meth:`MusicPlayer.ensure_song_url` /
    :meth:`MusicPlayer.ensure_lyrics` 是否真正委托给 source（而非空实现）。
    """

    def __init__(self) -> None:
        super().__init__()
        self.url_call_count: int = 0
        self.lyrics_call_count: int = 0

    def get_song_url(self, song_id: str, quality: str = "standard") -> str | None:
        self.url_call_count += 1
        return super().get_song_url(song_id, quality)

    def get_lyrics(self, song_id: str) -> str | None:
        self.lyrics_call_count += 1
        return super().get_lyrics(song_id)


def _make_song(
    song_id: str = "s1",
    name: str = "测试歌曲",
    url: str | None = "https://example.com/s1.mp3",
    lyrics: str | None = "[00:00] 测试歌词",
    source: MusicSourceEnum = MusicSourceEnum.NETEASE,
) -> Song:
    """构造测试用 Song（带默认字段，便于断言）。"""
    return Song(
        id=song_id,
        name=name,
        source=source,
        artists=["测试歌手"],
        album="测试专辑",
        duration_s=180,
        url=url,
        lyrics=lyrics,
        cover_url="https://example.com/cover.jpg",
    )


def _make_songs(n: int) -> list[Song]:
    """构造 n 首不同 id 的 Song 列表（id 为 s0..s{n-1}）。"""
    return [_make_song(song_id=f"s{i}", name=f"歌曲{i}") for i in range(n)]


# ---------------------------------------------------------------------------
# 构造与初始状态
# ---------------------------------------------------------------------------


class TestPlayerInit:
    def test_empty_player_init_state(self) -> None:
        """构造空 player：queue 空、index=-1、state=STOPPED。"""
        player = MusicPlayer()
        assert player.queue_length == 0
        assert player.current_index == -1
        assert player.current_state is PlayerState.STOPPED
        assert player.current_song is None
        assert player.is_playing is False
        assert player.position_s == 0
        assert player.history == []
        assert player.get_repeat_mode() is RepeatMode.SEQUENCE


# ---------------------------------------------------------------------------
# 队列管理
# ---------------------------------------------------------------------------


class TestQueueManagement:
    def test_set_queue_non_empty_sets_index_zero(self) -> None:
        """set_queue 非空：current_index=0。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        assert player.queue_length == 3
        assert player.current_index == 0

    def test_set_queue_empty_sets_index_minus_one(self) -> None:
        """set_queue 空：current_index=-1。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        player.set_queue([])
        assert player.queue_length == 0
        assert player.current_index == -1

    def test_set_queue_preserves_state(self) -> None:
        """set_queue 不改变 state（PLAYING 保持 PLAYING）。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        player.play()
        assert player.current_state is PlayerState.PLAYING
        player.set_queue(_make_songs(3))
        assert player.current_state is PlayerState.PLAYING

    def test_add_to_queue_empty_sets_index_zero(self) -> None:
        """add_to_queue 空队列：current_index=0。"""
        player = MusicPlayer()
        player.add_to_queue(_make_song())
        assert player.queue_length == 1
        assert player.current_index == 0

    def test_add_to_queue_non_empty_appends_index_unchanged(self) -> None:
        """add_to_queue 非空队列：追加末尾，current_index 不变。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        assert player.current_index == 0
        player.add_to_queue(_make_song(song_id="new"))
        assert player.queue_length == 3
        assert player.current_index == 0
        assert player.get_queue()[-1].id == "new"

    def test_add_next_inserts_after_current(self) -> None:
        """add_next 插入到当前曲目后一位。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=1)
        player.add_next(_make_song(song_id="inserted"))
        assert player.queue_length == 4
        assert player.get_queue()[2].id == "inserted"
        assert player.current_index == 1

    def test_add_next_empty_queue_sets_index_zero(self) -> None:
        """add_next 空队列：current_index=0。"""
        player = MusicPlayer()
        player.add_next(_make_song(song_id="only"))
        assert player.queue_length == 1
        assert player.current_index == 0

    def test_add_next_at_last_position(self) -> None:
        """add_next 在末尾曲目时追加到末尾。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        player.play(index=1)
        player.add_next(_make_song(song_id="tail"))
        assert player.queue_length == 3
        assert player.get_queue()[2].id == "tail"

    def test_remove_from_queue_out_of_range_raises(self) -> None:
        """remove_from_queue 越界 raise IndexError。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        with pytest.raises(IndexError):
            player.remove_from_queue(5)
        with pytest.raises(IndexError):
            player.remove_from_queue(-1)

    def test_remove_from_queue_before_current_adjusts_index(self) -> None:
        """移除当前曲目之前的索引，current_index 减一。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=2)
        player.remove_from_queue(0)
        assert player.queue_length == 2
        assert player.current_index == 1

    def test_remove_current_song_moves_to_next(self) -> None:
        """移除当前曲目，current_index 指向下一首（原 index+1 位置）。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=1)
        player.remove_from_queue(1)
        assert player.queue_length == 2
        assert player.current_index == 1
        assert player.current_song is not None
        assert player.current_song.id == "s2"

    def test_remove_current_song_at_last_keeps_valid(self) -> None:
        """移除末尾当前曲目，current_index 回退一位。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=2)
        player.remove_from_queue(2)
        assert player.queue_length == 2
        assert player.current_index == 1

    def test_remove_from_queue_empties_queue_sets_index_minus_one(self) -> None:
        """移除后队列空，current_index=-1，state=STOPPED。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(1))
        player.play()
        player.remove_from_queue(0)
        assert player.queue_length == 0
        assert player.current_index == -1
        assert player.current_state is PlayerState.STOPPED

    def test_clear_queue_resets_all(self) -> None:
        """clear_queue 清空队列、index=-1、state=STOPPED、position_s=0。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play()
        player.seek(60)
        player.clear_queue()
        assert player.queue_length == 0
        assert player.current_index == -1
        assert player.current_state is PlayerState.STOPPED
        assert player.position_s == 0

    def test_get_queue_returns_copy(self) -> None:
        """get_queue 返回副本，修改副本不影响内部队列。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        copy = player.get_queue()
        copy.clear()
        copy.append(_make_song(song_id="intruder"))
        assert player.queue_length == 2


# ---------------------------------------------------------------------------
# 播放控制
# ---------------------------------------------------------------------------


class TestPlaybackControl:
    def test_play_empty_queue_returns_none(self) -> None:
        """play 空队列返回 None，state 保持 STOPPED。"""
        player = MusicPlayer()
        assert player.play() is None
        assert player.current_state is PlayerState.STOPPED

    def test_play_default_starts_at_current_index(self) -> None:
        """play 无参数从 current_index 开始。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        result = player.play()
        assert result is not None
        assert result.id == "s0"
        assert player.current_state is PlayerState.PLAYING

    def test_play_with_index_jumps(self) -> None:
        """play 指定 index 跳转到该索引。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        result = player.play(index=2)
        assert result is not None
        assert result.id == "s2"
        assert player.current_index == 2

    def test_play_adds_to_history(self) -> None:
        """play 把当前 Song 加入 history。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        player.play()
        assert len(player.history) == 1
        assert player.history[0].id == "s0"

    def test_play_dedup_adjacent_same_song(self) -> None:
        """play 相邻同曲目 history 去重。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        player.play(index=0)
        player.play(index=0)
        assert len(player.history) == 1

    def test_play_different_songs_all_in_history(self) -> None:
        """play 不同曲目均加入 history（顺序保留）。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=0)
        player.play(index=1)
        player.play(index=2)
        assert len(player.history) == 3
        assert [s.id for s in player.history] == ["s0", "s1", "s2"]

    def test_pause_requires_playing_state(self) -> None:
        """pause 非 PLAYING raise RuntimeError。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        with pytest.raises(RuntimeError):
            player.pause()  # STOPPED
        player.play()
        player.pause()
        with pytest.raises(RuntimeError):
            player.pause()  # 已 PAUSED

    def test_pause_success_sets_paused(self) -> None:
        """pause 成功 state=PAUSED。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        player.play()
        player.pause()
        assert player.current_state is PlayerState.PAUSED
        assert player.is_playing is False

    def test_resume_requires_paused_state(self) -> None:
        """resume 非 PAUSED raise RuntimeError。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        with pytest.raises(RuntimeError):
            player.resume()  # STOPPED
        player.play()
        with pytest.raises(RuntimeError):
            player.resume()  # PLAYING

    def test_resume_success_sets_playing(self) -> None:
        """resume 成功 state=PLAYING。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        player.play()
        player.pause()
        player.resume()
        assert player.current_state is PlayerState.PLAYING
        assert player.is_playing is True

    def test_stop_resets_position_keeps_queue(self) -> None:
        """stop 重置 position 但不清队列、不重置 index。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play()
        player.seek(45)
        player.stop()
        assert player.current_state is PlayerState.STOPPED
        assert player.position_s == 0
        assert player.queue_length == 3
        assert player.current_index == 0

    def test_seek_negative_raises_value_error(self) -> None:
        """seek 负数 raise ValueError。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        with pytest.raises(ValueError):
            player.seek(-1)

    def test_seek_success_sets_position(self) -> None:
        """seek 成功设置 position_s。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        player.seek(120)
        assert player.position_s == 120

    def test_position_s_setter_negative_raises(self) -> None:
        """position_s setter 校验非负。"""
        player = MusicPlayer()
        with pytest.raises(ValueError):
            player.position_s = -5


# ---------------------------------------------------------------------------
# 播放模式（RepeatMode）
# ---------------------------------------------------------------------------


class TestRepeatModes:
    def test_next_single_keeps_current_resets_position(self) -> None:
        """next SINGLE 模式保持当前曲目，position 重置为 0。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=1)
        player.seek(50)
        player.set_repeat_mode(RepeatMode.SINGLE)
        result = player.next()
        assert result is not None
        assert result.id == "s1"
        assert player.current_index == 1
        assert player.position_s == 0

    def test_next_list_loop_wraps_around(self) -> None:
        """next LIST_LOOP 越界回绕到 0。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=2)
        player.set_repeat_mode(RepeatMode.LIST_LOOP)
        result = player.next()
        assert result is not None
        assert result.id == "s0"
        assert player.current_index == 0

    def test_next_list_loop_normal_advance(self) -> None:
        """next LIST_LOOP 正常前进。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=0)
        player.set_repeat_mode(RepeatMode.LIST_LOOP)
        result = player.next()
        assert result is not None
        assert result.id == "s1"

    def test_next_sequence_out_of_range_stops_returns_none(self) -> None:
        """next SEQUENCE 越界则 stop 返回 None。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=2)
        result = player.next()
        assert result is None
        assert player.current_state is PlayerState.STOPPED

    def test_next_random_selects_different_index(self) -> None:
        """next RANDOM 选不同索引（注入固定 seed 断言）。"""
        player = MusicPlayer()
        player._shuffle_rng = random.Random(42)
        player.set_queue(_make_songs(3))
        player.play(index=0)
        player.set_repeat_mode(RepeatMode.RANDOM)
        old_index = player.current_index
        result = player.next()
        assert result is not None
        assert player.current_index != old_index
        assert 0 <= player.current_index < 3

    def test_next_random_eventually_covers_all(self) -> None:
        """next RANDOM 多次后覆盖所有索引（全播放过则重置已播集合）。"""
        player = MusicPlayer()
        player._shuffle_rng = random.Random(123)
        player.set_queue(_make_songs(3))
        player.play(index=0)
        player.set_repeat_mode(RepeatMode.RANDOM)
        visited = {player.current_index}
        for _ in range(10):
            song = player.next()
            assert song is not None
            visited.add(player.current_index)
        assert visited == {0, 1, 2}

    def test_next_random_resets_played_set_when_all_played(self) -> None:
        """next RANDOM 全播放过后重置已播集合，可持续切歌。"""
        player = MusicPlayer()
        player._shuffle_rng = random.Random(7)
        player.set_queue(_make_songs(2))
        player.play(index=0)
        player.set_repeat_mode(RepeatMode.RANDOM)
        songs: list[str] = []
        for _ in range(5):
            s = player.next()
            assert s is not None
            songs.append(s.id)
        assert len(songs) == 5

    def test_previous_list_loop_wraps_to_last(self) -> None:
        """previous LIST_LOOP 在 index=0 回绕到末尾。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=0)
        player.set_repeat_mode(RepeatMode.LIST_LOOP)
        result = player.previous()
        assert result is not None
        assert result.id == "s2"
        assert player.current_index == 2

    def test_previous_sequence_keeps_zero(self) -> None:
        """previous SEQUENCE 在 index=0 保持 0。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=0)
        result = player.previous()
        assert result is not None
        assert result.id == "s0"
        assert player.current_index == 0

    def test_previous_normal_decrement(self) -> None:
        """previous 正常 index-1。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=2)
        player.set_repeat_mode(RepeatMode.LIST_LOOP)
        result = player.previous()
        assert result is not None
        assert result.id == "s1"

    def test_set_and_get_repeat_mode(self) -> None:
        """set_repeat_mode + get_repeat_mode。"""
        player = MusicPlayer()
        assert player.get_repeat_mode() is RepeatMode.SEQUENCE
        player.set_repeat_mode(RepeatMode.LIST_LOOP)
        assert player.get_repeat_mode() is RepeatMode.LIST_LOOP
        player.set_repeat_mode(RepeatMode.RANDOM)
        assert player.get_repeat_mode() is RepeatMode.RANDOM
        player.set_repeat_mode(RepeatMode.SINGLE)
        assert player.get_repeat_mode() is RepeatMode.SINGLE

    def test_next_keeps_playing_state(self) -> None:
        """next 在 PLAYING 状态下保持 PLAYING。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=0)
        player.set_repeat_mode(RepeatMode.LIST_LOOP)
        player.next()
        assert player.current_state is PlayerState.PLAYING

    def test_next_from_paused_keeps_paused(self) -> None:
        """next 在 PAUSED 状态下保持 PAUSED（不自动恢复播放）。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=0)
        player.pause()
        player.set_repeat_mode(RepeatMode.LIST_LOOP)
        player.next()
        assert player.current_state is PlayerState.PAUSED


# ---------------------------------------------------------------------------
# 状态查询
# ---------------------------------------------------------------------------


class TestStateQueries:
    def test_current_song_empty_queue_returns_none(self) -> None:
        """current_song 队列空返回 None。"""
        player = MusicPlayer()
        assert player.current_song is None

    def test_current_song_returns_current(self) -> None:
        """current_song 返回当前曲目。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=1)
        assert player.current_song is not None
        assert player.current_song.id == "s1"

    def test_is_playing_reflects_state(self) -> None:
        """is_playing 状态正确（play/pause/resume/stop 切换）。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        assert player.is_playing is False
        player.play()
        assert player.is_playing is True
        player.pause()
        assert player.is_playing is False
        player.resume()
        assert player.is_playing is True
        player.stop()
        assert player.is_playing is False

    def test_history_returns_copy(self) -> None:
        """history 返回副本，修改副本不影响内部。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        player.play()
        hist = player.history
        hist.clear()
        assert len(player.history) == 1

    def test_current_index_property(self) -> None:
        """current_index property 反映队列状态。"""
        player = MusicPlayer()
        assert player.current_index == -1
        player.set_queue(_make_songs(3))
        assert player.current_index == 0
        player.play(index=2)
        assert player.current_index == 2

    def test_current_state_property(self) -> None:
        """current_state property 反映状态机。"""
        player = MusicPlayer()
        assert player.current_state is PlayerState.STOPPED
        player.set_queue(_make_songs(2))
        player.play()
        assert player.current_state is PlayerState.PLAYING
        player.pause()
        assert player.current_state is PlayerState.PAUSED


# ---------------------------------------------------------------------------
# 与 MusicSource 协作
# ---------------------------------------------------------------------------


class TestSourceInteraction:
    def test_ensure_song_url_already_present(self) -> None:
        """ensure_song_url 已有 url 直接返回，不调 source。"""
        fake = CountingFakeMusicSource()
        player = MusicPlayer(source=fake)
        song = _make_song(song_id="x", url="https://direct.example.com/x.mp3")
        player.set_queue([song])
        player.play()
        url = player.ensure_song_url()
        assert url == "https://direct.example.com/x.mp3"
        assert fake.url_call_count == 0

    def test_ensure_song_url_calls_source_when_missing(self) -> None:
        """ensure_song_url 无 url 调 source.get_song_url。"""
        fake = CountingFakeMusicSource()
        player = MusicPlayer(source=fake)
        song = _make_song(song_id="fake_song_1", url=None)
        player.set_queue([song])
        player.play()
        url = player.ensure_song_url()
        assert url is not None
        assert "song_1" in url
        assert fake.url_call_count == 1

    def test_ensure_song_url_source_none_returns_none(self) -> None:
        """ensure_song_url source 为 None 返回 None。"""
        player = MusicPlayer(source=None)
        song = _make_song(song_id="x", url=None)
        player.set_queue([song])
        player.play()
        assert player.ensure_song_url() is None

    def test_ensure_song_url_source_returns_none(self) -> None:
        """ensure_song_url source 返回 None（VIP 无权限）则返回 None。"""
        fake = CountingFakeMusicSource()
        player = MusicPlayer(source=fake)
        song = _make_song(song_id="vip_only", url=None)
        player.set_queue([song])
        player.play()
        assert player.ensure_song_url() is None
        assert fake.url_call_count == 1

    def test_ensure_song_url_no_current_song_returns_none(self) -> None:
        """ensure_song_url 无当前曲目返回 None。"""
        fake = CountingFakeMusicSource()
        player = MusicPlayer(source=fake)
        assert player.ensure_song_url() is None
        assert fake.url_call_count == 0

    def test_ensure_song_url_quality_param(self) -> None:
        """ensure_song_url 透传 quality 参数到 source。"""
        fake = CountingFakeMusicSource()
        player = MusicPlayer(source=fake)
        song = _make_song(song_id="fake_song_1", url=None)
        player.set_queue([song])
        player.play()
        url = player.ensure_song_url(quality="hires")
        assert url is not None
        assert fake.url_call_count == 1

    def test_ensure_lyrics_already_present(self) -> None:
        """ensure_lyrics 已有歌词直接返回，不调 source。"""
        fake = CountingFakeMusicSource()
        player = MusicPlayer(source=fake)
        song = _make_song(song_id="x", lyrics="[00:00] 已有歌词")
        player.set_queue([song])
        player.play()
        lyrics = player.ensure_lyrics()
        assert lyrics == "[00:00] 已有歌词"
        assert fake.lyrics_call_count == 0

    def test_ensure_lyrics_calls_source_when_missing(self) -> None:
        """ensure_lyrics 无歌词调 source.get_lyrics。"""
        fake = CountingFakeMusicSource()
        player = MusicPlayer(source=fake)
        song = _make_song(song_id="fake_song_1", lyrics=None)
        player.set_queue([song])
        player.play()
        lyrics = player.ensure_lyrics()
        assert lyrics is not None
        assert "小黄花" in lyrics
        assert fake.lyrics_call_count == 1

    def test_ensure_lyrics_source_none_returns_none(self) -> None:
        """ensure_lyrics source 为 None 返回 None。"""
        player = MusicPlayer(source=None)
        song = _make_song(song_id="x", lyrics=None)
        player.set_queue([song])
        player.play()
        assert player.ensure_lyrics() is None

    def test_ensure_lyrics_source_returns_none(self) -> None:
        """ensure_lyrics source 返回 None（无歌词）则返回 None。"""
        fake = CountingFakeMusicSource()
        player = MusicPlayer(source=fake)
        song = _make_song(song_id="no_lyrics_id", lyrics=None)
        player.set_queue([song])
        player.play()
        assert player.ensure_lyrics() is None
        assert fake.lyrics_call_count == 1

    def test_ensure_lyrics_no_current_song_returns_none(self) -> None:
        """ensure_lyrics 无当前曲目返回 None。"""
        fake = CountingFakeMusicSource()
        player = MusicPlayer(source=fake)
        assert player.ensure_lyrics() is None
        assert fake.lyrics_call_count == 0

    def test_set_source_replaces(self) -> None:
        """set_source 替换 source（原 None 替换为 fake 后可获取 URL）。"""
        player = MusicPlayer(source=None)
        assert player.ensure_song_url() is None
        fake = CountingFakeMusicSource()
        player.set_source(fake)
        song = _make_song(song_id="fake_song_1", url=None)
        player.set_queue([song])
        player.play()
        url = player.ensure_song_url()
        assert url is not None
        assert fake.url_call_count == 1


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_to_state_dict_full(self) -> None:
        """to_state_dict 完整序列化（queue/index/state/repeat/position/song）。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=1)
        player.seek(30)
        player.set_repeat_mode(RepeatMode.LIST_LOOP)
        state = player.to_state_dict()
        assert state["current_index"] == 1
        assert state["state"] == "playing"
        assert state["repeat_mode"] == "list_loop"
        assert state["position_s"] == 30
        assert len(state["queue"]) == 3
        assert state["current_song"] is not None
        assert state["current_song"]["id"] == "s1"
        assert all(isinstance(s, dict) for s in state["queue"])

    def test_to_state_dict_empty_player(self) -> None:
        """空 player 的 to_state_dict。"""
        player = MusicPlayer()
        state = player.to_state_dict()
        assert state["current_index"] == -1
        assert state["state"] == "stopped"
        assert state["repeat_mode"] == "sequence"
        assert state["position_s"] == 0
        assert state["queue"] == []
        assert state["current_song"] is None

    def test_from_state_dict_restores(self) -> None:
        """from_state_dict 恢复 player 各字段。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(2))
        player.play(index=1)
        player.pause()
        player.set_repeat_mode(RepeatMode.SINGLE)
        state = player.to_state_dict()
        restored = MusicPlayer.from_state_dict(state)
        assert restored.queue_length == 2
        assert restored.current_index == 1
        assert restored.current_state is PlayerState.PAUSED
        assert restored.get_repeat_mode() is RepeatMode.SINGLE
        assert restored.current_song is not None
        assert restored.current_song.id == "s1"

    def test_state_dict_roundtrip(self) -> None:
        """to_state_dict + from_state_dict 往返一致。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(4))
        player.play(index=2)
        player.seek(99)
        player.set_repeat_mode(RepeatMode.RANDOM)
        state = player.to_state_dict()
        restored = MusicPlayer.from_state_dict(state)
        state2 = restored.to_state_dict()
        assert state2 == state

    def test_from_state_dict_with_source(self) -> None:
        """from_state_dict 接受 source 参数，恢复后可调 source 获取 URL。"""
        fake = CountingFakeMusicSource()
        player = MusicPlayer()
        player.set_queue([_make_song(song_id="fake_song_1", url=None)])
        player.play()
        state = player.to_state_dict()
        restored = MusicPlayer.from_state_dict(state, source=fake)
        url = restored.ensure_song_url()
        assert url is not None
        assert fake.url_call_count == 1


# ---------------------------------------------------------------------------
# 历史记录与 max_history
# ---------------------------------------------------------------------------


class TestHistoryAndMaxHistory:
    def test_max_history_truncates(self) -> None:
        """max_history=3，播放 5 首后 history 长度=3，保留最近 3 首。"""
        player = MusicPlayer(max_history=3)
        player.set_queue(_make_songs(5))
        for i in range(5):
            player.play(index=i)
        assert len(player.history) == 3
        assert [s.id for s in player.history] == ["s2", "s3", "s4"]

    def test_max_history_default_100_no_truncate(self) -> None:
        """默认 max_history=100，播放 5 首不截断。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(5))
        for i in range(5):
            player.play(index=i)
        assert len(player.history) == 5

    def test_history_dedup_non_adjacent_kept(self) -> None:
        """history 去重仅相邻，非相邻重复保留。"""
        player = MusicPlayer()
        player.set_queue(_make_songs(3))
        player.play(index=0)
        player.play(index=1)
        player.play(index=0)
        assert len(player.history) == 3
        assert [s.id for s in player.history] == ["s0", "s1", "s0"]
