"""DebouncedWriter 单元测试（M32.25）。

覆盖：
- flush() 死锁回归：修复前 flush() 在持有不可重入锁时调用 _do_flush()，
  _do_flush() 二次获取同一把锁导致永久 hang；回归测试用 daemon 线程 +
  join 超时判定，保证测试进程本身不会被挂死
- write() 防抖合并：窗口内多次写入只保留最后一次
- timer 自动触发与 flush() 立即写入语义（flush 后 timer 不重复写）
- 空 flush 幂等、writer_func 异常容错（吞异常、flush_count 仍 +1）
- stats() / delay / pending 字段正确性
"""

from __future__ import annotations

import threading
import time
from typing import Any

from omni_sdk.debounce import DebouncedWriter


def _flush_or_timeout(writer: DebouncedWriter, timeout: float = 2.0) -> None:
    """在 daemon 线程中调用 flush()，并要求其在 timeout 秒内返回。

    M32.25 修复前 flush() 存在死锁：直接在本线程调用会永久挂死测试进程，
    因此统一经本helper 间接调用——死锁时抛 AssertionError（测试失败）
    而不是阻塞 pytest。
    """
    t = threading.Thread(target=writer.flush, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        raise AssertionError("flush() 未在 2 秒内返回（疑似死锁）")


# ---------------------------------------------------------------------------
# flush() 死锁回归（M32.25 P0）
# ---------------------------------------------------------------------------
class TestFlushDeadlock:
    """flush() 在锁内调用 _do_flush() 导致的死锁回归。"""

    def test_flush_returns_promptly_with_pending_data(self) -> None:
        """有 pending 数据时 flush() 必须快速返回并完成写入（修复前 hang）。"""
        written: list[dict[str, Any]] = []
        # delay 拉长，保证 timer 不会在测试期间自动触发，隔离变量
        writer = DebouncedWriter(delay_ms=5000, writer_func=written.append)
        writer.write({"k": 1})

        _flush_or_timeout(writer)

        assert written == [{"k": 1}]
        assert writer.pending is False

    def test_flush_returns_promptly_without_pending_data(self) -> None:
        """无 pending 数据时 flush() 同样不得死锁（修复前空 flush 也 hang）。"""
        writer = DebouncedWriter(delay_ms=5000, writer_func=lambda data: None)
        _flush_or_timeout(writer)


# ---------------------------------------------------------------------------
# write() 防抖合并
# ---------------------------------------------------------------------------
class TestDebounceMerge:
    """防抖窗口内多次 write 合并为一次实际写入。"""

    def test_rapid_writes_merge_into_single_flush(self) -> None:
        """窗口内连续 write 3 次，writer_func 只被调用 1 次且数据为最后一次。"""
        called = threading.Event()
        written: list[dict[str, Any]] = []

        def _writer(data: dict[str, Any]) -> None:
            written.append(data)
            called.set()

        writer = DebouncedWriter(delay_ms=30, writer_func=_writer)
        writer.write({"n": 1})
        writer.write({"n": 2})
        writer.write({"n": 3})

        assert called.wait(timeout=1.0), "timer 未在预期时间内触发"
        time.sleep(0.1)  # 远超过 delay，确认没有第二次写入
        assert written == [{"n": 3}]

    def test_timer_auto_flush_clears_pending(self) -> None:
        """write 一次后等待 > delay，writer 被自动调用且 pending 变 False。"""
        called = threading.Event()
        written: list[dict[str, Any]] = []

        def _writer(data: dict[str, Any]) -> None:
            written.append(data)
            called.set()

        writer = DebouncedWriter(delay_ms=30, writer_func=_writer)
        writer.write({"a": 1})
        assert writer.pending is True

        assert called.wait(timeout=1.0), "timer 未在预期时间内触发"
        assert written == [{"a": 1}]
        # _do_flush 先弹出数据再调 writer_func，called 置位时 pending 已清空
        assert writer.pending is False


# ---------------------------------------------------------------------------
# flush() 立即写入
# ---------------------------------------------------------------------------
class TestFlushImmediate:
    """flush() 不等 delay 立即写入，且取消已调度的 timer。"""

    def test_flush_writes_immediately_without_waiting_delay(self) -> None:
        """write 后立即 flush：writer 被调用 1 次；再等 > delay 不重复写。"""
        written: list[dict[str, Any]] = []
        writer = DebouncedWriter(delay_ms=30, writer_func=written.append)
        writer.write({"x": 1})
        _flush_or_timeout(writer)

        # flush 返回时写入已完成（同步语义）
        assert written == [{"x": 1}]
        assert writer.pending is False

        time.sleep(0.1)  # 超过 delay：timer 已取消，不得重复写
        assert written == [{"x": 1}]

    def test_flush_cancels_timer_so_no_duplicate_write(self) -> None:
        """flush 后 stats 中 write_count 保持 1（timer 不二次触发）。"""
        written: list[dict[str, Any]] = []
        writer = DebouncedWriter(delay_ms=30, writer_func=written.append)
        writer.write({"x": 1})
        _flush_or_timeout(writer)
        time.sleep(0.1)
        assert writer.stats()["write_count"] == 1


# ---------------------------------------------------------------------------
# 空 flush 幂等 / 默认 writer_func
# ---------------------------------------------------------------------------
class TestEmptyFlush:
    """空 flush 与默认 writer_func 的容错。"""

    def test_flush_without_write_is_noop(self) -> None:
        """未 write 直接 flush：writer 不被调用、不抛错；连续两次安全。"""
        written: list[dict[str, Any]] = []
        writer = DebouncedWriter(delay_ms=30, writer_func=written.append)
        _flush_or_timeout(writer)
        _flush_or_timeout(writer)
        assert written == []

    def test_default_writer_func_none_is_safe(self) -> None:
        """默认 writer_func=None 时 write/flush 均不抛错。"""
        writer = DebouncedWriter(delay_ms=5000)
        writer.write({"k": 1})
        _flush_or_timeout(writer)
        assert writer.pending is False


# ---------------------------------------------------------------------------
# writer_func 异常容错
# ---------------------------------------------------------------------------
class TestWriterException:
    """writer_func 抛异常时 _do_flush 吞掉异常但仍计 flush。"""

    def test_writer_exception_is_swallowed(self) -> None:
        """异常不传播；flush_count 仍 +1，write_count 不增，last_write_time 不更新。"""

        def _boom(data: dict[str, Any]) -> None:
            raise RuntimeError("磁盘写入失败")

        writer = DebouncedWriter(delay_ms=5000, writer_func=_boom)
        writer.write({"k": 1})
        _flush_or_timeout(writer)  # 不抛错

        stats = writer.stats()
        assert stats["write_count"] == 0
        assert stats["flush_count"] == 1
        assert stats["pending"] is False
        assert stats["last_write_time"] == 0.0


# ---------------------------------------------------------------------------
# stats() / delay / pending
# ---------------------------------------------------------------------------
class TestStats:
    """统计字段与属性正确性。"""

    def test_initial_stats(self) -> None:
        """初始状态：计数为 0、无 pending、last_write_time 为 0。"""
        writer = DebouncedWriter()
        assert writer.stats() == {
            "write_count": 0,
            "flush_count": 0,
            "pending": False,
            "last_write_time": 0.0,
        }

    def test_stats_reflect_successful_write(self) -> None:
        """成功写入后 write_count / flush_count / last_write_time 正确更新。"""
        written: list[dict[str, Any]] = []
        writer = DebouncedWriter(delay_ms=5000, writer_func=written.append)
        before = time.time()
        writer.write({"k": 1})
        assert writer.pending is True
        _flush_or_timeout(writer)

        stats = writer.stats()
        assert stats["write_count"] == 1
        assert stats["flush_count"] == 1
        assert stats["pending"] is False
        assert before <= stats["last_write_time"] <= time.time()

    def test_delay_property_returns_seconds(self) -> None:
        """delay 属性返回秒（delay_ms / 1000）。"""
        assert DebouncedWriter(delay_ms=250).delay == 0.25
        assert DebouncedWriter().delay == 0.05
