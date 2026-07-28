"""omni_power 后端实现：FakePowerBackend（测试）+ MacPowerBackend（pmset/osascript）。

约定：
- 后端方法返回 dict：成功 ``{"ok": True, "action": str, "command": str}``；
  失败 ``{"ok": False, "error": {"code": "E_XXX", "message": "..."}}``。
- 危险操作（shutdown/restart）的确认由 tools 层负责（``confirm`` 参数），
  后端只执行命令，不再做二次校验。
- subprocess 在函数内 import（惰性导入，符合 CLAUDE.md §三）。

macOS 命令映射：
- lock_screen  ：``pmset displaysleepnow``（关闭显示，等同锁屏）
- sleep        ：``pmset sleepnow``
- shutdown     ：``osascript -e 'tell app "System Events" to shut down'``
- restart      ：``osascript -e 'tell app "System Events" to restart'``
"""

from __future__ import annotations

from typing import Any


class FakePowerBackend:
    """假电源后端：记录每次动作，不执行任何系统命令。

    ``calls`` 列表按调用顺序记录 ``action`` 字符串，供测试断言。
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.last_command: str | None = None

    def _record(self, action: str, command: str) -> dict[str, Any]:
        """记录调用并返回成功响应。"""
        self.calls.append(action)
        self.last_command = command
        return {"ok": True, "action": action, "command": command}

    def lock_screen(self) -> dict[str, Any]:
        """锁屏（关闭显示）。"""
        return self._record("lock_screen", "pmset displaysleepnow")

    def sleep(self) -> dict[str, Any]:
        """睡眠。"""
        return self._record("sleep", "pmset sleepnow")

    def shutdown(self) -> dict[str, Any]:
        """关机。"""
        return self._record("shutdown", "osascript -e 'tell app \"System Events\" to shut down'")

    def restart(self) -> dict[str, Any]:
        """重启。"""
        return self._record("restart", "osascript -e 'tell app \"System Events\" to restart'")


class MacPowerBackend:
    """macOS 电源后端：通过 ``pmset`` / ``osascript`` 控制电源动作。

    - lock_screen / sleep 使用 ``pmset``（系统自带）
    - shutdown / restart 使用 ``osascript`` 调用 System Events

    subprocess 在每个方法内 import；命令不存在或返回非零退出码时
    返回 ``E_BACKEND_UNAVAILABLE`` / ``E_COMMAND_FAILED``。
    """

    def _run(self, cmd: list[str]) -> tuple[bool, str]:
        """执行一条命令，返回 (success, output_or_error)。"""
        try:
            import subprocess  # 惰性导入（CLAUDE.md §三）
        except ImportError as exc:
            return False, f"subprocess 不可用: {exc}"

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except FileNotFoundError:
            return False, f"命令不存在: {cmd[0]}"
        except Exception as exc:  # noqa: BLE001 - 超时/权限等统一映射
            return False, f"命令调用失败: {exc}"

        if result.returncode != 0:
            err = (result.stderr or "").strip() or f"退出码 {result.returncode}"
            return False, err
        return True, (result.stdout or "").strip()

    def lock_screen(self) -> dict[str, Any]:
        """锁屏（关闭显示）。"""
        ok, output = self._run(["pmset", "displaysleepnow"])
        if not ok:
            return {
                "ok": False,
                "error": {"code": "E_BACKEND_UNAVAILABLE", "message": output},
            }
        return {"ok": True, "action": "lock_screen", "command": "pmset displaysleepnow"}

    def sleep(self) -> dict[str, Any]:
        """睡眠。"""
        ok, output = self._run(["pmset", "sleepnow"])
        if not ok:
            return {
                "ok": False,
                "error": {"code": "E_BACKEND_UNAVAILABLE", "message": output},
            }
        return {"ok": True, "action": "sleep", "command": "pmset sleepnow"}

    def shutdown(self) -> dict[str, Any]:
        """关机（osascript）。"""
        ok, output = self._run(
            ["osascript", "-e", 'tell app "System Events" to shut down']
        )
        if not ok:
            return {
                "ok": False,
                "error": {"code": "E_BACKEND_UNAVAILABLE", "message": output},
            }
        return {
            "ok": True,
            "action": "shutdown",
            "command": "osascript -e 'tell app \"System Events\" to shut down'",
        }

    def restart(self) -> dict[str, Any]:
        """重启（osascript）。"""
        ok, output = self._run(
            ["osascript", "-e", 'tell app "System Events" to restart']
        )
        if not ok:
            return {
                "ok": False,
                "error": {"code": "E_BACKEND_UNAVAILABLE", "message": output},
            }
        return {
            "ok": True,
            "action": "restart",
            "command": "osascript -e 'tell app \"System Events\" to restart'",
        }
