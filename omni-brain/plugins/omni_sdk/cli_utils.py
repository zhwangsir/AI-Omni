"""CLI 通用工具：输出标准 JSON 错误格式的 ArgumentParser。"""

from __future__ import annotations

import argparse
import json


class JsonErrorArgumentParser(argparse.ArgumentParser):
    """参数解析失败时输出 JSON 错误并退出（替代 argparse 默认英文用法信息）。

    输出格式遵循插件契约 ``{"ok": false, "error": {"code": "E_INVALID_PARAMS", "message": ...}}``，
    退出码固定为 ``1``，与 tools 层 ``ok:false`` 的退出码约定保持一致。
    ``--help`` 不受影响，仍以退出码 ``0`` 输出帮助文本。
    """

    def error(self, message: str) -> None:
        """重写 argparse 错误处理：打印 JSON 后退出。"""
        payload = {
            "ok": False,
            "error": {"code": "E_INVALID_PARAMS", "message": message},
        }
        print(json.dumps(payload, ensure_ascii=False))
        self.exit(1)
