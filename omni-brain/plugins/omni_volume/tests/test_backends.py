"""omni_volume backends 测试：FakeVolumeBackend 行为 + MacVolumeBackend 容错。

FakeVolumeBackend 是纯内存状态机，覆盖 set/get/mute/unmute 与边界。
MacVolumeBackend 通过 monkeypatch subprocess 验证命令拼装与错误映射，
不执行真实 osascript。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from omni_volume.backends import FakeVolumeBackend, MacVolumeBackend


# ---------------------------------------------------------------------------
# FakeVolumeBackend
# ---------------------------------------------------------------------------
class TestFakeVolumeBackend:
    def test_default_state(self):
        """默认音量 50、未静音。"""
        b = FakeVolumeBackend()
        assert b.volume == 50
        assert b.muted is False

    def test_set_volume_ok(self):
        """set_volume 更新音量并取消静音。"""
        b = FakeVolumeBackend(volume=20, muted=True)
        result = b.set_volume(80)
        assert result == {"ok": True, "volume": 80, "muted": False}
        assert b.volume == 80
        assert b.muted is False

    def test_set_volume_records_last_command(self):
        """set_volume 记录等价 osascript 命令（mac_level = round(level/100*7)）。"""
        b = FakeVolumeBackend()
        b.set_volume(50)
        # round(50/100*7) = round(3.5) = 4（Python banker's rounding）
        assert b.last_command == "set volume 4"

    def test_set_volume_zero(self):
        """音量 0 边界。"""
        b = FakeVolumeBackend()
        result = b.set_volume(0)
        assert result["ok"] is True
        assert result["volume"] == 0

    def test_set_volume_hundred(self):
        """音量 100 边界。"""
        b = FakeVolumeBackend()
        result = b.set_volume(100)
        assert result["ok"] is True
        assert result["volume"] == 100

    def test_set_volume_out_of_range_negative(self):
        """负数返回 E_OUT_OF_RANGE。"""
        b = FakeVolumeBackend()
        result = b.set_volume(-1)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_OUT_OF_RANGE"

    def test_set_volume_out_of_range_too_big(self):
        """101 返回 E_OUT_OF_RANGE。"""
        b = FakeVolumeBackend()
        result = b.set_volume(101)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_OUT_OF_RANGE"

    def test_set_volume_non_int(self):
        """非整数返回 E_INVALID_ARG。"""
        b = FakeVolumeBackend()
        result = b.set_volume("50")  # type: ignore[arg-type]
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_ARG"

    def test_get_volume_ok(self):
        """get_volume 返回当前状态。"""
        b = FakeVolumeBackend(volume=70, muted=True)
        result = b.get_volume()
        assert result == {"ok": True, "volume": 70, "muted": True}

    def test_mute_ok(self):
        """mute 设置 muted=True 并保留音量。"""
        b = FakeVolumeBackend(volume=60)
        result = b.mute()
        assert result["ok"] is True
        assert result["muted"] is True
        assert result["volume"] == 60
        assert b.muted is True
        assert b.last_command == "set volume with output muted"

    def test_unmute_ok(self):
        """unmute 设置 muted=False 并保留音量。"""
        b = FakeVolumeBackend(volume=60, muted=True)
        result = b.unmute()
        assert result["ok"] is True
        assert result["muted"] is False
        assert result["volume"] == 60
        assert b.muted is False
        assert b.last_command == "set volume without output muted"


# ---------------------------------------------------------------------------
# MacVolumeBackend
# ---------------------------------------------------------------------------
class TestMacVolumeBackend:
    """MacVolumeBackend 通过 monkeypatch subprocess 验证命令拼装与错误映射。"""

    def test_set_volume_calls_osascript_with_mac_level(self, monkeypatch):
        """set_volume 把 0-100 映射为 0-7 调用 osascript。"""
        calls: list[list[str]] = []

        class _Result:
            def __init__(self, returncode=0, stdout="", stderr=""):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            # set volume 总是返回空 stdout
            return _Result(returncode=0, stdout="", stderr="")

        import subprocess

        monkeypatch.setattr(subprocess, "run", fake_run)

        b = MacVolumeBackend()
        result = b.set_volume(100)
        assert result["ok"] is True
        assert result["volume"] == 100
        assert result["muted"] is False
        # 第一次调用是 set volume 7（round(100/100*7)）
        assert calls[0] == ["osascript", "-e", "set volume 7"]
        # 第二次调用是取消静音（与 macOS 行为一致）
        assert calls[1] == ["osascript", "-e", "set volume without output muted"]

    def test_set_volume_mid_level_mapping(self, monkeypatch):
        """level=50 映射为 mac_level=4（round(3.5)=4 Python banker's rounding）。"""
        calls: list[list[str]] = []

        class _Result:
            def __init__(self, returncode=0, stdout="", stderr=""):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _Result(returncode=0, stdout="", stderr="")

        import subprocess

        monkeypatch.setattr(subprocess, "run", fake_run)

        b = MacVolumeBackend()
        b.set_volume(50)
        assert calls[0] == ["osascript", "-e", "set volume 4"]

    def test_set_volume_out_of_range(self):
        """越界参数不调用 osascript，直接返回 E_OUT_OF_RANGE。"""
        b = MacVolumeBackend()
        result = b.set_volume(150)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_OUT_OF_RANGE"

    def test_set_volume_osascript_failure(self, monkeypatch):
        """osascript 返回非零退出码时映射为 E_BACKEND_UNAVAILABLE。"""

        class _Result:
            def __init__(self, returncode=1, stdout="", stderr="permission denied"):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        import subprocess

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Result())

        b = MacVolumeBackend()
        result = b.set_volume(50)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"
        assert "permission denied" in result["error"]["message"]

    def test_get_volume_parses_output(self, monkeypatch):
        """get_volume 解析 osascript 输出返回音量。"""
        # osascript 第一次返回音量值，第二次返回静音状态
        outputs = iter(["75", "false"])

        class _Result:
            def __init__(self, stdout):
                self.returncode = 0
                self.stdout = stdout
                self.stderr = ""

        import subprocess

        def fake_run(cmd, **kwargs):
            return _Result(stdout=next(outputs))

        monkeypatch.setattr(subprocess, "run", fake_run)

        b = MacVolumeBackend()
        result = b.get_volume()
        assert result["ok"] is True
        assert result["volume"] == 75
        assert result["muted"] is False

    def test_get_volume_parse_failure(self, monkeypatch):
        """osascript 输出非数字时返回 E_PARSE_FAILED。"""

        class _Result:
            def __init__(self, stdout="not-a-number"):
                self.returncode = 0
                self.stdout = stdout
                self.stderr = ""

        import subprocess

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Result())

        b = MacVolumeBackend()
        result = b.get_volume()
        assert result["ok"] is False
        assert result["error"]["code"] == "E_PARSE_FAILED"

    def test_get_volume_osascript_missing(self, monkeypatch):
        """osascript 命令不存在时返回 E_BACKEND_UNAVAILABLE。"""
        import subprocess

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("osascript")

        monkeypatch.setattr(subprocess, "run", fake_run)

        b = MacVolumeBackend()
        result = b.get_volume()
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"
        assert "osascript" in result["error"]["message"]

    def test_mute_calls_osascript(self, monkeypatch):
        """mute 调用 'set volume with output muted'。"""
        calls: list[list[str]] = []

        class _Result:
            def __init__(self, returncode=0, stdout="50", stderr=""):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            # mute 调用 set volume with output muted（无输出），
            # 紧接着 get_volume 调用 output volume of (get volume settings)
            if "with output muted" in cmd[2]:
                return _Result(stdout="")
            return _Result(stdout="50")

        import subprocess

        monkeypatch.setattr(subprocess, "run", fake_run)

        b = MacVolumeBackend()
        result = b.mute()
        assert result["ok"] is True
        assert result["muted"] is True
        assert any("with output muted" in c[2] for c in calls)

    def test_unmute_calls_osascript(self, monkeypatch):
        """unmute 调用 'set volume without output muted'。"""
        calls: list[list[str]] = []

        class _Result:
            def __init__(self, returncode=0, stdout="50", stderr=""):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = ""

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if "without output muted" in cmd[2]:
                return _Result(stdout="")
            return _Result(stdout="50")

        import subprocess

        monkeypatch.setattr(subprocess, "run", fake_run)

        b = MacVolumeBackend()
        result = b.unmute()
        assert result["ok"] is True
        assert result["muted"] is False
        assert any("without output muted" in c[2] for c in calls)
