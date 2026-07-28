"""omni_power backends 测试：FakePowerBackend + MacPowerBackend。

FakePowerBackend 记录调用，不执行系统命令。
MacPowerBackend 通过 monkeypatch subprocess 验证命令拼装与错误映射。
"""

from __future__ import annotations

import pytest

from omni_power.backends import FakePowerBackend, MacPowerBackend


# ---------------------------------------------------------------------------
# FakePowerBackend
# ---------------------------------------------------------------------------
class TestFakePowerBackend:
    def test_lock_screen_records_call(self):
        """lock_screen 记录调用并返回成功。"""
        b = FakePowerBackend()
        result = b.lock_screen()
        assert result["ok"] is True
        assert result["action"] == "lock_screen"
        assert result["command"] == "pmset displaysleepnow"
        assert b.calls == ["lock_screen"]
        assert b.last_command == "pmset displaysleepnow"

    def test_sleep_records_call(self):
        """sleep 记录调用并返回成功。"""
        b = FakePowerBackend()
        result = b.sleep()
        assert result["ok"] is True
        assert result["action"] == "sleep"
        assert result["command"] == "pmset sleepnow"
        assert b.calls == ["sleep"]

    def test_shutdown_records_call(self):
        """shutdown 记录调用并返回成功。"""
        b = FakePowerBackend()
        result = b.shutdown()
        assert result["ok"] is True
        assert result["action"] == "shutdown"
        assert "shut down" in result["command"]
        assert b.calls == ["shutdown"]

    def test_restart_records_call(self):
        """restart 记录调用并返回成功。"""
        b = FakePowerBackend()
        result = b.restart()
        assert result["ok"] is True
        assert result["action"] == "restart"
        assert "restart" in result["command"]
        assert b.calls == ["restart"]

    def test_multiple_calls_recorded_in_order(self):
        """多次调用按顺序记录。"""
        b = FakePowerBackend()
        b.lock_screen()
        b.sleep()
        b.shutdown()
        b.restart()
        assert b.calls == ["lock_screen", "sleep", "shutdown", "restart"]


# ---------------------------------------------------------------------------
# MacPowerBackend
# ---------------------------------------------------------------------------
class TestMacPowerBackend:
    def test_lock_screen_calls_pmset_displaysleepnow(self, monkeypatch):
        """lock_screen 调用 pmset displaysleepnow。"""
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

        b = MacPowerBackend()
        result = b.lock_screen()
        assert result["ok"] is True
        assert result["action"] == "lock_screen"
        assert calls[0] == ["pmset", "displaysleepnow"]

    def test_sleep_calls_pmset_sleepnow(self, monkeypatch):
        """sleep 调用 pmset sleepnow。"""
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

        b = MacPowerBackend()
        result = b.sleep()
        assert result["ok"] is True
        assert calls[0] == ["pmset", "sleepnow"]

    def test_shutdown_calls_osascript(self, monkeypatch):
        """shutdown 调用 osascript System Events shut down。"""
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

        b = MacPowerBackend()
        result = b.shutdown()
        assert result["ok"] is True
        assert calls[0][0] == "osascript"
        assert "shut down" in calls[0][2]

    def test_restart_calls_osascript(self, monkeypatch):
        """restart 调用 osascript System Events restart。"""
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

        b = MacPowerBackend()
        result = b.restart()
        assert result["ok"] is True
        assert calls[0][0] == "osascript"
        assert "restart" in calls[0][2]

    def test_command_failure_returns_error(self, monkeypatch):
        """命令返回非零退出码时映射为 E_BACKEND_UNAVAILABLE。"""

        class _Result:
            def __init__(self):
                self.returncode = 1
                self.stdout = ""
                self.stderr = "not authorized"

        import subprocess

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Result())

        b = MacPowerBackend()
        result = b.lock_screen()
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"
        assert "not authorized" in result["error"]["message"]

    def test_command_missing_returns_error(self, monkeypatch):
        """命令不存在时返回 E_BACKEND_UNAVAILABLE。"""
        import subprocess

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("pmset")))

        b = MacPowerBackend()
        result = b.sleep()
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"
        assert "pmset" in result["error"]["message"]
