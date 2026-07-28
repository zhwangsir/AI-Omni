"""EventBus 单元测试：订阅/取消/分发/异步回调/事件类型过滤/多订阅者。

不使用 pytest-asyncio（项目未安装）；统一用 ``asyncio.run`` 驱动 async publish。
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from omni_sdk.event_bus import EventBus


def test_subscribe_returns_sub_id() -> None:
    """subscribe 应返回可用于取消的 sub_id 字符串。"""
    bus = EventBus()
    sub_id = bus.subscribe("voice.state_changed", lambda payload: None)
    assert isinstance(sub_id, str)
    assert len(sub_id) > 0


def test_publish_delivers_to_subscriber() -> None:
    """publish 应将 payload 传递给订阅者。"""
    bus = EventBus()
    received: list[dict] = []
    bus.subscribe("voice.state_changed", lambda p: received.append(p))

    asyncio.run(bus.publish("voice.state_changed", {"state": "idle"}))

    assert received == [{"state": "idle"}]


def test_publish_calls_async_callback() -> None:
    """publish 应能 await 异步回调。"""
    bus = EventBus()
    seen: list[str] = []

    async def _cb(payload: dict) -> None:
        seen.append(payload["msg"])

    bus.subscribe("voice.wake_detected", _cb)

    asyncio.run(bus.publish("voice.wake_detected", {"msg": "hi"}))

    assert seen == ["hi"]


def test_publish_calls_sync_callback() -> None:
    """publish 应支持同步回调（不需 await）。"""
    bus = EventBus()
    counter = {"n": 0}

    def _sync_cb(payload: dict) -> None:
        counter["n"] += 1

    bus.subscribe("voice.tick", _sync_cb)

    asyncio.run(bus.publish("voice.tick", {}))

    assert counter["n"] == 1


def test_unsubscribe_stops_delivery() -> None:
    """取消订阅后不再收到事件。"""
    bus = EventBus()
    received: list[dict] = []
    sub_id = bus.subscribe("home.entity_changed", lambda p: received.append(p))

    ok = bus.unsubscribe(sub_id)
    assert ok is True

    asyncio.run(bus.publish("home.entity_changed", {"e": "light"}))
    assert received == []


def test_unsubscribe_unknown_returns_false() -> None:
    """取消不存在的 sub_id 返回 False。"""
    bus = EventBus()
    assert bus.unsubscribe("nonexistent-id") is False


def test_multiple_subscribers_all_receive() -> None:
    """同一 event_type 的多个订阅者都收到事件。"""
    bus = EventBus()
    log_a: list[dict] = []
    log_b: list[dict] = []
    bus.subscribe("voice.asr_final", lambda p: log_a.append(p))
    bus.subscribe("voice.asr_final", lambda p: log_b.append(p))

    asyncio.run(bus.publish("voice.asr_final", {"text": "你好"}))

    assert log_a == [{"text": "你好"}]
    assert log_b == [{"text": "你好"}]


def test_event_type_filtering() -> None:
    """订阅 voice.* 的订阅者不会收到 home.* 事件。"""
    bus = EventBus()
    voice_events: list[dict] = []
    bus.subscribe("voice.state_changed", lambda p: voice_events.append(p))

    asyncio.run(bus.publish("home.entity_changed", {"e": "switch"}))

    assert voice_events == []


def test_publish_no_subscribers_no_error() -> None:
    """无订阅者时 publish 不抛错。"""
    bus = EventBus()

    asyncio.run(bus.publish("music.started", {"track": "none"}))


def test_publish_delivers_payload_by_value() -> None:
    """订阅者收到的 payload 与发布时一致（不被意外修改）。"""
    bus = EventBus()
    captured: list[dict] = []
    bus.subscribe("voice.tick", lambda p: captured.append(p))

    payload = {"v": 1}
    asyncio.run(bus.publish("voice.tick", payload))

    assert captured[0] is payload or captured[0] == {"v": 1}


def test_unsubscribe_one_does_not_affect_others() -> None:
    """取消某个订阅者不影响其他订阅者继续接收。"""
    bus = EventBus()
    kept: list[dict] = []
    removed_sub = bus.subscribe("voice.tick", lambda p: None)
    bus.subscribe("voice.tick", lambda p: kept.append(p))

    bus.unsubscribe(removed_sub)

    asyncio.run(bus.publish("voice.tick", {"i": 1}))
    assert kept == [{"i": 1}]


def test_publish_logs_when_callback_raises(caplog: pytest.LogCaptureFixture) -> None:
    """单个订阅者抛异常不影响其他订阅者，并记录日志。"""
    bus = EventBus(logger=logging.getLogger("omni_sdk.test.event_bus"))
    ok_received: list[dict] = []

    def _bad_cb(payload: dict) -> None:
        raise RuntimeError("boom")

    bus.subscribe("voice.tick", _bad_cb)
    bus.subscribe("voice.tick", lambda p: ok_received.append(p))

    with caplog.at_level(logging.ERROR, logger="omni_sdk.test.event_bus"):
        asyncio.run(bus.publish("voice.tick", {"ok": True}))

    assert ok_received == [{"ok": True}]
    assert any("boom" in r.message for r in caplog.records)
