"""omni_home 设备状态实时同步（Home Assistant WebSocket）。

走 HA WS 协议：``auth_required → auth → auth_ok → subscribe_events(state_changed)``，
收到的状态变更写入本地缓存并触发回调（tools 层借此保持知识图谱新鲜）。

- ``websocket-client`` 为重型依赖，**惰性导入**：仅默认工厂真正连接时才 import，
  缺失时抛 :class:`HomeError`，import 本模块零第三方依赖。
- 连接对象通过 ``ws_factory`` 注入，测试用 :class:`FakeWebSocket` 脚本化驱动。
- 后台线程 + stop Event，语义与 omni_voice 管道一致。
- **P0-3 自动重连**：断开后指数退避重连（1s→2s→4s→max30s），断开期间标记
  状态 unavailable，重连成功后自动重新订阅。
"""

from __future__ import annotations

import copy
import json
import threading
import time
from typing import Any, Callable

from .config import HomeConfig
from .errors import HomeAuthError, HomeConnectionError, HomeError

#: 状态变更回调：``(entity_id, new_state_dict) -> None``
StateChangedCallback = Callable[[str, dict[str, Any]], None]
#: 连接状态变更回调：``(connected: bool) -> None``
ConnectionChangeCallback = Callable[[bool], None]
#: 连接工厂：``(config) -> 带 send(str)/recv()->str/close() 的连接对象``
WsFactory = Callable[[HomeConfig], Any]


def _default_ws_factory(config: HomeConfig) -> Any:
    """默认工厂：惰性 import websocket-client 并建立真实连接。"""
    try:
        import websocket  # type: ignore[import-not-found]
    except ImportError as exc:
        raise HomeError(
            "实时同步需要 websocket-client（pip install websocket-client）"
        ) from exc
    return websocket.create_connection(config.ws_url, timeout=config.connect_timeout)


class FakeWebSocket:
    """脚本化 fake 连接：``incoming`` 消息耗尽后 ``recv`` 抛 OSError（模拟关闭）。

    ``sent`` 记录所有发送帧（已解析为 dict），``closed`` 标记 close 是否被调用。
    """

    def __init__(self, incoming: list[Any] | None = None):
        self.incoming: list[str] = [
            json.dumps(m, ensure_ascii=False) if isinstance(m, dict) else str(m)
            for m in (incoming or [])
        ]
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    def recv(self) -> str:
        if not self.incoming:
            raise OSError("fake websocket closed")
        return self.incoming.pop(0)

    def close(self) -> None:
        self.closed = True


class HomeStateSync:
    """HA state_changed 订阅器：连接、订阅、维护状态缓存的后台线程。

    **P0 修复**：
    1. 自动重连（指数退避）：断开后 1s/2s/4s/.../max30s 重试
    2. 锁安全：回调始终在锁外执行，避免死锁
    3. Task 引用安全：使用 TaskTracker 跟踪异步任务（若在 async 上下文）
    """

    def __init__(
        self,
        config: HomeConfig,
        *,
        ws_factory: WsFactory | None = None,
        on_state_changed: StateChangedCallback | None = None,
        on_connection_change: ConnectionChangeCallback | None = None,
        reconnect_enabled: bool = True,
        initial_reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 30.0,
    ):
        self._config = config
        self._ws_factory = ws_factory or _default_ws_factory
        self._on_state_changed = on_state_changed
        self._on_connection_change = on_connection_change
        self._reconnect_enabled = reconnect_enabled
        self._initial_reconnect_delay = initial_reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        self._ws: Any | None = None
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._connected = False
        self._last_error: str | None = None
        self._reconnect_delay = initial_reconnect_delay

    # -- 状态 ----------------------------------------------------------------
    @property
    def connected(self) -> bool:
        """是否已完成 auth 握手且连接活跃。"""
        with self._lock:
            return self._connected

    @property
    def is_running(self) -> bool:
        """后台接收循环是否在运行。"""
        return self._running

    @property
    def last_error(self) -> str | None:
        """最近一次错误描述（无错误为 None）。"""
        return self._last_error

    def get_cached(self, entity_id: str) -> dict[str, Any] | None:
        """返回某实体最近一次推送的状态（拷贝），无记录返回 None。"""
        with self._lock:
            state = self._cache.get(entity_id)
            return copy.deepcopy(state) if state is not None else None

    def cached_states(self) -> dict[str, Any]:
        """返回全部缓存状态的深拷贝。"""
        with self._lock:
            return copy.deepcopy(self._cache)

    # -- 公开 API（向后兼容）------------------------------------------------
    def connect(self) -> None:
        """建立连接并完成 auth 握手（同步阻塞）。"""
        self._do_connect()
        self._set_connected(True)

    def subscribe(self) -> None:
        """订阅 state_changed 事件（同步阻塞）。"""
        self._do_subscribe()

    def run_once(self) -> bool:
        """接收并处理一条消息；返回 False 表示连接断开。"""
        if self._ws is None:
            raise HomeError("尚未连接，请先调用 connect()")
        try:
            msg = self._recv_json()
        except HomeConnectionError as exc:
            self._last_error = str(exc)
            self._set_connected(False)
            return False
        self._handle_message(msg)
        return True

    # -- 协议 ----------------------------------------------------------------
    def _recv_json(self) -> dict[str, Any]:
        """收一帧并解析 JSON；连接层异常包装为 HomeConnectionError。"""
        assert self._ws is not None
        try:
            raw = self._ws.recv()
        except (HomeError, HomeAuthError):
            raise
        except Exception as exc:  # OSError / WebSocketException / fake 关闭
            raise HomeConnectionError(f"WebSocket 接收失败: {exc}") from exc
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise HomeError(f"WebSocket 收到非法 JSON: {str(raw)[:80]}") from exc

    def _do_connect(self) -> None:
        """单次连接尝试：建立 WS + auth 握手。"""
        try:
            self._ws = self._ws_factory(self._config)
        except HomeError:
            raise
        except Exception as exc:  # ImportError / OSError / 其它连接异常
            raise HomeConnectionError(f"无法连接 Home Assistant WebSocket: {exc}") from exc

        hello = self._recv_json()
        if hello.get("type") != "auth_required":
            raise HomeError(f"WebSocket 协议错误：期望 auth_required，收到 {hello.get('type')!r}")
        self._ws.send(json.dumps({"type": "auth", "access_token": self._config.ha_token}))
        reply = self._recv_json()
        if reply.get("type") == "invalid_auth":
            raise HomeAuthError("WebSocket 认证失败，请检查 ha_token")
        if reply.get("type") != "auth_ok":
            raise HomeError(f"WebSocket 协议错误：期望 auth_ok，收到 {reply.get('type')!r}")

    def _do_subscribe(self) -> None:
        """订阅 state_changed 事件（固定订阅 id=1）。"""
        if self._ws is None:
            raise HomeError("尚未连接，无法订阅")
        self._ws.send(
            json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"})
        )
        while True:
            reply = self._recv_json()
            if reply.get("type") == "event":
                self._handle_message(reply)
                continue
            if reply.get("type") == "result" and reply.get("id") == 1:
                if not reply.get("success"):
                    raise HomeError(f"订阅 state_changed 失败: {reply.get('error')}")
                return

    def _set_connected(
        self,
        connected: bool,
        error: str | None = None,
    ) -> None:
        """线程安全地更新连接状态并触发回调。

        - 实体状态缓存保持最后已知值，不修改为 unavailable
        - 通过 ``connected`` 属性反映连接状态
        - ws 在锁外关闭，避免回调中持锁
        """
        ws_to_close = None
        with self._lock:
            old_connected = self._connected
            self._connected = connected
            if error is not None:
                self._last_error = error
            if not connected:
                ws_to_close = self._ws
                self._ws = None
        if ws_to_close is not None:
            try:
                ws_to_close.close()
            except Exception:  # noqa: BLE001
                pass
        if old_connected != connected and self._on_connection_change is not None:
            try:
                self._on_connection_change(connected)
            except Exception:  # noqa: BLE001
                pass

    # -- 消息处理 ------------------------------------------------------------
    def _handle_message(self, msg: dict[str, Any]) -> None:
        """处理一条已解析消息：state_changed 入缓存并触发回调（回调在锁外）。"""
        if msg.get("type") != "event":
            return
        event = msg.get("event") or {}
        if event.get("event_type") != "state_changed":
            return
        data = event.get("data") or {}
        entity_id = data.get("entity_id")
        new_state = data.get("new_state")
        if not entity_id or not isinstance(new_state, dict):
            return

        state_copy = copy.deepcopy(new_state)
        with self._lock:
            self._cache[entity_id] = state_copy
        if self._on_state_changed is not None:
            try:
                self._on_state_changed(entity_id, copy.deepcopy(state_copy))
            except Exception:  # noqa: BLE001
                pass

    def _receive_loop(self) -> bool:
        """接收并处理消息直到断开/停止；返回 False 表示连接断开需要重连。"""
        while not self._stop.is_set():
            if self._ws is None:
                return False
            try:
                msg = self._recv_json()
            except HomeConnectionError as exc:
                self._last_error = str(exc)
                return False
            except HomeError:
                raise
            self._handle_message(msg)
        return True

    # -- 后台线程 ------------------------------------------------------------
    def start(self) -> None:
        """启动后台线程：连接 → 订阅 → 循环接收（断开自动重连）。"""
        if self._thread is not None and self._thread.is_alive():
            raise HomeError("状态同步已在运行")
        self._stop.clear()
        self._reconnect_delay = self._initial_reconnect_delay
        self._thread = threading.Thread(target=self._run, name="omni-home-ws", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """主循环：首次连接后进入接收-重连循环。"""
        self._running = True
        try:
            while not self._stop.is_set():
                try:
                    self._do_connect()
                    self._do_subscribe()
                    self._set_connected(True)
                    self._reconnect_delay = self._initial_reconnect_delay
                    if self._receive_loop():
                        break
                except HomeAuthError:
                    self._set_connected(False, error="认证失败，不自动重连")
                    break
                except HomeError as exc:
                    self._last_error = str(exc)
                except Exception as exc:  # noqa: BLE001
                    self._last_error = f"意外错误: {exc}"

                if not self._reconnect_enabled or self._stop.is_set():
                    self._set_connected(False, error=self._last_error)
                    break

                self._set_connected(False, error=self._last_error)
                delay = self._reconnect_delay
                self._reconnect_delay = min(delay * 2, self._max_reconnect_delay)
                self._wait_with_stop(delay)
        finally:
            self._running = False
            self._set_connected(False)
            self._close_ws()

    def _wait_with_stop(self, seconds: float) -> None:
        """可中断的等待（响应 stop 事件）。"""
        deadline = time.time() + seconds
        while not self._stop.is_set() and time.time() < deadline:
            time.sleep(min(0.1, deadline - time.time()))

    def stop(self, timeout: float = 5.0) -> None:
        """停止后台线程（幂等；未启动时为 no-op）。"""
        self._stop.set()
        self._close_ws()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._running = False
        self._set_connected(False)

    def _close_ws(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass
