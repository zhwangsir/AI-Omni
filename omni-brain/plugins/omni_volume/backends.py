"""omni_volume 后端实现：FakeVolumeBackend（测试）+ MacVolumeBackend（osascript）。

约定：
- 后端方法返回 dict：成功 ``{"ok": True, "volume": int, "muted": bool}``；
  失败 ``{"ok": False, "error": {"code": "E_XXX", "message": "..."}}``。
- ``level`` 范围 0-100；macOS 内部音量刻度 0-7，由后端做映射。
- subprocess 在函数内 import（惰性导入，符合 CLAUDE.md §三）。
"""

from __future__ import annotations

from typing import Any


class FakeVolumeBackend:
    """假音量后端：内存状态机，用于测试与演示，不执行任何系统命令。

    初始音量 50、未静音；``set_volume`` 直接覆盖内部状态。
    """

    def __init__(self, volume: int = 50, muted: bool = False) -> None:
        """构造 fake 后端，初始音量默认 50、未静音。

        :param volume: 初始音量 0-100
        :param muted: 初始静音状态
        """
        self.volume: int = volume
        self.muted: bool = muted
        # 记录最近一次 osascript 等价命令（供测试断言后端调用）
        self.last_command: str | None = None

    def set_volume(self, level: int) -> dict[str, Any]:
        """设置音量（0-100）。"""
        if not isinstance(level, int):
            return {
                "ok": False,
                "error": {"code": "E_INVALID_ARG", "message": "level 必须是整数"},
            }
        if level < 0 or level > 100:
            return {
                "ok": False,
                "error": {
                    "code": "E_OUT_OF_RANGE",
                    "message": f"level 必须 0-100，got {level}",
                },
            }
        self.volume = level
        # 设置音量时取消静音（与 macOS 行为一致）
        self.muted = False
        self.last_command = f"set volume {round(level / 100 * 7)}"
        return {"ok": True, "volume": self.volume, "muted": self.muted}

    def get_volume(self) -> dict[str, Any]:
        """返回当前音量与静音状态。"""
        return {"ok": True, "volume": self.volume, "muted": self.muted}

    def mute(self) -> dict[str, Any]:
        """静音。"""
        self.muted = True
        self.last_command = "set volume with output muted"
        return {"ok": True, "volume": self.volume, "muted": self.muted}

    def unmute(self) -> dict[str, Any]:
        """取消静音。"""
        self.muted = False
        self.last_command = "set volume without output muted"
        return {"ok": True, "volume": self.volume, "muted": self.muted}


class MacVolumeBackend:
    """macOS 音量后端：通过 ``osascript`` 控制 AppleScript 音量设置。

    macOS 内部音量刻度为 0-7（整数），本后端把 0-100 百分比映射为 0-7：
    ``mac_level = round(level / 100 * 7)``。

    subprocess 在每个方法内 import；osascript 不可用或返回非零退出码时
    返回 ``E_BACKEND_UNAVAILABLE`` / ``E_COMMAND_FAILED``。
    """

    def _run_osascript(self, script: str) -> tuple[bool, str]:
        """执行一条 osascript 命令，返回 (success, output_or_error)。

        subprocess 惰性导入；osascript 不存在或调用异常时返回失败。
        """
        try:
            import subprocess  # 惰性导入（CLAUDE.md §三）
        except ImportError as exc:
            return False, f"subprocess 不可用: {exc}"

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except FileNotFoundError:
            return False, "osascript 命令不存在（非 macOS 平台？）"
        except Exception as exc:  # noqa: BLE001 - 超时/权限等统一映射
            return False, f"osascript 调用失败: {exc}"

        if result.returncode != 0:
            err = (result.stderr or "").strip() or f"退出码 {result.returncode}"
            return False, err
        return True, (result.stdout or "").strip()

    def set_volume(self, level: int) -> dict[str, Any]:
        """设置音量（0-100）。"""
        if not isinstance(level, int):
            return {
                "ok": False,
                "error": {"code": "E_INVALID_ARG", "message": "level 必须是整数"},
            }
        if level < 0 or level > 100:
            return {
                "ok": False,
                "error": {
                    "code": "E_OUT_OF_RANGE",
                    "message": f"level 必须 0-100，got {level}",
                },
            }
        mac_level = round(level / 100 * 7)
        ok, output = self._run_osascript(f"set volume {mac_level}")
        if not ok:
            return {
                "ok": False,
                "error": {"code": "E_BACKEND_UNAVAILABLE", "message": output},
            }
        # 设置音量时取消静音（与 macOS 行为一致）
        self._run_osascript("set volume without output muted")
        return {"ok": True, "volume": level, "muted": False}

    def get_volume(self) -> dict[str, Any]:
        """查询当前音量与静音状态。"""
        ok, output = self._run_osascript("output volume of (get volume settings)")
        if not ok:
            return {
                "ok": False,
                "error": {"code": "E_BACKEND_UNAVAILABLE", "message": output},
            }
        try:
            volume = int(output.strip())
        except ValueError:
            return {
                "ok": False,
                "error": {
                    "code": "E_PARSE_FAILED",
                    "message": f"无法解析音量值: {output!r}",
                },
            }
        # 查询静音状态
        ok2, muted_str = self._run_osascript("output muted of (get volume settings)")
        muted = False
        if ok2:
            muted = muted_str.strip().lower() == "true"
        return {"ok": True, "volume": volume, "muted": muted}

    def mute(self) -> dict[str, Any]:
        """静音。"""
        ok, output = self._run_osascript("set volume with output muted")
        if not ok:
            return {
                "ok": False,
                "error": {"code": "E_BACKEND_UNAVAILABLE", "message": output},
            }
        # 静音不影响音量值，只标记 muted=True
        vol = self.get_volume()
        volume = vol.get("volume", 0) if vol.get("ok") else 0
        return {"ok": True, "volume": volume, "muted": True}

    def unmute(self) -> dict[str, Any]:
        """取消静音。"""
        ok, output = self._run_osascript("set volume without output muted")
        if not ok:
            return {
                "ok": False,
                "error": {"code": "E_BACKEND_UNAVAILABLE", "message": output},
            }
        vol = self.get_volume()
        volume = vol.get("volume", 0) if vol.get("ok") else 0
        return {"ok": True, "volume": volume, "muted": False}
