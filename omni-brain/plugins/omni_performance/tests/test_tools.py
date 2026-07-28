"""omni_performance 工具 handler 测试（M16-P1）。

全部使用 FakePerformanceBackend，不依赖真实硬件。
覆盖：
- cpu_usage：成功 / 异常 / 后端不可用
- memory_usage：成功 / 异常
- disk_usage：默认路径 / 自定义路径 / 异常
- 返回 JSON 字串格式
- E_BACKEND_UNAVAILABLE 错误码
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from omni_sdk.context import PluginContext
from omni_sdk.event_bus import EventBus
from omni_sdk.permissions import PermissionChecker
from omni_sdk.registry import ToolRegistry

from omni_performance import PerformancePlugin
from omni_performance.backends import FakePerformanceBackend


def _setup_plugin(backend: Any = None) -> tuple[PerformancePlugin, PluginContext]:
    """构造已 on_load 的插件 + ctx。"""
    ctx = PluginContext(
        config={"backend": backend} if backend is not None else {},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        plugin_name="omni_performance",
    )
    plugin = PerformancePlugin()
    asyncio.run(plugin.on_load(ctx))
    return plugin, ctx


def _call_tool(ctx: PluginContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """调用工具并解析返回 JSON。"""
    tool = ctx.tool_registry.get_tool(name)
    assert tool is not None, f"工具 {name} 未注册"
    result = tool.handler_func(args)
    assert isinstance(result, str), "handler 必须返回 JSON 字符串"
    return json.loads(result)


class TestCpuUsage:
    def test_cpu_usage_success(self) -> None:
        """返回 CPU 使用率与核心数。"""
        fake = FakePerformanceBackend()
        plugin, ctx = _setup_plugin(fake)
        result = _call_tool(ctx, "system_get_cpu_usage", {})
        assert result["ok"] is True
        assert "cpu_percent" in result
        assert "cpu_count" in result
        assert result["cpu_percent"] == 23.5
        assert result["cpu_count"] == 10

    def test_cpu_usage_backend_exception(self) -> None:
        """后端异常映射为 ok:false。"""
        fake = FakePerformanceBackend(raise_on_cpu=True)
        plugin, ctx = _setup_plugin(fake)
        result = _call_tool(ctx, "system_get_cpu_usage", {})
        assert result["ok"] is False
        assert "error" in result


class TestMemoryUsage:
    def test_memory_usage_success(self) -> None:
        """返回内存总量/可用/使用率。"""
        fake = FakePerformanceBackend()
        plugin, ctx = _setup_plugin(fake)
        result = _call_tool(ctx, "system_get_memory_usage", {})
        assert result["ok"] is True
        assert "total" in result
        assert "available" in result
        assert "percent" in result
        assert result["total"] == 34359738368

    def test_memory_usage_backend_exception(self) -> None:
        """后端异常映射为 ok:false。"""
        fake = FakePerformanceBackend(raise_on_memory=True)
        plugin, ctx = _setup_plugin(fake)
        result = _call_tool(ctx, "system_get_memory_usage", {})
        assert result["ok"] is False
        assert "error" in result


class TestDiskUsage:
    def test_disk_usage_default_path(self) -> None:
        """默认路径 / 返回磁盘使用情况。"""
        fake = FakePerformanceBackend()
        plugin, ctx = _setup_plugin(fake)
        result = _call_tool(ctx, "system_get_disk_usage", {})
        assert result["ok"] is True
        assert "total" in result
        assert "used" in result
        assert "free" in result
        assert "percent" in result
        assert fake.last_disk_path == "/"

    def test_disk_usage_custom_path(self) -> None:
        """自定义路径透传到后端。"""
        fake = FakePerformanceBackend()
        plugin, ctx = _setup_plugin(fake)
        result = _call_tool(ctx, "system_get_disk_usage", {"path": "/Volumes/Data"})
        assert result["ok"] is True
        assert fake.last_disk_path == "/Volumes/Data"

    def test_disk_usage_empty_path(self) -> None:
        """空路径返回 ok:false。"""
        fake = FakePerformanceBackend()
        plugin, ctx = _setup_plugin(fake)
        result = _call_tool(ctx, "system_get_disk_usage", {"path": ""})
        assert result["ok"] is False
        assert "error" in result

    def test_disk_usage_invalid_path_type(self) -> None:
        """path 类型错误返回 ok:false。"""
        fake = FakePerformanceBackend()
        plugin, ctx = _setup_plugin(fake)
        result = _call_tool(ctx, "system_get_disk_usage", {"path": 123})
        assert result["ok"] is False
        assert "error" in result

    def test_disk_usage_backend_exception(self) -> None:
        """后端异常映射为 ok:false。"""
        fake = FakePerformanceBackend(raise_on_disk=True)
        plugin, ctx = _setup_plugin(fake)
        result = _call_tool(ctx, "system_get_disk_usage", {"path": "/"})
        assert result["ok"] is False
        assert "error" in result


class TestBackendUnavailable:
    def test_cpu_usage_no_backend(self) -> None:
        """未注入后端时返回 E_BACKEND_UNAVAILABLE。"""
        plugin, ctx = _setup_plugin(backend=None)
        result = _call_tool(ctx, "system_get_cpu_usage", {})
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"

    def test_memory_usage_no_backend(self) -> None:
        """未注入后端时返回 E_BACKEND_UNAVAILABLE。"""
        plugin, ctx = _setup_plugin(backend=None)
        result = _call_tool(ctx, "system_get_memory_usage", {})
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"

    def test_disk_usage_no_backend(self) -> None:
        """未注入后端时返回 E_BACKEND_UNAVAILABLE。"""
        plugin, ctx = _setup_plugin(backend=None)
        result = _call_tool(ctx, "system_get_disk_usage", {"path": "/"})
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"


class TestRealPsutilBackend:
    """真实 PsutilPerformanceBackend 测试（monkeypatch psutil）。"""

    def test_psutil_cpu_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_cpu_usage 用 psutil.cpu_percent / cpu_count。"""
        import sys
        import types

        fake_psutil = types.ModuleType("psutil")
        fake_psutil.cpu_percent = lambda interval=None: 42.5
        fake_psutil.cpu_count = lambda: 8
        monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

        from omni_performance.backends import PsutilPerformanceBackend

        backend = PsutilPerformanceBackend()
        result = backend.get_cpu_usage()
        assert result == {"cpu_percent": 42.5, "cpu_count": 8}

    def test_psutil_memory_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_memory_usage 用 psutil.virtual_memory。"""
        import sys
        import types

        class _FakeMem:
            total = 34359738368
            available = 17179869184
            percent = 50.0

        fake_psutil = types.ModuleType("psutil")
        fake_psutil.virtual_memory = lambda: _FakeMem()
        monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

        from omni_performance.backends import PsutilPerformanceBackend

        backend = PsutilPerformanceBackend()
        result = backend.get_memory_usage()
        assert result == {
            "total": 34359738368,
            "available": 17179869184,
            "percent": 50.0,
        }

    def test_psutil_disk_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_disk_usage 用 psutil.disk_usage。"""
        import sys
        import types

        class _FakeDisk:
            total = 500107862016
            used = 250053931008
            free = 250053931008
            percent = 50.0

        fake_psutil = types.ModuleType("psutil")
        fake_psutil.disk_usage = lambda path: _FakeDisk()
        monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

        from omni_performance.backends import PsutilPerformanceBackend

        backend = PsutilPerformanceBackend()
        result = backend.get_disk_usage(path="/Volumes/Data")
        assert result == {
            "total": 500107862016,
            "used": 250053931008,
            "free": 250053931008,
            "percent": 50.0,
        }
