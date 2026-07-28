"""omni_process 工具 handler 实现 + JSON Schema。

3 个工具：
- ``system_list_processes(limit=20)``：列出进程
- ``system_kill_process(pid)``：杀死进程
- ``system_start_process(command)``：启动进程

handler 返回 JSON 字符串：``{"ok": true, ...}`` / ``{"ok": false, "error": {...}}``。
后端经 PluginContext.config["backend"] 注入（测试用 fake）；缺省时返回 E_BACKEND_UNAVAILABLE。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON 响应约定
# ---------------------------------------------------------------------------
def _ok(data: dict[str, Any]) -> str:
    """成功响应。"""
    return json.dumps({"ok": True, **data}, ensure_ascii=False)


def _err(code: str, message: str) -> str:
    """失败响应。"""
    return json.dumps(
        {"ok": False, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# JSON Schema 定义
# ---------------------------------------------------------------------------
SYSTEM_LIST_PROCESSES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "limit": {
            "type": "integer",
            "description": "返回的进程数量上限，默认 20。",
            "default": 20,
            "minimum": 1,
        }
    },
    "required": [],
}

SYSTEM_KILL_PROCESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pid": {
            "type": "integer",
            "description": "目标进程的 PID。",
        }
    },
    "required": ["pid"],
}

SYSTEM_START_PROCESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "启动命令，macOS 下为应用名（如 Safari），其他平台为可执行路径。",
        }
    },
    "required": ["command"],
}


# ---------------------------------------------------------------------------
# 工具 handler 工厂
# ---------------------------------------------------------------------------
def make_handlers(
    get_backend: Callable[[], Any],
    publish_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Callable[[dict[str, Any]], str]]:
    """构造 3 个 system_* 工具 handler。

    :param get_backend: 返回当前后端（可能为 None）的回调
    :param publish_event: 可选的事件发布回调
    :return: {tool_name: handler_func}
    """

    def _list_processes(args: dict[str, Any]) -> str:
        """列出进程。"""
        backend = get_backend()
        if backend is None:
            return _err("E_BACKEND_UNAVAILABLE", "进程后端未初始化")
        limit = args.get("limit", 20)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            return _err("E_INVALID_PARAM", f"limit 必须为正整数，got {limit!r}")
        try:
            processes = backend.list_processes(limit=limit)
            return _ok({"processes": processes, "count": len(processes)})
        except Exception as exc:  # noqa: BLE001
            logger.debug("system_list_processes 失败: %s", exc)
            return _err("E_BACKEND_ERROR", str(exc))

    def _kill_process(args: dict[str, Any]) -> str:
        """杀死进程。"""
        backend = get_backend()
        if backend is None:
            return _err("E_BACKEND_UNAVAILABLE", "进程后端未初始化")
        pid = args.get("pid")
        if pid is None:
            return _err("E_MISSING_PARAM", "pid 参数必需")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid < 1:
            return _err("E_INVALID_PARAM", f"pid 必须为正整数，got {pid!r}")
        try:
            result = backend.kill_process(pid)
            if not result.get("killed", False):
                return _err("E_PROCESS_NOT_FOUND", f"进程 {pid} 不存在或无法杀死")
            if publish_event is not None:
                publish_event("system.process_killed", {"pid": pid})
            return _ok({"pid": pid, "killed": True})
        except Exception as exc:  # noqa: BLE001
            logger.debug("system_kill_process 失败: %s", exc)
            return _err("E_BACKEND_ERROR", str(exc))

    def _start_process(args: dict[str, Any]) -> str:
        """启动进程。"""
        backend = get_backend()
        if backend is None:
            return _err("E_BACKEND_UNAVAILABLE", "进程后端未初始化")
        command = args.get("command")
        if not command or not isinstance(command, str) or not command.strip():
            return _err("E_INVALID_PARAM", "command 必须为非空字符串")
        try:
            result = backend.start_process(command.strip())
            if not result.get("started", False):
                return _err("E_START_FAILED", f"启动 {command!r} 失败: {result}")
            if publish_event is not None:
                publish_event("system.process_started", {"command": command.strip()})
            return _ok({"command": command.strip(), "started": True})
        except Exception as exc:  # noqa: BLE001
            logger.debug("system_start_process 失败: %s", exc)
            return _err("E_BACKEND_ERROR", str(exc))

    return {
        "system_list_processes": _list_processes,
        "system_kill_process": _kill_process,
        "system_start_process": _start_process,
    }


# ---------------------------------------------------------------------------
# 工具元数据（供 on_load 注册用）
# ---------------------------------------------------------------------------
TOOLS_META: list[dict[str, Any]] = [
    {
        "name": "system_list_processes",
        "description": "列出系统进程（按 CPU 占用降序），返回 pid/name/cpu/memory。",
        "emoji": "📊",
        "schema": SYSTEM_LIST_PROCESSES_SCHEMA,
    },
    {
        "name": "system_kill_process",
        "description": "杀死指定 PID 的进程（kill -9 等效）。",
        "emoji": "🛑",
        "schema": SYSTEM_KILL_PROCESS_SCHEMA,
    },
    {
        "name": "system_start_process",
        "description": "启动一个进程或应用（macOS 用 open -a，其他平台用 Popen）。",
        "emoji": "🚀",
        "schema": SYSTEM_START_PROCESS_SCHEMA,
    },
]
