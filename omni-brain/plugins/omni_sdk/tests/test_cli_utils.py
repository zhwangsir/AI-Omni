"""omni_sdk.cli_utils 测试：JsonErrorArgumentParser。"""

from __future__ import annotations

import json

import pytest

from omni_sdk.cli_utils import JsonErrorArgumentParser


def test_missing_required_arg_prints_json_error(capsys: pytest.CaptureFixture[str]) -> None:
    """缺少 required 位置参数时输出 JSON E_INVALID_PARAMS 并退出码 1。"""
    parser = JsonErrorArgumentParser(prog="test")
    parser.add_argument("name", help="名称")
    with pytest.raises(SystemExit) as exc:
        parser.parse_args([])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "E_INVALID_PARAMS"
    assert "name" in payload["error"]["message"]


def test_unknown_argument_prints_json_error(capsys: pytest.CaptureFixture[str]) -> None:
    """未知参数时输出 JSON E_INVALID_PARAMS。"""
    parser = JsonErrorArgumentParser(prog="test")
    parser.add_argument("--flag", action="store_true")
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--unknown"])
    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "E_INVALID_PARAMS"


def test_help_still_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """--help 不受影响，仍以退出码 0 输出帮助。"""
    parser = JsonErrorArgumentParser(prog="test", description="测试")
    parser.add_argument("name")
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--help"])
    assert exc.value.code == 0
    assert "测试" in capsys.readouterr().out


def test_valid_args_parse_normally() -> None:
    """正常参数解析结果不变。"""
    parser = JsonErrorArgumentParser(prog="test")
    parser.add_argument("name")
    args = parser.parse_args(["alice"])
    assert args.name == "alice"
