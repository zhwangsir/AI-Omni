"""omni_music MusicPlugin 生命周期 + manifest 校验（M17.1-M17.4 + M17.9 + M19）。

验证：
- MusicPlugin 直接继承 OmniPlugin（不经过 LegacyPluginAdapter）
- on_load 注册完整 20 个工具（M17 12 个 + M19 8 个 library/playlist/decrypt）
- on_unload 幂等
- manifest.json 合法且字段齐全
- 工具 handler 返回 JSON 字符串
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

from omni_music import MusicPlugin, register


MUSIC_DIR = Path(__file__).resolve().parent.parent


def _make_plugin_context() -> PluginContext:
    """构造一份完整注入的 PluginContext。"""
    return PluginContext(
        config={},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register", "network"]),
        plugin_name="omni_music",
    )


class _LegacyCtx:
    """旧式 register(ctx) 契约的 fake ctx。"""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []
        self.event_bus: Any = None

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)


class TestMusicPluginMetadata:
    def test_plugin_is_omni_plugin_subclass(self) -> None:
        """MusicPlugin 是 OmniPlugin 子类。"""
        assert issubclass(MusicPlugin, OmniPlugin)

    def test_plugin_direct_subclass_not_compat(self) -> None:
        """MusicPlugin 直接继承 OmniPlugin，不经过 LegacyPluginAdapter。"""
        from omni_sdk.compat import LegacyPluginAdapter

        assert not issubclass(MusicPlugin, LegacyPluginAdapter)

    def test_plugin_metadata(self) -> None:
        """MusicPlugin 元数据 name="omni_music"。"""
        plugin = MusicPlugin()
        assert plugin.name == "omni_music"
        assert plugin.version
        assert plugin.description


class TestMusicPluginOnLoad:
    def test_on_load_registers_twelve_tools(self) -> None:
        """on_load 注册完整 20 个工具到 tool_registry（M17 12 + M19 8）。"""
        plugin = MusicPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tools = ctx.tool_registry.list_tools()
        assert "music_search" in tools
        assert "music_get_login_qr" in tools
        assert "music_play" in tools
        assert "music_get_player_state" in tools
        # M19 新增 8 个 library/playlist/decrypt 工具
        assert "music_library_scan" in tools
        assert "music_library_search" in tools
        assert "music_decrypt_file" in tools
        assert "music_playlist_create" in tools
        assert len(tools) == 20

    def test_on_load_tool_has_schema_and_handler(self) -> None:
        """注册的工具携带 schema 与 handler_func。"""
        plugin = MusicPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool = ctx.tool_registry.get_tool("music_search")
        assert tool is not None
        assert tool.schema
        assert callable(tool.handler_func)

    def test_on_load_tool_handler_returns_json(self) -> None:
        """工具 handler 返回合法 JSON 字符串。"""
        plugin = MusicPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool = ctx.tool_registry.get_tool("music_search")
        assert tool is not None
        result = tool.handler_func({"keyword": "晴天", "fake": True})
        data = json.loads(result)
        assert "ok" in data

    def test_on_load_music_get_login_qr_handler(self) -> None:
        """music_get_login_qr 工具 handler 返回 JSON。"""
        plugin = MusicPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool = ctx.tool_registry.get_tool("music_get_login_qr")
        assert tool is not None
        result = tool.handler_func({"fake": True})
        data = json.loads(result)
        assert "ok" in data

    def test_on_unload_idempotent(self) -> None:
        """on_unload 可多次调用（幂等）。"""
        plugin = MusicPlugin()
        asyncio.run(plugin.on_unload())
        asyncio.run(plugin.on_unload())


class TestMusicPluginBackwardCompat:
    def test_register_legacy_ctx_still_works(self) -> None:
        """旧式 register(ctx) 入口仍可直接调用（注册全部 20 工具）。"""
        ctx = _LegacyCtx()
        register(ctx)
        assert len(ctx.tools) == 20
        names = [t["name"] for t in ctx.tools]
        assert "music_search" in names
        assert "music_get_login_qr" in names
        assert "music_play" in names
        assert "music_get_player_state" in names
        # M19 新增工具
        assert "music_library_scan" in names
        assert "music_decrypt_file" in names

    def test_register_legacy_ctx_handler_returns_json(self) -> None:
        """旧式 ctx 收到的 handler 调用返回 JSON 字符串。"""
        ctx = _LegacyCtx()
        register(ctx)
        tool = next(t for t in ctx.tools if t["name"] == "music_search")
        result = tool["handler_func"]({"keyword": "晴天", "fake": True})
        data = json.loads(result)
        assert "ok" in data


class TestMusicManifest:
    def test_manifest_json_exists(self) -> None:
        """omni_music/manifest.json 存在。"""
        assert (MUSIC_DIR / "manifest.json").is_file()

    def test_manifest_json_parses(self) -> None:
        """manifest.json 经 parse_manifest 解析合法。"""
        data = json.loads((MUSIC_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert manifest.name == "omni_music"
        assert manifest.version
        assert manifest.description
        errors = validate_manifest(manifest)
        # 工具名与事件类型应合法；权限 network/tools.register 已知
        assert all("network" not in e for e in errors)
        assert all("tools.register" not in e for e in errors)

    def test_manifest_declares_network_permission(self) -> None:
        """manifest.permissions 含 network（音乐源需要联网）。"""
        data = json.loads((MUSIC_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert "network" in manifest.permissions
        assert "tools.register" in manifest.permissions

    def test_manifest_platforms_macos_linux(self) -> None:
        """manifest.platforms 含 macos 与 linux。"""
        data = json.loads((MUSIC_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert "macos" in manifest.platforms
        assert "linux" in manifest.platforms

    def test_manifest_dependencies_omni_sdk(self) -> None:
        """manifest.dependencies 声明 omni_sdk >=0.1.0。"""
        data = json.loads((MUSIC_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert "omni_sdk" in manifest.dependencies

    def test_manifest_tools_match_registered(self) -> None:
        """manifest.tools 与 register(ctx) 实际注册的工具名一致。"""
        data = json.loads((MUSIC_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        ctx = _LegacyCtx()
        register(ctx)
        declared = set(manifest.tools)
        registered = {t["name"] for t in ctx.tools}
        assert declared == registered

    def test_manifest_events_declares_music_events(self) -> None:
        """manifest.events.publishes 至少声明一个 music.* 事件。"""
        data = json.loads((MUSIC_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert any(e.startswith("music.") for e in manifest.events.publishes)
