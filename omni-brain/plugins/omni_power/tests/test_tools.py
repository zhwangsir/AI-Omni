"""omni_power tools 层测试：4 个 system_* 工具。

全部通过 FakePowerBackend 驱动，不执行真实系统命令；
每个测试用 ``_reset_runtime()`` 隔离进程内运行时单例。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from omni_power import tools
from omni_power.backends import FakePowerBackend


def _parse(result: str) -> dict:
    """工具返回的是 JSON 字符串，解析为 dict。"""
    assert isinstance(result, str)
    return json.loads(result)


@pytest.fixture(autouse=True)
def fresh_runtime():
    """每个测试前重置运行时单例。"""
    rt = tools._reset_runtime()
    yield rt


# ---------------------------------------------------------------------------
# system_lock_screen
# ---------------------------------------------------------------------------
class TestSystemLockScreen:
    def test_lock_screen_fake_ok(self):
        """fake 模式下锁屏返回成功。"""
        data = _parse(tools.system_lock_screen(fake=True))
        assert data["ok"] is True
        assert data["data"]["action"] == "lock_screen"
        assert data["data"]["command"] == "pmset displaysleepnow"

    def test_lock_screen_publishes_event(self):
        """锁屏后发布 system.power_action 事件。"""
        events: list[tuple[str, dict[str, Any]]] = []

        class _Bus:
            def publish(self, event_type, payload):
                events.append((event_type, payload))

        rt = tools._runtime
        rt.event_publisher = _Bus()
        tools.system_lock_screen(fake=True)
        assert len(events) == 1
        assert events[0][0] == "system.power_action"
        assert events[0][1]["action"] == "lock_screen"


# ---------------------------------------------------------------------------
# system_sleep
# ---------------------------------------------------------------------------
class TestSystemSleep:
    def test_sleep_fake_ok(self):
        """fake 模式下睡眠返回成功。"""
        data = _parse(tools.system_sleep(fake=True))
        assert data["ok"] is True
        assert data["data"]["action"] == "sleep"
        assert data["data"]["command"] == "pmset sleepnow"

    def test_sleep_publishes_event(self):
        """睡眠后发布 system.power_action 事件。"""
        events: list[tuple[str, dict[str, Any]]] = []

        class _Bus:
            def publish(self, event_type, payload):
                events.append((event_type, payload))

        rt = tools._runtime
        rt.event_publisher = _Bus()
        tools.system_sleep(fake=True)
        assert len(events) == 1
        assert events[0][1]["action"] == "sleep"


# ---------------------------------------------------------------------------
# system_shutdown（需确认）
# ---------------------------------------------------------------------------
class TestSystemShutdown:
    def test_shutdown_without_confirm_returns_error(self):
        """未传 confirm 时返回 E_CONFIRMATION_REQUIRED 错误。"""
        data = _parse(tools.system_shutdown(confirm=False, fake=True))
        assert data["ok"] is False
        assert "E_CONFIRMATION_REQUIRED" in data["error"]

    def test_shutdown_without_confirm_does_not_call_backend(self):
        """未确认时不调用后端（calls 列表为空）。"""
        rt = tools._runtime
        rt.backend = FakePowerBackend()
        tools.system_shutdown(confirm=False)
        assert rt.backend.calls == []

    def test_shutdown_with_confirm_fake_ok(self):
        """confirm=true 时执行关机。"""
        data = _parse(tools.system_shutdown(confirm=True, fake=True))
        assert data["ok"] is True
        assert data["data"]["action"] == "shutdown"
        assert "shut down" in data["data"]["command"]

    def test_shutdown_with_confirm_publishes_event(self):
        """确认关机后发布 system.power_action 事件。"""
        events: list[tuple[str, dict[str, Any]]] = []

        class _Bus:
            def publish(self, event_type, payload):
                events.append((event_type, payload))

        rt = tools._runtime
        rt.event_publisher = _Bus()
        tools.system_shutdown(confirm=True, fake=True)
        assert len(events) == 1
        assert events[0][1]["action"] == "shutdown"

    def test_shutdown_default_confirm_is_false(self):
        """confirm 参数默认 False，不传时返回确认错误。"""
        data = _parse(tools.system_shutdown(fake=True))
        assert data["ok"] is False
        assert "E_CONFIRMATION_REQUIRED" in data["error"]


# ---------------------------------------------------------------------------
# system_restart（需确认）
# ---------------------------------------------------------------------------
class TestSystemRestart:
    def test_restart_without_confirm_returns_error(self):
        """未传 confirm 时返回 E_CONFIRMATION_REQUIRED 错误。"""
        data = _parse(tools.system_restart(confirm=False, fake=True))
        assert data["ok"] is False
        assert "E_CONFIRMATION_REQUIRED" in data["error"]

    def test_restart_without_confirm_does_not_call_backend(self):
        """未确认时不调用后端。"""
        rt = tools._runtime
        rt.backend = FakePowerBackend()
        tools.system_restart(confirm=False)
        assert rt.backend.calls == []

    def test_restart_with_confirm_fake_ok(self):
        """confirm=true 时执行重启。"""
        data = _parse(tools.system_restart(confirm=True, fake=True))
        assert data["ok"] is True
        assert data["data"]["action"] == "restart"
        assert "restart" in data["data"]["command"]

    def test_restart_with_confirm_publishes_event(self):
        """确认重启后发布 system.power_action 事件。"""
        events: list[tuple[str, dict[str, Any]]] = []

        class _Bus:
            def publish(self, event_type, payload):
                events.append((event_type, payload))

        rt = tools._runtime
        rt.event_publisher = _Bus()
        tools.system_restart(confirm=True, fake=True)
        assert len(events) == 1
        assert events[0][1]["action"] == "restart"


# ---------------------------------------------------------------------------
# 工具注册
# ---------------------------------------------------------------------------
class TestRegister:
    def test_register_registers_four_tools(self):
        """register(ctx) 注册 4 个 system_* 工具。"""

        class _Ctx:
            def __init__(self):
                self.tools = []
                self.event_bus = None

            def register_tool(self, **kwargs):
                self.tools.append(kwargs)

        ctx = _Ctx()
        tools.register(ctx)
        names = [t["name"] for t in ctx.tools]
        assert "system_lock_screen" in names
        assert "system_sleep" in names
        assert "system_shutdown" in names
        assert "system_restart" in names
        assert len(names) == 4
        for t in ctx.tools:
            assert t["description"]
            assert t["emoji"]
            assert callable(t["handler_func"])
            assert t["schema"]["parameters"]["type"] == "object"

    def test_register_wires_event_bus(self):
        """register(ctx) 把 ctx.event_bus 接入运行时 event_publisher。"""

        class _Bus:
            def publish(self, event_type, payload):
                pass

        class _Ctx:
            def __init__(self):
                self.tools = []
                self.event_bus = _Bus()

            def register_tool(self, **kwargs):
                self.tools.append(kwargs)

        ctx = _Ctx()
        tools.register(ctx)
        assert tools._runtime.event_publisher is ctx.event_bus

    def test_make_handler_args_dict(self):
        """_make_handler 包装后的 handler 接受 args dict 返回 JSON 字符串。"""
        handler = tools._make_handler(tools.system_lock_screen)
        result = handler({"fake": True})
        data = _parse(result)
        assert data["ok"] is True
        assert data["data"]["action"] == "lock_screen"

    def test_make_handler_invalid_args_returns_error(self):
        """_make_handler 在参数错误时返回 ok:false 而非抛错。"""
        handler = tools._make_handler(tools.system_shutdown)
        # 缺少 confirm 参数时函数使用默认值 False，应返回确认错误（而非抛错）
        result = handler({"fake": True})
        data = _parse(result)
        assert data["ok"] is False


# ---------------------------------------------------------------------------
# 工具元数据 TOOLS
# ---------------------------------------------------------------------------
class TestToolsMetadata:
    def test_tools_count(self):
        """TOOLS 注册表包含 4 个工具元数据。"""
        assert len(tools.TOOLS) == 4

    def test_tools_have_required_fields(self):
        """每个工具元数据包含 name/description/emoji/schema/handler_func。"""
        for meta in tools.TOOLS:
            assert meta["name"]
            assert meta["description"]
            assert meta["emoji"]
            assert "parameters" in meta["schema"]
            assert callable(meta["handler_func"])

    def test_shutdown_schema_requires_confirm(self):
        """system_shutdown 的 schema 把 confirm 列入 required。"""
        meta = next(m for m in tools.TOOLS if m["name"] == "system_shutdown")
        assert "confirm" in meta["schema"]["parameters"]["required"]
        props = meta["schema"]["parameters"]["properties"]
        assert props["confirm"]["type"] == "boolean"

    def test_restart_schema_requires_confirm(self):
        """system_restart 的 schema 把 confirm 列入 required。"""
        meta = next(m for m in tools.TOOLS if m["name"] == "system_restart")
        assert "confirm" in meta["schema"]["parameters"]["required"]

    def test_lock_screen_schema_no_required(self):
        """system_lock_screen 不要求任何必填参数。"""
        meta = next(m for m in tools.TOOLS if m["name"] == "system_lock_screen")
        assert meta["schema"]["parameters"]["required"] == []


# ---------------------------------------------------------------------------
# async EventBus 集成（覆盖 _publish coroutine 分支）
# ---------------------------------------------------------------------------
class TestAsyncEventBusIntegration:
    def test_lock_screen_publishes_to_real_event_bus(self):
        """lock_screen 接入真实 EventBus 时事件被正确分发。"""
        import asyncio

        from omni_sdk.event_bus import EventBus

        bus = EventBus()
        received: list[dict] = []

        async def _collect(payload):
            received.append(payload)

        bus.subscribe("system.power_action", _collect)

        rt = tools._runtime
        rt.event_publisher = bus

        async def _run():
            tools.system_lock_screen(fake=True)
            await asyncio.sleep(0.01)

        asyncio.run(_run())
        assert len(received) == 1
        assert received[0]["action"] == "lock_screen"

    def test_publish_with_real_bus_no_running_loop(self):
        """无运行中事件循环时 _publish 走 asyncio.run 同步执行分支。"""
        from omni_sdk.event_bus import EventBus

        bus = EventBus()
        received: list[dict] = []

        async def _collect(payload):
            received.append(payload)

        bus.subscribe("system.power_action", _collect)

        rt = tools._runtime
        rt.event_publisher = bus
        tools.system_sleep(fake=True)
        assert len(received) == 1
        assert received[0]["action"] == "sleep"

    def test_publish_with_none_bus_is_noop(self):
        """event_publisher 为 None 时不抛错。"""
        rt = tools._runtime
        rt.event_publisher = None
        result = tools.system_lock_screen(fake=True)
        data = _parse(result)
        assert data["ok"] is True

    def test_publish_with_bus_publish_raising_is_swallowed(self):
        """bus.publish 抛异常时被吞掉，不影响工具返回。"""

        class _BadBus:
            def publish(self, event_type, payload):
                raise RuntimeError("bus broken")

        rt = tools._runtime
        rt.event_publisher = _BadBus()
        result = tools.system_lock_screen(fake=True)
        data = _parse(result)
        assert data["ok"] is True


# ---------------------------------------------------------------------------
# 后端异常路径（覆盖各 tool 的 except Exception 分支）
# ---------------------------------------------------------------------------
class TestBackendExceptionPaths:
    def test_lock_screen_backend_raises_returns_error(self):
        """后端 lock_screen 抛异常时工具返回 ok:false。"""
        rt = tools._runtime

        class _BadBackend:
            def lock_screen(self):
                raise RuntimeError("backend exploded")

        rt.backend = _BadBackend()
        result = tools.system_lock_screen()
        data = _parse(result)
        assert data["ok"] is False
        assert "backend exploded" in data["error"]

    def test_sleep_backend_raises_returns_error(self):
        """后端 sleep 抛异常时工具返回 ok:false。"""
        rt = tools._runtime

        class _BadBackend:
            def sleep(self):
                raise RuntimeError("sleep failed")

        rt.backend = _BadBackend()
        result = tools.system_sleep()
        data = _parse(result)
        assert data["ok"] is False

    def test_shutdown_backend_raises_returns_error(self):
        """后端 shutdown 抛异常时工具返回 ok:false（confirm=True 时）。"""
        rt = tools._runtime

        class _BadBackend:
            def shutdown(self):
                raise RuntimeError("shutdown failed")

        rt.backend = _BadBackend()
        result = tools.system_shutdown(confirm=True)
        data = _parse(result)
        assert data["ok"] is False

    def test_restart_backend_raises_returns_error(self):
        """后端 restart 抛异常时工具返回 ok:false（confirm=True 时）。"""
        rt = tools._runtime

        class _BadBackend:
            def restart(self):
                raise RuntimeError("restart failed")

        rt.backend = _BadBackend()
        result = tools.system_restart(confirm=True)
        data = _parse(result)
        assert data["ok"] is False

    def test_lock_screen_backend_returns_error_payload(self):
        """后端返回 ok:false 时工具透传错误消息。"""
        rt = tools._runtime

        class _ErrorBackend:
            def lock_screen(self):
                return {"ok": False, "error": {"code": "E_CUSTOM", "message": "custom fail"}}

        rt.backend = _ErrorBackend()
        result = tools.system_lock_screen()
        data = _parse(result)
        assert data["ok"] is False
        assert "custom fail" in data["error"]
