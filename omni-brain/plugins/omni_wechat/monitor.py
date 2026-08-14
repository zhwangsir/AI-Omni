"""omni_wechat 长轮询监听循环。

后台 asyncio Task 循环调用 ``ILinkClient.get_updates``，将收到的消息
通过回调推送到事件总线。支持优雅停止（``stop()`` 发 notifystop 并 cancel task）。

典型用法::

    monitor = MonitorLoop(client, store, account="5c5c75d92a90-im-bot")
    monitor.set_message_handler(lambda msg: print(msg))
    await monitor.start()
    ...
    await monitor.stop()
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from omni_wechat.accounts import AccountStore
from omni_wechat.ilink import ILinkClient

logger = logging.getLogger(__name__)

#: 连续失败阈值，超过则退避 30s
MAX_CONSECUTIVE_FAILURES = 5
#: 失败退避时长（秒）
FAILURE_BACKOFF_S = 30.0
#: 未达阈值时的短退避（秒），避免失败热循环
ERROR_RETRY_BACKOFF_S = 1.0
#: 默认服务端长轮询超时（秒）
DEFAULT_LONG_POLL_S = 35.0


#: 消息回调签名：接收单条 WeixinMessage dict，无返回值（可为 async）
MessageHandler = Callable[[dict[str, Any]], Any]


class MonitorLoop:
    """长轮询监听循环。

    生命周期：
    - ``start()``：发 notifystart → 启动后台 task 循环 get_updates
    - ``stop()``：cancel task → 发 notifystop
    """

    def __init__(
        self,
        client: ILinkClient,
        store: AccountStore,
        account: str,
        *,
        on_message: MessageHandler | None = None,
    ) -> None:
        """构造监听循环。

        :param client: iLink 客户端
        :param store: 凭据存储（用于持久化 sync_buf）
        :param account: 账户 ID
        :param on_message: 消息回调（同步或 async）
        """
        self._client = client
        self._store = store
        self._account = account
        self._on_message = on_message

        self._task: asyncio.Task[None] | None = None
        # asyncio.Event 延迟到 start() 中创建（避免 __init__ 时绑定到错误的 event loop）
        self._stop_event: asyncio.Event | None = None
        self._running = False
        # 服务端建议的下一次长轮询超时（毫秒），由 getupdates 响应更新
        self._next_timeout_s: float = DEFAULT_LONG_POLL_S
        # 已处理消息 client_id 集合（用于去重）
        self._seen_client_ids: set[str] = set()

    @property
    def is_running(self) -> bool:
        """监听是否运行中。"""
        return self._running and self._task is not None and not self._task.done()

    def set_message_handler(self, handler: MessageHandler) -> None:
        """设置消息回调（可在 start 前/中调用）。"""
        self._on_message = handler

    async def start(self) -> None:
        """启动监听循环。已在运行时调用为空操作。"""
        if self.is_running:
            return
        self._stop_event = asyncio.Event()
        # 通知服务端上线（失败不阻塞监听）
        try:
            await self._client.notify_start()
        except Exception:
            logger.debug("notify_start 失败（继续监听）", exc_info=True)
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name=f"wechat-monitor-{self._account}")

    async def stop(self) -> None:
        """停止监听循环（幂等）。"""
        if not self._running and self._task is None:
            return
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        # 通知服务端下线（失败忽略）
        try:
            await self._client.notify_stop()
        except Exception:
            logger.debug("notify_stop 失败", exc_info=True)

    async def _run_loop(self) -> None:
        """后台循环主体。"""
        consecutive_failures = 0
        # 从持久化加载 sync_buf（首次为空字符串）
        get_updates_buf = self._store.load_sync_buf(self._account)

        while self._running and self._stop_event is not None and not self._stop_event.is_set():
            try:
                result = await self._client.get_updates(
                    get_updates_buf,
                    timeout_s=self._next_timeout_s,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("get_updates 异常")
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.warning(
                        "连续 %d 次失败，退避 %.0fs",
                        consecutive_failures,
                        FAILURE_BACKOFF_S,
                    )
                    await self._sleep_or_stop(FAILURE_BACKOFF_S)
                    consecutive_failures = 0
                else:
                    # 短退避避免异常热循环（客户端同步失败时循环不 yield）
                    await self._sleep_or_stop(ERROR_RETRY_BACKOFF_S)
                continue

            if not result.get("ok"):
                consecutive_failures += 1
                err = result.get("error", {})
                logger.warning(
                    "get_updates 失败 (%d/%d): %s",
                    consecutive_failures,
                    MAX_CONSECUTIVE_FAILURES,
                    err.get("message", "unknown"),
                )
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    await self._sleep_or_stop(FAILURE_BACKOFF_S)
                    consecutive_failures = 0
                else:
                    # 短暂退避避免热循环
                    await self._sleep_or_stop(ERROR_RETRY_BACKOFF_S)
                continue

            # 成功：重置失败计数
            consecutive_failures = 0

            # 更新 sync_buf（服务端返回新 buf 时持久化）
            new_buf = result.get("get_updates_buf")
            if new_buf and new_buf != get_updates_buf:
                get_updates_buf = new_buf
                try:
                    self._store.save_sync_buf(self._account, new_buf)
                except Exception:
                    logger.debug("保存 sync_buf 失败", exc_info=True)

            # 更新服务端建议的下一次超时
            lp_ms = result.get("longpolling_timeout_ms")
            if isinstance(lp_ms, (int, float)) and lp_ms > 0:
                self._next_timeout_s = lp_ms / 1000.0

            # 分发消息
            msgs = result.get("msgs", []) or []
            for msg in msgs:
                if not isinstance(msg, dict):
                    continue
                await self._dispatch(msg)

            # 保证每轮循环至少让出一次 event loop：
            # 防止异常后端同步即时返回空结果时循环热空转、stop() 无法被调度
            await asyncio.sleep(0)

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        """分发单条消息：去重 + 调用回调。"""
        client_id = msg.get("client_id")
        if client_id and client_id in self._seen_client_ids:
            return
        if client_id:
            self._seen_client_ids.add(client_id)
            # 限制去重集合大小
            if len(self._seen_client_ids) > 1000:
                self._seen_client_ids = set(list(self._seen_client_ids)[-500:])

        handler = self._on_message
        if handler is None:
            return
        try:
            result = handler(msg)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.exception("消息回调异常")

    async def _sleep_or_stop(self, seconds: float) -> None:
        """睡眠指定秒数；期间收到 stop 信号立即返回。"""
        if self._stop_event is None:
            await asyncio.sleep(seconds)
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
