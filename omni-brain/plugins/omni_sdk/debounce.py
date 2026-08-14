"""防抖/节流工具集。

提供防抖写入（DebouncedWriter）用于减少短时间内多次磁盘IO。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


class DebouncedWriter:
    """防抖写入器：短时间内多次写入合并为一次实际IO。

    - delay_ms: 防抖窗口（毫秒），窗口内多次写入只保留最后一次
    - flush() 可强制立即刷入
    - 线程安全
    """

    def __init__(self, delay_ms: int = 50, writer_func: Callable[[dict[str, Any]], None] | None = None):
        self._delay = delay_ms / 1000.0
        self._writer_func = writer_func
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._pending_data: dict[str, Any] | None = None
        self._last_write_time: float = 0.0
        self._write_count: int = 0
        self._flush_count: int = 0

    @property
    def delay(self) -> float:
        """当前防抖延迟（秒）。"""
        return self._delay

    @property
    def pending(self) -> bool:
        """是否有待写入数据。"""
        with self._lock:
            return self._pending_data is not None

    def write(self, data: dict[str, Any]) -> None:
        """调度一次写入（防抖）。"""
        with self._lock:
            self._pending_data = dict(data)
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay, self._do_flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> None:
        """强制立即写入所有待处理数据。"""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        # _do_flush 内部会自行取锁弹数据，必须在锁外调用：
        # self._lock 为不可重入锁，锁内调用会二次获取导致死锁（M32.25 修复）
        self._do_flush()

    def _do_flush(self) -> None:
        """实际执行写入（内部方法，锁外调用）。"""
        data_to_write: dict[str, Any] | None = None
        with self._lock:
            if self._pending_data is not None:
                data_to_write = self._pending_data
                self._pending_data = None
                self._timer = None
        write_ok = False
        # writer_func 保持在锁外调用：避免用户回调里再调 write/flush 造成死锁
        if data_to_write is not None and self._writer_func is not None:
            try:
                self._writer_func(data_to_write)
                write_ok = True
            except Exception:
                logger.debug("DebouncedWriter 写入失败", exc_info=True)
        # 计数更新收回锁内，与 stats() 的锁内读取保持一致（M32.25 修复统计竞态）
        with self._lock:
            if write_ok:
                self._write_count += 1
                self._last_write_time = time.time()
            self._flush_count += 1

    def stats(self) -> dict[str, Any]:
        """返回统计信息（用于测试和诊断）。"""
        with self._lock:
            return {
                "write_count": self._write_count,
                "flush_count": self._flush_count,
                "pending": self._pending_data is not None,
                "last_write_time": self._last_write_time,
            }
