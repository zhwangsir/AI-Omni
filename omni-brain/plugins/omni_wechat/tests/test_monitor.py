"""omni_wechat MonitorLoop 长轮询监听测试。

使用 fake ILinkClient + tmp_path AccountStore，不访问真实网络。
验证：start/stop 生命周期、消息分发、去重、错误退避、sync_buf 持久化。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from omni_wechat.accounts import AccountStore
from omni_wechat.ilink import ILinkClient
from omni_wechat import monitor as monitor_module
from omni_wechat.monitor import (
    DEFAULT_LONG_POLL_S,
    FAILURE_BACKOFF_S,
    MAX_CONSECUTIVE_FAILURES,
    MonitorLoop,
)


# ---------------------------------------------------------------------------
# Fake ILinkClient
# ---------------------------------------------------------------------------
class FakeILinkClient:
    """预置 get_updates 响应序列的 fake 客户端。"""

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.responses = list(responses or [])
        self.get_updates_calls: list[tuple[str, float | None]] = []
        self.notify_start_called = False
        self.notify_stop_called = False
        self._call_idx = 0

    async def get_updates(
        self,
        get_updates_buf: str = "",
        *,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        self.get_updates_calls.append((get_updates_buf, timeout_s))
        # 微小延迟让出 event loop，避免测试中空转
        await asyncio.sleep(0.01)
        if self._call_idx < len(self.responses):
            resp = self.responses[self._call_idx]
            self._call_idx += 1
            return resp
        # 默认返回空消息
        return {"ok": True, "msgs": [], "get_updates_buf": get_updates_buf}

    async def notify_start(self) -> dict[str, Any]:
        self.notify_start_called = True
        return {"ok": True}

    async def notify_stop(self) -> dict[str, Any]:
        self.notify_stop_called = True
        return {"ok": True}

    async def close(self) -> None:
        pass


@pytest.fixture()
def store(tmp_path: Path) -> AccountStore:
    return AccountStore(tmp_path)


@pytest.fixture()
def account() -> str:
    return "test-account-001"


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------
class TestLifecycle:
    @pytest.mark.asyncio()
    async def test_start_calls_notify_start(self, store: AccountStore, account: str) -> None:
        client = FakeILinkClient()
        monitor = MonitorLoop(client, store, account)  # type: ignore[arg-type]
        await monitor.start()
        assert client.notify_start_called
        await monitor.stop()

    @pytest.mark.asyncio()
    async def test_stop_calls_notify_stop(self, store: AccountStore, account: str) -> None:
        client = FakeILinkClient()
        monitor = MonitorLoop(client, store, account)  # type: ignore[arg-type]
        await monitor.start()
        await monitor.stop()
        assert client.notify_stop_called

    @pytest.mark.asyncio()
    async def test_is_running(self, store: AccountStore, account: str) -> None:
        client = FakeILinkClient()
        monitor = MonitorLoop(client, store, account)  # type: ignore[arg-type]
        assert not monitor.is_running
        await monitor.start()
        assert monitor.is_running
        await monitor.stop()
        assert not monitor.is_running

    @pytest.mark.asyncio()
    async def test_start_idempotent(self, store: AccountStore, account: str) -> None:
        client = FakeILinkClient()
        monitor = MonitorLoop(client, store, account)  # type: ignore[arg-type]
        await monitor.start()
        await monitor.start()  # 第二次应空操作
        assert monitor.is_running
        await monitor.stop()

    @pytest.mark.asyncio()
    async def test_stop_idempotent(self, store: AccountStore, account: str) -> None:
        client = FakeILinkClient()
        monitor = MonitorLoop(client, store, account)  # type: ignore[arg-type]
        await monitor.stop()  # 未启动时 stop 应空操作
        await monitor.start()
        await monitor.stop()
        await monitor.stop()  # 第二次 stop 应幂等

    @pytest.mark.asyncio()
    async def test_notify_start_failure_does_not_block(self, store: AccountStore, account: str) -> None:
        """notify_start 失败不阻塞监听启动。"""
        client = FakeILinkClient()
        client.notify_start = AsyncMock(side_effect=Exception("network error"))  # type: ignore[assignment]
        monitor = MonitorLoop(client, store, account)  # type: ignore[arg-type]
        await monitor.start()
        assert monitor.is_running
        await monitor.stop()

    @pytest.mark.asyncio()
    async def test_notify_stop_failure_ignored(self, store: AccountStore, account: str) -> None:
        client = FakeILinkClient()
        client.notify_stop = AsyncMock(side_effect=Exception("network error"))  # type: ignore[assignment]
        monitor = MonitorLoop(client, store, account)  # type: ignore[arg-type]
        await monitor.start()
        await monitor.stop()  # 不抛异常


# ---------------------------------------------------------------------------
# 消息分发
# ---------------------------------------------------------------------------
class TestMessageDispatch:
    @pytest.mark.asyncio()
    async def test_messages_dispatched_to_handler(self, store: AccountStore, account: str) -> None:
        received: list[dict[str, Any]] = []
        msgs = [
            {"from_user_id": "u1", "client_id": "c1", "item_list": [{"type": 1, "text_item": {"text": "hi"}}]},
            {"from_user_id": "u2", "client_id": "c2", "item_list": [{"type": 1, "text_item": {"text": "yo"}}]},
        ]
        client = FakeILinkClient([
            {"ok": True, "msgs": msgs, "get_updates_buf": "buf-1"},
        ])
        monitor = MonitorLoop(client, store, account, on_message=lambda m: received.append(m))  # type: ignore[arg-type]
        await monitor.start()
        # 给 loop 执行时间
        await asyncio.sleep(0.3)
        await monitor.stop()
        assert len(received) == 2
        assert received[0]["from_user_id"] == "u1"
        assert received[1]["from_user_id"] == "u2"

    @pytest.mark.asyncio()
    async def test_async_handler_supported(self, store: AccountStore, account: str) -> None:
        received: list[dict[str, Any]] = []

        async def handler(msg: dict[str, Any]) -> None:
            received.append(msg)

        msgs = [{"from_user_id": "u1", "client_id": "c1"}]
        client = FakeILinkClient([
            {"ok": True, "msgs": msgs, "get_updates_buf": "buf-1"},
        ])
        monitor = MonitorLoop(client, store, account, on_message=handler)  # type: ignore[arg-type]
        await monitor.start()
        await asyncio.sleep(0.3)
        await monitor.stop()
        assert len(received) == 1

    @pytest.mark.asyncio()
    async def test_no_handler_no_crash(self, store: AccountStore, account: str) -> None:
        """无消息回调时不崩溃。"""
        msgs = [{"from_user_id": "u1", "client_id": "c1"}]
        client = FakeILinkClient([
            {"ok": True, "msgs": msgs, "get_updates_buf": "buf-1"},
        ])
        monitor = MonitorLoop(client, store, account)  # type: ignore[arg-type]
        await monitor.start()
        await asyncio.sleep(0.3)
        await monitor.stop()

    @pytest.mark.asyncio()
    async def test_handler_exception_caught(self, store: AccountStore, account: str) -> None:
        """消息回调抛异常不影响后续消息。"""
        call_count = 0

        def bad_handler(msg: dict[str, Any]) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("handler error")

        msgs = [
            {"from_user_id": "u1", "client_id": "c1"},
            {"from_user_id": "u2", "client_id": "c2"},
        ]
        client = FakeILinkClient([
            {"ok": True, "msgs": msgs, "get_updates_buf": "buf-1"},
        ])
        monitor = MonitorLoop(client, store, account, on_message=bad_handler)  # type: ignore[arg-type]
        await monitor.start()
        await asyncio.sleep(0.3)
        await monitor.stop()
        assert call_count == 2

    @pytest.mark.asyncio()
    async def test_set_message_handler_after_creation(self, store: AccountStore, account: str) -> None:
        received: list[dict[str, Any]] = []
        msgs = [{"from_user_id": "u1", "client_id": "c1"}]
        client = FakeILinkClient([
            {"ok": True, "msgs": msgs, "get_updates_buf": "buf-1"},
        ])
        monitor = MonitorLoop(client, store, account)  # type: ignore[arg-type]
        monitor.set_message_handler(lambda m: received.append(m))
        await monitor.start()
        await asyncio.sleep(0.3)
        await monitor.stop()
        assert len(received) == 1


# ---------------------------------------------------------------------------
# 消息去重
# ---------------------------------------------------------------------------
class TestDeduplication:
    @pytest.mark.asyncio()
    async def test_duplicate_client_id_deduped(self, store: AccountStore, account: str) -> None:
        received: list[dict[str, Any]] = []
        # 同一条消息出现两次（不同轮询轮次）
        msg = {"from_user_id": "u1", "client_id": "same-id"}
        client = FakeILinkClient([
            {"ok": True, "msgs": [msg], "get_updates_buf": "buf-1"},
            {"ok": True, "msgs": [msg], "get_updates_buf": "buf-2"},
            {"ok": True, "msgs": [], "get_updates_buf": "buf-3"},
        ])
        monitor = MonitorLoop(client, store, account, on_message=lambda m: received.append(m))  # type: ignore[arg-type]
        await monitor.start()
        await asyncio.sleep(0.5)
        await monitor.stop()
        assert len(received) == 1

    @pytest.mark.asyncio()
    async def test_dedup_set_size_limited(self, store: AccountStore, account: str) -> None:
        """去重集合大小有限，不无限增长。"""
        monitor = MonitorLoop(FakeILinkClient(), store, account)  # type: ignore[arg-type]
        # 模拟超过 1000 条
        for i in range(1200):
            await monitor._dispatch({"client_id": f"id-{i}"})
        # 触发裁剪 (>1000 → 保留后500)，再加上后续添加的 ~200
        assert len(monitor._seen_client_ids) <= 700


# ---------------------------------------------------------------------------
# sync_buf 持久化
# ---------------------------------------------------------------------------
class TestSyncBufPersistence:
    @pytest.mark.asyncio()
    async def test_sync_buf_saved(self, store: AccountStore, account: str) -> None:
        client = FakeILinkClient([
            {"ok": True, "msgs": [], "get_updates_buf": "buf-saved-001"},
        ])
        monitor = MonitorLoop(client, store, account)  # type: ignore[arg-type]
        await monitor.start()
        await asyncio.sleep(0.3)
        await monitor.stop()
        assert store.load_sync_buf(account) == "buf-saved-001"

    @pytest.mark.asyncio()
    async def test_sync_buf_loaded_on_start(self, store: AccountStore, account: str) -> None:
        store.save_sync_buf(account, "existing-buf")
        client = FakeILinkClient([
            {"ok": True, "msgs": [], "get_updates_buf": "new-buf"},
        ])
        monitor = MonitorLoop(client, store, account)  # type: ignore[arg-type]
        await monitor.start()
        await asyncio.sleep(0.3)
        await monitor.stop()
        # 第一次 get_updates 调用应使用已保存的 buf
        assert client.get_updates_calls[0][0] == "existing-buf"


# ---------------------------------------------------------------------------
# 错误处理与退避
# ---------------------------------------------------------------------------
class TestErrorHandling:
    @pytest.mark.asyncio()
    async def test_error_response_increments_failure(
        self, store: AccountStore, account: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """连续错误响应触发退避。"""
        # 缩短退避时间以便测试（错误路径短退避 1s → 0.02s）
        monkeypatch.setattr(monitor_module, "ERROR_RETRY_BACKOFF_S", 0.02)
        client = FakeILinkClient([
            {"ok": False, "error": {"code": "E_TEST", "message": "server error"}},
        ] * MAX_CONSECUTIVE_FAILURES + [
            {"ok": True, "msgs": [], "get_updates_buf": "buf-ok"},
        ])
        monitor = MonitorLoop(client, store, account)  # type: ignore[arg-type]
        monitor._next_timeout_s = 0.05
        await monitor.start()
        await asyncio.sleep(0.5)
        await monitor.stop()
        # 应经历了多次重试
        assert len(client.get_updates_calls) >= MAX_CONSECUTIVE_FAILURES

    @pytest.mark.asyncio()
    async def test_exception_in_get_updates_caught(
        self, store: AccountStore, account: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_updates 抛异常被捕获并重试。"""
        monkeypatch.setattr(monitor_module, "ERROR_RETRY_BACKOFF_S", 0.02)
        call_count = 0

        class ThrowingClient(FakeILinkClient):
            async def get_updates(self, *a: Any, **kw: Any) -> dict[str, Any]:
                nonlocal call_count
                call_count += 1
                # 让出 event loop，模拟真实客户端的异步行为
                await asyncio.sleep(0.01)
                if call_count <= 2:
                    raise ConnectionError("network down")
                return {"ok": True, "msgs": [], "get_updates_buf": "buf"}

        client = ThrowingClient()
        monitor = MonitorLoop(client, store, account)  # type: ignore[arg-type]
        monitor._next_timeout_s = 0.05
        await monitor.start()
        await asyncio.sleep(0.5)
        await monitor.stop()
        assert call_count >= 3


# ---------------------------------------------------------------------------
# 超时适配
# ---------------------------------------------------------------------------
class TestTimeoutAdaptation:
    @pytest.mark.asyncio()
    async def test_longpolling_timeout_updates_next_timeout(self, store: AccountStore, account: str) -> None:
        client = FakeILinkClient([
            {"ok": True, "msgs": [], "get_updates_buf": "b", "longpolling_timeout_ms": 50000},
        ])
        monitor = MonitorLoop(client, store, account)  # type: ignore[arg-type]
        await monitor.start()
        await asyncio.sleep(0.3)
        await monitor.stop()
        assert monitor._next_timeout_s == 50.0

    @pytest.mark.asyncio()
    async def test_default_timeout(self, store: AccountStore, account: str) -> None:
        monitor = MonitorLoop(FakeILinkClient(), store, account)  # type: ignore[arg-type]
        assert monitor._next_timeout_s == DEFAULT_LONG_POLL_S
