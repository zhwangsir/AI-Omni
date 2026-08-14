"""omni_office OfficePlugin 生命周期测试 + manifest 校验。

验证：
- ``OfficePlugin`` 继承 ``OmniPlugin``，元数据 name="omni_office"
- ``on_load(ctx)`` 把 19 个 office_* 工具注册到 ``ctx.tool_registry``
- ``on_load`` 后事件总线接入运行时 event_publisher
- ``on_unload`` 关闭 db 且幂等
- ``manifest.json`` 合法且 tools/events 与实际注册一致
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from omni_sdk.context import PluginContext
from omni_sdk.event_bus import EventBus
from omni_sdk.manifest import parse_manifest, validate_manifest
from omni_sdk.permissions import PermissionChecker
from omni_sdk.plugin import OmniPlugin
from omni_sdk.registry import ToolRegistry

from omni_office import OfficePlugin, register
from omni_office.tests.test_tools import EXPECTED_TOOLS

OFFICE_DIR = Path(__file__).resolve().parent.parent


def _make_plugin_context() -> PluginContext:
    """构造完整注入的 PluginContext（db 走内存，不触盘）。"""
    return PluginContext(
        config={"db_path": ":memory:"},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(
            allowed=[
                "tools.register",
                "network",
                "fs.read:~/.ai-omni/office",
                "fs.write:~/.ai-omni/office",
            ]
        ),
        plugin_name="omni_office",
    )


class _LegacyCtx:
    """旧式 register(ctx) 契约的 fake ctx。"""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []
        self.event_bus: Any = None

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)


class TestOfficePluginMetadata:
    def test_is_omni_plugin_subclass(self) -> None:
        assert issubclass(OfficePlugin, OmniPlugin)

    def test_metadata(self) -> None:
        plugin = OfficePlugin()
        assert plugin.name == "omni_office"
        assert plugin.version
        assert plugin.description
        assert plugin.emoji

    def test_not_legacy_adapter(self) -> None:
        from omni_sdk.compat import LegacyPluginAdapter

        assert not issubclass(OfficePlugin, LegacyPluginAdapter)


class TestOfficePluginOnLoad:
    def test_on_load_registers_all_tools(self) -> None:
        plugin = OfficePlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        names = set(ctx.tool_registry.list_tools())
        assert EXPECTED_TOOLS <= names

    def test_on_load_tool_has_schema_and_handler(self) -> None:
        plugin = OfficePlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool = ctx.tool_registry.get_tool("office_doc_create")
        assert tool is not None
        assert tool.schema
        assert callable(tool.handler_func)

    def test_on_load_wires_event_bus(self) -> None:
        plugin = OfficePlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        from omni_office import tools as t

        assert t._runtime.event_publisher is ctx.event_bus
        asyncio.run(plugin.on_unload())

    def test_on_load_uses_config_db_path(self) -> None:
        plugin = OfficePlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        from omni_office import tools as t

        assert t._runtime.db is not None
        asyncio.run(plugin.on_unload())

    def test_on_unload_closes_db_and_idempotent(self) -> None:
        plugin = OfficePlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        from omni_office import tools as t

        asyncio.run(plugin.on_unload())
        assert t._runtime.db is None or t._runtime.db._conn is None
        asyncio.run(plugin.on_unload())  # 幂等不抛错

    def test_on_event_default_noop(self) -> None:
        plugin = OfficePlugin()
        asyncio.run(plugin.on_event("any.event", {"foo": "bar"}))


class TestOfficePluginBackwardCompat:
    def test_register_legacy_ctx(self) -> None:
        ctx = _LegacyCtx()
        register(ctx)
        assert len(ctx.tools) == len(EXPECTED_TOOLS)
        names = {t["name"] for t in ctx.tools}
        assert EXPECTED_TOOLS <= names
        for tool in ctx.tools:
            assert tool["description"]
            assert tool["emoji"]
            assert callable(tool["handler_func"])


class TestOfficeManifest:
    def test_manifest_exists(self) -> None:
        assert (OFFICE_DIR / "manifest.json").is_file()

    def test_manifest_parses_and_validates(self) -> None:
        data = json.loads((OFFICE_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert manifest.name == "omni_office"
        assert manifest.description
        errors = validate_manifest(manifest)
        assert errors == [], f"manifest 软错误: {errors}"

    def test_manifest_tools_match_registered(self) -> None:
        data = json.loads((OFFICE_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert set(manifest.tools) == EXPECTED_TOOLS

    def test_manifest_declares_events(self) -> None:
        data = json.loads((OFFICE_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        for evt in (
            "office.doc_created",
            "office.doc_updated",
            "office.email_sent",
            "office.email_auto_replied",
            "office.event_created",
            "office.event_reminder",
            "office.workflow_completed",
        ):
            assert evt in manifest.events.publishes

    def test_manifest_platforms_and_permissions(self) -> None:
        data = json.loads((OFFICE_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert "macos" in manifest.platforms
        assert "linux" in manifest.platforms
        assert "tools.register" in manifest.permissions
        assert "network" in manifest.permissions
