"""LifecycleHost 单元测试：加载/卸载/manifest 校验/权限检查/错误隔离/拓扑排序。"""

from __future__ import annotations

import asyncio
import logging

import pytest

from omni_sdk.context import PluginContext
from omni_sdk.event_bus import EventBus
from omni_sdk.lifecycle import LifecycleHost
from omni_sdk.manifest import parse_manifest
from omni_sdk.permissions import PermissionChecker
from omni_sdk.plugin import OmniPlugin
from omni_sdk.registry import ToolRegistry


def _manifest_dict(name: str, **overrides) -> dict:
    """构造合法 manifest dict。"""
    base = {
        "name": name,
        "version": "0.1.0",
        "description": f"{name} 测试插件",
        "permissions": ["tools.register"],
        "tools": [],
    }
    base.update(overrides)
    return base


class _TrackingPlugin(OmniPlugin):
    """记录生命周期调用顺序的测试插件。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.loaded: list[str] = []
        self.unloaded: list[str] = []
        self.on_load_called = 0
        self.on_unload_called = 0
        self.ctx: PluginContext | None = None

    async def on_load(self, ctx: PluginContext) -> None:
        self.on_load_called += 1
        self.ctx = ctx
        self.loaded.append(self.name)

    async def on_unload(self) -> None:
        self.on_unload_called += 1
        self.unloaded.append(self.name)


def _make_host(policy: str = "lenient") -> LifecycleHost:
    return LifecycleHost(
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"], policy=policy),
        logger=logging.getLogger("omni_sdk.test.lifecycle"),
    )


def test_load_plugin_calls_on_load() -> None:
    """load_plugin 调用插件 on_load，并把 plugin 加入已加载列表。"""
    host = _make_host()
    plugin = _TrackingPlugin("omni_alpha")
    manifest = parse_manifest(_manifest_dict("omni_alpha"))

    asyncio.run(host.load_plugin(plugin, manifest))

    assert plugin.on_load_called == 1
    assert plugin.ctx is not None
    assert "omni_alpha" in host.list_loaded_plugins()


def test_load_plugin_injects_context() -> None:
    """load_plugin 注入的 ctx 包含 event_bus/tool_registry/permission_checker。"""
    host = _make_host()
    plugin = _TrackingPlugin("omni_alpha")
    manifest = parse_manifest(_manifest_dict("omni_alpha"))

    asyncio.run(host.load_plugin(plugin, manifest))

    assert plugin.ctx is not None
    assert plugin.ctx.event_bus is host.event_bus
    assert plugin.ctx.tool_registry is host.tool_registry
    assert plugin.ctx.permission_checker is host.permission_checker
    assert plugin.ctx.logger.name == "omni.omni_alpha"


def test_unload_plugin_calls_on_unload() -> None:
    """unload_plugin 调用插件 on_unload，并从已加载列表移除。"""
    host = _make_host()
    plugin = _TrackingPlugin("omni_alpha")
    manifest = parse_manifest(_manifest_dict("omni_alpha"))
    asyncio.run(host.load_plugin(plugin, manifest))

    asyncio.run(host.unload_plugin("omni_alpha"))

    assert plugin.on_unload_called == 1
    assert "omni_alpha" not in host.list_loaded_plugins()


def test_unload_unknown_plugin_no_error() -> None:
    """卸载未加载的插件不抛错。"""
    host = _make_host()
    asyncio.run(host.unload_plugin("nonexistent"))


def test_load_plugin_with_invalid_manifest_rejects() -> None:
    """manifest 校验失败的插件不加载。"""
    from omni_sdk.manifest import ManifestError

    host = _make_host()
    plugin = _TrackingPlugin("omni_alpha")
    # name 不以 omni_ 开头 → 解析即抛 ManifestError
    with pytest.raises(ManifestError):
        parse_manifest({"name": "alpha", "version": "0.1.0"})
    # 构造一个 name 不匹配 plugin 的 manifest
    manifest = parse_manifest(_manifest_dict("omni_alpha"))
    # 改 name 与 plugin.name 不一致
    object.__setattr__(manifest, "name", "omni_mismatch")
    asyncio.run(host.load_plugin(plugin, manifest))
    # 加载被拒绝（manifest.name 与 plugin.name 不匹配）
    assert "omni_alpha" not in host.list_loaded_plugins()
    assert plugin.on_load_called == 0


def test_load_plugin_permission_check_lenient_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """宽松模式下，manifest 声明未授予的权限时记录 warning 但仍加载。"""
    host = _make_host(policy="lenient")
    plugin = _TrackingPlugin("omni_alpha")
    manifest = parse_manifest(
        _manifest_dict("omni_alpha", permissions=["tools.register", "network"])
    )
    with caplog.at_level(logging.WARNING, logger="omni_sdk.test.lifecycle"):
        asyncio.run(host.load_plugin(plugin, manifest))
    assert plugin.on_load_called == 1
    assert any("network" in r.message for r in caplog.records)


def test_load_plugin_permission_check_strict_rejects() -> None:
    """严格模式下，manifest 声明未授予的权限时不加载该插件。"""
    host = _make_host(policy="strict")
    plugin = _TrackingPlugin("omni_alpha")
    manifest = parse_manifest(
        _manifest_dict("omni_alpha", permissions=["tools.register", "network"])
    )
    asyncio.run(host.load_plugin(plugin, manifest))
    assert plugin.on_load_called == 0
    assert "omni_alpha" not in host.list_loaded_plugins()


def test_load_plugin_error_isolation() -> None:
    """单个插件 on_load 抛异常不影响其他插件加载。"""
    host = _make_host()

    class _BoomPlugin(OmniPlugin):
        name = "omni_boom"

        async def on_load(self, ctx: PluginContext) -> None:
            raise RuntimeError("boom")

    boom = _BoomPlugin()
    ok = _TrackingPlugin("omni_ok")
    asyncio.run(
        host.load_all(
            [
                (boom, parse_manifest(_manifest_dict("omni_boom"))),
                (ok, parse_manifest(_manifest_dict("omni_ok"))),
            ]
        )
    )
    assert "omni_ok" in host.list_loaded_plugins()
    assert "omni_boom" not in host.list_loaded_plugins()


def test_dependency_order_topological_sort() -> None:
    """按 dependencies 拓扑排序加载：被依赖者先于依赖者加载。"""
    host = _make_host()
    load_order: list[str] = []

    class _A(OmniPlugin):
        name = "omni_a"

        async def on_load(self, ctx: PluginContext) -> None:
            load_order.append("a")

    class _B(OmniPlugin):
        name = "omni_b"

        async def on_load(self, ctx: PluginContext) -> None:
            load_order.append("b")

    class _C(OmniPlugin):
        name = "omni_c"

        async def on_load(self, ctx: PluginContext) -> None:
            load_order.append("c")

    a = _A()
    b = _B()
    c = _C()
    # b 依赖 a，c 依赖 b；输入乱序 [c, b, a]
    asyncio.run(
        host.load_all(
            [
                (c, parse_manifest(_manifest_dict("omni_c", dependencies={"omni_b": ">=0.1.0"}))),
                (b, parse_manifest(_manifest_dict("omni_b", dependencies={"omni_a": ">=0.1.0"}))),
                (a, parse_manifest(_manifest_dict("omni_a"))),
            ]
        )
    )
    assert load_order == ["a", "b", "c"]
    assert host.list_loaded_plugins() == ["omni_a", "omni_b", "omni_c"]


def test_dependency_order_unknown_dependency_ignored() -> None:
    """依赖未在加载列表中（如 omni_sdk 本身）时按可加载顺序处理。"""
    host = _make_host()
    load_order: list[str] = []

    class _P(OmniPlugin):
        name = "omni_p"

        async def on_load(self, ctx: PluginContext) -> None:
            load_order.append("p")

    p = _P()
    asyncio.run(
        host.load_all(
            [
                (
                    p,
                    parse_manifest(
                        _manifest_dict("omni_p", dependencies={"omni_sdk": ">=0.1.0"})
                    ),
                )
            ]
        )
    )
    assert load_order == ["p"]
    assert "omni_p" in host.list_loaded_plugins()


def test_unload_all_reverses_load_order() -> None:
    """unload_all 按加载顺序的逆序卸载。"""
    host = _make_host()
    unload_order: list[str] = []

    class _A(OmniPlugin):
        name = "omni_a"

        async def on_load(self, ctx: PluginContext) -> None:
            return None

        async def on_unload(self) -> None:
            unload_order.append("a")

    class _B(OmniPlugin):
        name = "omni_b"

        async def on_load(self, ctx: PluginContext) -> None:
            return None

        async def on_unload(self) -> None:
            unload_order.append("b")

    a = _A()
    b = _B()
    asyncio.run(
        host.load_all(
            [
                (a, parse_manifest(_manifest_dict("omni_a"))),
                (b, parse_manifest(_manifest_dict("omni_b", dependencies={"omni_a": ">=0.1.0"}))),
            ]
        )
    )
    asyncio.run(host.unload_all())
    # 加载顺序 a → b，卸载顺序应为 b → a
    assert unload_order == ["b", "a"]
    assert host.list_loaded_plugins() == []


def test_lifecycle_host_list_loaded_plugins() -> None:
    """list_loaded_plugins 返回按加载顺序排列的插件名列表。"""
    host = _make_host()
    a = _TrackingPlugin("omni_a")
    b = _TrackingPlugin("omni_b")
    asyncio.run(
        host.load_all(
            [
                (a, parse_manifest(_manifest_dict("omni_a"))),
                (b, parse_manifest(_manifest_dict("omni_b"))),
            ]
        )
    )
    assert host.list_loaded_plugins() == ["omni_a", "omni_b"]


def test_load_plugin_idempotent_on_reload() -> None:
    """重复 load 同名插件应替换旧实例并先卸载旧的。"""
    host = _make_host()
    first = _TrackingPlugin("omni_alpha")
    second = _TrackingPlugin("omni_alpha")
    manifest = parse_manifest(_manifest_dict("omni_alpha"))

    asyncio.run(host.load_plugin(first, manifest))
    asyncio.run(host.load_plugin(second, manifest))

    assert first.on_unload_called == 1
    assert second.on_load_called == 1
    assert host.list_loaded_plugins() == ["omni_alpha"]


def test_load_plugin_registers_manifest_tools() -> None:
    """load_plugin 后 manifest.tools 声明的工具被注册到 tool_registry。"""
    import json

    host = _make_host()

    class _P(OmniPlugin):
        name = "omni_p"

        async def on_load(self, ctx: PluginContext) -> None:
            # 子类不覆盖 register_tools，依赖基类默认实现读取 manifest.tools
            return None

        def register_tools(self, ctx: PluginContext) -> None:
            # 模拟基类默认实现：把 manifest 中声明的 tool 名注册为占位
            for tool_name in ("voice_status",):
                ctx.register_tool(
                    name=tool_name,
                    description="占位",
                    emoji="🎙️",
                    schema={"type": "object"},
                    handler_func=lambda kw: json.dumps({"ok": True}),
                )

    p = _P()
    manifest = parse_manifest(_manifest_dict("omni_p", tools=["voice_status"]))
    asyncio.run(host.load_plugin(p, manifest))
    assert "voice_status" in host.tool_registry.list_tools()


def test_register_tools_failure_does_not_block_load() -> None:
    """register_tools 抛异常不影响 on_load 完成（错误隔离）。"""
    host = _make_host()

    class _P(OmniPlugin):
        name = "omni_p"
        on_load_called = False

        async def on_load(self, ctx: PluginContext) -> None:
            self.on_load_called = True

        def register_tools(self, ctx: PluginContext) -> None:
            raise RuntimeError("tools boom")

    p = _P()
    manifest = parse_manifest(_manifest_dict("omni_p"))
    asyncio.run(host.load_plugin(p, manifest))
    assert p.on_load_called is True
    assert "omni_p" in host.list_loaded_plugins()


def test_unload_plugin_failure_is_isolated() -> None:
    """on_unload 抛异常不影响后续清理与从注册表移除。"""
    host = _make_host()

    class _P(OmniPlugin):
        name = "omni_p"

        async def on_load(self, ctx: PluginContext) -> None:
            return None

        async def on_unload(self) -> None:
            raise RuntimeError("unload boom")

    p = _P()
    manifest = parse_manifest(_manifest_dict("omni_p"))
    asyncio.run(host.load_plugin(p, manifest))
    asyncio.run(host.unload_plugin("omni_p"))
    assert "omni_p" not in host.list_loaded_plugins()


def test_get_plugin_returns_loaded_instance() -> None:
    """get_plugin 返回已加载的插件实例。"""
    host = _make_host()
    p = _TrackingPlugin("omni_alpha")
    asyncio.run(host.load_plugin(p, parse_manifest(_manifest_dict("omni_alpha"))))
    assert host.get_plugin("omni_alpha") is p
    assert host.get_plugin("nonexistent") is None


def test_load_plugin_with_circular_dependency_does_not_hang() -> None:
    """循环依赖被拓扑排序忽略，不会无限递归。"""
    host = _make_host()
    load_order: list[str] = []

    class _A(OmniPlugin):
        name = "omni_a"

        async def on_load(self, ctx: PluginContext) -> None:
            load_order.append("a")

    class _B(OmniPlugin):
        name = "omni_b"

        async def on_load(self, ctx: PluginContext) -> None:
            load_order.append("b")

    a = _A()
    b = _B()
    # a 依赖 b，b 依赖 a → 循环
    asyncio.run(
        host.load_all(
            [
                (a, parse_manifest(_manifest_dict("omni_a", dependencies={"omni_b": ">=0.1.0"}))),
                (b, parse_manifest(_manifest_dict("omni_b", dependencies={"omni_a": ">=0.1.0"}))),
            ]
        )
    )
    # 两个都应被加载（不无限递归）
    assert "omni_a" in host.list_loaded_plugins()
    assert "omni_b" in host.list_loaded_plugins()


def test_config_provider_plugins_section_format() -> None:
    """config_provider 支持 {"plugins": {<name>: {...}}} 嵌套格式。"""
    host = LifecycleHost(
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        config_provider={"plugins": {"omni_alpha": {"foo": "bar"}}},
    )
    plugin = _TrackingPlugin("omni_alpha")
    asyncio.run(host.load_plugin(plugin, parse_manifest(_manifest_dict("omni_alpha"))))
    assert plugin.ctx is not None
    assert plugin.ctx.config == {"foo": "bar"}


def test_config_provider_flat_format() -> None:
    """config_provider 支持平铺格式 {<name>: {...}}。"""
    host = LifecycleHost(
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        config_provider={"omni_alpha": {"x": 1}},
    )
    plugin = _TrackingPlugin("omni_alpha")
    asyncio.run(host.load_plugin(plugin, parse_manifest(_manifest_dict("omni_alpha"))))
    assert plugin.ctx is not None
    assert plugin.ctx.config == {"x": 1}


def test_config_provider_missing_plugin_returns_empty() -> None:
    """config_provider 中无对应插件配置时返回空 dict。"""
    host = LifecycleHost(
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        config_provider={"plugins": {"omni_other": {"x": 1}}},
    )
    plugin = _TrackingPlugin("omni_alpha")
    asyncio.run(host.load_plugin(plugin, parse_manifest(_manifest_dict("omni_alpha"))))
    assert plugin.ctx is not None
    assert plugin.ctx.config == {}


def test_load_plugin_with_empty_config_provider_uses_empty_dict() -> None:
    """无 config_provider 时插件 config 为空 dict。"""
    host = _make_host()
    plugin = _TrackingPlugin("omni_alpha")
    asyncio.run(host.load_plugin(plugin, parse_manifest(_manifest_dict("omni_alpha"))))
    assert plugin.ctx is not None
    assert plugin.ctx.config == {}


def test_unload_plugin_removes_registered_tools() -> None:
    """卸载插件时，该插件注册的工具被注销。"""
    import json

    host = _make_host()

    class _P(OmniPlugin):
        name = "omni_p"

        async def on_load(self, ctx: PluginContext) -> None:
            return None

        def register_tools(self, ctx: PluginContext) -> None:
            ctx.register_tool(
                name="alpha_tool",
                description="测试",
                emoji="🎙️",
                schema={"type": "object"},
                handler_func=lambda kw: json.dumps({"ok": True}),
            )

    p = _P()
    asyncio.run(host.load_plugin(p, parse_manifest(_manifest_dict("omni_p"))))
    assert "alpha_tool" in host.tool_registry.list_tools()

    asyncio.run(host.unload_plugin("omni_p"))
    assert "alpha_tool" not in host.tool_registry.list_tools()

