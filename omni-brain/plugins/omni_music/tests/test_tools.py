"""omni_music tools 层测试（M17.9 完整 12 工具）。

覆盖：
- ``music_search`` / ``music_get_login_qr`` / ``music_check_login_status``：搜索与登录三件套
- ``music_play``：song_id / index / keyword / 无参恢复 / 空队列 五种路径
- ``music_pause`` / ``music_resume`` / ``music_stop`` / ``music_next`` / ``music_previous``：播放控制
- ``music_seek`` / ``music_set_repeat_mode`` / ``music_get_player_state``：进度/模式/状态
- 后端选择：``_get_source`` / ``_get_store`` / ``_get_player``
- 错误码：E_BACKEND_UNAVAILABLE / E_INVALID_ARGS / E_PLAYER_NOT_READY /
  E_STATE_VIOLATION / E_SEARCH_FAILED / E_LOGIN_FAILED
- state_file 原子写入（env ``AI_OMNI_MUSIC_STATE_FILE`` 覆盖路径）
- ``_make_handler`` 参数适配与异常捕获
- ``register(ctx)`` 注册 12 工具 + schema 合法性

全部用 FakeMusicSource + 真实 MusicPlayer（player 是纯逻辑无音频依赖）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from omni_music import tools
from omni_music.auth.cookie_store import FakeCookieStore
from omni_music.models import MusicSourceEnum, Song
from omni_music.player import MusicPlayer, PlayerState, RepeatMode
from omni_music.sources.base import FakeMusicSource


def _parse(result: str) -> dict:
    """工具返回的是 JSON 字符串，解析为 dict。"""
    assert isinstance(result, str)
    return json.loads(result)


@pytest.fixture(autouse=True)
def fresh_runtime(tmp_path, monkeypatch) -> Any:
    """每个测试前重置运行时单例 + 把 state_file 指向临时目录。

    env ``AI_OMNI_MUSIC_STATE_FILE`` 覆盖默认 ``~/.ai-omni/state/music_state.json``，
    避免测试污染用户家目录。
    """
    state_path = tmp_path / "music_state.json"
    monkeypatch.setenv("AI_OMNI_MUSIC_STATE_FILE", str(state_path))
    rt = tools._reset_runtime()
    yield rt
    # 清理 env（monkeypatch 自动恢复）


@pytest.fixture
def state_path(tmp_path, monkeypatch) -> Path:
    """返回当前测试的 state_file 路径。"""
    return Path(tmp_path / "music_state.json")


# ---------------------------------------------------------------------------
# 辅助：构造预置 fake 运行时并预热 player
# ---------------------------------------------------------------------------
def _prepare_player_with_queue(rt: Any, songs: list[Song] | None = None) -> MusicPlayer:
    """预置 fake source + player，并装入队列（默认 FakeMusicSource 内置 3 首）。"""
    rt.source = FakeMusicSource()
    rt.player = MusicPlayer(source=rt.source)
    if songs is None:
        songs = list(rt.source.songs)
    if songs:
        rt.player.set_queue(songs)
    return rt.player


# ===========================================================================
# music_search
# ===========================================================================
class TestMusicSearch:
    def test_search_fake_returns_songs(self) -> None:
        """fake 模式搜索返回内置 Song 列表。"""
        data = _parse(tools.music_search(keyword="晴天", fake=True))
        assert data["ok"] is True
        payload = data["data"]
        assert "songs" in payload
        assert payload["count"] == len(payload["songs"])
        assert payload["count"] > 0
        song = payload["songs"][0]
        assert "id" in song
        assert "name" in song
        assert "source" in song

    def test_search_fake_keyword_filter(self) -> None:
        """fake 模式按 keyword 过滤。"""
        data = _parse(tools.music_search(keyword="晴天", fake=True))
        songs = data["data"]["songs"]
        assert all("晴天" in s["name"] for s in songs)

    def test_search_fake_limit(self) -> None:
        """fake 模式 limit 截断。"""
        data = _parse(tools.music_search(keyword="", limit=1, fake=True))
        assert data["data"]["count"] <= 1

    def test_search_no_source_returns_error(self) -> None:
        """真实模式（fake=False）未配置源时返回 E_BACKEND_UNAVAILABLE。"""
        data = _parse(tools.music_search(keyword="x", fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_BACKEND_UNAVAILABLE"

    def test_search_with_preset_source(self) -> None:
        """预置 source 后 fake=False 也能搜索。"""
        rt = tools._runtime
        rt.source = FakeMusicSource()
        data = _parse(tools.music_search(keyword="晴天", fake=False))
        assert data["ok"] is True
        assert data["data"]["count"] > 0

    def test_search_exception_returns_error(self) -> None:
        """source.search 抛异常时返回 E_SEARCH_FAILED。"""
        rt = tools._runtime

        class _BrokenSource(FakeMusicSource):
            def search(self, keyword: str, limit: int = 20) -> list:
                raise RuntimeError("boom")

        rt.source = _BrokenSource()
        data = _parse(tools.music_search(keyword="x", fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_SEARCH_FAILED"
        assert "boom" in data["error"]["message"]

    def test_search_returns_correct_song_dict(self) -> None:
        """返回的 song dict 含全部字段（to_dict 完整性）。"""
        data = _parse(tools.music_search(keyword="晴天", fake=True))
        song = data["data"]["songs"][0]
        for key in ("id", "name", "artists", "album", "duration_s", "url", "source"):
            assert key in song
        assert song["source"] == "netease"
        assert isinstance(song["artists"], list)


# ===========================================================================
# music_get_login_qr
# ===========================================================================
class TestMusicGetLoginQR:
    def test_qr_fake_returns_key_and_url(self) -> None:
        """fake 模式返回 key + qr_url + source。"""
        data = _parse(tools.music_get_login_qr(fake=True))
        assert data["ok"] is True
        payload = data["data"]
        assert payload["key"]
        assert payload["qr_url"]
        assert payload["source"] == "netease"

    def test_qr_no_source_returns_error(self) -> None:
        """真实模式未配置源返回 E_BACKEND_UNAVAILABLE。"""
        data = _parse(tools.music_get_login_qr(fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_BACKEND_UNAVAILABLE"

    def test_qr_with_preset_source(self) -> None:
        """预置 source 后 fake=False 也能发起扫码。"""
        rt = tools._runtime
        rt.source = FakeMusicSource()
        rt.store = FakeCookieStore()
        data = _parse(tools.music_get_login_qr(fake=False))
        assert data["ok"] is True
        assert data["data"]["key"]
        assert rt.flow is not None

    def test_qr_exception_returns_error(self) -> None:
        """source.login_qr 抛异常时返回 E_LOGIN_QR_FAILED。"""
        rt = tools._runtime

        class _BrokenSource(FakeMusicSource):
            def login_qr(self) -> dict:
                raise RuntimeError("qr boom")

        rt.source = _BrokenSource()
        data = _parse(tools.music_get_login_qr(fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_LOGIN_QR_FAILED"
        assert "qr boom" in data["error"]["message"]

    def test_qr_fake_constructs_fake_flow(self) -> None:
        """fake=True 构造 FakeQRLoginFlow。"""
        data = _parse(tools.music_get_login_qr(fake=True))
        assert data["ok"] is True
        from omni_music.auth.qr_login import FakeQRLoginFlow

        assert isinstance(tools._runtime.flow, FakeQRLoginFlow)


# ===========================================================================
# music_check_login_status
# ===========================================================================
class TestMusicCheckLoginStatus:
    def _start_login(self) -> str:
        """发起一次扫码登录并返回 key。"""
        data = _parse(tools.music_get_login_qr(fake=True))
        return data["data"]["key"]

    def test_status_waiting_first_poll(self) -> None:
        """首次轮询返回 waiting。"""
        key = self._start_login()
        data = _parse(tools.music_check_login_status(key=key, fake=True))
        assert data["ok"] is True
        assert data["data"]["status"] == "waiting"
        assert data["data"]["key"] == key

    def test_status_scanned_second_poll(self) -> None:
        """第二次轮询返回 scanned。"""
        key = self._start_login()
        tools.music_check_login_status(key=key, fake=True)
        data = _parse(tools.music_check_login_status(key=key, fake=True))
        assert data["data"]["status"] == "scanned"

    def test_status_confirmed_saves_cookie(self) -> None:
        """第三次轮询返回 confirmed 且 cookie_saved=True。"""
        key = self._start_login()
        tools.music_check_login_status(key=key, fake=True)
        tools.music_check_login_status(key=key, fake=True)
        data = _parse(tools.music_check_login_status(key=key, fake=True))
        assert data["data"]["status"] == "confirmed"
        assert data["data"]["cookie_saved"] is True

    def test_status_expired_via_custom_sequence(self) -> None:
        """自定义状态序列返回 expired。"""
        rt = tools._runtime
        rt.source = FakeMusicSource()
        rt.source.fake_login_status_sequence = ["waiting", "expired"]
        rt.store = FakeCookieStore()
        from omni_music.auth.qr_login import FakeQRLoginFlow

        rt.flow = FakeQRLoginFlow(source=rt.source, store=rt.store)
        rt.flow.start()
        key = rt.flow._key  # type: ignore[attr-defined]
        tools.music_check_login_status(key=key, fake=True)
        data = _parse(tools.music_check_login_status(key=key, fake=True))
        assert data["data"]["status"] == "expired"
        assert "cookie_saved" not in data["data"]

    def test_status_no_flow_returns_error(self) -> None:
        """未发起扫码登录（flow 为 None）返回 E_LOGIN_FAILED。"""
        data = _parse(tools.music_check_login_status(key="any", fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_LOGIN_FAILED"

    def test_status_key_mismatch_returns_error(self) -> None:
        """key 不匹配返回 E_LOGIN_FAILED。"""
        self._start_login()
        data = _parse(
            tools.music_check_login_status(key="wrong_key", fake=True)
        )
        assert data["ok"] is False
        assert data["error"]["code"] == "E_LOGIN_FAILED"
        assert "key 不匹配" in data["error"]["message"]

    def test_status_poll_exception_returns_error(self) -> None:
        """flow.poll 抛异常时返回 E_LOGIN_FAILED。"""
        rt = tools._runtime
        rt.source = FakeMusicSource()
        rt.store = FakeCookieStore()
        from omni_music.auth.qr_login import FakeQRLoginFlow

        class _BrokenFlow(FakeQRLoginFlow):
            def poll(self) -> str:
                raise RuntimeError("poll boom")

        rt.flow = _BrokenFlow(source=rt.source, store=rt.store)
        rt.flow.start()
        key = rt.flow._key  # type: ignore[attr-defined]
        data = _parse(tools.music_check_login_status(key=key, fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_LOGIN_FAILED"
        assert "poll boom" in data["error"]["message"]


# ===========================================================================
# music_play
# ===========================================================================
class TestMusicPlay:
    def test_play_no_source_returns_error(self) -> None:
        """未配置源返回 E_BACKEND_UNAVAILABLE。"""
        data = _parse(tools.music_play(fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_BACKEND_UNAVAILABLE"

    def test_play_song_id_mode(self) -> None:
        """song_id 模式：追加并播放该曲。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt, songs=[])  # 空队列起步
        data = _parse(tools.music_play(song_id="fake_song_2", fake=True))
        assert data["ok"] is True
        current = data["data"]["current_song"]
        assert current["id"] == "fake_song_2"
        state = data["data"]
        assert state["state"] == "playing"
        assert state["current_index"] == 0
        assert len(state["queue"]) == 1

    def test_play_song_id_not_found_returns_error(self) -> None:
        """song_id 不存在返回 E_SEARCH_FAILED。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt, songs=[])
        data = _parse(tools.music_play(song_id="not_exist", fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_SEARCH_FAILED"

    def test_play_index_mode(self) -> None:
        """index 模式：跳到指定索引播放。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)  # 3 首
        data = _parse(tools.music_play(index=2, fake=True))
        assert data["ok"] is True
        assert data["data"]["current_song"]["id"] == "fake_song_3"
        assert player.current_index == 2
        assert player.current_state is PlayerState.PLAYING

    def test_play_index_out_of_range_returns_error(self) -> None:
        """index 越界返回 E_INVALID_ARGS。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt)
        data = _parse(tools.music_play(index=99, fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "index 越界" in data["error"]["message"]

    def test_play_keyword_mode(self) -> None:
        """keyword 模式：搜索第一首追加并播放。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt, songs=[])
        data = _parse(tools.music_play(keyword="稻香", fake=True))
        assert data["ok"] is True
        assert data["data"]["current_song"]["id"] == "fake_song_2"
        state = data["data"]
        assert len(state["queue"]) == 1

    def test_play_keyword_no_match_returns_error(self) -> None:
        """keyword 无匹配返回 E_SEARCH_FAILED。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt, songs=[])
        data = _parse(tools.music_play(keyword="不存在的歌曲xyz", fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_SEARCH_FAILED"

    def test_play_resume_mode_with_queue(self) -> None:
        """无参模式：有队列时恢复当前曲目。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        # 先 stop 再 play 恢复
        player.stop()
        assert player.current_state is PlayerState.STOPPED
        data = _parse(tools.music_play(fake=True))
        assert data["ok"] is True
        assert data["data"]["state"] == "playing"

    def test_play_resume_empty_queue_returns_none_song(self) -> None:
        """无参模式 + 空队列：current_song=null 但 ok=True。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt, songs=[])
        data = _parse(tools.music_play(fake=True))
        assert data["ok"] is True
        assert data["data"]["current_song"] is None
        assert data["data"]["current_index"] == -1

    def test_play_writes_state_file(self, state_path: Path) -> None:
        """play 后写入 state_file。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt)
        tools.music_play(index=0, fake=True)
        assert state_path.is_file()
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["state"] == "playing"
        assert payload["current_index"] == 0
        assert "ts" in payload

    def test_play_song_id_priority_over_index(self) -> None:
        """song_id 与 index 同时传时优先 song_id。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt, songs=[])
        data = _parse(
            tools.music_play(song_id="fake_song_1", index=99, fake=True)
        )
        assert data["ok"] is True
        assert data["data"]["current_song"]["id"] == "fake_song_1"


# ===========================================================================
# music_pause / music_resume
# ===========================================================================
class TestMusicPauseResume:
    def test_pause_when_stopped_returns_error(self) -> None:
        """STOPPED 态 pause 返回 E_STATE_VIOLATION。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt)
        # player 初始 STOPPED
        data = _parse(tools.music_pause(fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_STATE_VIOLATION"

    def test_pause_when_playing_success(self) -> None:
        """PLAYING 态 pause 成功。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        player.play(0)
        data = _parse(tools.music_pause(fake=True))
        assert data["ok"] is True
        assert data["data"]["state"] == "paused"

    def test_resume_when_stopped_returns_error(self) -> None:
        """STOPPED 态 resume 返回 E_STATE_VIOLATION。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt)
        data = _parse(tools.music_resume(fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_STATE_VIOLATION"

    def test_resume_when_playing_returns_error(self) -> None:
        """PLAYING 态 resume 返回 E_STATE_VIOLATION。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        player.play(0)
        data = _parse(tools.music_resume(fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_STATE_VIOLATION"

    def test_resume_after_pause_success(self) -> None:
        """PAUSED → resume 成功恢复为 playing。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        player.play(0)
        player.pause()
        data = _parse(tools.music_resume(fake=True))
        assert data["ok"] is True
        assert data["data"]["state"] == "playing"

    def test_pause_no_source_returns_player_not_ready(self) -> None:
        """未配置源 pause 返回 E_PLAYER_NOT_READY。"""
        data = _parse(tools.music_pause(fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_PLAYER_NOT_READY"

    def test_pause_writes_state_file(self, state_path: Path) -> None:
        """pause 后写入 state_file。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        player.play(0)
        tools.music_pause(fake=True)
        assert state_path.is_file()
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["state"] == "paused"


# ===========================================================================
# music_stop / music_next / music_previous
# ===========================================================================
class TestMusicStopNextPrevious:
    def test_stop_success(self) -> None:
        """stop 成功；状态置为 stopped，position 清零。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        player.play(0)
        player.seek(30)
        assert player.position_s == 30
        data = _parse(tools.music_stop(fake=True))
        assert data["ok"] is True
        state = data["data"]
        assert state["state"] == "stopped"
        assert state["position_s"] == 0
        # 队列与索引保留
        assert len(state["queue"]) == 3
        assert state["current_index"] == 0

    def test_stop_no_source_returns_error(self) -> None:
        """未配置源 stop 返回 E_PLAYER_NOT_READY。"""
        data = _parse(tools.music_stop(fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_PLAYER_NOT_READY"

    def test_next_success_sequence_mode(self) -> None:
        """SEQUENCE 模式 next 推进索引。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        player.play(0)
        data = _parse(tools.music_next(fake=True))
        assert data["ok"] is True
        assert data["data"]["current_song"]["id"] == "fake_song_2"
        assert player.current_index == 1

    def test_next_empty_queue_returns_none_song(self) -> None:
        """空队列 next 返回 current_song=null 但 ok=True。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt, songs=[])
        data = _parse(tools.music_next(fake=True))
        assert data["ok"] is True
        assert data["data"]["current_song"] is None

    def test_next_sequence_end_stops(self) -> None:
        """SEQUENCE 模式到末尾 next 停止；state=stopped，队列末尾曲目仍驻留。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        player.play(2)  # 末尾
        data = _parse(tools.music_next(fake=True))
        assert data["ok"] is True
        # 扁平契约：to_state_dict 的 current_song 为 index-based（末尾曲目仍驻留），
        # state=stopped 表示播放已停止；current_index 保留指向末尾曲目便于恢复。
        assert data["data"]["state"] == "stopped"
        assert data["data"]["current_song"]["id"] == "fake_song_3"
        assert player.current_state is PlayerState.STOPPED

    def test_previous_success(self) -> None:
        """previous 回退索引。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        player.play(2)
        data = _parse(tools.music_previous(fake=True))
        assert data["ok"] is True
        assert data["data"]["current_song"]["id"] == "fake_song_2"
        assert player.current_index == 1

    def test_previous_at_zero_stays(self) -> None:
        """index=0 时 previous 保持 0。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        player.play(0)
        data = _parse(tools.music_previous(fake=True))
        assert data["ok"] is True
        assert player.current_index == 0

    def test_next_writes_state_file(self, state_path: Path) -> None:
        """next 后写入 state_file。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        player.play(0)
        tools.music_next(fake=True)
        assert state_path.is_file()


# ===========================================================================
# music_seek
# ===========================================================================
class TestMusicSeek:
    def test_seek_success(self) -> None:
        """seek 成功；position_s 更新。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        data = _parse(tools.music_seek(position_s=120, fake=True))
        assert data["ok"] is True
        assert player.position_s == 120
        assert data["data"]["position_s"] == 120

    def test_seek_negative_returns_error(self) -> None:
        """负数 position_s 返回 E_INVALID_ARGS。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt)
        data = _parse(tools.music_seek(position_s=-5, fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "不能为负" in data["error"]["message"]

    def test_seek_zero_allowed(self) -> None:
        """position_s=0 合法。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        player.seek(50)
        data = _parse(tools.music_seek(position_s=0, fake=True))
        assert data["ok"] is True
        assert player.position_s == 0

    def test_seek_no_source_returns_error(self) -> None:
        """未配置源 seek 返回 E_PLAYER_NOT_READY。"""
        data = _parse(tools.music_seek(position_s=10, fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_PLAYER_NOT_READY"

    def test_seek_writes_state_file(self, state_path: Path) -> None:
        """seek 后写入 state_file。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt)
        tools.music_seek(position_s=30, fake=True)
        assert state_path.is_file()
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["position_s"] == 30


# ===========================================================================
# music_set_repeat_mode
# ===========================================================================
class TestMusicSetRepeatMode:
    @pytest.mark.parametrize(
        "mode,expected",
        [
            ("single", RepeatMode.SINGLE),
            ("list_loop", RepeatMode.LIST_LOOP),
            ("random", RepeatMode.RANDOM),
            ("sequence", RepeatMode.SEQUENCE),
        ],
    )
    def test_set_mode_success(self, mode: str, expected: RepeatMode) -> None:
        """4 种合法 mode 设置成功。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        data = _parse(tools.music_set_repeat_mode(mode=mode, fake=True))
        assert data["ok"] is True
        assert data["data"]["repeat_mode"] == expected.value
        assert player.get_repeat_mode() is expected

    def test_set_mode_unknown_returns_error(self) -> None:
        """未知 mode 返回 E_INVALID_ARGS。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt)
        data = _parse(tools.music_set_repeat_mode(mode="shuffle", fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "未知 mode" in data["error"]["message"]

    def test_set_mode_no_source_returns_error(self) -> None:
        """未配置源返回 E_PLAYER_NOT_READY。"""
        data = _parse(tools.music_set_repeat_mode(mode="single", fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_PLAYER_NOT_READY"

    def test_set_mode_writes_state_file(self, state_path: Path) -> None:
        """set_repeat_mode 后写入 state_file。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt)
        tools.music_set_repeat_mode(mode="list_loop", fake=True)
        assert state_path.is_file()
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["repeat_mode"] == "list_loop"


# ===========================================================================
# music_get_player_state
# ===========================================================================
class TestMusicGetPlayerState:
    def test_state_returns_full_dict(self) -> None:
        """返回完整 to_state_dict 字段（扁平位于 data 顶层）。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        player.play(1)
        player.set_repeat_mode(RepeatMode.LIST_LOOP)
        player.seek(45)
        data = _parse(tools.music_get_player_state(fake=True))
        assert data["ok"] is True
        state = data["data"]
        assert state["queue"] is not None
        assert len(state["queue"]) == 3
        assert state["current_index"] == 1
        assert state["state"] == "playing"
        assert state["repeat_mode"] == "list_loop"
        assert state["position_s"] == 45
        assert state["current_song"]["id"] == "fake_song_2"

    def test_state_empty_queue(self) -> None:
        """空队列时 current_song=null。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt, songs=[])
        data = _parse(tools.music_get_player_state(fake=True))
        assert data["ok"] is True
        state = data["data"]
        assert state["queue"] == []
        assert state["current_index"] == -1
        assert state["current_song"] is None
        assert state["state"] == "stopped"

    def test_state_no_source_returns_error(self) -> None:
        """未配置源返回 E_PLAYER_NOT_READY。"""
        data = _parse(tools.music_get_player_state(fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_PLAYER_NOT_READY"


# ===========================================================================
# _get_player / 后端选择
# ===========================================================================
class TestBackendSelection:
    def test_get_source_fake_caches(self) -> None:
        """_get_source(fake=True) 缓存 FakeMusicSource 实例。"""
        rt = tools._runtime
        s1 = tools._get_source(rt, fake=True)
        s2 = tools._get_source(rt, fake=False)  # 已缓存，不再构造
        assert s1 is s2
        assert rt.fake_mode is True

    def test_get_source_real_returns_none(self) -> None:
        """_get_source(fake=False) 未预置时返回 None。"""
        rt = tools._runtime
        assert tools._get_source(rt, fake=False) is None

    def test_get_store_fake_caches(self) -> None:
        """_get_store(fake=True) 缓存 FakeCookieStore。"""
        rt = tools._runtime
        st1 = tools._get_store(rt, fake=True)
        st2 = tools._get_store(rt, fake=False)
        assert st1 is st2

    def test_get_store_real_constructs_cookie_store(self) -> None:
        """_get_store(fake=False) 构造真实 CookieStore。"""
        rt = tools._runtime
        st = tools._get_store(rt, fake=False)
        from omni_music.auth.cookie_store import CookieStore

        assert isinstance(st, CookieStore)

    def test_get_player_lazy_constructs(self) -> None:
        """_get_player 未预置时用当前 source 构造 MusicPlayer。"""
        rt = tools._runtime
        rt.source = FakeMusicSource()
        player = tools._get_player(rt, fake=False)
        assert player is not None
        assert isinstance(player, MusicPlayer)
        # 缓存
        assert tools._get_player(rt, fake=False) is player

    def test_get_player_no_source_returns_none(self) -> None:
        """_get_player 未预置 source 且非 fake 时返回 None。"""
        rt = tools._runtime
        assert tools._get_player(rt, fake=False) is None

    def test_get_player_fake_creates_fake_source(self) -> None:
        """_get_player(fake=True) 同时构造 FakeMusicSource + MusicPlayer。"""
        rt = tools._runtime
        player = tools._get_player(rt, fake=True)
        assert player is not None
        assert rt.source is not None
        assert isinstance(rt.source, FakeMusicSource)
        assert rt.player is player

    def test_get_player_preset_player_kept(self) -> None:
        """预置 player 后 _get_player 直接返回，不重新构造。"""
        rt = tools._runtime
        custom = MusicPlayer(source=FakeMusicSource())
        rt.player = custom
        assert tools._get_player(rt, fake=False) is custom


# ===========================================================================
# _make_handler 适配
# ===========================================================================
class TestMakeHandler:
    def test_handler_args_dict(self) -> None:
        """_make_handler 包装的 handler 接受 args dict。"""
        rt = tools._reset_runtime()
        rt.source = FakeMusicSource()
        from omni_music.tools import _make_handler, music_search

        handler = _make_handler(music_search)
        result = handler({"keyword": "晴天", "fake": False})
        data = _parse(result)
        assert data["ok"] is True

    def test_handler_invalid_args_returns_error(self) -> None:
        """_make_handler 收到非法参数：内部 except 返回 E_SEARCH_FAILED。"""
        from omni_music.tools import _make_handler, music_search

        handler = _make_handler(music_search)
        # 故意传 keyword 为 int（FakeMusicSource.search 用 `in` 操作，int 会抛 TypeError）
        result = handler({"keyword": 123, "fake": True})
        data = _parse(result)
        assert data["ok"] is False
        assert data["error"]["code"] == "E_SEARCH_FAILED"

    def test_handler_no_args_uses_defaults(self) -> None:
        """_make_handler 无 args 时使用默认参数。"""
        rt = tools._reset_runtime()
        rt.source = FakeMusicSource()
        from omni_music.tools import _make_handler, music_search

        handler = _make_handler(music_search)
        # music_search 的 keyword 是 required；缺省会抛 TypeError → E_INVALID_ARGS
        result = handler({})
        data = _parse(result)
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"

    def test_handler_play_with_args(self) -> None:
        """_make_handler 包装 music_play 接受 args dict。"""
        rt = tools._reset_runtime()
        rt.source = FakeMusicSource()
        rt.player = MusicPlayer(source=rt.source)
        rt.player.set_queue(list(rt.source.songs))
        from omni_music.tools import _make_handler, music_play

        handler = _make_handler(music_play)
        result = handler({"index": 0, "fake": False})
        data = _parse(result)
        assert data["ok"] is True
        assert data["data"]["current_song"]["id"] == "fake_song_1"

    def test_handler_unknown_kwarg_raises_invalid_args(self) -> None:
        """_make_handler 收到未知 kwarg 返回 E_INVALID_ARGS。"""
        from omni_music.tools import _make_handler, music_stop

        handler = _make_handler(music_stop)
        result = handler({"unknown_arg": "x", "fake": True})
        data = _parse(result)
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"


# ===========================================================================
# state_file 原子写入
# ===========================================================================
class TestStateFile:
    def test_write_state_file_atomic(self, state_path: Path) -> None:
        """_write_state_file 原子写入 JSON。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        player.play(0)
        tools._write_state_file(player)
        assert state_path.is_file()
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["state"] == "playing"
        assert payload["current_index"] == 0
        assert len(payload["queue"]) == 3
        assert "ts" in payload

    def test_write_state_file_silent_on_failure(
        self, monkeypatch, tmp_path
    ) -> None:
        """_write_state_file 写入失败时静默吞掉异常。"""
        # 指向一个不可写路径（父目录是文件）
        blocker = tmp_path / "blocker"
        blocker.write_text("x")
        bad_path = blocker / "music_state.json"
        monkeypatch.setenv("AI_OMNI_MUSIC_STATE_FILE", str(bad_path))
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)
        # 不应抛异常
        tools._write_state_file(player)
        # 文件未生成
        assert not bad_path.exists()

    def test_no_state_file_when_get_only(self, state_path: Path) -> None:
        """music_get_player_state 是只读，不写 state_file。"""
        rt = tools._runtime
        _prepare_player_with_queue(rt)
        tools.music_get_player_state(fake=True)
        # get_player_state 不主动写文件
        assert not state_path.exists()

    def test_state_file_default_path_when_env_unset(
        self, monkeypatch, tmp_path
    ) -> None:
        """未设 env 时使用默认 ~/.ai-omni/state/music_state.json。

        这里只验证 _state_file_path() 的回退逻辑，不真正写家目录。
        """
        monkeypatch.delenv("AI_OMNI_MUSIC_STATE_FILE", raising=False)
        path = tools._state_file_path()
        assert path.name == "music_state.json"
        assert ".ai-omni" in path.parts


# ===========================================================================
# 异常捕获（fake 抛异常 → E_*）
# ===========================================================================
class TestExceptionHandling:
    def test_play_source_search_exception_returns_search_failed(self) -> None:
        """keyword 模式 source.search 抛异常返回 E_SEARCH_FAILED。"""
        rt = tools._runtime

        class _BrokenSource(FakeMusicSource):
            def search(self, keyword: str, limit: int = 20) -> list:
                raise RuntimeError("search boom")

        rt.source = _BrokenSource()
        rt.player = MusicPlayer(source=rt.source)
        data = _parse(tools.music_play(keyword="x", fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_SEARCH_FAILED"

    def test_play_song_detail_exception_returns_search_failed(self) -> None:
        """song_id 模式 source.get_song_detail 抛异常返回 E_SEARCH_FAILED。"""
        rt = tools._runtime

        class _BrokenSource(FakeMusicSource):
            def get_song_detail(self, song_id: str) -> Song | None:
                raise RuntimeError("detail boom")

        rt.source = _BrokenSource()
        rt.player = MusicPlayer(source=rt.source)
        data = _parse(tools.music_play(song_id="fake_song_1", fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_SEARCH_FAILED"

    def test_next_player_exception_returns_invalid_args(self) -> None:
        """player.next 抛异常返回 E_INVALID_ARGS。"""
        rt = tools._runtime
        player = _prepare_player_with_queue(rt)

        class _BrokenPlayer(MusicPlayer):
            def next(self) -> Song | None:
                raise RuntimeError("next boom")

        # 替换 rt.player 为 BrokenPlayer 但保留相同队列
        broken = _BrokenPlayer(source=rt.source)
        broken.set_queue(list(player.get_queue()))
        rt.player = broken
        data = _parse(tools.music_next(fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"


# ===========================================================================
# 注册入口 + 工具元数据 + schema 合法性
# ===========================================================================
class TestRegisterAndMetadata:
    def test_tools_count(self) -> None:
        """TOOLS 注册表含 20 个工具（M17 12 + M19 8 library/playlist/decrypt）。"""
        assert len(tools.TOOLS) == 20

    def test_tools_have_required_fields(self) -> None:
        """每个工具元数据含 name/description/emoji/schema/handler_func。"""
        for meta in tools.TOOLS:
            assert meta["name"]
            assert meta["description"]
            assert meta["emoji"]
            assert "schema" in meta
            assert callable(meta["handler_func"])

    def test_tools_all_params_have_type_and_description(self) -> None:
        """每个工具 schema 的每个参数都有 type 与 description。"""
        for meta in tools.TOOLS:
            props = meta["schema"]["parameters"]["properties"]
            assert props, f"{meta['name']} 应至少有一个参数（含 fake）"
            for pname, pschema in props.items():
                assert "type" in pschema, f"{meta['name']}.{pname} 缺 type"
                assert "description" in pschema, f"{meta['name']}.{pname} 缺 description"

    def test_all_tool_names_must_prefix(self) -> None:
        """所有工具名以 music_ 开头。"""
        for meta in tools.TOOLS:
            assert meta["name"].startswith("music_")

    def test_register_registers_twenty_tools(self) -> None:
        """register(ctx) 注册 20 个工具到 ctx（M17 12 + M19 8）。"""

        class _Ctx:
            def __init__(self) -> None:
                self.tools: list[dict[str, Any]] = []

            def register_tool(self, **kwargs: Any) -> None:
                self.tools.append(kwargs)

        ctx = _Ctx()
        tools.register(ctx)
        assert len(ctx.tools) == 20
        names = [t["name"] for t in ctx.tools]
        expected = [
            "music_search",
            "music_get_login_qr",
            "music_check_login_status",
            "music_play",
            "music_pause",
            "music_resume",
            "music_stop",
            "music_next",
            "music_previous",
            "music_seek",
            "music_set_repeat_mode",
            "music_get_player_state",
            # M19 library / playlist / decrypt
            "music_library_scan",
            "music_library_search",
            "music_library_status",
            "music_playlist_create",
            "music_playlist_add",
            "music_playlist_remove",
            "music_playlist_list",
            "music_decrypt_file",
        ]
        for name in expected:
            assert name in names, f"缺少工具: {name}"

    def test_music_search_schema_has_keyword_str(self) -> None:
        """music_search schema 的 keyword 参数为 string 类型。"""
        meta = next(t for t in tools.TOOLS if t["name"] == "music_search")
        props = meta["schema"]["parameters"]["properties"]
        assert props["keyword"]["type"] == "string"
        assert "keyword" in meta["schema"]["parameters"]["required"]

    def test_music_get_login_qr_schema_has_fake_param(self) -> None:
        """music_get_login_qr schema 含 fake 参数。"""
        meta = next(t for t in tools.TOOLS if t["name"] == "music_get_login_qr")
        props = meta["schema"]["parameters"]["properties"]
        assert "fake" in props

    def test_music_check_login_status_schema(self) -> None:
        """music_check_login_status schema：key 为 string 且 required。"""
        meta = next(
            t for t in tools.TOOLS if t["name"] == "music_check_login_status"
        )
        props = meta["schema"]["parameters"]["properties"]
        assert props["key"]["type"] == "string"
        assert meta["schema"]["parameters"]["required"] == ["key"]

    def test_music_play_schema_no_required(self) -> None:
        """music_play 无必填参数（四种模式可任选其一或都不传）。"""
        meta = next(t for t in tools.TOOLS if t["name"] == "music_play")
        assert meta["schema"]["parameters"]["required"] == []
        props = meta["schema"]["parameters"]["properties"]
        assert "song_id" in props
        assert "index" in props
        assert "keyword" in props
        assert props["index"]["type"] == "integer"
        assert props["song_id"]["type"] == "string"

    def test_music_seek_schema_required_position(self) -> None:
        """music_seek schema：position_s 为 integer 且 required。"""
        meta = next(t for t in tools.TOOLS if t["name"] == "music_seek")
        props = meta["schema"]["parameters"]["properties"]
        assert props["position_s"]["type"] == "integer"
        assert meta["schema"]["parameters"]["required"] == ["position_s"]

    def test_music_set_repeat_mode_schema_enum(self) -> None:
        """music_set_repeat_mode schema：mode 含 enum 约束。"""
        meta = next(
            t for t in tools.TOOLS if t["name"] == "music_set_repeat_mode"
        )
        props = meta["schema"]["parameters"]["properties"]
        assert props["mode"]["type"] == "string"
        assert props["mode"]["enum"] == [
            "single",
            "list_loop",
            "random",
            "sequence",
        ]
        assert meta["schema"]["parameters"]["required"] == ["mode"]

    def test_tool_emojis_distinct(self) -> None:
        """12 个工具 emoji 非空（CLI 展示契约）。"""
        emojis = [meta["emoji"] for meta in tools.TOOLS]
        assert all(emojis), "存在空 emoji"
        # 关键工具 emoji 唯一性（play/pause/resume/stop/next/previous/seek/repeat/state/search/login）
        key_names = [
            "music_search",
            "music_get_login_qr",
            "music_check_login_status",
            "music_play",
            "music_pause",
            "music_resume",
            "music_stop",
            "music_next",
            "music_previous",
            "music_seek",
            "music_set_repeat_mode",
            "music_get_player_state",
        ]
        emoji_by_name = {
            m["name"]: m["emoji"] for m in tools.TOOLS if m["name"] in key_names
        }
        assert len(emoji_by_name) == 12
        # play/pause/stop/next/previous/seek/repeat/state 各不同
        distinct = {
            "music_play",
            "music_pause",
            "music_resume",
            "music_stop",
            "music_next",
            "music_previous",
            "music_seek",
            "music_set_repeat_mode",
            "music_get_player_state",
        }
        sub = {k: emoji_by_name[k] for k in distinct}
        assert len(set(sub.values())) == len(distinct), f"控制工具 emoji 重复: {sub}"
