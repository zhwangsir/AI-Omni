"""事件总线：插件间解耦的事件分发机制。

每个事件由 ``event_type`` (点分小写，如 ``voice.state_changed``) 与 ``payload`` (dict) 组成；
订阅者经 :meth:`EventBus.subscribe` 注册回调，返回 ``sub_id`` 用于取消订阅。
publish 为 async，自动 await 异步回调；同步回调直接调用。
单个订阅者抛异常不影响其他订阅者，异常被记录到 logger。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from typing import Callable, Dict, List, Tuple

Payload = Dict[str, object]
Callback = Callable[[Payload], object]


class EventBus:
    """进程内事件总线：subscribe/unsubscribe/publish。

    订阅按 ``event_type`` 精确匹配（M15 不支持通配符）；
    publish 时遍历该 event_type 下所有订阅者，依次调用回调。
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        """构造事件总线。

        :param logger: 可选 logger；默认使用 ``omni.sdk.event_bus`` 命名空间。
        """
        self._logger = logger or logging.getLogger("omni.sdk.event_bus")
        # sub_id -> (event_type, callback)
        self._subs: Dict[str, Tuple[str, Callback]] = {}
        # event_type -> [sub_id, ...]
        self._by_type: Dict[str, List[str]] = defaultdict(list)

    def subscribe(self, event_type: str, callback: Callback) -> str:
        """订阅事件；返回 sub_id（用于 :meth:`unsubscribe`）。

        :param event_type: 点分小写事件类型，如 ``voice.state_changed``
        :param callback: 同步或异步回调，签名 ``callback(payload: dict) -> None``
        :return: sub_id 字符串
        """
        sub_id = uuid.uuid4().hex
        self._subs[sub_id] = (event_type, callback)
        self._by_type[event_type].append(sub_id)
        return sub_id

    def unsubscribe(self, sub_id: str) -> bool:
        """取消订阅。

        :param sub_id: :meth:`subscribe` 返回的 sub_id
        :return: 取消成功返回 True；sub_id 不存在返回 False
        """
        entry = self._subs.pop(sub_id, None)
        if entry is None:
            return False
        event_type = entry[0]
        subs = self._by_type.get(event_type, [])
        if sub_id in subs:
            subs.remove(sub_id)
        if not subs:
            self._by_type.pop(event_type, None)
        return True

    async def publish(self, event_type: str, payload: Payload) -> None:
        """发布事件；遍历该 event_type 下所有订阅者并调用回调。

        :param event_type: 点分小写事件类型
        :param payload: 可 JSON 序列化的 dict
        """
        # 复制一份避免迭代过程中订阅者变化
        sub_ids = list(self._by_type.get(event_type, []))
        for sub_id in sub_ids:
            entry = self._subs.get(sub_id)
            if entry is None:
                continue
            callback = entry[1]
            try:
                result = callback(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # noqa: BLE001
                self._logger.error(
                    "事件 %s 订阅者 %s 抛异常: %s", event_type, sub_id, exc, exc_info=True
                )
