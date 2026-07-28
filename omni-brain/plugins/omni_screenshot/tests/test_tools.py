"""omni_screenshot tools 层测试：2 个 system_* 工具。

全部通过 FakeScreenshotBackend 驱动，不执行真实系统命令；
每个测试用 ``_reset_runtime()`` 隔离进程内运行时单例。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from omni_screenshot import tools
from omni_screenshot.backends import FakeScreenshotBackend


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
# system_screenshot_full
# ---------------------------------------------------------------------------
class TestSystemScreenshotFull:
    def test_full_fake_ok(self):
        """fake 模式下全屏截图返回成功。"""
        data = _parse(tools.system_screenshot_full(fake=True))
        assert data["ok"] is True
        assert "Pictures" in data["data"]["path"]
        assert data["data"]["mode"] == "full"

    def test_full_with_custom_path(self):
        """指定 path 时使用自定义路径。"""
        data = _parse(tools.system_screenshot_full(path="/tmp/shot.png", fake=True))
        assert data["ok"] is True
        assert data["data"]["path"] == "/tmp/shot.png"

    def test_full_publishes_event(self):
        """全屏截图后发布 system.screenshot_taken 事件。"""
        events: list[tuple[str, dict[str, Any]]] = []

        class _Bus:
            def publish(self, event_type, payload):
                events.append((event_type, payload))

        rt = tools._runtime
        rt.event_publisher = _Bus()
        tools.system_screenshot_full(fake=True)
        assert len(events) == 1
        assert events[0][0] == "system.screenshot_taken"
        assert events[0][1]["action"] == "full"
        assert "path" in events[0][1]


# ---------------------------------------------------------------------------
# system_screenshot_region
# ---------------------------------------------------------------------------
class TestSystemScreenshotRegion:
    def test_region_with_coords_fake_ok(self):
        """fake 模式下区域截图返回成功。"""
        data = _parse(
            tools.system_screenshot_region(
                x=10, y=20, width=300, height=200, fake=True
            )
        )
        assert data["ok"] is True
        assert data["data"]["mode"] == "region"

    def test_region_interactive_fake_ok(self):
        """省略坐标时进入交互式模式。"""
        data = _parse(tools.system_screenshot_region(fake=True))
        assert data["ok"] is True
        assert data["data"]["mode"] == "interactive"

    def test_region_partial_coords_returns_error(self):
        """部分坐标（缺一个）返回错误。"""
        data = _parse(
            tools.system_screenshot_region(
                x=10, y=20, width=300, fake=True  # 缺 height
            )
        )
        assert data["ok"] is False
        assert "x/y/width/height" in data["error"]

    def test_region_only_one_coord_returns_error(self):
        """只给一个坐标返回错误。"""
        data = _parse(tools.system_screenshot_region(x=10, fake=True))
        assert data["ok"] is False

    def test_region_with_custom_path(self):
        """区域截图接受自定义路径。"""
        data = _parse(
            tools.system_screenshot_region(
                x=0, y=0, width=100, height=100, path="/tmp/r.png", fake=True
            )
        )
        assert data["ok"] is True
        assert data["data"]["path"] == "/tmp/r.png"

    def test_region_publishes_event(self):
        """区域截图后发布 system.screenshot_taken 事件。"""
        events: list[tuple[str, dict[str, Any]]] = []

        class _Bus:
            def publish(self, event_type, payload):
                events.append((event_type, payload))

        rt = tools._runtime
        rt.event_publisher = _Bus()
        tools.system_screenshot_region(x=0, y=0, width=10, height=10, fake=True)
        assert len(events) == 1
        assert events[0][1]["action"] == "region"

    def test_region_interactive_publishes_event(self):
        """交互式截图后发布 action=interactive 事件。"""
        events: list[tuple[str, dict[str, Any]]] = []

        class _Bus:
            def publish(self, event_type, payload):
                events.append((event_type, payload))

        rt = tools._runtime
        rt.event_publisher = _Bus()
        tools.system_screenshot_region(fake=True)
        assert len(events) == 1
        assert events[0][1]["action"] == "interactive"

    def test_region_with_preset_backend(self):
        """预置 fake 后端时不重建。"""
        rt = tools._runtime
        rt.backend = FakeScreenshotBackend()
        data = _parse(tools.system_screenshot_region(x=1, y=2, width=3, height=4))
        assert data["ok"] is True
        assert rt.backend.calls[0][2] == (1, 2, 3, 4)


# ---------------------------------------------------------------------------
# 工具注册
# ---------------------------------------------------------------------------
class TestRegister:
    def test_register_registers_two_tools(self):
        """register(ctx) 注册 2 个 system_* 工具。"""

        class _Ctx:
            def __init__(self):
                self.tools = []
                self.event_bus = None

            def register_tool(self, **kwargs):
                self.tools.append(kwargs)

        ctx = _Ctx()
        tools.register(ctx)
        names = [t["name"] for t in ctx.tools]
        assert "system_screenshot_full" in names
        assert "system_screenshot_region" in names
        assert len(names) == 2
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
        handler = tools._make_handler(tools.system_screenshot_full)
        result = handler({"fake": True})
        data = _parse(result)
        assert data["ok"] is True

    def test_make_handler_invalid_args_returns_error(self):
        """_make_handler 在参数错误时返回 ok:false 而非抛错。"""
        handler = tools._make_handler(tools.system_screenshot_region)
        # 部分坐标应返回错误而非抛错
        result = handler({"x": 10, "fake": True})
        data = _parse(result)
        assert data["ok"] is False


# ---------------------------------------------------------------------------
# 工具元数据 TOOLS
# ---------------------------------------------------------------------------
class TestToolsMetadata:
    def test_tools_count(self):
        """TOOLS 注册表包含 2 个工具元数据。"""
        assert len(tools.TOOLS) == 2

    def test_tools_have_required_fields(self):
        """每个工具元数据包含 name/description/emoji/schema/handler_func。"""
        for meta in tools.TOOLS:
            assert meta["name"]
            assert meta["description"]
            assert meta["emoji"]
            assert "parameters" in meta["schema"]
            assert callable(meta["handler_func"])

    def test_region_schema_has_coords(self):
        """system_screenshot_region 的 schema 声明 x/y/width/height 参数。"""
        meta = next(m for m in tools.TOOLS if m["name"] == "system_screenshot_region")
        props = meta["schema"]["parameters"]["properties"]
        assert props["x"]["type"] == "integer"
        assert props["y"]["type"] == "integer"
        assert props["width"]["type"] == "integer"
        assert props["width"]["minimum"] == 1
        assert props["height"]["type"] == "integer"
        assert props["height"]["minimum"] == 1
        # 坐标不是必填（同时省略 = 交互式）
        assert "x" not in meta["schema"]["parameters"]["required"]

    def test_full_schema_no_required(self):
        """system_screenshot_full 不要求任何必填参数。"""
        meta = next(m for m in tools.TOOLS if m["name"] == "system_screenshot_full")
        assert meta["schema"]["parameters"]["required"] == []


# ---------------------------------------------------------------------------
# async EventBus 集成（覆盖 _publish coroutine 分支）
# ---------------------------------------------------------------------------
class TestAsyncEventBusIntegration:
    def test_full_publishes_to_real_event_bus(self):
        """全屏截图接入真实 EventBus 时事件被正确分发。"""
        import asyncio

        from omni_sdk.event_bus import EventBus

        bus = EventBus()
        received: list[dict] = []

        async def _collect(payload):
            received.append(payload)

        bus.subscribe("system.screenshot_taken", _collect)

        rt = tools._runtime
        rt.event_publisher = bus

        async def _run():
            tools.system_screenshot_full(fake=True)
            await asyncio.sleep(0.01)

        asyncio.run(_run())
        assert len(received) == 1
        assert received[0]["action"] == "full"

    def test_publish_with_real_bus_no_running_loop(self):
        """无运行中事件循环时 _publish 走 asyncio.run 同步执行分支。"""
        from omni_sdk.event_bus import EventBus

        bus = EventBus()
        received: list[dict] = []

        async def _collect(payload):
            received.append(payload)

        bus.subscribe("system.screenshot_taken", _collect)

        rt = tools._runtime
        rt.event_publisher = bus
        tools.system_screenshot_region(fake=True)
        assert len(received) == 1
        assert received[0]["action"] == "interactive"

    def test_publish_with_none_bus_is_noop(self):
        """event_publisher 为 None 时不抛错。"""
        rt = tools._runtime
        rt.event_publisher = None
        result = tools.system_screenshot_full(fake=True)
        data = _parse(result)
        assert data["ok"] is True

    def test_publish_with_bus_publish_raising_is_swallowed(self):
        """bus.publish 抛异常时被吞掉，不影响工具返回。"""

        class _BadBus:
            def publish(self, event_type, payload):
                raise RuntimeError("bus broken")

        rt = tools._runtime
        rt.event_publisher = _BadBus()
        result = tools.system_screenshot_full(fake=True)
        data = _parse(result)
        assert data["ok"] is True


# ---------------------------------------------------------------------------
# 后端异常路径（覆盖各 tool 的 except Exception 分支）
# ---------------------------------------------------------------------------
class TestBackendExceptionPaths:
    def test_full_backend_raises_returns_error(self):
        """后端 capture_full 抛异常时工具返回 ok:false。"""
        rt = tools._runtime

        class _BadBackend:
            def capture_full(self, path=None):
                raise RuntimeError("backend exploded")

        rt.backend = _BadBackend()
        result = tools.system_screenshot_full()
        data = _parse(result)
        assert data["ok"] is False
        assert "backend exploded" in data["error"]

    def test_region_backend_raises_returns_error(self):
        """后端 capture_region 抛异常时工具返回 ok:false。"""
        rt = tools._runtime

        class _BadBackend:
            def capture_region(self, region=None, path=None):
                raise RuntimeError("region failed")

        rt.backend = _BadBackend()
        result = tools.system_screenshot_region(x=0, y=0, width=10, height=10)
        data = _parse(result)
        assert data["ok"] is False

    def test_full_backend_returns_error_payload(self):
        """后端返回 ok:false 时工具透传错误消息。"""
        rt = tools._runtime

        class _ErrorBackend:
            def capture_full(self, path=None):
                return {"ok": False, "error": {"code": "E_CUSTOM", "message": "custom fail"}}

        rt.backend = _ErrorBackend()
        result = tools.system_screenshot_full()
        data = _parse(result)
        assert data["ok"] is False
        assert "custom fail" in data["error"]

    def test_region_backend_returns_error_payload(self):
        """后端 capture_region 返回 ok:false 时工具透传错误消息。"""
        rt = tools._runtime

        class _ErrorBackend:
            def capture_region(self, region=None, path=None):
                return {"ok": False, "error": {"code": "E_CUSTOM", "message": "region fail"}}

        rt.backend = _ErrorBackend()
        result = tools.system_screenshot_region()
        data = _parse(result)
        assert data["ok"] is False
        assert "region fail" in data["error"]
