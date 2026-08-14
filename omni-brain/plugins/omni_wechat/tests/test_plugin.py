"""omni_wechat WechatPlugin 生命周期测试 + manifest 校验。

验证：
- ``WechatPlugin`` 继承 ``OmniPlugin``，元数据 name="omni_wechat"
- ``on_load(ctx)`` 把 5 个 wechat_* 工具注册到 ``ctx.tool_registry``
- ``on_load`` 后事件总线接入运行时 event_publisher
- ``on_unload`` 停止监听且幂等
- ``manifest.json`` 合法且 tools 与实际注册一致
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from omni_sdk.context import PluginContext
from omni_sdk.event_bus import EventBus
from omni_sdk.manifest import parse_manifest, validate_manifest
from omni_sdk.permissions import PermissionChecker
from omni_sdk.plugin import OmniPlugin
from omni_sdk.registry import ToolRegistry

from omni_wechat import WechatPlugin, register


WECHAT_DIR = Path(__file__).resolve().parent.parent


def _make_plugin_context(config: dict[str, Any] | None = None) -> PluginContext:
    """构造完整注入的 PluginContext。"""
    return PluginContext(
        config=config or {},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(
            allowed=["network", "fs.read:~/.omni_wechat", "fs.write:~/.omni_wechat", "tools.register"]
        ),
        plugin_name="omni_wechat",
    )


class _LegacyCtx:
    """旧式 register(ctx) 契约的 fake ctx。"""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []
        self.event_bus: Any = None

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)


class TestWechatPluginMetadata:
    def test_is_omni_plugin_subclass(self) -> None:
        assert issubclass(WechatPlugin, OmniPlugin)

    def test_metadata(self) -> None:
        plugin = WechatPlugin()
        assert plugin.name == "omni_wechat"
        assert plugin.version == "0.1.0"
        assert plugin.description
        assert plugin.emoji == "💬"

    def test_not_legacy_adapter(self) -> None:
        from omni_sdk.compat import LegacyPluginAdapter

        assert not issubclass(WechatPlugin, LegacyPluginAdapter)


class TestWechatPluginOnLoad:
    def test_on_load_registers_five_tools(self) -> None:
        plugin = WechatPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool_names = ctx.tool_registry.list_tools()
        assert "wechat_send" in tool_names
        assert "wechat_status" in tool_names
        assert "wechat_set_target" in tool_names
        assert "wechat_start_listen" in tool_names
        assert "wechat_stop_listen" in tool_names
        assert len(tool_names) == 5

    def test_on_load_tool_has_schema(self) -> None:
        plugin = WechatPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool = ctx.tool_registry.get_tool("wechat_send")
        assert tool is not None
        assert tool.schema
        assert callable(tool.handler_func)

    def test_on_load_wires_event_bus(self) -> None:
        plugin = WechatPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        from omni_wechat import tools as t

        assert t._runtime.event_publisher is ctx.event_bus

    def test_on_load_with_config(self) -> None:
        plugin = WechatPlugin()
        ctx = _make_plugin_context(config={
            "account": "cfg-acc",
            "token": "cfg-token",
            "default_target": "cfg-target@im.wechat",
            "state_dir": "/tmp/test_wechat",
        })
        asyncio.run(plugin.on_load(ctx))
        from omni_wechat import tools as t

        assert t._runtime.config is not None
        assert t._runtime.config.account == "cfg-acc"
        assert t._runtime.config.token == "cfg-token"

    def test_on_load_with_invalid_config_falls_back(self) -> None:
        plugin = WechatPlugin()
        ctx = _make_plugin_context(config={"unknown_field": "value"})
        # 不应抛异常，回退到默认配置
        asyncio.run(plugin.on_load(ctx))

    def test_on_load_with_backend(self) -> None:
        class FakeBackend:
            async def request(self, *a: Any, **kw: Any) -> tuple[int, Any]:
                return (200, {"ret": 0})

            async def close(self) -> None:
                pass

        plugin = WechatPlugin()
        ctx = _make_plugin_context(config={
            "account": "acc",
            "token": "tok",
            "backend": FakeBackend(),
        })
        asyncio.run(plugin.on_load(ctx))
        from omni_wechat import tools as t

        assert t._runtime.backend is not None

    def test_on_unload_stops_monitor(self) -> None:
        plugin = WechatPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        asyncio.run(plugin.on_unload())
        from omni_wechat import tools as t

        assert t._runtime.monitor is None
        assert t._runtime.event_publisher is None

    def test_on_unload_is_idempotent(self) -> None:
        plugin = WechatPlugin()
        asyncio.run(plugin.on_unload())
        asyncio.run(plugin.on_unload())

    def test_on_event_default_noop(self) -> None:
        plugin = WechatPlugin()
        asyncio.run(plugin.on_event("any.event", {"foo": "bar"}))


class TestWechatPluginBackwardCompat:
    def test_register_legacy_ctx(self) -> None:
        ctx = _LegacyCtx()
        register(ctx)
        assert len(ctx.tools) == 5
        names = {t["name"] for t in ctx.tools}
        assert "wechat_send" in names
        assert "wechat_status" in names
        assert "wechat_set_target" in names
        assert "wechat_start_listen" in names
        assert "wechat_stop_listen" in names
        for tool in ctx.tools:
            assert tool["description"]
            assert tool["emoji"]
            assert callable(tool["handler_func"])


class TestWechatManifest:
    def test_manifest_exists(self) -> None:
        assert (WECHAT_DIR / "manifest.json").is_file()

    def test_manifest_parses(self) -> None:
        data = json.loads((WECHAT_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert manifest.name == "omni_wechat"
        assert manifest.version == "0.1.0"
        assert manifest.description
        errors = validate_manifest(manifest)
        assert errors == [], f"manifest 软错误: {errors}"

    def test_manifest_tools_match_registered(self) -> None:
        data = json.loads((WECHAT_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        ctx = _LegacyCtx()
        register(ctx)
        declared = set(manifest.tools)
        registered = {t["name"] for t in ctx.tools}
        assert declared == registered

    def test_manifest_declares_events(self) -> None:
        data = json.loads((WECHAT_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert "wechat.message_received" in manifest.events.publishes
        assert "wechat.message_sent" in manifest.events.publishes
        assert "wechat.listen_started" in manifest.events.publishes
        assert "wechat.listen_stopped" in manifest.events.publishes

    def test_manifest_platforms(self) -> None:
        data = json.loads((WECHAT_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert "macos" in manifest.platforms
        assert "linux" in manifest.platforms

    def test_manifest_permissions(self) -> None:
        data = json.loads((WECHAT_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert "network" in manifest.permissions
        assert "tools.register" in manifest.permissions
        assert any(p.startswith("fs.read") for p in manifest.permissions)
        assert any(p.startswith("fs.write") for p in manifest.permissions)
