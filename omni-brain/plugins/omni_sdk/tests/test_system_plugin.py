"""SystemPluginBase 测试：系统插件公共基类功能验证。"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from omni_sdk.system_plugin import SystemPluginBase


class _FakeBackend:
    """测试用 fake 后端。"""

    def __init__(self) -> None:
        self.value = 0

    def set_value(self, v: int) -> dict[str, Any]:
        self.value = v
        return {"ok": True, "value": v}

    def get_value(self) -> dict[str, Any]:
        return {"ok": True, "value": self.value}


class TestSystemPluginBase:
    """SystemPluginBase：统一事件桥接、backend 注入、handler 包装、manifest 校验。"""

    def test_backend_injection_from_config(self) -> None:
        """backend 从 ctx.config['backend'] 注入。"""
        fake_backend = _FakeBackend()

        class TestPlugin(SystemPluginBase):
            name = "test_plugin"
            version = "0.1.0"
            description = "test"
            emoji = "🧪"
            backend_class = _FakeBackend
            event_domain = "test"

            def _build_tools_meta(self) -> list[dict[str, Any]]:
                return []

        plugin = TestPlugin()
        ctx = MagicMock()
        ctx.config = {"backend": fake_backend}
        ctx.event_bus = MagicMock()
        ctx.tool_registry = MagicMock()

        asyncio.run(plugin.on_load(ctx))
        assert plugin._backend is fake_backend

    def test_event_publish_uses_tracker(self) -> None:
        """事件发布使用 TaskTracker 防止 GC。"""
        published: list[tuple[str, dict[str, Any]]] = []

        async def fake_publish(event_type: str, payload: dict[str, Any]) -> None:
            published.append((event_type, payload))

        class TestPlugin(SystemPluginBase):
            name = "test_plugin"
            version = "0.1.0"
            description = "test"
            emoji = "🧪"
            event_domain = "test"

            def _build_tools_meta(self) -> list[dict[str, Any]]:
                return []

        plugin = TestPlugin()
        ctx = MagicMock()
        ctx.config = {}
        bus = MagicMock()
        bus.publish = fake_publish
        ctx.event_bus = bus
        ctx.tool_registry = MagicMock()

        asyncio.run(plugin.on_load(ctx))

        # 同步发布应调度到事件循环
        async def run_publish() -> None:
            plugin.publish_event("changed", {"v": 42})
            await asyncio.sleep(0.05)

        asyncio.run(run_publish())
        assert len(published) == 1
        assert published[0][0] == "test.changed"
        assert published[0][1]["v"] == 42

    def test_handler_wraps_exceptions(self) -> None:
        """handler 自动捕获异常并返回 JSON 错误信封。"""

        class TestPlugin(SystemPluginBase):
            name = "test_plugin"
            version = "0.1.0"
            description = "test"
            emoji = "🧪"
            event_domain = "test"

            def _build_tools_meta(self) -> list[dict[str, Any]]:
                return [
                    {
                        "name": "test_action",
                        "description": "test",
                        "emoji": "🧪",
                        "schema": {
                            "name": "test_action",
                            "parameters": {"properties": {"x": {"type": "integer"}}},
                        },
                        "handler": self._make_handler(self._bad_handler),
                    }
                ]

            def _bad_handler(self, x: int = 0) -> str:
                raise RuntimeError(f"bad value: {x}")

        plugin = TestPlugin()
        ctx = MagicMock()
        ctx.config = {}
        ctx.event_bus = MagicMock()
        registered_tools: dict[str, Any] = {}

        def fake_register(name: str, **kwargs: Any) -> None:
            registered_tools[name] = kwargs

        ctx.register_tool = fake_register

        asyncio.run(plugin.on_load(ctx))
        handler = registered_tools["test_action"]["handler_func"]
        result = json.loads(handler({"x": 123}))
        assert result["ok"] is False
        assert "bad value: 123" in result["error"]["message"]

    def test_successful_handler_returns_ok(self) -> None:
        """成功 handler 返回 ok:true JSON。"""

        class TestPlugin(SystemPluginBase):
            name = "test_plugin"
            version = "0.1.0"
            description = "test"
            emoji = "🧪"
            event_domain = "test"

            def _build_tools_meta(self) -> list[dict[str, Any]]:
                return [
                    {
                        "name": "test_get",
                        "description": "get value",
                        "emoji": "📥",
                        "schema": {"name": "test_get", "parameters": {"properties": {}}},
                        "handler": self._make_handler(self._ok_handler),
                    }
                ]

            def _ok_handler(self) -> dict[str, Any]:
                return {"value": 99}

        plugin = TestPlugin()
        ctx = MagicMock()
        ctx.config = {}
        ctx.event_bus = MagicMock()
        registered_tools: dict[str, Any] = {}

        def fake_register(name: str, **kwargs: Any) -> None:
            registered_tools[name] = kwargs

        ctx.register_tool = fake_register

        asyncio.run(plugin.on_load(ctx))
        handler = registered_tools["test_get"]["handler_func"]
        result = json.loads(handler({}))
        assert result["ok"] is True
        assert result["data"]["value"] == 99

    def test_backend_unavailable_returns_error(self) -> None:
        """无 backend 时调用工具返回 E_BACKEND_UNAVAILABLE。"""

        class TestPlugin(SystemPluginBase):
            name = "test_plugin"
            version = "0.1.0"
            description = "test"
            emoji = "🧪"
            backend_class = None
            event_domain = "test"

            def _build_tools_meta(self) -> list[dict[str, Any]]:
                return [
                    {
                        "name": "test_op",
                        "description": "op",
                        "emoji": "⚙️",
                        "schema": {"name": "test_op", "parameters": {"properties": {}}},
                        "handler": self._make_handler(self._op, require_backend=True),
                    }
                ]

            def _op(self) -> dict[str, Any]:
                return {"ok": True}

        plugin = TestPlugin()
        ctx = MagicMock()
        ctx.config = {}
        ctx.event_bus = MagicMock()
        registered_tools: dict[str, Any] = {}

        def fake_register(name: str, **kwargs: Any) -> None:
            registered_tools[name] = kwargs

        ctx.register_tool = fake_register

        asyncio.run(plugin.on_load(ctx))
        handler = registered_tools["test_op"]["handler_func"]
        result = json.loads(handler({}))
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"
