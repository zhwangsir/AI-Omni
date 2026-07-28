"""omni_sdk 异步工具测试：TaskTracker、safe_publish、async-sync 桥接。"""

from __future__ import annotations

import asyncio
import gc
import threading
import time
from typing import Any

import pytest

from omni_sdk.utils import (
    TaskTracker,
    create_tracked_task,
    safe_publish,
    sync_to_async_publish,
)


class TestTaskTracker:
    """TaskTracker：防止 asyncio Task 被 GC 意外取消。"""

    @pytest.mark.asyncio
    async def test_task_retained_until_done(self) -> None:
        """Task 完成前必须被 tracker 持有，不会被 GC 回收。"""
        tracker = TaskTracker()
        completed = []

        async def worker() -> None:
            await asyncio.sleep(0.05)
            completed.append(True)

        task = create_tracked_task(tracker, worker())
        assert len(tracker) == 1
        assert not task.done()

        # 强制 GC，Task 不应被取消
        gc.collect()
        await asyncio.sleep(0.1)

        assert task.done()
        assert completed == [True]
        assert len(tracker) == 0

    @pytest.mark.asyncio
    async def test_multiple_tasks(self) -> None:
        """多个 Task 并行，全部完成后自动清理。"""
        tracker = TaskTracker()
        counter = 0

        async def inc() -> None:
            nonlocal counter
            await asyncio.sleep(0.01)
            counter += 1

        tasks = [create_tracked_task(tracker, inc()) for _ in range(10)]
        assert len(tracker) == 10

        await asyncio.gather(*tasks)
        assert counter == 10
        assert len(tracker) == 0

    @pytest.mark.asyncio
    async def test_task_exception_does_not_break_tracker(self) -> None:
        """Task 抛异常不应影响 tracker，异常被记录但不传播。"""
        tracker = TaskTracker()
        errors: list[BaseException] = []
        tracker.on_task_exception = lambda t, e: errors.append(e)

        async def fail() -> None:
            raise ValueError("test error")

        task = create_tracked_task(tracker, fail())
        await asyncio.sleep(0.05)

        assert task.done()
        assert isinstance(task.exception(), ValueError)
        assert len(errors) == 1
        assert len(tracker) == 0

    @pytest.mark.asyncio
    async def test_cancel_task(self) -> None:
        """取消 Task 后 tracker 正确清理。"""
        tracker = TaskTracker()
        started = asyncio.Event()

        async def hang() -> None:
            started.set()
            await asyncio.sleep(10)

        task = create_tracked_task(tracker, hang())
        await started.wait()
        assert len(tracker) == 1

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(tracker) == 0


class TestSafePublish:
    """safe_publish：锁外执行回调，避免死锁。"""

    @pytest.mark.asyncio
    async def test_callback_called_outside_lock(self) -> None:
        """回调在锁释放后执行，不会持锁调用外部代码。"""
        lock = asyncio.Lock()
        call_order: list[str] = []
        data_snapshot: dict[str, Any] | None = None

        async def publish(event_type: str, payload: dict[str, Any]) -> None:
            nonlocal data_snapshot
            data_snapshot = payload
            call_order.append("callback")
            # 回调中尝试获取锁 - 如果持锁调用会死锁
            async with lock:
                call_order.append("callback_got_lock")

        async with lock:
            call_order.append("locked")
            data = {"value": 42, "timestamp": time.time()}
            # safe_publish 应立即克隆数据并调度回调在锁外执行
            safe_publish(publish, "test.event", data)
            call_order.append("still_locked")
            # 修改原始数据 - 回调不应看到修改（说明用了快照）
            data["value"] = 999

        await asyncio.sleep(0.05)
        assert call_order == ["locked", "still_locked", "callback", "callback_got_lock"]
        assert data_snapshot is not None
        assert data_snapshot["value"] == 42

    @pytest.mark.asyncio
    async def test_callback_exception_isolated(self) -> None:
        """回调异常不应影响调用方。"""
        lock = asyncio.Lock()

        async def bad_publish(event_type: str, payload: dict[str, Any]) -> None:
            raise RuntimeError("publish failed")

        async with lock:
            # 不应抛出
            safe_publish(bad_publish, "test.event", {"x": 1})

        await asyncio.sleep(0.05)


class TestSyncToAsyncPublish:
    """sync_to_async_publish：同步上下文安全发布 async 事件。"""

    def test_from_running_loop(self) -> None:
        """在运行中的事件循环线程调用，用 create_task 调度。"""
        tracker = TaskTracker()
        results: list[tuple[str, dict[str, Any]]] = []

        async def async_publish(event_type: str, payload: dict[str, Any]) -> None:
            results.append((event_type, payload))

        async def main() -> None:
            sync_to_async_publish(async_publish, "test.event", {"k": "v"}, tracker=tracker)
            await asyncio.sleep(0.05)

        asyncio.run(main())
        assert results == [("test.event", {"k": "v"})]

    def test_from_external_thread(self) -> None:
        """从非事件循环线程调用，用 call_soon_threadsafe + run_coroutine_threadsafe。"""
        tracker = TaskTracker()
        results: list[tuple[str, dict[str, Any]]] = []
        done = threading.Event()

        async def async_publish(event_type: str, payload: dict[str, Any]) -> None:
            results.append((event_type, payload))

        def external_thread(loop: asyncio.AbstractEventLoop) -> None:
            sync_to_async_publish(async_publish, "thread.event", {"from": "thread"}, tracker=tracker, loop=loop)
            done.set()

        async def main() -> None:
            loop = asyncio.get_running_loop()
            t = threading.Thread(target=external_thread, args=(loop,))
            t.start()
            await asyncio.sleep(0.1)
            t.join(timeout=1)
            assert done.is_set()

        asyncio.run(main())
        assert len(results) == 1
        assert results[0][0] == "thread.event"
        assert results[0][1]["from"] == "thread"
