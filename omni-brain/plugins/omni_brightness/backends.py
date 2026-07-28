"""omni_brightness 后端实现：FakeBrightnessBackend（测试）+ MacBrightnessBackend（brightness CLI）。

约定：
- 后端方法返回 dict：成功 ``{"ok": True, "brightness": int}``；
  失败 ``{"ok": False, "error": {"code": "E_XXX", "message": "..."}}``。
- ``level`` 范围 0-100；macOS ``brightness`` CLI 接受 0-1 浮点，由后端做映射。
- subprocess 在函数内 import（惰性导入，符合 CLAUDE.md §三）。
"""

from __future__ import annotations

from typing import Any


class FakeBrightnessBackend:
    """假亮度后端：内存状态机，用于测试与演示，不执行任何系统命令。

    初始亮度 75。
    """

    def __init__(self, brightness: int = 75) -> None:
        """构造 fake 后端，初始亮度默认 75。

        :param brightness: 初始亮度 0-100
        """
        self.brightness: int = brightness
        # 记录最近一次 CLI 等价命令（供测试断言后端调用）
        self.last_command: str | None = None

    def set_brightness(self, level: int) -> dict[str, Any]:
        """设置亮度（0-100）。"""
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
        self.brightness = level
        # brightness CLI 接受 0-1 浮点；记录等价命令供测试断言
        self.last_command = f"brightness {level / 100:.2f}"
        return {"ok": True, "brightness": self.brightness}

    def get_brightness(self) -> dict[str, Any]:
        """返回当前亮度。"""
        return {"ok": True, "brightness": self.brightness}


class MacBrightnessBackend:
    """macOS 亮度后端：通过 ``brightness`` CLI 控制屏幕亮度。

    依赖第三方 ``brightness`` 命令（``brew install brightness``），
    接受 0-1 浮点参数。本后端把 0-100 百分比映射为 0-1：
    ``mac_level = level / 100``。

    查询亮度时尝试 ``brightness -l`` 解析 ``brightness`` 字段；
    命令不存在或解析失败时返回 ``E_BACKEND_UNAVAILABLE`` / ``E_PARSE_FAILED``。

    subprocess 在每个方法内 import。
    """

    def _run_brightness(self, args: list[str]) -> tuple[bool, str]:
        """执行一条 ``brightness`` 命令，返回 (success, output_or_error)。"""
        try:
            import subprocess  # 惰性导入（CLAUDE.md §三）
        except ImportError as exc:
            return False, f"subprocess 不可用: {exc}"

        try:
            result = subprocess.run(
                ["brightness", *args],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except FileNotFoundError:
            return False, "brightness 命令不存在（需 brew install brightness）"
        except Exception as exc:  # noqa: BLE001 - 超时/权限等统一映射
            return False, f"brightness 调用失败: {exc}"

        if result.returncode != 0:
            err = (result.stderr or "").strip() or f"退出码 {result.returncode}"
            return False, err
        return True, (result.stdout or "").strip()

    def set_brightness(self, level: int) -> dict[str, Any]:
        """设置亮度（0-100）。"""
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
        mac_level = level / 100
        ok, output = self._run_brightness([f"{mac_level:.2f}"])
        if not ok:
            return {
                "ok": False,
                "error": {"code": "E_BACKEND_UNAVAILABLE", "message": output},
            }
        return {"ok": True, "brightness": level}

    def get_brightness(self) -> dict[str, Any]:
        """查询当前亮度。

        ``brightness -l`` 输出形如 ``brightness 0.75``，解析第二个 token 为浮点。
        """
        ok, output = self._run_brightness(["-l"])
        if not ok:
            return {
                "ok": False,
                "error": {"code": "E_BACKEND_UNAVAILABLE", "message": output},
            }
        # 解析 "brightness 0.75" 格式
        try:
            # 取最后一行（避免多余输出干扰），按空白分割
            line = output.strip().splitlines()[-1] if output.strip() else ""
            parts = line.split()
            # 找到 "brightness" 关键字后的浮点值
            value: float | None = None
            for i, token in enumerate(parts):
                if token.lower() == "brightness" and i + 1 < len(parts):
                    value = float(parts[i + 1])
                    break
            if value is None:
                # 退化：尝试解析第一个浮点
                value = float(parts[0])
        except (ValueError, IndexError) as exc:
            return {
                "ok": False,
                "error": {
                    "code": "E_PARSE_FAILED",
                    "message": f"无法解析亮度值: {output!r} ({exc})",
                },
            }
        # 0-1 浮点映射回 0-100 整数
        return {"ok": True, "brightness": round(value * 100)}
