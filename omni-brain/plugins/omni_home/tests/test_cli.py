"""omni_home CLI 测试：``python -m omni_home <子命令>``。

CLI 是 tools 层的薄壳：解析参数 → 调 tools → 打印 JSON → 映射退出码；
全部走 fake 演示家庭，无需真实 Home Assistant。
"""

from __future__ import annotations

import json

import pytest

from omni_home import tools
from omni_home.cli import build_parser, main


@pytest.fixture(autouse=True)
def fresh_runtime():
    """每个测试前重置运行时单例。"""
    yield tools._reset_runtime()


def _run(capsys, argv: list[str]) -> tuple[int, dict]:
    """执行 CLI 并返回 (退出码, 最后一行 JSON 输出)。"""
    code = main(argv)
    out = capsys.readouterr().out
    last_line = [line for line in out.strip().splitlines() if line.strip()][-1]
    return code, json.loads(last_line)


class TestParser:
    def test_subcommand_required_returns_json_invalid_params(self, capsys):
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args([])
        assert exc.value.code == 1
        result = json.loads(capsys.readouterr().out)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    def test_control_missing_text_returns_json_invalid_params(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["control", "--fake"])
        assert exc.value.code == 1
        result = json.loads(capsys.readouterr().out)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    def test_parse_control(self):
        args = build_parser().parse_args(["control", "打开客厅灯", "--fake"])
        assert args.command == "control"
        assert args.text == "打开客厅灯"
        assert args.fake is True

    def test_parse_list_filters(self):
        args = build_parser().parse_args(["list", "--room", "客厅", "--domain", "light"])
        assert args.room == "客厅"
        assert args.domain == "light"


class TestStatus:
    def test_status_fake(self, capsys):
        code, payload = _run(capsys, ["status", "--fake"])
        assert code == 0
        assert payload["ok"] is True
        assert payload["data"]["fake_mode"] is True


class TestRefresh:
    def test_refresh_fake(self, capsys):
        code, payload = _run(capsys, ["refresh", "--fake"])
        assert code == 0
        assert payload["ok"] is True
        assert payload["data"]["devices"] == 14


class TestControl:
    def test_control_turn_on(self, capsys):
        code, payload = _run(capsys, ["control", "打开客厅灯", "--fake"])
        assert code == 0
        assert payload["ok"] is True
        assert payload["data"]["results"][0]["state"] == "on"

    def test_control_failure_exit_1(self, capsys):
        code, payload = _run(capsys, ["control", " blah blah", "--fake"])
        assert code == 1
        assert payload["ok"] is False


class TestQuery:
    def test_query_state(self, capsys):
        code, payload = _run(capsys, ["query", "卧室灯开着吗", "--fake"])
        assert code == 0
        assert payload["ok"] is True
        assert payload["data"]["answers"][0]["state_text"] == "开启"


class TestList:
    def test_list_all(self, capsys):
        code, payload = _run(capsys, ["list", "--fake"])
        assert code == 0
        assert payload["ok"] is True
        assert payload["data"]["stats"]["devices"] == 14

    def test_list_room(self, capsys):
        code, payload = _run(capsys, ["list", "--room", "书房", "--fake"])
        assert code == 0
        assert payload["data"]["devices"][0]["entity_id"] == "fan.study_fan"


class TestConfig:
    def test_config_get(self, capsys):
        code, payload = _run(capsys, ["config", "get"])
        assert code == 0
        assert payload["ok"] is True
        assert "ha_url" in payload["data"]

    def test_config_set(self, capsys):
        code, payload = _run(capsys, ["config", "set", "default_room", "卧室"])
        assert code == 0
        assert payload["ok"] is True
        assert tools._runtime.config.default_room == "卧室"

    def test_config_set_invalid_exit_1(self, capsys):
        code, payload = _run(capsys, ["config", "set", "connect_timeout", "-5"])
        assert code == 1
        assert payload["ok"] is False


class TestDemoFlow:
    def test_full_demo_flow(self, capsys):
        """演示完整链路：refresh → control → query 状态联动。"""
        code, _ = _run(capsys, ["refresh", "--fake"])
        assert code == 0
        code, payload = _run(capsys, ["control", "把客厅空调温度调到24度", "--fake"])
        assert code == 0
        assert payload["data"]["results"][0]["attributes"]["temperature"] == 24.0
        code, payload = _run(capsys, ["query", "客厅空调怎么样", "--fake"])
        assert code == 0
        assert "24" in payload["data"]["answers"][0]["state_text"]
