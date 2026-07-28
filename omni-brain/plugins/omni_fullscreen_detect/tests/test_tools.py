"""omni_fullscreen_detect 工具 handler 测试（M16-P1）。

全部使用 FakeFullscreenBackend，不依赖 macOS Accessibility API。
覆盖：
- 检测到全屏应用
- 无全屏应用
- 后端异常
- 后端不可用（E_BACKEND_UNAVAILABLE）
- 事件发布
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

from omni_fullscreen_detect import FullscreenDetectPlugin
from omni_fullscreen_detect.backends import FakeFullscreenBackend


def _setup_plugin(
    backend: Any = None,
) -> tuple[FullscreenDetectPlugin, PluginContext, EventBus]:
    """构造已 on_load 的插件 + ctx + event_bus。"""
    event_bus = EventBus()
    ctx = PluginContext(
        config={"backend": backend} if backend is not None else {},
        event_bus=event_bus,
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        plugin_name="omni_fullscreen_detect",
    )
    plugin = FullscreenDetectPlugin()
    asyncio.run(plugin.on_load(ctx))
    return plugin, ctx, event_bus


def _call_tool(ctx: PluginContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """调用工具并解析返回 JSON。"""
    tool = ctx.tool_registry.get_tool(name)
    assert tool is not None, f"工具 {name} 未注册"
    result = tool.handler_func(args)
    assert isinstance(result, str), "handler 必须返回 JSON 字符串"
    return json.loads(result)


class TestDetectFullscreenApp:
    def test_detect_fullscreen_app_found(self) -> None:
        """检测到全屏应用时返回应用名 + pid + window_title。"""
        fake = FakeFullscreenBackend(
            fullscreen_app="Safari",
            pid=1234,
            window_title="Apple",
        )
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_detect_fullscreen_app", {})
        assert result["ok"] is True
        assert result["fullscreen"] is True
        assert result["app"] == "Safari"
        assert result["pid"] == 1234
        assert result["window_title"] == "Apple"

    def test_detect_fullscreen_app_none(self) -> None:
        """无全屏应用时返回 fullscreen=False。"""
        fake = FakeFullscreenBackend(fullscreen_app=None)
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_detect_fullscreen_app", {})
        assert result["ok"] is True
        assert result["fullscreen"] is False
        assert result["app"] is None

    def test_detect_fullscreen_app_publishes_event(self) -> None:
        """检测到全屏应用时发布 system.fullscreen_changed 事件。"""
        fake = FakeFullscreenBackend(fullscreen_app="VLC", pid=5678)
        plugin, ctx, event_bus = _setup_plugin(fake)
        received: list[dict[str, Any]] = []
        event_bus.subscribe("system.fullscreen_changed", lambda p: received.append(p))
        _call_tool(ctx, "system_detect_fullscreen_app", {})
        asyncio.run(asyncio.sleep(0.01))
        assert len(received) == 1
        assert received[0]["app"] == "VLC"
        assert received[0]["fullscreen"] is True

    def test_detect_fullscreen_app_no_event_when_none(self) -> None:
        """无全屏应用时不发布事件。"""
        fake = FakeFullscreenBackend(fullscreen_app=None)
        plugin, ctx, event_bus = _setup_plugin(fake)
        received: list[dict[str, Any]] = []
        event_bus.subscribe("system.fullscreen_changed", lambda p: received.append(p))
        _call_tool(ctx, "system_detect_fullscreen_app", {})
        asyncio.run(asyncio.sleep(0.01))
        assert len(received) == 0

    def test_detect_fullscreen_app_backend_exception(self) -> None:
        """后端异常映射为 ok:false。"""
        fake = FakeFullscreenBackend(raise_on_detect=True)
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_detect_fullscreen_app", {})
        assert result["ok"] is False
        assert "error" in result


class TestBackendUnavailable:
    def test_no_backend_returns_e_backend_unavailable(self) -> None:
        """未注入后端时返回 E_BACKEND_UNAVAILABLE。"""
        plugin, ctx, _ = _setup_plugin(backend=None)
        result = _call_tool(ctx, "system_detect_fullscreen_app", {})
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"


class TestBackendDeclarations:
    def test_fake_backend_records_calls(self) -> None:
        """FakeFullscreenBackend 记录调用次数以供断言。"""
        fake = FakeFullscreenBackend(fullscreen_app="Xcode")
        assert fake.detect_count == 0
        fake.detect_fullscreen_app()
        assert fake.detect_count == 1
        fake.detect_fullscreen_app()
        assert fake.detect_count == 2


class TestRealAppleScriptBackend:
    """AppleScriptFullscreenBackend 测试（monkeypatch subprocess）。"""

    def test_applescript_detect_fullscreen_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """检测到全屏窗口。"""
        import sys
        import types

        class _FakeResult:
            returncode = 0
            stdout = "Safari|Apple, VLC|Movie"

        fake_subprocess = types.ModuleType("subprocess")
        fake_subprocess.run = lambda *a, **kw: _FakeResult()
        monkeypatch.setitem(sys.modules, "subprocess", fake_subprocess)

        from omni_fullscreen_detect.backends import AppleScriptFullscreenBackend

        backend = AppleScriptFullscreenBackend()
        result = backend.detect_fullscreen_app()
        assert result["fullscreen"] is True
        assert result["app"] == "Safari"
        assert result["window_title"] == "Apple"
        assert result["pid"] is None

    def test_applescript_detect_no_fullscreen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无全屏窗口。"""
        import sys
        import types

        class _FakeResult:
            returncode = 0
            stdout = ""

        fake_subprocess = types.ModuleType("subprocess")
        fake_subprocess.run = lambda *a, **kw: _FakeResult()
        monkeypatch.setitem(sys.modules, "subprocess", fake_subprocess)

        from omni_fullscreen_detect.backends import AppleScriptFullscreenBackend

        backend = AppleScriptFullscreenBackend()
        result = backend.detect_fullscreen_app()
        assert result["fullscreen"] is False
        assert result["app"] is None

    def test_applescript_no_separator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """输出无 | 分隔符时 app 取整段、title 为空。"""
        import sys
        import types

        class _FakeResult:
            returncode = 0
            stdout = "SomeApp"

        fake_subprocess = types.ModuleType("subprocess")
        fake_subprocess.run = lambda *a, **kw: _FakeResult()
        monkeypatch.setitem(sys.modules, "subprocess", fake_subprocess)

        from omni_fullscreen_detect.backends import AppleScriptFullscreenBackend

        backend = AppleScriptFullscreenBackend()
        result = backend.detect_fullscreen_app()
        assert result["fullscreen"] is True
        assert result["app"] == "SomeApp"
        assert result["window_title"] == ""

    def test_applescript_osascript_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """osascript 返回非 0 时抛 RuntimeError。"""
        import sys
        import types

        class _FakeResult:
            returncode = 1
            stderr = "not authorized"

        fake_subprocess = types.ModuleType("subprocess")
        fake_subprocess.run = lambda *a, **kw: _FakeResult()
        monkeypatch.setitem(sys.modules, "subprocess", fake_subprocess)

        from omni_fullscreen_detect.backends import AppleScriptFullscreenBackend

        backend = AppleScriptFullscreenBackend()
        with pytest.raises(RuntimeError, match="osascript"):
            backend.detect_fullscreen_app()


class TestRealAccessibilityBackend:
    """AccessibilityFullscreenBackend 测试（monkeypatch pyobjc 模块）。"""

    def test_accessibility_detect_no_fullscreen(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无全屏窗口时返回 fullscreen=False。"""
        import sys
        import types

        # 构造 fake AppKit / ApplicationServices / CoreFoundation
        class _FakeApp:
            def __init__(self, pid):
                self.pid = pid

            def processIdentifier(self):
                return self.pid

            def localizedName(self):
                return f"App{self.pid}"

            def bundleIdentifier(self):
                return f"com.app{self.pid}"

        class _FakeWorkspace:
            @staticmethod
            def sharedWorkspace():
                class _WS:
                    @staticmethod
                    def runningApplications():
                        return [_FakeApp(1), _FakeApp(2)]

                return _WS()

        fake_appkit = types.ModuleType("AppKit")
        fake_appkit.NSWorkspace = _FakeWorkspace
        monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)

        # AXUIElementCopyAttributeValue 返回 (err, value)，err=0 表示成功
        def _copy_attr(element, attr, _arg):
            if attr == "AXChildren":
                return (0, [])  # 无窗口
            return (1, None)

        fake_as = types.ModuleType("ApplicationServices")
        fake_as.AXUIElementCopyAttributeValue = _copy_attr
        fake_as.AXUIElementCreateApplication = lambda pid: ("app", pid)
        fake_as.kAXChildrenAttribute = "AXChildren"
        fake_as.kAXFullScreenAttribute = "AXFullScreen"
        fake_as.kAXRoleAttribute = "AXRole"
        fake_as.kAXTitleAttribute = "AXTitle"
        monkeypatch.setitem(sys.modules, "ApplicationServices", fake_as)

        fake_cf = types.ModuleType("CoreFoundation")
        fake_cf.CFRelease = lambda x: None
        fake_cf.CFArrayGetCount = lambda x: 0
        fake_cf.CFArrayGetValueAtIndex = lambda x, i: None
        monkeypatch.setitem(sys.modules, "CoreFoundation", fake_cf)

        from omni_fullscreen_detect.backends import AccessibilityFullscreenBackend

        backend = AccessibilityFullscreenBackend()
        result = backend.detect_fullscreen_app()
        assert result["fullscreen"] is False
        assert result["app"] is None

    def test_accessibility_detect_fullscreen_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """检测到全屏窗口。"""
        import sys
        import types

        # 构造一个 app，其有一个 AXWindow 角色、AXFullScreen=True 的窗口
        window_marker = {"role": "AXWindow", "fullscreen": True, "title": "Apple"}

        class _FakeApp:
            def __init__(self, pid):
                self.pid = pid

            def processIdentifier(self):
                return self.pid

            def localizedName(self):
                return "Safari"

            def bundleIdentifier(self):
                return "com.apple.Safari"

        class _FakeWorkspace:
            @staticmethod
            def sharedWorkspace():
                class _WS:
                    @staticmethod
                    def runningApplications():
                        return [_FakeApp(1234)]

                return _WS()

        fake_appkit = types.ModuleType("AppKit")
        fake_appkit.NSWorkspace = _FakeWorkspace
        monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)

        def _copy_attr(element, attr, _arg=None):
            if attr == "AXChildren":
                # 返回包含一个 fake window 的 CFArray-like
                return (0, [window_marker])
            if attr == "AXRole":
                return (0, window_marker["role"])
            if attr == "AXFullScreen":
                return (0, window_marker["fullscreen"])
            if attr == "AXTitle":
                return (0, window_marker["title"])
            return (1, None)

        fake_as = types.ModuleType("ApplicationServices")
        fake_as.AXUIElementCopyAttributeValue = _copy_attr
        fake_as.AXUIElementCreateApplication = lambda pid: ("app", pid)
        fake_as.kAXChildrenAttribute = "AXChildren"
        fake_as.kAXFullScreenAttribute = "AXFullScreen"
        fake_as.kAXRoleAttribute = "AXRole"
        fake_as.kAXTitleAttribute = "AXTitle"
        monkeypatch.setitem(sys.modules, "ApplicationServices", fake_as)

        fake_cf = types.ModuleType("CoreFoundation")
        fake_cf.CFRelease = lambda x: None
        fake_cf.CFArrayGetCount = lambda x: 1
        fake_cf.CFArrayGetValueAtIndex = lambda x, i: window_marker
        monkeypatch.setitem(sys.modules, "CoreFoundation", fake_cf)

        from omni_fullscreen_detect.backends import AccessibilityFullscreenBackend

        backend = AccessibilityFullscreenBackend()
        result = backend.detect_fullscreen_app()
        assert result["fullscreen"] is True
        assert result["app"] == "Safari"
        assert result["pid"] == 1234
        assert result["window_title"] == "Apple"


class TestFullscreenEventPublish:
    """omni_fullscreen_detect._publish_event 边界分支测试。"""

    def test_publish_event_no_event_bus(self) -> None:
        """event_bus 为 None 时静默返回。"""
        from omni_fullscreen_detect import FullscreenDetectPlugin

        plugin = FullscreenDetectPlugin()
        plugin._event_bus = None
        plugin._publish_event("system.fullscreen_changed", {"app": "X"})

    def test_publish_event_bus_exception_swallowed(self) -> None:
        """event_bus.publish 抛异常时被吞掉。"""
        from omni_fullscreen_detect import FullscreenDetectPlugin

        plugin = FullscreenDetectPlugin()

        class _BadBus:
            def publish(self, event_type, payload):
                raise RuntimeError("bus broken")

        plugin._event_bus = _BadBus()
        plugin._publish_event("system.fullscreen_changed", {"app": "X"})
