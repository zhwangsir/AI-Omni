"""omni_screenshot 后端实现：FakeScreenshotBackend（测试）+ MacScreenshotBackend（screencapture）。

约定：
- 后端方法返回 dict：
  成功 ``{"ok": True, "path": str, "mode": str}``；
  失败 ``{"ok": False, "error": {"code": "E_XXX", "message": "..."}}``。
- 截图默认保存到 ``~/Pictures/screenshot_<timestamp>.png``；
  可通过 ``path`` 参数指定输出路径。
- subprocess 在函数内 import（惰性导入，符合 CLAUDE.md §三）。

macOS 命令映射：
- full        ：``screencapture <path>``
- region(x,y,w,h)：``screencapture -R x,y,w,h <path>``
- region(interactive)：``screencapture -i <path>``（用户拖选区域）
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any


def _default_path() -> str:
    """生成默认截图路径：~/Pictures/screenshot_<timestamp>.png。"""
    pictures = Path.home() / "Pictures"
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return str(pictures / f"screenshot_{timestamp}.png")


class FakeScreenshotBackend:
    """假截图后端：记录每次调用参数，不执行真实 screencapture。

    ``calls`` 列表记录每次调用的 ``(mode, path, region)`` 元组。
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[int, int, int, int] | None]] = []
        # 模拟创建的文件大小（字节）；测试可断言返回 path
        self.fake_file_size: int = 1024

    def _record(
        self,
        mode: str,
        path: str,
        region: tuple[int, int, int, int] | None = None,
    ) -> dict[str, Any]:
        """记录调用并返回成功响应。"""
        self.calls.append((mode, path, region))
        return {"ok": True, "path": path, "mode": mode, "size": self.fake_file_size}

    def capture_full(self, path: str | None = None) -> dict[str, Any]:
        """全屏截图。"""
        out = path or _default_path()
        return self._record("full", out)

    def capture_region(
        self,
        region: tuple[int, int, int, int] | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """区域截图。

        :param region: ``(x, y, width, height)`` 元组；None 表示交互式选择
        :param path: 输出路径；None 使用默认路径
        """
        out = path or _default_path()
        mode = "region" if region is not None else "interactive"
        return self._record(mode, out, region)


class MacScreenshotBackend:
    """macOS 截图后端：通过 ``screencapture`` 命令截图。

    - ``capture_full``：``screencapture <path>``
    - ``capture_region(region=(x,y,w,h))``：``screencapture -R x,y,w,h <path>``
    - ``capture_region(region=None)``：``screencapture -i <path>``（交互式拖选）

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
                timeout=30,  # 截图可能需要用户交互，给足超时
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

    def capture_full(self, path: str | None = None) -> dict[str, Any]:
        """全屏截图。"""
        out = path or _default_path()
        # 确保父目录存在
        self._ensure_parent(out)
        ok, output = self._run(["screencapture", out])
        if not ok:
            return {
                "ok": False,
                "error": {"code": "E_BACKEND_UNAVAILABLE", "message": output},
            }
        return {"ok": True, "path": out, "mode": "full"}

    def capture_region(
        self,
        region: tuple[int, int, int, int] | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """区域截图。

        :param region: ``(x, y, width, height)`` 元组；None 表示交互式选择
        :param path: 输出路径；None 使用默认路径
        """
        out = path or _default_path()
        self._ensure_parent(out)
        if region is not None:
            # 校验 region 参数
            if len(region) != 4 or any(not isinstance(v, int) for v in region):
                return {
                    "ok": False,
                    "error": {
                        "code": "E_INVALID_ARG",
                        "message": f"region 必须是 4 个整数的元组 (x,y,w,h)，got {region!r}",
                    },
                }
            x, y, w, h = region
            if w <= 0 or h <= 0:
                return {
                    "ok": False,
                    "error": {
                        "code": "E_OUT_OF_RANGE",
                        "message": f"region 宽高必须 > 0，got w={w}, h={h}",
                    },
                }
            region_arg = f"{x},{y},{w},{h}"
            ok, output = self._run(["screencapture", "-R", region_arg, out])
            mode = "region"
        else:
            ok, output = self._run(["screencapture", "-i", out])
            mode = "interactive"
        if not ok:
            return {
                "ok": False,
                "error": {"code": "E_BACKEND_UNAVAILABLE", "message": output},
            }
        return {"ok": True, "path": out, "mode": mode}

    @staticmethod
    def _ensure_parent(path: str) -> None:
        """确保输出路径的父目录存在（不强制要求成功，screencapture 自身会报错）。"""
        try:
            parent = Path(path).parent
            parent.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001 - 目录创建失败不影响命令执行，由 screencapture 报错
            pass
