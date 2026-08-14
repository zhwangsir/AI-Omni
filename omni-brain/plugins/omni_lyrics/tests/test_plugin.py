"""omni_lyrics LyricsPlugin 生命周期测试 + manifest 校验（M18 TDD）。

验证：
- ``LyricsPlugin`` 继承 ``OmniPlugin``，元数据 name="omni_lyrics"
- ``LyricsPlugin.on_load(ctx)`` 把 5 个 lyrics_* 工具注册到 ``ctx.tool_registry``
- ``on_unload`` 清理引用且幂等
- ``manifest.json`` 存在且经 ``parse_manifest`` 合法
- manifest.tools 与实际注册工具名一致
- manifest.events 声明 lyrics.* 事件
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

from omni_lyrics import LyricsPlugin, register
from omni_lyrics import tools as lyrics_tools


LYRICS_DIR = Path(__file__).resolve().parent.parent


def _make_plugin_context() -> PluginContext:
    """构造一份完整注入的 PluginContext，用于 on_load。"""
    return PluginContext(
        config={},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        plugin_name="omni_lyrics",
    )


class _LegacyCtx:
    """旧式 register(ctx) 契约的 fake ctx，收集 register_tool 调用。"""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)


class TestLyricsPluginMetadata:
    def test_lyrics_plugin_is_omni_plugin_subclass(self) -> None:
        """LyricsPlugin 是 OmniPlugin 子类。"""
        assert issubclass(LyricsPlugin, OmniPlugin)

    def test_lyrics_plugin_metadata(self) -> None:
        """LyricsPlugin 元数据 name="omni_lyrics"。"""
        plugin = LyricsPlugin()
        assert plugin.name == "omni_lyrics"
        assert plugin.version
        assert plugin.description
        assert plugin.emoji

    def test_lyrics_plugin_direct_subclass_not_compat(self) -> None:
        """LyricsPlugin 直接继承 OmniPlugin，不经过 LegacyPluginAdapter。"""
        from omni_sdk.compat import LegacyPluginAdapter

        assert not issubclass(LyricsPlugin, LegacyPluginAdapter)


class TestLyricsPluginOnLoad:
    def test_on_load_calls_register(self) -> None:
        """on_load(ctx) 调用 register(ctx)，工具注册到 PluginContext.tool_registry。"""
        plugin = LyricsPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tools = ctx.tool_registry.list_tools()
        assert "lyrics_get" in tools
        assert "lyrics_search" in tools
        assert "lyrics_set_offset" in tools
        assert "lyrics_upload" in tools
        assert "lyrics_get_current" in tools
        assert len(tools) == 5

    def test_on_load_tool_has_schema(self) -> None:
        """on_load 后 tool_registry 中的工具携带 schema 与 handler_func。"""
        plugin = LyricsPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool = ctx.tool_registry.get_tool("lyrics_get")
        assert tool is not None
        assert tool.schema
        assert callable(tool.handler_func)

    def test_on_load_tool_handler_returns_json(self) -> None:
        """on_load 后调用 handler 返回合法 JSON 字符串。"""
        plugin = LyricsPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        tool = ctx.tool_registry.get_tool("lyrics_set_offset")
        assert tool is not None
        result = tool.handler_func({"offset_s": 1.5})
        data = json.loads(result)
        assert data["ok"] is True

    def test_on_unload_is_idempotent(self) -> None:
        """on_unload 可多次调用（幂等）。"""
        plugin = LyricsPlugin()
        asyncio.run(plugin.on_unload())
        asyncio.run(plugin.on_unload())


class TestLyricsPluginBackwardCompat:
    def test_register_legacy_ctx_still_works(self) -> None:
        """旧式 register(ctx) 入口仍可直接调用（鸭子类型 ctx）。"""
        ctx = _LegacyCtx()
        register(ctx)
        assert len(ctx.tools) == 5
        names = [t["name"] for t in ctx.tools]
        assert "lyrics_get" in names
        for tool in ctx.tools:
            assert tool["description"]
            assert tool["emoji"]
            assert callable(tool["handler_func"])

    def test_register_legacy_ctx_handler_returns_json(self) -> None:
        """旧式 ctx 收到的 handler 调用返回 JSON 字符串。"""
        ctx = _LegacyCtx()
        register(ctx)
        tool = next(t for t in ctx.tools if t["name"] == "lyrics_set_offset")
        result = tool["handler_func"]({"offset_s": 0.0})
        data = json.loads(result)
        assert data["ok"] is True


class TestLyricsPluginEventSubscriptions:
    """on_load 订阅 music.* 事件自动启停歌词同步（__init__.py 事件回调分支）。"""

    @pytest.fixture(autouse=True)
    def _reset_tools_runtime(self):
        """每个测试前后重置 tools._runtime，避免跨测试状态污染。"""
        lyrics_tools._reset_runtime()
        yield
        lyrics_tools._reset_runtime()

    def _load(self) -> PluginContext:
        """加载插件并返回注入的 PluginContext（含真实 EventBus）。"""
        plugin = LyricsPlugin()
        ctx = _make_plugin_context()
        asyncio.run(plugin.on_load(ctx))
        return ctx

    def test_music_started_starts_sync(self) -> None:
        """music.started 携带 track_id 时启动歌词同步。"""
        ctx = self._load()
        asyncio.run(ctx.event_bus.publish("music.started", {"track_id": "s1"}))
        assert lyrics_tools._runtime.sync_active is True
        assert lyrics_tools._runtime.current_song_id == "s1"

    def test_music_started_without_track_id_ignored(self) -> None:
        """music.started 缺少 track_id 时不启动同步。"""
        ctx = self._load()
        asyncio.run(ctx.event_bus.publish("music.started", {}))
        assert lyrics_tools._runtime.sync_active is False
        assert lyrics_tools._runtime.current_song_id is None

    def test_music_paused_keeps_sync_state(self) -> None:
        """music.paused 不改变同步状态（保持当前行显示）。"""
        ctx = self._load()
        asyncio.run(ctx.event_bus.publish("music.started", {"track_id": "s1"}))
        asyncio.run(ctx.event_bus.publish("music.paused", {}))
        assert lyrics_tools._runtime.sync_active is True
        assert lyrics_tools._runtime.current_song_id == "s1"

    def test_music_stopped_stops_sync(self) -> None:
        """music.stopped 停止歌词同步并清除当前歌曲。"""
        ctx = self._load()
        asyncio.run(ctx.event_bus.publish("music.started", {"track_id": "s1"}))
        asyncio.run(ctx.event_bus.publish("music.stopped", {}))
        assert lyrics_tools._runtime.sync_active is False
        assert lyrics_tools._runtime.current_song_id is None

    def test_track_changed_switches_sync(self) -> None:
        """music.track_changed 携带 track_id 时切换同步到新曲目。"""
        ctx = self._load()
        asyncio.run(ctx.event_bus.publish("music.started", {"track_id": "s1"}))
        asyncio.run(ctx.event_bus.publish("music.track_changed", {"track_id": "s2"}))
        assert lyrics_tools._runtime.sync_active is True
        assert lyrics_tools._runtime.current_song_id == "s2"

    def test_track_changed_without_track_id_keeps_state(self) -> None:
        """music.track_changed 缺少 track_id 时保持原同步状态。"""
        ctx = self._load()
        asyncio.run(ctx.event_bus.publish("music.started", {"track_id": "s1"}))
        asyncio.run(ctx.event_bus.publish("music.track_changed", {}))
        assert lyrics_tools._runtime.sync_active is True
        assert lyrics_tools._runtime.current_song_id == "s1"


class TestLyricsManifest:
    def test_manifest_json_exists(self) -> None:
        """omni_lyrics/manifest.json 文件存在。"""
        assert (LYRICS_DIR / "manifest.json").is_file()

    def test_manifest_json_parses(self) -> None:
        """manifest.json 经 parse_manifest 解析合法。"""
        data = json.loads((LYRICS_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert manifest.name == "omni_lyrics"
        assert manifest.version
        assert manifest.description
        errors = validate_manifest(manifest)
        assert all("tools.register" not in e for e in errors)

    def test_manifest_tools_match_registered(self) -> None:
        """manifest.tools 与 register(ctx) 实际注册的工具名一致。"""
        data = json.loads((LYRICS_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        ctx = _LegacyCtx()
        register(ctx)
        declared = set(manifest.tools)
        registered = {t["name"] for t in ctx.tools}
        assert declared == registered

    def test_manifest_declares_lyrics_events(self) -> None:
        """manifest.events.publishes 声明 lyrics.* 事件。"""
        data = json.loads((LYRICS_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        # 至少声明一个 lyrics.* 事件
        assert any(e.startswith("lyrics.") for e in manifest.events.publishes)

    def test_manifest_subscribes_music_events(self) -> None:
        """manifest.events.subscribes 订阅 music.* 事件（播放进度同步用）。"""
        data = json.loads((LYRICS_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        # 订阅 music.track_changed 用于歌词切换
        assert any(e.startswith("music.") for e in manifest.events.subscribes)

    def test_manifest_declares_fs_permissions(self) -> None:
        """manifest.permissions 声明 fs.write（上传歌词写 .lrc）。"""
        data = json.loads((LYRICS_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert any(p.startswith("fs.write") for p in manifest.permissions)

    def test_manifest_dependencies_omni_sdk(self) -> None:
        """manifest.dependencies 声明 omni_sdk 依赖。"""
        data = json.loads((LYRICS_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest = parse_manifest(data)
        assert "omni_sdk" in manifest.dependencies
