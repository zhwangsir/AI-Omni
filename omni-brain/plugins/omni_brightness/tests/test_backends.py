"""omni_brightness backends 测试：FakeBrightnessBackend + MacBrightnessBackend。

FakeBrightnessBackend 是纯内存状态机。
MacBrightnessBackend 通过 monkeypatch subprocess 验证命令拼装与错误映射，
不执行真实 brightness 命令。
"""

from __future__ import annotations

import pytest

from omni_brightness.backends import FakeBrightnessBackend, MacBrightnessBackend


# ---------------------------------------------------------------------------
# FakeBrightnessBackend
# ---------------------------------------------------------------------------
class TestFakeBrightnessBackend:
    def test_default_state(self):
        """默认亮度 75。"""
        b = FakeBrightnessBackend()
        assert b.brightness == 75

    def test_set_brightness_ok(self):
        """set_brightness 更新亮度。"""
        b = FakeBrightnessBackend()
        result = b.set_brightness(80)
        assert result == {"ok": True, "brightness": 80}
        assert b.brightness == 80

    def test_set_brightness_records_last_command(self):
        """set_brightness 记录等价 CLI 命令（level/100 浮点）。"""
        b = FakeBrightnessBackend()
        b.set_brightness(50)
        # 50/100 = 0.5 → "brightness 0.50"
        assert b.last_command == "brightness 0.50"

    def test_set_brightness_zero(self):
        """亮度 0 边界。"""
        b = FakeBrightnessBackend()
        result = b.set_brightness(0)
        assert result["ok"] is True
        assert result["brightness"] == 0

    def test_set_brightness_hundred(self):
        """亮度 100 边界。"""
        b = FakeBrightnessBackend()
        result = b.set_brightness(100)
        assert result["ok"] is True
        assert result["brightness"] == 100

    def test_set_brightness_out_of_range_negative(self):
        """负数返回 E_OUT_OF_RANGE。"""
        b = FakeBrightnessBackend()
        result = b.set_brightness(-1)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_OUT_OF_RANGE"

    def test_set_brightness_out_of_range_too_big(self):
        """101 返回 E_OUT_OF_RANGE。"""
        b = FakeBrightnessBackend()
        result = b.set_brightness(101)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_OUT_OF_RANGE"

    def test_set_brightness_non_int(self):
        """非整数返回 E_INVALID_ARG。"""
        b = FakeBrightnessBackend()
        result = b.set_brightness("50")  # type: ignore[arg-type]
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_ARG"

    def test_get_brightness_ok(self):
        """get_brightness 返回当前状态。"""
        b = FakeBrightnessBackend(brightness=70)
        result = b.get_brightness()
        assert result == {"ok": True, "brightness": 70}


# ---------------------------------------------------------------------------
# MacBrightnessBackend
# ---------------------------------------------------------------------------
class TestMacBrightnessBackend:
    def test_set_brightness_calls_cli_with_float(self, monkeypatch):
        """set_brightness 把 0-100 映射为 0-1 调用 brightness CLI。"""
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

        b = MacBrightnessBackend()
        result = b.set_brightness(75)
        assert result["ok"] is True
        assert result["brightness"] == 75
        # 75/100 = 0.75 → ["brightness", "0.75"]
        assert calls[0] == ["brightness", "0.75"]

    def test_set_brightness_zero(self, monkeypatch):
        """亮度 0 映射为 0.00。"""
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

        b = MacBrightnessBackend()
        b.set_brightness(0)
        assert calls[0] == ["brightness", "0.00"]

    def test_set_brightness_out_of_range(self):
        """越界参数不调用 CLI，直接返回 E_OUT_OF_RANGE。"""
        b = MacBrightnessBackend()
        result = b.set_brightness(150)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_OUT_OF_RANGE"

    def test_set_brightness_cli_failure(self, monkeypatch):
        """CLI 返回非零退出码时映射为 E_BACKEND_UNAVAILABLE。"""

        class _Result:
            def __init__(self, returncode=1, stdout="", stderr="command not found"):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        import subprocess

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Result())

        b = MacBrightnessBackend()
        result = b.set_brightness(50)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"
        assert "command not found" in result["error"]["message"]

    def test_set_brightness_cli_missing(self, monkeypatch):
        """brightness 命令不存在时返回 E_BACKEND_UNAVAILABLE。"""
        import subprocess

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("brightness")

        monkeypatch.setattr(subprocess, "run", fake_run)

        b = MacBrightnessBackend()
        result = b.set_brightness(50)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"
        assert "brightness" in result["error"]["message"]

    def test_get_brightness_parses_output(self, monkeypatch):
        """get_brightness 解析 'brightness 0.75' 输出返回 75。"""

        class _Result:
            def __init__(self, stdout="brightness 0.75"):
                self.returncode = 0
                self.stdout = stdout
                self.stderr = ""

        import subprocess

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Result())

        b = MacBrightnessBackend()
        result = b.get_brightness()
        assert result["ok"] is True
        assert result["brightness"] == 75

    def test_get_brightness_parses_with_extra_lines(self, monkeypatch):
        """get_brightness 处理多行输出，取最后一行。"""

        class _Result:
            def __init__(self, stdout="display 0: main\nbrightness 0.42"):
                self.returncode = 0
                self.stdout = stdout
                self.stderr = ""

        import subprocess

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Result())

        b = MacBrightnessBackend()
        result = b.get_brightness()
        assert result["ok"] is True
        assert result["brightness"] == 42

    def test_get_brightness_parse_failure(self, monkeypatch):
        """CLI 输出无法解析时返回 E_PARSE_FAILED。"""

        class _Result:
            def __init__(self, stdout="not-a-number"):
                self.returncode = 0
                self.stdout = stdout
                self.stderr = ""

        import subprocess

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Result())

        b = MacBrightnessBackend()
        result = b.get_brightness()
        assert result["ok"] is False
        assert result["error"]["code"] == "E_PARSE_FAILED"

    def test_get_brightness_cli_missing(self, monkeypatch):
        """brightness 命令不存在时返回 E_BACKEND_UNAVAILABLE。"""
        import subprocess

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("brightness")))

        b = MacBrightnessBackend()
        result = b.get_brightness()
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"
