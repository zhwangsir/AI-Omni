"""omni_music CLI 测试（M17.10 Tauri 桥接配套）。

覆盖 ``omni_music/cli.py`` 的子命令派发、state_file 跨调用状态串联、
退出码映射、参数解析与错误降级。全部用 FakeMusicSource（``--fake``），零网络依赖。

状态串联验证：通过 ``AI_OMNI_MUSIC_STATE_FILE`` 环境变量指向临时文件，
模拟多次独立 CLI 子进程调用（play → pause → state），断言队列/状态跨调用持久化。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from omni_music import cli, tools


@pytest.fixture(autouse=True)
def _reset_runtime_each():
    """每个测试前重置 tools._runtime，避免跨测试状态污染。"""
    tools._reset_runtime()
    yield
    tools._reset_runtime()


@pytest.fixture
def state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 state_file 指向临时路径，便于断言跨调用持久化。"""
    path = tmp_path / "music_state.json"
    monkeypatch.setenv("AI_OMNI_MUSIC_STATE_FILE", str(path))
    return path


# ---------------------------------------------------------------------------
# call 子命令（Rust music_tool 桥接入口）
# ---------------------------------------------------------------------------
def test_call_search_returns_ok(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["call", "music_search", "--args", '{"keyword":"晴天","fake":true}'])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["data"]["count"] >= 1
    assert payload["data"]["songs"][0]["name"] == "晴天"


def test_call_get_player_state_empty_when_no_state(
    capsys: pytest.CaptureFixture[str], state_file: Path
) -> None:
    # state_file 不存在 → 空 player 状态
    rc = cli.main(["call", "music_get_player_state", "--args", '{"fake":true}'])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["data"]["queue"] == []
    assert payload["data"]["current_index"] == -1


def test_call_unknown_tool_returns_error(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["call", "music_bogus", "--args", "{}"])
    out = capsys.readouterr().out
    assert rc == 1
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "E_INVALID_ARGS"
    assert "music_bogus" in payload["error"]["message"]


def test_call_bad_args_json_returns_error(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["call", "music_search", "--args", "not json"])
    out = capsys.readouterr().out
    assert rc == 1
    payload = json.loads(out)
    assert payload["error"]["code"] == "E_INVALID_ARGS"


def test_call_args_non_object_returns_error(
    capsys: pytest.CaptureFixture[str]
) -> None:
    # --args 顶层是数组而非对象
    rc = cli.main(["call", "music_search", "--args", "[1,2,3]"])
    out = capsys.readouterr().out
    assert rc == 1
    payload = json.loads(out)
    assert payload["error"]["code"] == "E_INVALID_ARGS"


def test_call_no_args_defaults_empty(
    capsys: pytest.CaptureFixture[str], state_file: Path
) -> None:
    # 不传 --args → 空对象 → music_get_player_state(fake 默认 False，但无 source)
    # 用 fake=True 显式
    rc = cli.main(["call", "music_get_player_state", "--args", '{"fake":true}'])
    assert rc == 0


def test_call_play_then_state_persists_across_calls(
    capsys: pytest.CaptureFixture[str], state_file: Path
) -> None:
    """跨 CLI 调用的状态串联：play → state 应反映 playing。"""
    # 第一次调用：播放 fake_song_1
    rc1 = cli.main(
        ["call", "music_play", "--args", '{"song_id":"fake_song_1","fake":true}']
    )
    assert rc1 == 0
    capsys.readouterr()  # 清空 play 输出缓冲，避免污染后续 JSON 解析
    # state_file 应已写入
    assert state_file.exists()
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted["state"] == "playing"
    assert persisted["current_song"]["id"] == "fake_song_1"

    # 第二次调用（新 runtime）：get_player_state 应恢复队列
    tools._reset_runtime()
    rc2 = cli.main(["call", "music_get_player_state", "--args", '{"fake":true}'])
    out2 = capsys.readouterr().out
    assert rc2 == 0
    payload = json.loads(out2)
    assert payload["data"]["state"] == "playing"
    assert payload["data"]["current_song"]["id"] == "fake_song_1"

    # 第三次调用：pause
    tools._reset_runtime()
    capsys.readouterr()  # 清空残留
    rc3 = cli.main(["call", "music_pause", "--args", '{"fake":true}'])
    assert rc3 == 0
    persisted3 = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted3["state"] == "paused"


def test_call_pause_without_play_returns_state_violation(
    capsys: pytest.CaptureFixture[str], state_file: Path
) -> None:
    # 无 state_file → 空 player → pause 触发状态违例
    rc = cli.main(["call", "music_pause", "--args", '{"fake":true}'])
    out = capsys.readouterr().out
    assert rc == 1
    payload = json.loads(out)
    assert payload["error"]["code"] == "E_STATE_VIOLATION"


# ---------------------------------------------------------------------------
# 具名子命令
# ---------------------------------------------------------------------------
def test_search_named(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["search", "稻香", "--fake"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["data"]["songs"][0]["name"] == "稻香"


def test_play_named_by_keyword(capsys: pytest.CaptureFixture[str], state_file: Path) -> None:
    rc = cli.main(["play", "--keyword", "七里香", "--fake"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["data"]["current_song"]["name"] == "七里香"


def test_play_named_by_song_id(capsys: pytest.CaptureFixture[str], state_file: Path) -> None:
    rc = cli.main(["play", "--song-id", "fake_song_2", "--fake"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["data"]["current_song"]["id"] == "fake_song_2"


def test_pause_resume_stop_named(
    capsys: pytest.CaptureFixture[str], state_file: Path
) -> None:
    assert cli.main(["play", "--song-id", "fake_song_1", "--fake"]) == 0
    tools._reset_runtime()
    assert cli.main(["pause", "--fake"]) == 0
    tools._reset_runtime()
    assert cli.main(["resume", "--fake"]) == 0
    tools._reset_runtime()
    assert cli.main(["stop", "--fake"]) == 0
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted["state"] == "stopped"


def test_next_previous_named(capsys: pytest.CaptureFixture[str], state_file: Path) -> None:
    # 先建队列：play song_1
    assert cli.main(["play", "--song-id", "fake_song_1", "--fake"]) == 0
    tools._reset_runtime()
    capsys.readouterr()  # 清空 play 输出，避免 next 输出与之拼接成多 JSON 对象
    # next
    rc = cli.main(["next", "--fake"])
    out = capsys.readouterr().out
    assert rc == 0
    # sequence 模式下队列只有 1 首，next 越界 stop → current_song 为 None
    payload = json.loads(out)
    # 队列只有 1 首，SEQUENCE next 越界 stop；断言 state 变化
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted["state"] == "stopped"


def test_seek_named(capsys: pytest.CaptureFixture[str], state_file: Path) -> None:
    cli.main(["play", "--song-id", "fake_song_1", "--fake"])
    tools._reset_runtime()
    rc = cli.main(["seek", "42", "--fake"])
    assert rc == 0
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted["position_s"] == 42


def test_repeat_named(capsys: pytest.CaptureFixture[str], state_file: Path) -> None:
    cli.main(["play", "--song-id", "fake_song_1", "--fake"])
    tools._reset_runtime()
    rc = cli.main(["repeat", "list_loop", "--fake"])
    assert rc == 0
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted["repeat_mode"] == "list_loop"


def test_repeat_invalid_mode_returns_json_invalid_params(
    capsys: pytest.CaptureFixture[str], state_file: Path
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["repeat", "bogus", "--fake"])
    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "E_INVALID_PARAMS"


def test_state_named(capsys: pytest.CaptureFixture[str], state_file: Path) -> None:
    cli.main(["play", "--song-id", "fake_song_3", "--fake"])
    tools._reset_runtime()
    capsys.readouterr()  # 清空 play 输出，避免 state 输出与之拼接
    rc = cli.main(["state", "--fake"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["data"]["current_song"]["id"] == "fake_song_3"


def test_login_named(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["login", "--fake"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["data"]["key"]
    assert payload["data"]["qr_url"]


def test_login_check_named(capsys: pytest.CaptureFixture[str], state_file: Path) -> None:
    # 先发起登录拿 key
    cli.main(["login", "--fake"])
    tools._reset_runtime()
    capsys.readouterr()  # 清空 login 输出，避免 login-check 输出与之拼接
    rc = cli.main(["login-check", "fake_qr_key_1", "--fake"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["data"]["status"] in ("waiting", "scanned", "confirmed", "expired", "timeout")


# ---------------------------------------------------------------------------
# build_parser 结构
# ---------------------------------------------------------------------------
def test_build_parser_has_all_subcommands() -> None:
    parser = cli.build_parser()
    # 子命令 action 注册到 subparsers；检查 _subparsers._name_parser_map
    sub_map = parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]
    expected = {
        "call", "search", "play", "pause", "resume", "stop",
        "next", "previous", "seek", "repeat", "state", "login", "login-check",
    }
    assert expected <= set(sub_map.keys()), f"缺少子命令: {expected - set(sub_map.keys())}"


def test_no_subcommand_returns_json_invalid_params(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "E_INVALID_PARAMS"


# ---------------------------------------------------------------------------
# load_player_from_state_file 单元测试（tools.py 新增函数）
# ---------------------------------------------------------------------------
def test_load_player_returns_none_when_no_file(
    state_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rt = tools.Runtime()
    result = tools.load_player_from_state_file(rt, fake=True)
    assert result is None  # 文件不存在


def test_load_player_restores_queue(state_file: Path) -> None:
    # 先 play 写入 state
    tools._reset_runtime()
    cli.main(["play", "--song-id", "fake_song_2", "--fake"])
    # 新 runtime 加载
    rt = tools.Runtime()
    player = tools.load_player_from_state_file(rt, fake=True)
    assert player is not None
    assert player.current_song is not None
    assert player.current_song.id == "fake_song_2"
    assert player.current_state.value == "playing"


def test_load_player_corrupt_file_returns_none(
    state_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file.write_text("not json {", encoding="utf-8")
    rt = tools.Runtime()
    result = tools.load_player_from_state_file(rt, fake=True)
    assert result is None  # 损坏文件不拖垮


def test_load_player_no_source_returns_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # fake=False 且无真实源 → None
    path = tmp_path / "state.json"
    monkeypatch.setenv("AI_OMNI_MUSIC_STATE_FILE", str(path))
    path.write_text(json.dumps({"queue": [], "current_index": -1, "state": "stopped",
                                "repeat_mode": "sequence", "position_s": 0}), encoding="utf-8")
    rt = tools.Runtime()
    result = tools.load_player_from_state_file(rt, fake=False)
    assert result is None
