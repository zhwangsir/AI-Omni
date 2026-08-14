"""omni_sdk __main__ 入口 smoke 测试。

经 runpy 以 ``python -m omni_sdk`` 语义执行 __main__.py（cli.main 用 Mock 替换，
不触碰真实后端），验证转发契约；另验证真实 ``--help`` 不炸。
"""

from __future__ import annotations

import runpy
from unittest.mock import Mock

import pytest


class TestDunderMain:
    def test_main_forwards_to_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """__main__ 转发到 cli.main 并正常返回（无 SystemExit）。"""
        mock_main = Mock()
        monkeypatch.setattr("omni_sdk.cli.main", mock_main)
        runpy.run_module("omni_sdk", run_name="__main__", alter_sys=True)
        mock_main.assert_called_once_with()


class TestCliHelp:
    def test_help_exits_zero(self) -> None:
        """真实 cli.main --help 打印帮助并以 0 退出（不触碰后端）。"""
        from omni_sdk.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0
