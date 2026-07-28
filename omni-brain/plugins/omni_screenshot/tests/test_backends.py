"""omni_screenshot backends 测试：FakeScreenshotBackend + MacScreenshotBackend。

FakeScreenshotBackend 记录调用，不执行系统命令。
MacScreenshotBackend 通过 monkeypatch subprocess 验证命令拼装与错误映射。
"""

from __future__ import annotations

import pytest

from omni_screenshot.backends import (
    FakeScreenshotBackend,
    MacScreenshotBackend,
    _default_path,
)


# ---------------------------------------------------------------------------
# _default_path
# ---------------------------------------------------------------------------
class TestDefaultPath:
    def test_default_path_under_pictures(self):
        """默认路径在 ~/Pictures 下。"""
        path = _default_path()
        assert "Pictures" in path
        assert "screenshot_" in path
        assert path.endswith(".png")

    def test_default_path_has_timestamp(self):
        """默认路径包含时间戳。"""
        path = _default_path()
        # timestamp 形如 20260727_120000
        assert len(path.split("screenshot_")[1].split(".png")[0]) == 15


# ---------------------------------------------------------------------------
# FakeScreenshotBackend
# ---------------------------------------------------------------------------
class TestFakeScreenshotBackend:
    def test_capture_full_default_path(self):
        """全屏截图使用默认路径。"""
        b = FakeScreenshotBackend()
        result = b.capture_full()
        assert result["ok"] is True
        assert result["mode"] == "full"
        assert "Pictures" in result["path"]
        assert b.calls == [("full", result["path"], None)]

    def test_capture_full_custom_path(self):
        """全屏截图接受自定义路径。"""
        b = FakeScreenshotBackend()
        result = b.capture_full(path="/tmp/shot.png")
        assert result["ok"] is True
        assert result["path"] == "/tmp/shot.png"
        assert b.calls[0][1] == "/tmp/shot.png"

    def test_capture_region_with_coords(self):
        """区域截图使用指定坐标。"""
        b = FakeScreenshotBackend()
        result = b.capture_region(region=(10, 20, 300, 200))
        assert result["ok"] is True
        assert result["mode"] == "region"
        assert b.calls[0] == ("region", result["path"], (10, 20, 300, 200))

    def test_capture_region_interactive(self):
        """region=None 时进入交互式模式。"""
        b = FakeScreenshotBackend()
        result = b.capture_region(region=None)
        assert result["ok"] is True
        assert result["mode"] == "interactive"
        assert b.calls[0][0] == "interactive"
        assert b.calls[0][2] is None

    def test_capture_region_custom_path(self):
        """区域截图接受自定义路径。"""
        b = FakeScreenshotBackend()
        result = b.capture_region(region=(0, 0, 100, 100), path="/tmp/region.png")
        assert result["ok"] is True
        assert result["path"] == "/tmp/region.png"

    def test_multiple_calls_recorded(self):
        """多次调用按顺序记录。"""
        b = FakeScreenshotBackend()
        b.capture_full()
        b.capture_region(region=(0, 0, 50, 50))
        b.capture_region()
        assert len(b.calls) == 3
        assert b.calls[0][0] == "full"
        assert b.calls[1][0] == "region"
        assert b.calls[2][0] == "interactive"


# ---------------------------------------------------------------------------
# MacScreenshotBackend
# ---------------------------------------------------------------------------
class TestMacScreenshotBackend:
    def test_capture_full_calls_screencapture(self, monkeypatch, tmp_path):
        """capture_full 调用 screencapture <path>。"""
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

        out = str(tmp_path / "full.png")
        b = MacScreenshotBackend()
        result = b.capture_full(path=out)
        assert result["ok"] is True
        assert result["path"] == out
        assert result["mode"] == "full"
        assert calls[0] == ["screencapture", out]

    def test_capture_full_default_path(self, monkeypatch):
        """未提供 path 时使用默认路径。"""
        calls: list[list[str]] = []

        class _Result:
            def __init__(self):
                self.returncode = 0
                self.stdout = ""
                self.stderr = ""

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _Result()

        import subprocess

        monkeypatch.setattr(subprocess, "run", fake_run)

        b = MacScreenshotBackend()
        result = b.capture_full()
        assert result["ok"] is True
        assert "Pictures" in result["path"]
        # 命令应为 ["screencapture", <path>]
        assert calls[0][0] == "screencapture"
        assert calls[0][1].endswith(".png")

    def test_capture_region_with_coords(self, monkeypatch, tmp_path):
        """区域截图调用 screencapture -R x,y,w,h <path>。"""
        calls: list[list[str]] = []

        class _Result:
            def __init__(self):
                self.returncode = 0
                self.stdout = ""
                self.stderr = ""

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _Result()

        import subprocess

        monkeypatch.setattr(subprocess, "run", fake_run)

        out = str(tmp_path / "region.png")
        b = MacScreenshotBackend()
        result = b.capture_region(region=(10, 20, 300, 200), path=out)
        assert result["ok"] is True
        assert result["mode"] == "region"
        assert calls[0] == ["screencapture", "-R", "10,20,300,200", out]

    def test_capture_region_interactive(self, monkeypatch, tmp_path):
        """region=None 调用 screencapture -i <path>。"""
        calls: list[list[str]] = []

        class _Result:
            def __init__(self):
                self.returncode = 0
                self.stdout = ""
                self.stderr = ""

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _Result()

        import subprocess

        monkeypatch.setattr(subprocess, "run", fake_run)

        out = str(tmp_path / "interactive.png")
        b = MacScreenshotBackend()
        result = b.capture_region(region=None, path=out)
        assert result["ok"] is True
        assert result["mode"] == "interactive"
        assert calls[0] == ["screencapture", "-i", out]

    def test_capture_region_invalid_region_length(self, tmp_path):
        """region 长度不为 4 时返回 E_INVALID_ARG。"""
        b = MacScreenshotBackend()
        result = b.capture_region(region=(10, 20, 30), path=str(tmp_path / "x.png"))  # type: ignore[arg-type]
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_ARG"

    def test_capture_region_non_positive_size(self, tmp_path):
        """region 宽高 <= 0 时返回 E_OUT_OF_RANGE。"""
        b = MacScreenshotBackend()
        result = b.capture_region(region=(0, 0, 0, 100), path=str(tmp_path / "x.png"))
        assert result["ok"] is False
        assert result["error"]["code"] == "E_OUT_OF_RANGE"

    def test_capture_full_command_failure(self, monkeypatch, tmp_path):
        """screencapture 返回非零退出码时映射为 E_BACKEND_UNAVAILABLE。"""

        class _Result:
            def __init__(self):
                self.returncode = 1
                self.stdout = ""
                self.stderr = "permission denied"

        import subprocess

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Result())

        b = MacScreenshotBackend()
        result = b.capture_full(path=str(tmp_path / "fail.png"))
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"
        assert "permission denied" in result["error"]["message"]

    def test_capture_full_command_missing(self, monkeypatch, tmp_path):
        """screencapture 命令不存在时返回 E_BACKEND_UNAVAILABLE。"""
        import subprocess

        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("screencapture"))
        )

        b = MacScreenshotBackend()
        result = b.capture_full(path=str(tmp_path / "missing.png"))
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"
        assert "screencapture" in result["error"]["message"]

    def test_capture_full_creates_parent_dir(self, monkeypatch, tmp_path):
        """capture_full 创建输出路径的父目录。"""
        calls: list[list[str]] = []

        class _Result:
            def __init__(self):
                self.returncode = 0
                self.stdout = ""
                self.stderr = ""

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _Result()

        import subprocess

        monkeypatch.setattr(subprocess, "run", fake_run)

        # 使用嵌套路径，验证父目录被创建
        nested = tmp_path / "nested" / "dir" / "shot.png"
        b = MacScreenshotBackend()
        result = b.capture_full(path=str(nested))
        assert result["ok"] is True
        assert nested.parent.is_dir()
