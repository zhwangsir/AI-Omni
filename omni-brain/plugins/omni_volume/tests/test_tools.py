"""omni_volume tools 层测试：4 个 system_* 工具。

全部通过 FakeVolumeBackend 驱动，不执行真实系统命令；
每个测试用 ``_reset_runtime()`` 隔离进程内运行时单例。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from omni_volume import tools
from omni_volume.backends import FakeVolumeBackend


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
# system_set_volume
# ---------------------------------------------------------------------------
class TestSystemSetVolume:
    def test_set_volume_fake_ok(self):
        """fake 模式下设置音量返回成功与新音量。"""
        data = _parse(tools.system_set_volume(level=80, fake=True))
        assert data["ok"] is True
        payload = data["data"]
        assert payload["volume"] == 80
        assert payload["muted"] is False

    def test_set_volume_zero(self):
        """设置音量为 0 返回成功（不报越界）。"""
        data = _parse(tools.system_set_volume(level=0, fake=True))
        assert data["ok"] is True
        assert data["data"]["volume"] == 0

    def test_set_volume_hundred(self):
        """设置音量为 100 返回成功。"""
        data = _parse(tools.system_set_volume(level=100, fake=True))
        assert data["ok"] is True
        assert data["data"]["volume"] == 100

    def test_set_volume_out_of_range_negative(self):
        """负数音量返回 E_OUT_OF_RANGE 错误。"""
        data = _parse(tools.system_set_volume(level=-1, fake=True))
        assert data["ok"] is False
        assert "0-100" in data["error"]

    def test_set_volume_out_of_range_too_big(self):
        """超过 100 的音量返回 E_OUT_OF_RANGE 错误。"""
        data = _parse(tools.system_set_volume(level=101, fake=True))
        assert data["ok"] is False
        assert "0-100" in data["error"]

    def test_set_volume_unmutes_when_setting(self):
        """设置音量时自动取消静音（与 macOS 行为一致）。"""
        rt = tools._runtime
        rt.backend = FakeVolumeBackend(volume=50, muted=True)
        data = _parse(tools.system_set_volume(level=70))
        assert data["ok"] is True
        assert data["data"]["muted"] is False
        assert data["data"]["volume"] == 70

    def test_set_volume_publishes_event(self):
        """设置音量后发布 system.volume_changed 事件。"""
        events: list[tuple[str, dict[str, Any]]] = []

        class _Bus:
            def publish(self, event_type, payload):
                events.append((event_type, payload))

        rt = tools._runtime
        rt.event_publisher = _Bus()
        tools.system_set_volume(level=42, fake=True)
        assert len(events) == 1
        assert events[0][0] == "system.volume_changed"
        assert events[0][1]["action"] == "set"
        assert events[0][1]["volume"] == 42
        assert events[0][1]["muted"] is False


# ---------------------------------------------------------------------------
# system_get_volume
# ---------------------------------------------------------------------------
class TestSystemGetVolume:
    def test_get_volume_fake_default(self):
        """fake 模式下默认音量为 50、未静音。"""
        data = _parse(tools.system_get_volume(fake=True))
        assert data["ok"] is True
        payload = data["data"]
        assert payload["volume"] == 50
        assert payload["muted"] is False

    def test_get_volume_reflects_set(self):
        """设置音量后查询返回新值。"""
        tools.system_set_volume(level=30, fake=True)
        data = _parse(tools.system_get_volume())
        assert data["ok"] is True
        assert data["data"]["volume"] == 30

    def test_get_volume_reflects_mute(self):
        """静音后查询返回 muted=True。"""
        tools.system_mute(fake=True)
        data = _parse(tools.system_get_volume())
        assert data["ok"] is True
        assert data["data"]["muted"] is True

    def test_get_volume_with_preset_backend(self):
        """预置 fake 后端时 get_volume 反映其初始状态。"""
        rt = tools._runtime
        rt.backend = FakeVolumeBackend(volume=25, muted=True)
        data = _parse(tools.system_get_volume())
        assert data["ok"] is True
        assert data["data"]["volume"] == 25
        assert data["data"]["muted"] is True


# ---------------------------------------------------------------------------
# system_mute
# ---------------------------------------------------------------------------
class TestSystemMute:
    def test_mute_fake_ok(self):
        """静音返回成功且 muted=True。"""
        data = _parse(tools.system_mute(fake=True))
        assert data["ok"] is True
        assert data["data"]["muted"] is True

    def test_mute_preserves_volume(self):
        """静音不改变音量值。"""
        tools.system_set_volume(level=60, fake=True)
        data = _parse(tools.system_mute())
        assert data["ok"] is True
        assert data["data"]["volume"] == 60
        assert data["data"]["muted"] is True

    def test_mute_publishes_event(self):
        """静音后发布 system.volume_changed 事件 action=mute。"""
        events: list[tuple[str, dict[str, Any]]] = []

        class _Bus:
            def publish(self, event_type, payload):
                events.append((event_type, payload))

        rt = tools._runtime
        rt.event_publisher = _Bus()
        tools.system_mute(fake=True)
        assert len(events) == 1
        assert events[0][1]["action"] == "mute"
        assert events[0][1]["muted"] is True


# ---------------------------------------------------------------------------
# system_unmute
# ---------------------------------------------------------------------------
class TestSystemUnmute:
    def test_unmute_fake_ok(self):
        """取消静音返回成功且 muted=False。"""
        tools.system_mute(fake=True)
        data = _parse(tools.system_unmute())
        assert data["ok"] is True
        assert data["data"]["muted"] is False

    def test_unmute_preserves_volume(self):
        """取消静音不改变音量值。"""
        tools.system_set_volume(level=55, fake=True)
        tools.system_mute()
        data = _parse(tools.system_unmute())
        assert data["ok"] is True
        assert data["data"]["volume"] == 55
        assert data["data"]["muted"] is False

    def test_unmute_publishes_event(self):
        """取消静音后发布 system.volume_changed 事件 action=unmute。"""
        events: list[tuple[str, dict[str, Any]]] = []

        class _Bus:
            def publish(self, event_type, payload):
                events.append((event_type, payload))

        rt = tools._runtime
        rt.event_publisher = _Bus()
        tools.system_unmute(fake=True)
        assert len(events) == 1
        assert events[0][1]["action"] == "unmute"
        assert events[0][1]["muted"] is False


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
        assert "system_set_volume" in names
        assert "system_get_volume" in names
        assert "system_mute" in names
        assert "system_unmute" in names
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
        handler = tools._make_handler(tools.system_set_volume)
        result = handler({"level": 30, "fake": True})
        data = _parse(result)
        assert data["ok"] is True
        assert data["data"]["volume"] == 30

    def test_make_handler_invalid_args_returns_error(self):
        """_make_handler 在参数错误时返回 ok:false 而非抛错。"""
        handler = tools._make_handler(tools.system_set_volume)
        result = handler({"level": "not-an-int", "fake": True})
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

    def test_set_volume_schema_has_level_int(self):
        """system_set_volume 的 schema 声明 level 为 integer 0-100。"""
        meta = next(m for m in tools.TOOLS if m["name"] == "system_set_volume")
        props = meta["schema"]["parameters"]["properties"]
        assert props["level"]["type"] == "integer"
        assert props["level"]["minimum"] == 0
        assert props["level"]["maximum"] == 100
        assert "level" in meta["schema"]["parameters"]["required"]


# ---------------------------------------------------------------------------
# async EventBus 集成（覆盖 _publish coroutine 分支）
# ---------------------------------------------------------------------------
class TestAsyncEventBusIntegration:
    def test_set_volume_publishes_to_real_event_bus(self):
        """set_volume 接入真实 EventBus（async publish）时事件被正确分发。"""
        import asyncio

        from omni_sdk.event_bus import EventBus

        bus = EventBus()
        received: list[dict] = []

        async def _collect(payload):
            received.append(payload)

        bus.subscribe("system.volume_changed", _collect)

        rt = tools._runtime
        rt.event_publisher = bus
        # 在事件循环内调用，使 _publish 走 create_task 分支
        async def _run():
            tools.system_set_volume(level=42, fake=True)
            # 让 create_task 调度的协程有机会执行
            await asyncio.sleep(0.01)

        asyncio.run(_run())
        assert len(received) == 1
        assert received[0]["volume"] == 42

    def test_publish_with_real_bus_no_running_loop(self):
        """无运行中事件循环时 _publish 走 asyncio.run 同步执行分支。"""
        from omni_sdk.event_bus import EventBus

        bus = EventBus()
        received: list[dict] = []

        async def _collect(payload):
            received.append(payload)

        bus.subscribe("system.volume_changed", _collect)

        rt = tools._runtime
        rt.event_publisher = bus
        # 同步调用（无运行中的事件循环）→ asyncio.run 分支
        tools.system_mute(fake=True)
        assert len(received) == 1
        assert received[0]["action"] == "mute"

    def test_publish_with_none_bus_is_noop(self):
        """event_publisher 为 None 时不抛错。"""
        rt = tools._runtime
        rt.event_publisher = None
        # 不应抛错
        result = tools.system_set_volume(level=50, fake=True)
        data = _parse(result)
        assert data["ok"] is True

    def test_publish_with_bus_publish_raising_is_swallowed(self):
        """bus.publish 抛异常时被吞掉，不影响工具返回。"""

        class _BadBus:
            def publish(self, event_type, payload):
                raise RuntimeError("bus broken")

        rt = tools._runtime
        rt.event_publisher = _BadBus()
        result = tools.system_set_volume(level=50, fake=True)
        data = _parse(result)
        assert data["ok"] is True  # 工具仍成功，事件异常不拖垮


# ---------------------------------------------------------------------------
# 后端异常路径（覆盖各 tool 的 except Exception 分支）
# ---------------------------------------------------------------------------
class TestBackendExceptionPaths:
    def test_set_volume_backend_raises_returns_error(self):
        """后端 set_volume 抛异常时工具返回 ok:false。"""
        rt = tools._runtime

        class _BadBackend:
            def set_volume(self, level):
                raise RuntimeError("backend exploded")

        rt.backend = _BadBackend()
        result = tools.system_set_volume(level=50)
        data = _parse(result)
        assert data["ok"] is False
        assert "backend exploded" in data["error"]

    def test_get_volume_backend_raises_returns_error(self):
        """后端 get_volume 抛异常时工具返回 ok:false。"""
        rt = tools._runtime

        class _BadBackend:
            def get_volume(self):
                raise RuntimeError("get failed")

        rt.backend = _BadBackend()
        result = tools.system_get_volume()
        data = _parse(result)
        assert data["ok"] is False

    def test_mute_backend_raises_returns_error(self):
        """后端 mute 抛异常时工具返回 ok:false。"""
        rt = tools._runtime

        class _BadBackend:
            def mute(self):
                raise RuntimeError("mute failed")

        rt.backend = _BadBackend()
        result = tools.system_mute()
        data = _parse(result)
        assert data["ok"] is False

    def test_unmute_backend_raises_returns_error(self):
        """后端 unmute 抛异常时工具返回 ok:false。"""
        rt = tools._runtime

        class _BadBackend:
            def unmute(self):
                raise RuntimeError("unmute failed")

        rt.backend = _BadBackend()
        result = tools.system_unmute()
        data = _parse(result)
        assert data["ok"] is False

    def test_set_volume_backend_returns_error_payload(self):
        """后端返回 ok:false 时工具透传错误消息。"""
        rt = tools._runtime

        class _ErrorBackend:
            def set_volume(self, level):
                return {"ok": False, "error": {"code": "E_CUSTOM", "message": "custom fail"}}

        rt.backend = _ErrorBackend()
        result = tools.system_set_volume(level=50)
        data = _parse(result)
        assert data["ok"] is False
        assert "custom fail" in data["error"]
