"""omni_fullscreen_detect 后端实现：全屏检测抽象 + fake/真实后端。

- :class:`FullscreenBackend`：抽象基类（Protocol）
- :class:`FakeFullscreenBackend`：测试用 fake 后端
- :class:`AccessibilityFullscreenBackend`：macOS Accessibility API 真实后端（惰性导入）

真实后端策略：
1. 优先用 macOS Accessibility API（AXUIElement）遍历窗口，检测 AXFullScreen 属性
2. Accessibility API 不可用时（未授权 / 非 macOS）降级为 AppleScript 窗口标题检测
3. 均不可用则由调用方返回 E_BACKEND_UNAVAILABLE
"""

from __future__ import annotations

from typing import Any, Protocol


class FullscreenBackend(Protocol):
    """全屏检测后端契约。"""

    def detect_fullscreen_app(self) -> dict[str, Any]:
        """检测当前全屏应用。

        :return: ``{"fullscreen": bool, "app": str|None, "pid": int|None,
                  "window_title": str|None}``
        """
        ...


class FakeFullscreenBackend:
    """假全屏检测后端，用于测试与演示。

    内置固定的全屏应用信息；记录调用次数以供断言。
    """

    def __init__(
        self,
        fullscreen_app: str | None = None,
        pid: int | None = None,
        window_title: str | None = None,
        *,
        raise_on_detect: bool = False,
    ) -> None:
        """构造 fake 后端。

        :param fullscreen_app: 全屏应用名；None 表示无全屏应用
        :param pid: 进程 PID
        :param window_title: 窗口标题
        :param raise_on_detect: detect 时抛 RuntimeError
        """
        self._app = fullscreen_app
        self._pid = pid
        self._title = window_title
        self._raise_on_detect = raise_on_detect
        self.detect_count: int = 0

    def detect_fullscreen_app(self) -> dict[str, Any]:
        """返回固定的全屏检测结果。"""
        if self._raise_on_detect:
            raise RuntimeError("fake: detect_fullscreen_app failed")
        self.detect_count += 1
        if self._app is None:
            return {"fullscreen": False, "app": None, "pid": None, "window_title": None}
        return {
            "fullscreen": True,
            "app": self._app,
            "pid": self._pid,
            "window_title": self._title,
        }


class AccessibilityFullscreenBackend:
    """macOS Accessibility API 真实后端（惰性导入 AppKit / ApplicationServices）。

    检测策略：
    1. 遍历所有运行中应用的窗口（AXWindows）
    2. 检查每个窗口的 AXFullScreen 属性
    3. 找到第一个全屏窗口即返回

    Accessibility API 未授权时抛 RuntimeError，由调用方降级处理。
    """

    def detect_fullscreen_app(self) -> dict[str, Any]:
        """用 Accessibility API 检测全屏应用。"""
        # 惰性导入：仅在真正调用时拉入 AppKit / ApplicationServices
        from AppKit import NSWorkspace  # type: ignore
        from ApplicationServices import (  # type: ignore
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
            kAXChildrenAttribute,
            kAXFullScreenAttribute,
            kAXRoleAttribute,
            kAXTitleAttribute,
        )
        from CoreFoundation import CFRelease  # type: ignore

        workspace = NSWorkspace.sharedWorkspace()
        apps = workspace.runningApplications()
        for app in apps:
            pid = app.processIdentifier()
            if pid <= 0:
                continue
            app_name = app.localizedName() or app.bundleIdentifier() or ""
            app_element = AXUIElementCreateApplication(pid)
            try:
                # 取窗口列表
                windows_ref = self._copy_attr(app_element, kAXChildrenAttribute)
                if windows_ref is None:
                    continue
                windows = self._to_list(windows_ref)
                for window in windows:
                    # 确认是 window 角色
                    role = self._copy_attr(window, kAXRoleAttribute)
                    if role != "AXWindow":
                        continue
                    # 检查全屏属性
                    is_fullscreen = self._copy_attr(window, kAXFullScreenAttribute)
                    if is_fullscreen is True:
                        title = self._copy_attr(window, kAXTitleAttribute) or ""
                        return {
                            "fullscreen": True,
                            "app": str(app_name),
                            "pid": int(pid),
                            "window_title": str(title),
                        }
            finally:
                if windows_ref is not None:
                    CFRelease(windows_ref)
        return {"fullscreen": False, "app": None, "pid": None, "window_title": None}

    @staticmethod
    def _copy_attr(element: Any, attr: str) -> Any:
        """从 AXUIElement 复制属性值；失败返回 None。"""
        from ApplicationServices import AXUIElementCopyAttributeValue  # type: ignore

        err, value = AXUIElementCopyAttributeValue(element, attr, None)
        if err != 0:
            return None
        return value

    @staticmethod
    def _to_list(cf_array: Any) -> list[Any]:
        """把 CFArray 转为 Python list。"""
        from CoreFoundation import CFArrayGetCount, CFArrayGetValueAtIndex  # type: ignore

        count = CFArrayGetCount(cf_array)
        return [CFArrayGetValueAtIndex(cf_array, i) for i in range(count)]


class AppleScriptFullscreenBackend:
    """AppleScript 降级后端：用 System Events 检测全屏窗口。

    当 Accessibility API 不可用时（pyobjc 未装 / 未授权），用 osascript 调用
    System Events 检测全屏窗口标题。仅返回窗口标题，无 pid。
    """

    def detect_fullscreen_app(self) -> dict[str, Any]:
        """用 AppleScript 检测全屏窗口。"""
        import subprocess  # 惰性导入

        script = """
        tell application "System Events"
            set fullscreenWindows to {}
            repeat with proc in (every process whose background only is false)
                try
                    repeat with w in windows of proc
                        try
                            set isFS to value of attribute "AXFullScreen" of w
                            if isFS is true then
                                set end of fullscreenWindows to (name of proc) & "|" & (name of w)
                            end if
                        end try
                    end repeat
                end try
            end repeat
            return fullscreenWindows
        end tell
        """
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError(f"osascript 失败: {result.stderr.strip()}")
        output = result.stdout.strip()
        if not output:
            return {"fullscreen": False, "app": None, "pid": None, "window_title": None}
        # 解析输出（格式: app|title, app2|title2）
        first = output.split(",")[0].strip()
        if "|" in first:
            app_name, title = first.split("|", 1)
        else:
            app_name, title = first, ""
        return {
            "fullscreen": True,
            "app": app_name.strip(),
            "pid": None,
            "window_title": title.strip(),
        }
