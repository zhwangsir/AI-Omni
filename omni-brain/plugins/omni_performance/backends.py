"""omni_performance 后端实现：性能监控抽象 + fake/真实后端。

- :class:`PerformanceBackend`：抽象基类（Protocol），定义 cpu/memory/disk 契约
- :class:`FakePerformanceBackend`：测试用 fake 后端
- :class:`PsutilPerformanceBackend`：真实后端，惰性导入 psutil，可缺省
"""

from __future__ import annotations

from typing import Any, Protocol


class PerformanceBackend(Protocol):
    """性能监控后端契约。"""

    def get_cpu_usage(self) -> dict[str, Any]:
        """返回 {cpu_percent, cpu_count}。"""
        ...

    def get_memory_usage(self) -> dict[str, Any]:
        """返回 {total, available, percent}。"""
        ...

    def get_disk_usage(self, path: str = "/") -> dict[str, Any]:
        """返回 {total, used, free, percent}。"""
        ...


class FakePerformanceBackend:
    """假性能后端，用于测试与演示。

    内置固定的 CPU/内存/磁盘数据；可记录调用参数以供断言。
    """

    def __init__(
        self,
        *,
        raise_on_cpu: bool = False,
        raise_on_memory: bool = False,
        raise_on_disk: bool = False,
    ) -> None:
        """构造 fake 后端。

        :param raise_on_cpu: get_cpu_usage 时抛 RuntimeError
        :param raise_on_memory: get_memory_usage 时抛 RuntimeError
        :param raise_on_disk: get_disk_usage 时抛 RuntimeError
        """
        self.last_disk_path: str | None = None
        self._raise_on_cpu = raise_on_cpu
        self._raise_on_memory = raise_on_memory
        self._raise_on_disk = raise_on_disk

    def get_cpu_usage(self) -> dict[str, Any]:
        """返回固定 CPU 数据。"""
        if self._raise_on_cpu:
            raise RuntimeError("fake: get_cpu_usage failed")
        return {"cpu_percent": 23.5, "cpu_count": 10}

    def get_memory_usage(self) -> dict[str, Any]:
        """返回固定内存数据。"""
        if self._raise_on_memory:
            raise RuntimeError("fake: get_memory_usage failed")
        return {
            "total": 34359738368,  # 32 GB
            "available": 17179869184,  # 16 GB
            "percent": 50.0,
        }

    def get_disk_usage(self, path: str = "/") -> dict[str, Any]:
        """返回固定磁盘数据。"""
        if self._raise_on_disk:
            raise RuntimeError("fake: get_disk_usage failed")
        self.last_disk_path = path
        return {
            "total": 500107862016,  # ~500 GB
            "used": 250053931008,  # ~250 GB
            "free": 250053931008,
            "percent": 50.0,
        }


class PsutilPerformanceBackend:
    """真实性能后端：基于 psutil（惰性导入）。

    psutil 未安装时由调用方捕获 ImportError 并返回 E_BACKEND_UNAVAILABLE。
    """

    def get_cpu_usage(self) -> dict[str, Any]:
        """用 psutil 取 CPU 使用率与核心数。"""
        import psutil  # 惰性导入

        return {
            "cpu_percent": float(psutil.cpu_percent(interval=1)),
            "cpu_count": int(psutil.cpu_count() or 0),
        }

    def get_memory_usage(self) -> dict[str, Any]:
        """用 psutil 取内存使用情况。"""
        import psutil  # 惰性导入

        mem = psutil.virtual_memory()
        return {
            "total": int(mem.total),
            "available": int(mem.available),
            "percent": float(mem.percent),
        }

    def get_disk_usage(self, path: str = "/") -> dict[str, Any]:
        """用 psutil 取磁盘使用情况。"""
        import psutil  # 惰性导入

        disk = psutil.disk_usage(path)
        return {
            "total": int(disk.total),
            "used": int(disk.used),
            "free": int(disk.free),
            "percent": float(disk.percent),
        }
