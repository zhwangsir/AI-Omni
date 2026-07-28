"""omni_home WebSocket 状态同步测试。

HomeStateSync 走 HA WebSocket 协议（auth → subscribe_events → state_changed），
全部用脚本化 :class:`FakeWebSocket` 驱动，不发起真实网络连接；
后台线程用 ``threading`` + stop Event，测试可确定性等待/停止。
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from omni_home.config import HomeConfig
from omni_home.errors import HomeAuthError, HomeConnectionError, HomeError
from omni_home.ws_sync import FakeWebSocket, HomeStateSync


def _config() -> HomeConfig:
    return HomeConfig(ha_url="http://ha.local:8123", ha_token="tok123")


def _auth_handshake() -> list[dict]:
    return [{"type": "auth_required", "ha_version": "2026.7"}, {"type": "auth_ok"}]


def _subscribe_result(success: bool = True) -> dict:
    return {"id": 1, "type": "result", "success": success}


def _state_event(entity_id: str, state: str, **attrs) -> dict:
    return {
        "id": 1,
        "type": "event",
        "event": {
            "event_type": "state_changed",
            "data": {
                "entity_id": entity_id,
                "old_state": {"entity_id": entity_id, "state": "off", "attributes": {}},
                "new_state": {"entity_id": entity_id, "state": state, "attributes": attrs},
            },
        },
    }


def _sync(ws: FakeWebSocket, **kwargs) -> HomeStateSync:
    kwargs.setdefault("reconnect_enabled", False)
    return HomeStateSync(_config(), ws_factory=lambda config: ws, **kwargs)


# ---------------------------------------------------------------------------
# 连接与认证
# ---------------------------------------------------------------------------
class TestConnect:
    def test_auth_flow(self):
        ws = FakeWebSocket(_auth_handshake())
        sync = _sync(ws)
        sync.connect()
        assert sync.connected is True
        assert ws.sent == [{"type": "auth", "access_token": "tok123"}]

    def test_invalid_auth_raises(self):
        ws = FakeWebSocket([
            {"type": "auth_required", "ha_version": "2026.7"},
            {"type": "invalid_auth", "message": "bad token"},
        ])
        with pytest.raises(HomeAuthError):
            _sync(ws).connect()

    def test_protocol_error_on_unexpected_first_message(self):
        ws = FakeWebSocket([{"type": "pong"}])
        with pytest.raises(HomeError, match="协议"):
            _sync(ws).connect()

    def test_factory_import_error_wrapped(self):
        def factory(config):
            raise ImportError("No module named 'websocket'")

        with pytest.raises(HomeError):
            HomeStateSync(_config(), ws_factory=factory).connect()

    def test_factory_connection_failure(self):
        def factory(config):
            raise OSError("connection refused")

        with pytest.raises(HomeConnectionError):
            HomeStateSync(_config(), ws_factory=factory).connect()

    def test_default_factory_lazy_import(self):
        # 默认工厂惰性 import websocket；本机未装时应抛 HomeError 而非 ImportError
        sync = HomeStateSync(_config())
        try:
            sync.connect()
        except HomeError:
            pass  # 未装依赖或连不上都属预期
        except ImportError:  # pragma: no cover - 不应泄漏原始 ImportError
            pytest.fail("默认工厂把 ImportError 泄漏给了调用方")


# ---------------------------------------------------------------------------
# 订阅
# ---------------------------------------------------------------------------
class TestSubscribe:
    def test_subscribe_sends_correct_message(self):
        ws = FakeWebSocket(_auth_handshake() + [_subscribe_result()])
        sync = _sync(ws)
        sync.connect()
        sync.subscribe()
        assert ws.sent[1] == {"id": 1, "type": "subscribe_events", "event_type": "state_changed"}

    def test_subscribe_failure_raises(self):
        ws = FakeWebSocket(_auth_handshake() + [_subscribe_result(success=False)])
        sync = _sync(ws)
        sync.connect()
        with pytest.raises(HomeError):
            sync.subscribe()


# ---------------------------------------------------------------------------
# 事件处理与缓存
# ---------------------------------------------------------------------------
class TestEventsAndCache:
    def _connected_sync(self, ws: FakeWebSocket, **kwargs) -> HomeStateSync:
        sync = _sync(ws, **kwargs)
        sync.connect()
        sync.subscribe()
        return sync

    def test_state_event_updates_cache_and_fires_callback(self):
        ws = FakeWebSocket(
            _auth_handshake() + [_subscribe_result(), _state_event("light.a", "on", brightness=200)]
        )
        calls: list[tuple[str, dict]] = []
        sync = self._connected_sync(ws, on_state_changed=lambda eid, st: calls.append((eid, st)))
        assert sync.run_once() is True
        assert calls == [("light.a", {"entity_id": "light.a", "state": "on", "attributes": {"brightness": 200}})]
        assert sync.get_cached("light.a")["state"] == "on"

    def test_non_state_event_ignored(self):
        ws = FakeWebSocket(
            _auth_handshake() + [_subscribe_result(), {"id": 1, "type": "event", "event": {"event_type": "call_service", "data": {}}}]
        )
        sync = self._connected_sync(ws)
        assert sync.run_once() is True
        assert sync.cached_states() == {}

    def test_event_missing_new_state_skipped(self):
        event = {"id": 1, "type": "event", "event": {"event_type": "state_changed", "data": {"entity_id": "light.a"}}}
        ws = FakeWebSocket(_auth_handshake() + [_subscribe_result(), event])
        sync = self._connected_sync(ws)
        assert sync.run_once() is True
        assert sync.get_cached("light.a") is None

    def test_malformed_json_raises(self):
        ws = FakeWebSocket(_auth_handshake() + [_subscribe_result(), "not-json{"])
        sync = self._connected_sync(ws)
        with pytest.raises(HomeError, match="JSON"):
            sync.run_once()

    def test_connection_loss_returns_false_and_records_error(self):
        ws = FakeWebSocket(_auth_handshake() + [_subscribe_result()])
        sync = self._connected_sync(ws)
        assert sync.run_once() is False  # 脚本耗尽 → fake 抛关闭异常
        assert sync.last_error is not None

    def test_cached_states_returns_copy(self):
        ws = FakeWebSocket(
            _auth_handshake() + [_subscribe_result(), _state_event("light.a", "on")]
        )
        sync = self._connected_sync(ws)
        sync.run_once()
        snapshot = sync.cached_states()
        snapshot["light.a"]["state"] = "tampered"
        assert sync.get_cached("light.a")["state"] == "on"

    def test_run_once_without_connect_raises(self):
        with pytest.raises(HomeError):
            _sync(FakeWebSocket()).run_once()


# ---------------------------------------------------------------------------
# 后台线程
# ---------------------------------------------------------------------------
class TestBackgroundThread:
    def test_start_consumes_events_then_stop(self):
        ws = FakeWebSocket(
            _auth_handshake()
            + [_subscribe_result(), _state_event("light.living_room_main", "on")]
        )
        sync = _sync(ws)
        sync.start()
        deadline = time.time() + 2.0
        while time.time() < deadline and sync.get_cached("light.living_room_main") is None:
            time.sleep(0.01)
        assert sync.get_cached("light.living_room_main")["state"] == "on"
        sync.stop()
        assert sync.is_running is False
        assert ws.closed is True

    def test_double_start_raises(self):
        blocker = threading.Event()

        class BlockingWs(FakeWebSocket):
            def recv(self):  # 脚本消息耗尽后阻塞，模拟长连接
                if self.incoming:
                    return super().recv()
                blocker.wait(2.0)
                raise OSError("closed")

        ws = BlockingWs(_auth_handshake() + [_subscribe_result()])
        sync = _sync(ws)
        sync.start()
        deadline = time.time() + 2.0
        while time.time() < deadline and not sync.is_running:
            time.sleep(0.01)
        try:
            with pytest.raises(HomeError):
                sync.start()
        finally:
            blocker.set()
            sync.stop()
        assert sync.is_running is False

    def test_stop_without_start_is_noop(self):
        _sync(FakeWebSocket()).stop()  # 不应抛错


# ---------------------------------------------------------------------------
# 自动重连（P0-3）
# ---------------------------------------------------------------------------
class TestAutoReconnect:
    def test_reconnect_with_exponential_backoff(self):
        """断开后自动重连，指数退避；实体状态保持最后已知值，connected 属性反映连接状态。"""
        connection_attempts = []
        disconnect_events = []
        connect_events = []

        class ReconnectableWsFactory:
            def __init__(self):
                self.attempt = 0
                self.instances = []

            def __call__(self, config):
                self.attempt += 1
                connection_attempts.append(self.attempt)
                if self.attempt == 1:
                    ws = FakeWebSocket(
                        _auth_handshake() + [_subscribe_result(), _state_event("light.test", "on")]
                    )
                    self.instances.append(ws)
                    return ws
                elif self.attempt == 2:
                    ws = FakeWebSocket(
                        _auth_handshake() + [_subscribe_result(), _state_event("light.test", "off")]
                    )
                    self.instances.append(ws)
                    return ws
                else:
                    return FakeWebSocket(_auth_handshake() + [_subscribe_result()])

        factory = ReconnectableWsFactory()
        state_changes = []

        def on_state(entity_id, state):
            state_changes.append((entity_id, state.get("state")))

        def on_connection_change(connected):
            if connected:
                connect_events.append(time.time())
            else:
                disconnect_events.append(time.time())

        sync = HomeStateSync(
            _config(),
            ws_factory=factory,
            on_state_changed=on_state,
            on_connection_change=on_connection_change,
            reconnect_enabled=True,
            initial_reconnect_delay=0.01,
            max_reconnect_delay=0.05,
        )

        sync.start()
        deadline = time.time() + 3.0
        while time.time() < deadline and len(connection_attempts) < 2:
            time.sleep(0.01)
        while time.time() < deadline:
            cached = sync.get_cached("light.test")
            if cached is not None and cached.get("state") == "off":
                break
            time.sleep(0.01)

        assert len(connection_attempts) >= 2
        assert connection_attempts[0] == 1
        assert connection_attempts[1] == 2
        assert len(disconnect_events) >= 1
        assert len(connect_events) >= 2

        states = [s for _, s in state_changes]
        assert "on" in states
        assert "off" in states

        final_state = sync.get_cached("light.test")
        assert final_state is not None
        assert final_state["state"] == "off"

        sync.stop()
        assert sync.is_running is False

    def test_callback_called_outside_lock_no_deadlock(self):
        """回调在锁外执行，持锁回调不会死锁。"""
        lock_acquired_inside_callback = False
        done = threading.Event()

        def bad_callback(entity_id, state):
            nonlocal lock_acquired_inside_callback
            sync._lock.acquire()
            lock_acquired_inside_callback = True
            sync._lock.release()
            done.set()

        ws = FakeWebSocket(
            _auth_handshake() + [_subscribe_result(), _state_event("light.a", "on")]
        )
        sync = _sync(ws, on_state_changed=bad_callback)
        sync.connect()
        sync.subscribe()
        sync.run_once()

        assert done.wait(timeout=1.0) is True
        assert lock_acquired_inside_callback is True
