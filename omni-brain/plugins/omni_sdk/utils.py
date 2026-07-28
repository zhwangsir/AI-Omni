"""omni_sdk 异步工具：TaskTracker、safe_publish、sync-async 桥接。

解决的问题：
1. asyncio Task 引用丢失导致 GC 意外取消
2. 持锁时调用回调/事件发布导致死锁
3. 同步上下文（非 async 线程）安全发布 async 事件
"""

from __future__ import annotations

import asyncio
import copy
import functools
import logging
import threading
from typing import Any, Awaitable, Callable, Coroutine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TaskTracker：防止 asyncio Task 被 GC 意外取消
# ---------------------------------------------------------------------------
class TaskTracker:
    """持有 asyncio Task 强引用，直到 Task 完成/取消/异常后自动移除。

    Python asyncio 文档警告："If a Task is destroyed while it's still pending,
    you will get a warning because the Task was never awaited and may not have
    completed." 不显式持有引用时，GC 可能在 Task 运行中回收它，导致任务
    无声取消——这是生产环境偶发"事件丢失""回调不触发"的常见根因。

    用法::

        tracker = TaskTracker()
        task = create_tracked_task(tracker, coro)
        # task 完成后自动从 tracker 移除，无需手动清理
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()
        self._lock = threading.Lock()
        self.on_task_exception: Callable[[asyncio.Task[Any], BaseException], None] | None = None

    def __len__(self) -> int:
        with self._lock:
            return len(self._tasks)

    def add(self, task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        """注册一个 Task，添加 done 回调自动移除。"""
        with self._lock:
            self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        """Task 完成回调：从集合移除，记录异常。"""
        with self._lock:
            self._tasks.discard(task)
        # 异常处理：不抛出，只记录或回调
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                if self.on_task_exception is not None:
                    try:
                        self.on_task_exception(task, exc)
                    except Exception:  # noqa: BLE001
                        logger.debug("TaskTracker on_task_exception 回调自身异常", exc_info=True)
                else:
                    logger.debug("Tracked task raised exception: %s", exc, exc_info=(type(exc), exc, exc.__traceback__))

    def cancel_all(self) -> None:
        """取消所有跟踪中的 Task。"""
        with self._lock:
            tasks = list(self._tasks)
        for t in tasks:
            t.cancel()


def create_tracked_task(
    tracker: TaskTracker,
    coro: Coroutine[Any, Any, Any],
    *,
    name: str | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> asyncio.Task[Any]:
    """创建 Task 并注册到 tracker，防止 GC 回收。

    :param tracker: TaskTracker 实例
    :param coro: 要调度的协程
    :param name: 可选 Task 名（调试用）
    :param loop: 可选事件循环，默认当前运行循环
    :return: 创建的 Task
    """
    target_loop = loop or asyncio.get_running_loop()
    if target_loop.is_running():
        task = target_loop.create_task(coro, name=name)
    else:
        task = asyncio.ensure_future(coro, loop=target_loop)
    tracker.add(task)
    return task


# ---------------------------------------------------------------------------
# safe_publish：锁外执行回调，避免死锁
# ---------------------------------------------------------------------------
def safe_publish(
    publish_fn: Callable[..., Awaitable[None]],
    event_type: str,
    payload: dict[str, Any],
    *,
    tracker: TaskTracker | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """安全发布事件：先深拷贝 payload，调度回调在锁外执行。

    **关键设计**：调用方通常持有关联数据的锁（如 ws_sync._lock、pipeline._state_lock），
    若在锁内直接调用 publish → 回调中再尝试获取同一把锁（或回调触发的链路间接地
    获取锁）会死锁。``safe_publish`` 做两件事：
    1. 立即深拷贝 payload（快照），调用方继续持锁修改原数据不影响回调
    2. 通过 create_task 调度 publish 协程在下一个事件循环周期执行——
       此时调用方已退出 with 锁块，回调在无锁环境执行。

    :param publish_fn: async 发布函数 ``(event_type, payload) -> None``
    :param event_type: 事件类型
    :param payload: 事件负载（会被深拷贝）
    :param tracker: 可选 TaskTracker，防止 Task 被 GC
    :param loop: 可选事件循环
    """
    # 立即深拷贝快照，调用方后续修改原 dict 不影响回调
    snapshot = copy.deepcopy(payload)

    async def _do_publish() -> None:
        try:
            await publish_fn(event_type, snapshot)
        except Exception:  # noqa: BLE001
            logger.debug("safe_publish 事件发布失败: %s", event_type, exc_info=True)

    target_loop = loop
    if target_loop is None:
        try:
            target_loop = asyncio.get_running_loop()
        except RuntimeError:
            # 无运行循环，直接同步执行（调用方不在锁内的场景）
            asyncio.run(_do_publish())
            return

    if target_loop.is_running():
        task = target_loop.create_task(_do_publish())
        if tracker is not None:
            tracker.add(task)
    else:
        target_loop.run_until_complete(_do_publish())


# ---------------------------------------------------------------------------
# sync_to_async_publish：同步上下文安全桥接到 async 事件总线
# ---------------------------------------------------------------------------
def sync_to_async_publish(
    publish_fn: Callable[..., Awaitable[None]],
    event_type: str,
    payload: dict[str, Any],
    *,
    tracker: TaskTracker | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """从同步上下文（可能在非事件循环线程）安全发布 async 事件。

    - 若当前线程有运行中的事件循环：create_task 调度（配合 tracker）
    - 若在其他线程且提供了 loop：call_soon_threadsafe → run_coroutine_threadsafe
    - 若无运行循环也无 loop：asyncio.run 同步执行

    :param publish_fn: async 发布函数
    :param event_type: 事件类型
    :param payload: 事件负载（会被深拷贝）
    :param tracker: TaskTracker 实例
    :param loop: 目标事件循环（跨线程发布必需）
    """
    snapshot = copy.deepcopy(payload)

    async def _do_publish() -> None:
        try:
            await publish_fn(event_type, snapshot)
        except Exception:  # noqa: BLE001
            logger.debug("sync_to_async_publish 失败: %s", event_type, exc_info=True)

    # 场景1：当前线程有运行中的事件循环
    try:
        running_loop = asyncio.get_running_loop()
        if running_loop.is_running():
            task = running_loop.create_task(_do_publish())
            if tracker is not None:
                tracker.add(task)
            return
    except RuntimeError:
        pass

    # 场景2：提供了外部 loop（跨线程发布）
    target_loop = loop
    if target_loop is not None and target_loop.is_running():
        future = asyncio.run_coroutine_threadsafe(_do_publish(), target_loop)
        # 不等待 future 结果（非阻塞）；异常在 _do_publish 内部捕获
        return

    # 场景3：无运行循环，同步执行
    asyncio.run(_do_publish())
