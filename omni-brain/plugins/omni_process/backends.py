"""omni_process 后端实现：进程管理抽象 + fake/真实后端。

- :class:`ProcessBackend`：抽象基类，定义 list_processes / kill_process / start_process 契约
- :class:`FakeProcessBackend`：测试用 fake 后端，不执行真实系统命令
- :class:`SubprocessProcessBackend`：真实后端，惰性导入 subprocess / psutil，可缺省

CLAUDE.md §三 要求：重型依赖惰性导入且可缺省，ImportError 降级为 E_BACKEND_UNAVAILABLE。
"""

from __future__ import annotations

from typing import Any, Protocol


class ProcessBackend(Protocol):
    """进程管理后端契约。"""

    def list_processes(self, limit: int = 20) -> list[dict[str, Any]]:
        """列出进程，返回 [{pid, name, cpu, memory}, ...]。"""
        ...

    def kill_process(self, pid: int) -> dict[str, Any]:
        """杀死进程；返回 {pid, killed: bool}，进程不存在时 killed=False。"""
        ...

    def start_process(self, command: str) -> dict[str, Any]:
        """启动进程；返回 {command, started: bool}。"""
        ...


class FakeProcessBackend:
    """假进程后端，用于测试与演示。

    内置 2 个演示进程；可记录 kill/start 调用以供断言。
    """

    def __init__(
        self,
        processes: list[dict[str, Any]] | None = None,
        *,
        raise_on_list: bool = False,
        raise_on_kill: bool = False,
        raise_on_start: bool = False,
    ) -> None:
        """构造 fake 后端。

        :param processes: 初始进程列表；None 时使用演示数据
        :param raise_on_list: list_processes 时抛 RuntimeError
        :param raise_on_kill: kill_process 时抛 RuntimeError
        :param raise_on_start: start_process 时抛 RuntimeError
        """
        if processes is None:
            self.processes: list[dict[str, Any]] = [
                {"pid": 1, "name": "init", "cpu": 0.1, "memory": 0.5},
                {"pid": 1234, "name": "python", "cpu": 5.2, "memory": 120.5},
            ]
        else:
            self.processes = list(processes)
        self.killed: list[int] = []
        self.last_limit: int | None = None
        self.last_started_command: str | None = None
        self._raise_on_list = raise_on_list
        self._raise_on_kill = raise_on_kill
        self._raise_on_start = raise_on_start

    def list_processes(self, limit: int = 20) -> list[dict[str, Any]]:
        """返回前 ``limit`` 个进程。"""
        if self._raise_on_list:
            raise RuntimeError("fake: list_processes failed")
        self.last_limit = limit
        return list(self.processes[:limit])

    def kill_process(self, pid: int) -> dict[str, Any]:
        """杀死指定 pid 的进程；不存在时 killed=False。"""
        if self._raise_on_kill:
            raise RuntimeError("fake: kill_process failed")
        for proc in self.processes:
            if proc["pid"] == pid:
                self.killed.append(pid)
                return {"pid": pid, "killed": True}
        return {"pid": pid, "killed": False}

    def start_process(self, command: str) -> dict[str, Any]:
        """记录启动命令并返回 started=True。"""
        if self._raise_on_start:
            raise RuntimeError("fake: start_process failed")
        self.last_started_command = command
        return {"command": command, "started": True}


class SubprocessProcessBackend:
    """真实进程后端：基于 psutil + subprocess（惰性导入）。

    - list_processes：psutil.process_iter 取 cpu/memory
    - kill_process：psutil.Process(pid).kill()
    - start_process：macOS 用 ``open -a``，其他平台用 subprocess.Popen
    """

    def list_processes(self, limit: int = 20) -> list[dict[str, Any]]:
        """用 psutil 列出进程，按 cpu 降序取前 limit。"""
        import psutil  # 惰性导入

        procs: list[dict[str, Any]] = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            info = proc.info
            mem = info.get("memory_info")
            procs.append(
                {
                    "pid": info.get("pid", 0),
                    "name": info.get("name", "") or "",
                    "cpu": float(info.get("cpu_percent", 0.0) or 0.0),
                    "memory": float(mem.rss / 1024 / 1024) if mem else 0.0,  # MB
                }
            )
        procs.sort(key=lambda p: p["cpu"], reverse=True)
        return procs[:limit]

    def kill_process(self, pid: int) -> dict[str, Any]:
        """用 psutil 杀死进程；不存在抛 NoSuchProcess 映射为 killed=False。"""
        import psutil  # 惰性导入

        try:
            proc = psutil.Process(pid)
            proc.kill()
            return {"pid": pid, "killed": True}
        except psutil.NoSuchProcess:
            return {"pid": pid, "killed": False}

    def start_process(self, command: str) -> dict[str, Any]:
        """启动进程；macOS 用 open -a，其他平台用 subprocess.Popen。"""
        import platform
        import subprocess  # 惰性导入

        if platform.system() == "Darwin":
            # macOS: open -a <app>
            result = subprocess.run(
                ["open", "-a", command],
                capture_output=True,
                text=True,
                check=False,
            )
            return {
                "command": command,
                "started": result.returncode == 0,
                "stderr": result.stderr.strip() if result.stderr else "",
            }
        # 其他平台：尝试 Popen
        try:
            subprocess.Popen(command, shell=False)
            return {"command": command, "started": True}
        except Exception as exc:  # noqa: BLE001
            return {"command": command, "started": False, "error": str(exc)}
