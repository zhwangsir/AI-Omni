"""omni_music __main__ 入口 smoke 测试。

经 runpy 以 ``python -m omni_music`` 语义执行 __main__.py（cli.main 用 Mock 替换，
不触碰真实后端），验证转发契约与退出码透出；另验证真实 ``--help`` 不炸。
"""

from __future__ import annotations

import runpy
from unittest.mock import Mock

import pytest


class TestDunderMain:
    def test_main_forwards_to_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """__main__ 转发到 cli.main，返回值作为 SystemExit 退出码透出。"""
        mock_main = Mock(return_value=0)
        monkeypatch.setattr("omni_music.cli.main", mock_main)
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("omni_music", run_name="__main__", alter_sys=True)
        assert exc_info.value.code == 0
        mock_main.assert_called_once_with()

    def test_main_propagates_nonzero_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """cli.main 返回非 0 时退出码原样透出。"""
        mock_main = Mock(return_value=2)
        monkeypatch.setattr("omni_music.cli.main", mock_main)
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("omni_music", run_name="__main__", alter_sys=True)
        assert exc_info.value.code == 2


class TestCliHelp:
    def test_help_exits_zero(self) -> None:
        """真实 cli.main --help 打印帮助并以 0 退出（不触碰后端）。"""
        from omni_music.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0
