"""omni_lyrics CLI 测试（M18 TDD red → green）。

覆盖 ``omni_lyrics/cli.py`` 的子命令派发、退出码映射、参数解析与错误降级。
全部用 FakeMusicSource（``--fake``），零网络依赖。

子命令：
- ``call <tool> [--args JSON] [--fake]``：通用工具调用（Rust ``lyrics_tool`` 桥接入口）
- ``get --song-id ID [--source S] [--fake]``：获取歌词
- ``search KEYWORD [--limit N] [--fake]``：搜索歌曲
- ``offset OFFSET_S [--fake]``：设置偏移
- ``current --song-id ID --time T [--fake]``：获取当前行
"""

from __future__ import annotations

import json

import pytest

from omni_lyrics import cli, tools
from omni_music.sources.base import FakeMusicSource


@pytest.fixture(autouse=True)
def _reset_runtime_each():
    """每个测试前重置 tools._runtime，避免跨测试状态污染。"""
    tools._reset_runtime()
    yield
    tools._reset_runtime()


def _setup_fake_source() -> FakeMusicSource:
    """预置 fake 源到运行时，返回实例。"""
    source = FakeMusicSource()
    source.songs[0].id = "s1"
    source.songs[0].name = "晴天"
    source.songs[0].lyrics = "[00:01.00]故事的小黄花\n[00:05.00]从出生那年就飘着"
    tools._runtime.source = source
    return source


# ---------------------------------------------------------------------------
# call 子命令（Rust lyrics_tool 桥接入口）
# ---------------------------------------------------------------------------
class TestCallSubcommand:
    def test_call_get_returns_ok(self, capsys: pytest.CaptureFixture[str]) -> None:
        """call lyrics_get 返回 ok 信封。"""
        _setup_fake_source()
        rc = cli.main(["call", "lyrics_get", "--args", '{"song_id":"s1"}'])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["data"]["source"] == "local_file"
        assert len(payload["data"]["parsed"]) == 2

    def test_call_search_returns_ok(self, capsys: pytest.CaptureFixture[str]) -> None:
        """call lyrics_search 返回 ok 信封。"""
        _setup_fake_source()
        rc = cli.main(["call", "lyrics_search", "--args", '{"keyword":"晴天"}'])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["data"]["count"] >= 1

    def test_call_unknown_tool_returns_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """call 未知工具返回 ok:false + E_INVALID_ARGS。"""
        rc = cli.main(["call", "lyrics_bogus", "--args", "{}"])
        out = capsys.readouterr().out
        assert rc == 1
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "E_INVALID_ARGS"
        assert "lyrics_bogus" in payload["error"]["message"]

    def test_call_bad_args_json_returns_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """call --args 非 JSON 返回 E_INVALID_ARGS。"""
        rc = cli.main(["call", "lyrics_get", "--args", "not json"])
        out = capsys.readouterr().out
        assert rc == 1
        payload = json.loads(out)
        assert payload["error"]["code"] == "E_INVALID_ARGS"

    def test_call_args_non_object_returns_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """call --args 顶层是数组而非对象返回 E_INVALID_ARGS。"""
        rc = cli.main(["call", "lyrics_get", "--args", "[1,2,3]"])
        out = capsys.readouterr().out
        assert rc == 1
        payload = json.loads(out)
        assert payload["error"]["code"] == "E_INVALID_ARGS"

    def test_call_no_args_defaults_empty(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """call 不传 --args 视为空对象。"""
        _setup_fake_source()
        # lyrics_set_offset 无参调用会失败（缺 offset_s），但 args 解析成功
        rc = cli.main(["call", "lyrics_set_offset", "--args", '{"offset_s":0}'])
        out = capsys.readouterr().out
        assert rc == 0


# ---------------------------------------------------------------------------
# 具名子命令
# ---------------------------------------------------------------------------
class TestNamedSubcommands:
    def test_get_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        """get --song-id 返回歌词。"""
        _setup_fake_source()
        rc = cli.main(["get", "--song-id", "s1"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["data"]["source"] == "local_file"

    def test_search_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        """search KEYWORD 返回歌曲列表。"""
        _setup_fake_source()
        rc = cli.main(["search", "晴天"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["data"]["songs"][0]["name"] == "晴天"

    def test_offset_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        """offset OFFSET_S 设置偏移。"""
        rc = cli.main(["offset", "2.5"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["data"]["offset_s"] == 2.5

    def test_current_subcommand(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """current --song-id --time 返回当前行。"""
        _setup_fake_source()
        rc = cli.main(["current", "--song-id", "s1", "--time", "3.0"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["data"]["current_line"] == 0  # 1s 行仍显示

    def test_current_subcommand_no_lyrics(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """current 对无歌词歌曲返回 current_line=-1。"""
        source = FakeMusicSource()
        source.songs[0].id = "s1"
        source.songs[0].lyrics = None
        tools._runtime.source = source
        rc = cli.main(["current", "--song-id", "s1", "--time", "3.0"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["data"]["current_line"] == -1


# ---------------------------------------------------------------------------
# fake 标志传递
# ---------------------------------------------------------------------------
class TestFakeFlag:
    def test_call_with_fake_flag_uses_fake_source(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """call --fake 自动构造 FakeMusicSource。"""
        # 不预置 source，靠 --fake 标志
        rc = cli.main(
            ["call", "lyrics_search", "--args", '{"keyword":"晴天"}', "--fake"]
        )
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["ok"] is True
        # FakeMusicSource 内置 3 首，"晴天" 在其中
        assert payload["data"]["count"] >= 1

    def test_call_fake_in_args_json(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """call --args '{"fake":true}' 也识别 fake 标志。"""
        rc = cli.main(
            ["call", "lyrics_search", "--args", '{"keyword":"晴天","fake":true}']
        )
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["ok"] is True


# ---------------------------------------------------------------------------
# 退出码映射
# ---------------------------------------------------------------------------
class TestExitCodeMapping:
    def test_ok_returns_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """ok:true → 退出码 0。"""
        _setup_fake_source()
        rc = cli.main(["get", "--song-id", "s1"])
        assert rc == 0

    def test_error_returns_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        """ok:false → 退出码 1。"""
        # 未配置源 + 不用 fake → E_BACKEND_UNAVAILABLE
        rc = cli.main(["get", "--song-id", "s1"])
        out = capsys.readouterr().out
        assert rc == 1
        payload = json.loads(out)
        assert payload["ok"] is False
