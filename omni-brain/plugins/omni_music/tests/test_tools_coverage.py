"""omni_music tools 层覆盖率补全测试（M32 覆盖率提升）。

针对 test_tools.py / test_library_tools.py 未覆盖的分支补测：

- ``_write_state_file``：os.replace 失败后的临时文件清理（含 unlink OSError 兜底）
- ``load_player_from_state_file``：player 已预置 / 状态文件损坏两条路径
- ``_publish_event``：事件总线发布成功（附 timestamp/source 元数据）与发布失败静默
- ``music_check_login_status``：flow 已构造但未 start（_key 为空）
- ``music_play``：song_id / keyword 模式下 source 缺失（E_BACKEND_UNAVAILABLE）
- 播放控制工具外层 except（player 方法抛非预期异常 → E_INVALID_ARGS）
- ``music_resume`` / ``music_next`` / ``music_previous`` 的 E_PLAYER_NOT_READY
- ``_LibraryRuntime.close``：db.close 抛异常静默
- ``music_library_scan``：真实扫描器空目录分支 + 扫描异常 → E_SCAN_FAILED
- library/playlist 工具外层 except（fake db 注入）
- ``music_decrypt_file``：E_DECRYPT_KEY_MISSING（真实 mflac 无密钥）与外层 except
- ``set_volume_gain``：增益设置与 [0.0, 2.0] 钳制

全部 fake 注入，不访问真实网络 / 音频硬件 / 模型文件。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from omni_music import tools
from omni_music.auth.cookie_store import FakeCookieStore
from omni_music.auth.qr_login import FakeQRLoginFlow
from omni_music.models import Song
from omni_music.player import MusicPlayer
from omni_music.sources.base import FakeMusicSource


def _parse(result: str) -> dict:
    """工具返回 JSON 字符串 → dict。"""
    assert isinstance(result, str)
    return json.loads(result)


@pytest.fixture(autouse=True)
def fresh_runtimes(tmp_path: Path, monkeypatch) -> Any:
    """每个测试前重置主运行时 + library 运行时，state_file / DB 指向临时目录。"""
    monkeypatch.setenv("AI_OMNI_MUSIC_STATE_FILE", str(tmp_path / "music_state.json"))
    monkeypatch.setenv("AI_OMNI_MUSIC_DB", str(tmp_path / "library.db"))
    tools._reset_runtime()
    tools._reset_library_runtime()
    yield tmp_path


def _prepare_player(rt: Any) -> MusicPlayer:
    """预置 fake source + player（3 首内置队列）。"""
    rt.source = FakeMusicSource()
    rt.player = MusicPlayer(source=rt.source)
    rt.player.set_queue(list(rt.source.songs))
    return rt.player


# ===========================================================================
# _write_state_file：replace 失败后的临时文件清理
# ===========================================================================
class TestWriteStateFileCleanup:
    def test_replace_failure_cleans_tmp_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """os.replace 抛异常：静默吞掉且临时文件被清理。"""
        rt = tools._runtime
        player = _prepare_player(rt)

        def _boom_replace(src: Any, dst: Any) -> None:
            raise OSError("replace boom")

        monkeypatch.setattr(os, "replace", _boom_replace)
        tools._write_state_file(player)  # 不抛
        # 临时文件已清理，目标文件未生成
        assert list(tmp_path.glob(".music_state.json.*.tmp")) == []
        assert not (tmp_path / "music_state.json").exists()

    def test_tmp_unlink_oserror_swallowed(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """replace 失败且临时文件 unlink 也 OSError：双重失败仍静默。"""
        rt = tools._runtime
        player = _prepare_player(rt)

        def _boom_replace(src: Any, dst: Any) -> None:
            raise OSError("replace boom")

        def _boom_unlink(self: Any, *args: Any, **kwargs: Any) -> None:
            raise OSError("unlink boom")

        monkeypatch.setattr(os, "replace", _boom_replace)
        monkeypatch.setattr(Path, "unlink", _boom_unlink)
        tools._write_state_file(player)  # 不抛


# ===========================================================================
# load_player_from_state_file
# ===========================================================================
class TestLoadPlayerFromStateFile:
    def test_returns_preset_player_without_reading_file(self, tmp_path: Path) -> None:
        """rt.player 已预置时直接返回，不读 state_file。"""
        rt = tools._runtime
        player = _prepare_player(rt)
        # state_file 不存在也应直接返回预置 player
        loaded = tools.load_player_from_state_file(rt, fake=False)
        assert loaded is player

    def test_corrupt_state_content_returns_none(self, tmp_path: Path) -> None:
        """state_file JSON 合法但内容损坏（非法 state 枚举）→ 恢复失败返回 None。"""
        rt = tools._runtime
        rt.source = FakeMusicSource()
        state_path = tmp_path / "music_state.json"
        state_path.write_text(
            json.dumps({"state": "bogus_state", "queue": []}), encoding="utf-8"
        )
        loaded = tools.load_player_from_state_file(rt, fake=False)
        assert loaded is None
        assert rt.player is None


# ===========================================================================
# _publish_event：事件总线发布
# ===========================================================================
class TestPublishEvent:
    def test_publish_success_adds_meta_fields(self) -> None:
        """接入事件总线后发布成功，payload 附带 timestamp/source 元数据。"""
        rt = tools._runtime

        class _FakeBus:
            def __init__(self) -> None:
                self.events: list[tuple[str, dict]] = []

            async def publish(self, event_type: str, payload: dict) -> None:
                self.events.append((event_type, payload))

        bus = _FakeBus()
        rt.event_publisher = bus
        tools._publish_event("music.test_event", {"track_id": "t1"})
        assert len(bus.events) == 1
        event_type, payload = bus.events[0]
        assert event_type == "music.test_event"
        assert payload["track_id"] == "t1"
        assert payload["source"] == "omni_music"
        assert "timestamp" in payload

    def test_publish_failure_silent(self, monkeypatch) -> None:
        """发布桥接抛异常被吞，不向调用方传播。"""
        rt = tools._runtime

        class _FakeBus:
            async def publish(self, event_type: str, payload: dict) -> None:
                pass

        rt.event_publisher = _FakeBus()

        import omni_sdk.utils

        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("publish boom")

        monkeypatch.setattr(omni_sdk.utils, "sync_to_async_publish", _boom)
        tools._publish_event("music.test_event", {"k": "v"})  # 不抛

    def test_publish_via_play_tool_emits_started(self) -> None:
        """music_play 播放成功经总线发布 music.started 事件。"""
        rt = tools._runtime

        class _FakeBus:
            def __init__(self) -> None:
                self.events: list[tuple[str, dict]] = []

            async def publish(self, event_type: str, payload: dict) -> None:
                self.events.append((event_type, payload))

        bus = _FakeBus()
        rt.event_publisher = bus
        _prepare_player(rt)
        data = _parse(tools.music_play(index=0, fake=True))
        assert data["ok"] is True
        started = [e for e in bus.events if e[0] == "music.started"]
        assert len(started) == 1
        assert started[0][1]["track_id"] == "fake_song_1"


# ===========================================================================
# music_check_login_status：flow 未 start（_key 为空）
# ===========================================================================
class TestCheckLoginStatusFlowNotStarted:
    def test_flow_without_start_returns_error(self) -> None:
        """flow 已构造但未 start（_key=None）返回 E_LOGIN_FAILED。"""
        rt = tools._runtime
        rt.source = FakeMusicSource()
        rt.store = FakeCookieStore()
        rt.flow = FakeQRLoginFlow(source=rt.source, store=rt.store)
        # 不调 start()，_key 保持 None
        data = _parse(tools.music_check_login_status(key="any", fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_LOGIN_FAILED"
        assert "未启动" in data["error"]["message"]


# ===========================================================================
# music_play：song_id / keyword 模式下 source 缺失
# ===========================================================================
class TestPlaySourceMissingBranches:
    def test_play_song_id_source_none_returns_error(self) -> None:
        """预置 player 但无 source：song_id 模式返回 E_BACKEND_UNAVAILABLE。"""
        rt = tools._runtime
        # player 预置（绑定一个 fake source），但 rt.source 保持 None
        rt.player = MusicPlayer(source=FakeMusicSource())
        data = _parse(tools.music_play(song_id="fake_song_1", fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_BACKEND_UNAVAILABLE"

    def test_play_keyword_source_none_returns_error(self) -> None:
        """预置 player 但无 source：keyword 模式返回 E_BACKEND_UNAVAILABLE。"""
        rt = tools._runtime
        rt.player = MusicPlayer(source=FakeMusicSource())
        data = _parse(tools.music_play(keyword="晴天", fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_BACKEND_UNAVAILABLE"


# ===========================================================================
# 播放控制工具外层 except（player 方法抛非预期异常）
# ===========================================================================
class TestPlayerToolOuterExcept:
    def test_play_unexpected_error_returns_invalid_args(self) -> None:
        """无参 play 时 player.play 抛非 IndexError 异常 → E_INVALID_ARGS。"""
        rt = tools._runtime

        class _BrokenPlayer(MusicPlayer):
            def play(self, index: int | None = None) -> Song | None:
                raise RuntimeError("play boom")

        rt.source = FakeMusicSource()
        rt.player = _BrokenPlayer(source=rt.source)
        data = _parse(tools.music_play(fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "play boom" in data["error"]["message"]

    def test_pause_unexpected_error_returns_invalid_args(self) -> None:
        """player.pause 抛非 RuntimeError 异常 → 外层 E_INVALID_ARGS。"""
        rt = tools._runtime

        class _BrokenPlayer(MusicPlayer):
            def pause(self) -> None:
                raise ValueError("pause boom")

        rt.source = FakeMusicSource()
        rt.player = _BrokenPlayer(source=rt.source)
        data = _parse(tools.music_pause(fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "pause boom" in data["error"]["message"]

    def test_resume_unexpected_error_returns_invalid_args(self) -> None:
        """player.resume 抛非 RuntimeError 异常 → 外层 E_INVALID_ARGS。"""
        rt = tools._runtime

        class _BrokenPlayer(MusicPlayer):
            def resume(self) -> None:
                raise ValueError("resume boom")

        rt.source = FakeMusicSource()
        rt.player = _BrokenPlayer(source=rt.source)
        data = _parse(tools.music_resume(fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "resume boom" in data["error"]["message"]

    def test_stop_unexpected_error_returns_invalid_args(self) -> None:
        """player.stop 抛异常 → E_INVALID_ARGS。"""
        rt = tools._runtime

        class _BrokenPlayer(MusicPlayer):
            def stop(self) -> None:
                raise RuntimeError("stop boom")

        rt.source = FakeMusicSource()
        rt.player = _BrokenPlayer(source=rt.source)
        data = _parse(tools.music_stop(fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "stop boom" in data["error"]["message"]

    def test_previous_unexpected_error_returns_invalid_args(self) -> None:
        """player.previous 抛异常 → E_INVALID_ARGS。"""
        rt = tools._runtime

        class _BrokenPlayer(MusicPlayer):
            def previous(self) -> Song | None:
                raise RuntimeError("previous boom")

        rt.source = FakeMusicSource()
        rt.player = _BrokenPlayer(source=rt.source)
        data = _parse(tools.music_previous(fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "previous boom" in data["error"]["message"]

    def test_seek_value_error_returns_invalid_args(self) -> None:
        """player.seek 抛 ValueError → 内层 E_INVALID_ARGS。"""
        rt = tools._runtime

        class _BrokenPlayer(MusicPlayer):
            def seek(self, position_s: int) -> None:
                raise ValueError("seek value boom")

        rt.source = FakeMusicSource()
        rt.player = _BrokenPlayer(source=rt.source)
        data = _parse(tools.music_seek(position_s=10, fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "seek value boom" in data["error"]["message"]

    def test_seek_unexpected_error_returns_invalid_args(self) -> None:
        """player.seek 抛非 ValueError 异常 → 外层 E_INVALID_ARGS。"""
        rt = tools._runtime

        class _BrokenPlayer(MusicPlayer):
            def seek(self, position_s: int) -> None:
                raise RuntimeError("seek boom")

        rt.source = FakeMusicSource()
        rt.player = _BrokenPlayer(source=rt.source)
        data = _parse(tools.music_seek(position_s=10, fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "seek boom" in data["error"]["message"]

    def test_set_repeat_mode_unexpected_error_returns_invalid_args(self) -> None:
        """player.set_repeat_mode 抛异常 → E_INVALID_ARGS。"""
        rt = tools._runtime

        class _BrokenPlayer(MusicPlayer):
            def set_repeat_mode(self, mode: Any) -> None:
                raise RuntimeError("repeat boom")

        rt.source = FakeMusicSource()
        rt.player = _BrokenPlayer(source=rt.source)
        data = _parse(tools.music_set_repeat_mode(mode="single", fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "repeat boom" in data["error"]["message"]

    def test_get_player_state_unexpected_error_returns_invalid_args(self) -> None:
        """player.to_state_dict 抛异常 → E_INVALID_ARGS。"""
        rt = tools._runtime

        class _BrokenPlayer(MusicPlayer):
            def to_state_dict(self) -> dict:
                raise RuntimeError("state boom")

        rt.source = FakeMusicSource()
        rt.player = _BrokenPlayer(source=rt.source)
        data = _parse(tools.music_get_player_state(fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "state boom" in data["error"]["message"]


# ===========================================================================
# E_PLAYER_NOT_READY 补全（resume / next / previous）
# ===========================================================================
class TestPlayerNotReady:
    def test_resume_no_source_returns_player_not_ready(self) -> None:
        """未配置源 resume 返回 E_PLAYER_NOT_READY。"""
        data = _parse(tools.music_resume(fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_PLAYER_NOT_READY"

    def test_next_no_source_returns_player_not_ready(self) -> None:
        """未配置源 next 返回 E_PLAYER_NOT_READY。"""
        data = _parse(tools.music_next(fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_PLAYER_NOT_READY"

    def test_previous_no_source_returns_player_not_ready(self) -> None:
        """未配置源 previous 返回 E_PLAYER_NOT_READY。"""
        data = _parse(tools.music_previous(fake=False))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_PLAYER_NOT_READY"


# ===========================================================================
# _LibraryRuntime.close：db.close 异常静默
# ===========================================================================
class TestLibraryRuntimeClose:
    def test_close_swallows_db_close_error(self) -> None:
        """db.close 抛异常被吞，runtime 各单例仍被清空。"""

        class _BrokenDB:
            def close(self) -> None:
                raise RuntimeError("close boom")

        lrt = tools._library_runtime
        lrt.db = _BrokenDB()
        lrt.scanner = object()
        lrt.watcher = object()
        tools._reset_library_runtime()  # 内部调 close()，不抛
        assert tools._library_runtime.db is None
        assert tools._library_runtime.scanner is None
        assert tools._library_runtime.watcher is None


# ===========================================================================
# music_library_scan：真实扫描器分支 + 异常路径
# ===========================================================================
class TestLibraryScanRealBranch:
    def test_scan_real_empty_dir_returns_zero_counts(self, tmp_path: Path) -> None:
        """非 fake 模式扫描空目录：构造真实 LibraryScanner，统计全 0。"""
        music_dir = tmp_path / "music"
        music_dir.mkdir()
        data = _parse(tools.music_library_scan(root_dir=str(music_dir), fake=False))
        assert data["ok"] is True
        result = data["data"]
        assert result["scanned"] == 0
        assert result["added"] == 0
        assert result["errors"] == 0

    def test_scan_failure_returns_scan_failed(self) -> None:
        """scanner.scan 抛异常 → E_SCAN_FAILED。"""
        lrt = tools._library_runtime

        class _BrokenScanner:
            def scan(self) -> dict:
                raise RuntimeError("scan boom")

        lrt.fake_scanner = _BrokenScanner()
        data = _parse(tools.music_library_scan(fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_SCAN_FAILED"
        assert "scan boom" in data["error"]["message"]


# ===========================================================================
# library / playlist 工具外层 except（fake db 注入）
# ===========================================================================
class TestLibraryToolOuterExcept:
    def test_library_search_db_error_returns_search_failed(self) -> None:
        """db.search 抛异常 → E_SEARCH_FAILED。"""
        lrt = tools._library_runtime

        class _BrokenDB:
            def search(self, query: str, limit: int = 20) -> list:
                raise RuntimeError("search boom")

        lrt.db = _BrokenDB()
        data = _parse(tools.music_library_search(query="x", fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_SEARCH_FAILED"
        assert "search boom" in data["error"]["message"]

    def test_library_status_db_error_returns_invalid_args(self) -> None:
        """db.get_status 抛异常 → E_INVALID_ARGS。"""
        lrt = tools._library_runtime

        class _BrokenDB:
            def get_status(self) -> dict:
                raise RuntimeError("status boom")

        lrt.db = _BrokenDB()
        data = _parse(tools.music_library_status(fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "status boom" in data["error"]["message"]

    def test_playlist_create_db_error_returns_invalid_args(self) -> None:
        """db.create_playlist 抛异常 → E_INVALID_ARGS。"""
        lrt = tools._library_runtime

        class _BrokenDB:
            def create_playlist(self, name: str) -> int:
                raise RuntimeError("create boom")

        lrt.db = _BrokenDB()
        data = _parse(tools.music_playlist_create(name="我的歌单", fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "create boom" in data["error"]["message"]

    def test_playlist_add_db_error_returns_invalid_args(self) -> None:
        """db.add_to_playlist 抛异常 → E_INVALID_ARGS。"""
        lrt = tools._library_runtime

        class _BrokenDB:
            def get_song(self, song_id: str) -> dict:
                return {"id": song_id}  # 歌曲存在，进入 add_to_playlist

            def add_to_playlist(
                self, playlist_id: int, song_id: str, position: Any = None
            ) -> None:
                raise RuntimeError("add boom")

        lrt.db = _BrokenDB()
        data = _parse(
            tools.music_playlist_add(playlist_id=1, song_id="s1", fake=True)
        )
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "add boom" in data["error"]["message"]

    def test_playlist_remove_db_error_returns_invalid_args(self) -> None:
        """db.remove_from_playlist 抛异常 → E_INVALID_ARGS。"""
        lrt = tools._library_runtime

        class _BrokenDB:
            def remove_from_playlist(self, playlist_id: int, song_id: str) -> None:
                raise RuntimeError("remove boom")

        lrt.db = _BrokenDB()
        data = _parse(
            tools.music_playlist_remove(playlist_id=1, song_id="s1", fake=True)
        )
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "remove boom" in data["error"]["message"]

    def test_playlist_list_db_error_returns_invalid_args(self) -> None:
        """db.get_playlists 抛异常 → E_INVALID_ARGS。"""
        lrt = tools._library_runtime

        class _BrokenDB:
            def get_playlists(self) -> list:
                raise RuntimeError("list boom")

        lrt.db = _BrokenDB()
        data = _parse(tools.music_playlist_list(fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"
        assert "list boom" in data["error"]["message"]


# ===========================================================================
# music_decrypt_file：E_DECRYPT_KEY_MISSING 与外层 except
# ===========================================================================
class TestDecryptFileErrorBranches:
    def test_decrypt_mflac_without_key_returns_key_missing(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """mflac 格式缺密钥 → E_DECRYPT_KEY_MISSING。"""
        monkeypatch.delenv("AI_OMNNI_MUSIC_KEY", raising=False)
        src = tmp_path / "song.mflac"
        src.write_bytes(b"\x00" * 32)
        data = _parse(tools.music_decrypt_file(path=str(src), confirm=True, fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_DECRYPT_KEY_MISSING"

    def test_decrypt_unexpected_error_returns_decrypt_failed(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """decryptor.decrypt 抛非预期异常 → 外层 E_DECRYPT_FAILED。"""
        import omni_music.library.decryptor as decryptor_mod

        class _BrokenDecryptor:
            def is_supported(self, path: str) -> bool:
                return True

            def decrypt(self, path: str, output_path: str | None = None) -> str:
                raise ZeroDivisionError("decrypt boom")

        monkeypatch.setattr(decryptor_mod, "AudioDecryptor", _BrokenDecryptor)
        src = tmp_path / "song.qmc0"
        src.write_bytes(b"\x00" * 16)
        data = _parse(tools.music_decrypt_file(path=str(src), confirm=True, fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_DECRYPT_FAILED"
        assert "decrypt boom" in data["error"]["message"]


# ===========================================================================
# set_volume_gain
# ===========================================================================
class TestSetVolumeGain:
    def test_set_gain_within_range(self) -> None:
        """正常范围增益直接设置。"""
        tools.set_volume_gain(1.5)
        assert tools._runtime.volume_gain == 1.5

    def test_set_gain_clamped_high(self) -> None:
        """超过 2.0 钳制到 2.0。"""
        tools.set_volume_gain(99.0)
        assert tools._runtime.volume_gain == 2.0

    def test_set_gain_clamped_low(self) -> None:
        """低于 0.0 钳制到 0.0。"""
        tools.set_volume_gain(-1.0)
        assert tools._runtime.volume_gain == 0.0
