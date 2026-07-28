"""LegacyPluginAdapter / wrap_legacy_plugin 单元测试（M15.9）。

覆盖：
- :class:`LegacyPluginAdapter` 包装 ``register(ctx)`` 函数为 :class:`OmniPlugin` 子类
- ``on_load(ctx)`` 调用 ``register(ctx)`` 完成工具注册（经 :class:`_LegacyCtxAdapter` 适配）
- 工具注册经适配层翻译 ``handler=`` → ``handler_func=``
- :func:`wrap_legacy_plugin` 从模块提取 ``register`` 函数 + 元数据
- 真实模块集成：``omni_voice`` / ``omni_home`` 经适配层加载并注册工具
- 向后兼容：``RegisterCompatPlugin`` 别名与 ``register_func`` 参数仍可用
"""

from __future__ import annotations

import asyncio
import json
import types
from typing import Any, Callable

import pytest

from omni_sdk.compat import (
    LegacyPluginAdapter,
    RegisterCompatPlugin,
    _LegacyCtxAdapter,
    wrap_legacy_plugin,
)
from omni_sdk.context import PluginContext
from omni_sdk.event_bus import EventBus
from omni_sdk.permissions import PermissionChecker
from omni_sdk.plugin import OmniPlugin
from omni_sdk.registry import ToolRegistry


def _make_ctx(tool_registry: ToolRegistry | None = None) -> PluginContext:
    """构造测试用 PluginContext。

    注意：不能用 ``tool_registry or ToolRegistry()``——空 ToolRegistry 的 ``__len__`` 返回 0，
    在布尔上下文中为假，会导致 ``or`` 误创建新实例。必须用 ``is not None`` 显式判断。
    """
    return PluginContext(
        config={},
        event_bus=EventBus(),
        tool_registry=tool_registry if tool_registry is not None else ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        plugin_name="omni_test",
    )


def _make_legacy_register(calls: list[tuple[str, dict]] | None = None) -> Callable[[Any], None]:
    """构造一个 fake register(ctx) 函数：注册 2 个工具，可选记录调用。"""

    def register(ctx: Any) -> None:
        if calls is not None:
            calls.append(("register", {"ctx": ctx}))
        ctx.register_tool(
            name="demo_status",
            toolset="omni_demo",
            schema={"type": "object", "properties": {}},
            handler=lambda args: json.dumps({"ok": True, "data": {"state": "idle"}}),
            description="演示状态工具",
            emoji="📊",
        )
        ctx.register_tool(
            name="demo_ping",
            toolset="omni_demo",
            schema={"type": "object", "properties": {}},
            handler=lambda args: json.dumps({"ok": True, "data": "pong"}),
            description="演示 ping 工具",
            emoji="🏓",
        )

    return register


# ---------------------------------------------------------------------------
# LegacyPluginAdapter 基础行为
# ---------------------------------------------------------------------------
class TestLegacyPluginAdapterBasics:
    """LegacyPluginAdapter 包装 register(ctx) 为 OmniPlugin。"""

    def test_adapter_is_omni_plugin(self) -> None:
        """LegacyPluginAdapter 是 OmniPlugin 子类。"""
        adapter = LegacyPluginAdapter(
            register_fn=lambda ctx: None,
            name="omni_test",
        )
        assert isinstance(adapter, OmniPlugin)

    def test_adapter_stores_metadata(self) -> None:
        """构造时传入的元数据写入实例属性。"""
        adapter = LegacyPluginAdapter(
            register_fn=lambda ctx: None,
            name="omni_voice",
            version="1.2.3",
            description="语音插件",
            emoji="🎙️",
        )
        assert adapter.name == "omni_voice"
        assert adapter.version == "1.2.3"
        assert adapter.description == "语音插件"
        assert adapter.emoji == "🎙️"

    def test_adapter_default_version(self) -> None:
        """未传 version 时默认 0.1.0（继承 OmniPlugin 类属性）。"""
        adapter = LegacyPluginAdapter(
            register_fn=lambda ctx: None,
            name="omni_test",
        )
        assert adapter.version == "0.1.0"

    def test_adapter_default_description_empty(self) -> None:
        """未传 description 时默认空字符串。"""
        adapter = LegacyPluginAdapter(
            register_fn=lambda ctx: None,
            name="omni_test",
        )
        assert adapter.description == ""

    def test_adapter_default_emoji_empty(self) -> None:
        """未传 emoji 时默认空字符串。"""
        adapter = LegacyPluginAdapter(
            register_fn=lambda ctx: None,
            name="omni_test",
        )
        assert adapter.emoji == ""

    def test_adapter_subclass_uses_class_attributes(self) -> None:
        """子类设置类属性后，super().__init__(register_fn=...) 即可。"""

        class _MyPlugin(LegacyPluginAdapter):
            name = "omni_my"
            version = "2.0.0"
            description = "自定义插件"
            emoji = "🎯"

        plugin = _MyPlugin(register_fn=lambda ctx: None)
        assert plugin.name == "omni_my"
        assert plugin.version == "2.0.0"
        assert plugin.description == "自定义插件"
        assert plugin.emoji == "🎯"

    def test_adapter_raises_without_register_fn(self) -> None:
        """未提供 register_fn 或 register_func 时抛 ValueError。"""
        with pytest.raises(ValueError, match="register_fn"):
            LegacyPluginAdapter(name="omni_test")  # type: ignore[call-arg]

    def test_adapter_accepts_register_func_alias(self) -> None:
        """register_func= 作为向后兼容别名也被接受。"""
        fn = lambda ctx: None  # noqa: E731
        adapter = LegacyPluginAdapter(register_func=fn, name="omni_test")
        # 双名存储
        assert adapter._register_func is fn
        assert adapter._register_fn is fn


# ---------------------------------------------------------------------------
# 向后兼容：RegisterCompatPlugin 别名
# ---------------------------------------------------------------------------
class TestRegisterCompatPluginAlias:
    """RegisterCompatPlugin 是 LegacyPluginAdapter 的向后兼容别名。"""

    def test_alias_is_same_class(self) -> None:
        """RegisterCompatPlugin 就是 LegacyPluginAdapter（别名）。"""
        assert RegisterCompatPlugin is LegacyPluginAdapter

    def test_voice_plugin_still_works_with_alias(self) -> None:
        """VoicePlugin(RegisterCompatPlugin) 子类化仍可正常构造。"""
        from omni_voice import VoicePlugin

        plugin = VoicePlugin()
        assert isinstance(plugin, LegacyPluginAdapter)
        assert plugin.name == "omni_voice"


# ---------------------------------------------------------------------------
# on_load 调用 register(ctx)
# ---------------------------------------------------------------------------
class TestOnLoadCallsRegister:
    """on_load 经 _LegacyCtxAdapter 调用 register(ctx)。"""

    def test_on_load_calls_register_once(self) -> None:
        """on_load 调用 register(ctx) 一次。"""
        calls: list[tuple[str, dict]] = []
        adapter = LegacyPluginAdapter(
            register_fn=_make_legacy_register(calls),
            name="omni_test",
        )
        ctx = _make_ctx()
        asyncio.run(adapter.on_load(ctx))
        assert len(calls) == 1
        assert calls[0][0] == "register"

    def test_on_load_passes_legacy_ctx_adapter(self) -> None:
        """on_load 传给 register 的是 _LegacyCtxAdapter（包装 PluginContext）。"""
        captured: list[Any] = []
        adapter = LegacyPluginAdapter(
            register_fn=lambda ctx: captured.append(ctx),
            name="omni_test",
        )
        ctx = _make_ctx()
        asyncio.run(adapter.on_load(ctx))
        assert len(captured) == 1
        assert isinstance(captured[0], _LegacyCtxAdapter)

    def test_on_load_preserves_event_bus(self) -> None:
        """_LegacyCtxAdapter 透传 event_bus（register(ctx) 用它接入事件总线）。"""
        captured: list[Any] = []
        adapter = LegacyPluginAdapter(
            register_fn=lambda ctx: captured.append(ctx),
            name="omni_test",
        )
        ctx = _make_ctx()
        asyncio.run(adapter.on_load(ctx))
        # 旧式代码：bus = getattr(ctx, "event_bus", None)
        bus = getattr(captured[0], "event_bus", None)
        assert bus is not None
        # _LegacyEventBusAdapter 包装了 EventBus，提供 sync publish


# ---------------------------------------------------------------------------
# 工具注册保持不变（handler= → handler_func= 翻译）
# ---------------------------------------------------------------------------
class TestToolRegistrationPreserved:
    """_LegacyCtxAdapter 把 register(ctx) 的 handler= 翻译为 handler_func=。"""

    def test_on_load_registers_tools_to_registry(self) -> None:
        """on_load 调用 register(ctx) 后，工具注册到 ctx.tool_registry。"""
        calls: list[tuple[str, dict]] = []
        adapter = LegacyPluginAdapter(
            register_fn=_make_legacy_register(calls),
            name="omni_test",
        )
        tool_registry = ToolRegistry()
        ctx = _make_ctx(tool_registry=tool_registry)
        asyncio.run(adapter.on_load(ctx))

        assert "demo_status" in tool_registry.list_tools()
        assert "demo_ping" in tool_registry.list_tools()
        assert len(tool_registry) == 2

    def test_registered_tool_has_correct_metadata(self) -> None:
        """经适配层注册的工具携带正确的 description / emoji / schema。"""
        adapter = LegacyPluginAdapter(
            register_fn=_make_legacy_register(),
            name="omni_test",
        )
        tool_registry = ToolRegistry()
        ctx = _make_ctx(tool_registry=tool_registry)
        asyncio.run(adapter.on_load(ctx))

        tool = tool_registry.get_tool("demo_status")
        assert tool is not None
        assert tool.description == "演示状态工具"
        assert tool.emoji == "📊"
        assert tool.schema == {"type": "object", "properties": {}}

    def test_registered_handler_returns_json_string(self) -> None:
        """经适配层注册的 handler_func 返回 JSON 字符串。"""
        adapter = LegacyPluginAdapter(
            register_fn=_make_legacy_register(),
            name="omni_test",
        )
        tool_registry = ToolRegistry()
        ctx = _make_ctx(tool_registry=tool_registry)
        asyncio.run(adapter.on_load(ctx))

        tool = tool_registry.get_tool("demo_status")
        assert tool is not None
        result = tool.handler_func({})
        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert parsed["data"]["state"] == "idle"

    def test_register_tools_is_noop_after_on_load(self) -> None:
        """register_tools 默认空实现（工具已在 on_load 中注册，不重复）。"""
        adapter = LegacyPluginAdapter(
            register_fn=_make_legacy_register(),
            name="omni_test",
        )
        tool_registry = ToolRegistry()
        ctx = _make_ctx(tool_registry=tool_registry)
        asyncio.run(adapter.on_load(ctx))
        assert len(tool_registry) == 2

        # 调用 register_tools 不应再增加工具
        adapter.register_tools(ctx)
        assert len(tool_registry) == 2

    def test_extra_kwargs_ignored(self) -> None:
        """register(ctx) 传 toolset= 等额外 kwargs 不报错（仅用必要字段）。"""

        def register(ctx: Any) -> None:
            ctx.register_tool(
                name="extra_tool",
                toolset="omni_extra",
                schema={"type": "object"},
                handler=lambda args: json.dumps({"ok": True}),
                description="额外工具",
                emoji="📦",
                extra_kwarg="ignored",
            )

        adapter = LegacyPluginAdapter(register_fn=register, name="omni_test")
        tool_registry = ToolRegistry()
        ctx = _make_ctx(tool_registry=tool_registry)
        asyncio.run(adapter.on_load(ctx))
        assert "extra_tool" in tool_registry.list_tools()

    def test_handler_func_kwarg_accepted_directly(self) -> None:
        """_LegacyCtxAdapter.register_tool 也接受 handler_func= 新式签名。"""

        def register(ctx: Any) -> None:
            ctx.register_tool(
                name="new_style",
                description="新式签名",
                emoji="🆕",
                schema={"type": "object"},
                handler_func=lambda args: json.dumps({"ok": True}),
            )

        adapter = LegacyPluginAdapter(register_fn=register, name="omni_test")
        tool_registry = ToolRegistry()
        ctx = _make_ctx(tool_registry=tool_registry)
        asyncio.run(adapter.on_load(ctx))
        assert "new_style" in tool_registry.list_tools()


# ---------------------------------------------------------------------------
# on_unload / on_event 默认实现
# ---------------------------------------------------------------------------
class TestDefaultHooks:
    """on_unload / on_event 默认空实现，幂等可多次调用。"""

    def test_on_unload_is_idempotent(self) -> None:
        """on_unload 默认空实现可多次调用。"""
        adapter = LegacyPluginAdapter(
            register_fn=lambda ctx: None,
            name="omni_test",
        )
        asyncio.run(adapter.on_unload())
        asyncio.run(adapter.on_unload())

    def test_on_event_is_noop(self) -> None:
        """on_event 默认空实现可调用不抛错。"""
        adapter = LegacyPluginAdapter(
            register_fn=lambda ctx: None,
            name="omni_test",
        )
        asyncio.run(adapter.on_event("voice.state_changed", {"state": "idle"}))


# ---------------------------------------------------------------------------
# wrap_legacy_plugin 从模块提取元数据
# ---------------------------------------------------------------------------
class TestWrapLegacyPlugin:
    """wrap_legacy_plugin(module) 从模块属性读取 register 函数 + 元数据。"""

    def test_wrap_extracts_register_function(self) -> None:
        """从模块的 register 属性提取 register 函数。"""
        mod = types.ModuleType("omni_fake")

        def register(ctx) -> None:
            ctx.register_tool(
                name="fake_status",
                schema={"type": "object"},
                handler=lambda args: json.dumps({"ok": True}),
                description="fake",
                emoji="🧪",
            )

        mod.register = register
        adapter = wrap_legacy_plugin(mod)
        assert adapter.name == "omni_fake"
        assert adapter._register_fn is register

    def test_wrap_reads_plugin_name_attribute(self) -> None:
        """优先读取 __plugin_name__ 属性。"""
        mod = types.ModuleType("some_module")
        mod.__plugin_name__ = "omni_custom"
        mod.register = lambda ctx: None
        adapter = wrap_legacy_plugin(mod)
        assert adapter.name == "omni_custom"

    def test_wrap_reads_plugin_version_attribute(self) -> None:
        """读取 __plugin_version__ 属性。"""
        mod = types.ModuleType("omni_fake")
        mod.__plugin_version__ = "3.1.2"
        mod.register = lambda ctx: None
        adapter = wrap_legacy_plugin(mod)
        assert adapter.version == "3.1.2"

    def test_wrap_reads_version_attribute(self) -> None:
        """回退读取 __version__ 属性。"""
        mod = types.ModuleType("omni_fake")
        mod.__version__ = "1.5.0"
        mod.register = lambda ctx: None
        adapter = wrap_legacy_plugin(mod)
        assert adapter.version == "1.5.0"

    def test_wrap_default_version_when_missing(self) -> None:
        """无版本属性时默认 0.1.0。"""
        mod = types.ModuleType("omni_fake")
        mod.register = lambda ctx: None
        adapter = wrap_legacy_plugin(mod)
        assert adapter.version == "0.1.0"

    def test_wrap_reads_docstring_as_description(self) -> None:
        """从 __doc__ 第一行提取 description。"""
        mod = types.ModuleType("omni_fake")
        mod.__doc__ = "omni_fake：示例插件。\n\n更多详情。"
        mod.register = lambda ctx: None
        adapter = wrap_legacy_plugin(mod)
        assert adapter.description == "omni_fake：示例插件。"

    def test_wrap_reads_plugin_emoji_attribute(self) -> None:
        """读取 __plugin_emoji__ 属性。"""
        mod = types.ModuleType("omni_fake")
        mod.__plugin_emoji__ = "🚀"
        mod.register = lambda ctx: None
        adapter = wrap_legacy_plugin(mod)
        assert adapter.emoji == "🚀"

    def test_wrap_default_emoji_empty(self) -> None:
        """无 emoji 属性时默认空字符串。"""
        mod = types.ModuleType("omni_fake")
        mod.register = lambda ctx: None
        adapter = wrap_legacy_plugin(mod)
        assert adapter.emoji == ""

    def test_wrap_raises_on_missing_register(self) -> None:
        """模块缺少 register 函数时抛 ValueError。"""
        mod = types.ModuleType("omni_fake")
        with pytest.raises(ValueError, match="register"):
            wrap_legacy_plugin(mod)

    def test_wrap_raises_on_non_callable_register(self) -> None:
        """register 不是可调用对象时抛 ValueError。"""
        mod = types.ModuleType("omni_fake")
        mod.register = "not callable"
        with pytest.raises(ValueError, match="register"):
            wrap_legacy_plugin(mod)

    def test_wrap_name_from_dotted_module_name(self) -> None:
        """模块名为点分形式时取最后一段作为 name。"""
        mod = types.ModuleType("omni_brain.plugins.omni_dotted")
        mod.register = lambda ctx: None
        adapter = wrap_legacy_plugin(mod)
        assert adapter.name == "omni_dotted"

    def test_wrap_description_empty_when_no_doc(self) -> None:
        """模块无 __doc__ 时 description 为空字符串。"""
        mod = types.ModuleType("omni_fake")
        mod.register = lambda ctx: None
        adapter = wrap_legacy_plugin(mod)
        assert adapter.description == ""

    def test_wrap_description_strips_whitespace(self) -> None:
        """description 去除首尾空白。"""
        mod = types.ModuleType("omni_fake")
        mod.__doc__ = "  带空白的描述。  \n\n详情。"
        mod.register = lambda ctx: None
        adapter = wrap_legacy_plugin(mod)
        assert adapter.description == "带空白的描述。"


# ---------------------------------------------------------------------------
# 真实模块集成：omni_voice / omni_home
# ---------------------------------------------------------------------------
class TestRealModuleIntegration:
    """用真实 omni_voice / omni_home 模块验证适配层。"""

    def test_wrap_omni_voice_module(self) -> None:
        """wrap omni_voice 模块得到 name=omni_voice 的 adapter。"""
        import omni_voice

        adapter = wrap_legacy_plugin(omni_voice)
        assert adapter.name == "omni_voice"
        assert callable(adapter._register_fn)
        assert adapter.version  # 非空
        assert adapter.description  # 非空（从 docstring 第一行）

    def test_wrap_omni_home_module(self) -> None:
        """wrap omni_home 模块得到 name=omni_home 的 adapter。"""
        import omni_home

        adapter = wrap_legacy_plugin(omni_home)
        assert adapter.name == "omni_home"
        assert callable(adapter._register_fn)
        assert adapter.version
        assert adapter.description

    def test_omni_voice_adapter_loads_and_registers_tools(self) -> None:
        """omni_voice adapter on_load 后注册 7 个 voice_* 工具。"""
        from omni_voice.tools import _reset_runtime

        rt = _reset_runtime()
        try:
            import omni_voice

            adapter = wrap_legacy_plugin(omni_voice)
            tool_registry = ToolRegistry()
            ctx = _make_ctx(tool_registry=tool_registry)
            asyncio.run(adapter.on_load(ctx))

            tools = tool_registry.list_tools()
            assert "voice_status" in tools
            assert "voice_speak" in tools
            assert "voice_listen_once" in tools
            assert "voice_pipeline_start" in tools
            assert "voice_pipeline_stop" in tools
            assert "voice_config" in tools
            assert "voice_interrupt" in tools
            assert "voice_identity" in tools
            assert len(tools) == 8
        finally:
            if rt.pipeline is not None:
                rt.pipeline.stop()
                rt.pipeline = None

    def test_omni_home_adapter_loads_and_registers_tools(self) -> None:
        """omni_home adapter on_load 后注册 6 个 home_* 工具。"""
        from omni_home.tools import _reset_runtime

        _reset_runtime()
        import omni_home

        adapter = wrap_legacy_plugin(omni_home)
        tool_registry = ToolRegistry()
        ctx = _make_ctx(tool_registry=tool_registry)
        asyncio.run(adapter.on_load(ctx))

        tools = tool_registry.list_tools()
        assert "home_status" in tools
        assert "home_refresh" in tools
        assert "home_control" in tools
        assert "home_query" in tools
        assert "home_list" in tools
        assert "home_config" in tools
        assert len(tools) == 6

    def test_omni_voice_adapter_handler_returns_json(self) -> None:
        """omni_voice adapter 注册的 voice_status handler 返回 ok:true JSON。"""
        from omni_voice.tools import _reset_runtime

        rt = _reset_runtime()
        try:
            import omni_voice

            adapter = wrap_legacy_plugin(omni_voice)
            tool_registry = ToolRegistry()
            ctx = _make_ctx(tool_registry=tool_registry)
            asyncio.run(adapter.on_load(ctx))

            tool = tool_registry.get_tool("voice_status")
            assert tool is not None
            result = tool.handler_func({})
            parsed = json.loads(result)
            assert parsed["ok"] is True
            assert "data" in parsed
        finally:
            if rt.pipeline is not None:
                rt.pipeline.stop()
                rt.pipeline = None

    def test_omni_home_adapter_handler_returns_json(self) -> None:
        """omni_home adapter 注册的 home_status handler 返回 ok:true JSON。"""
        from omni_home.tools import _reset_runtime

        _reset_runtime()
        import omni_home

        adapter = wrap_legacy_plugin(omni_home)
        tool_registry = ToolRegistry()
        ctx = _make_ctx(tool_registry=tool_registry)
        asyncio.run(adapter.on_load(ctx))

        tool = tool_registry.get_tool("home_status")
        assert tool is not None
        result = tool.handler_func({})
        parsed = json.loads(result)
        assert parsed["ok"] is True


# ---------------------------------------------------------------------------
# 经 LifecycleHost 完整加载流程
# ---------------------------------------------------------------------------
class TestLifecycleHostIntegration:
    """LegacyPluginAdapter 经 LifecycleHost 完整加载/卸载流程。

    LifecycleHost 的 ``before_tools`` 快照在 ``on_load`` 之前拍摄（M15.9 修复），
    因此 LegacyPluginAdapter 在 ``on_load`` 中经 ``register(ctx)`` 注册的工具
    也能被 ``_plugin_tools`` 跟踪，卸载时正确注销。
    """

    def test_load_via_lifecycle_host(self) -> None:
        """LegacyPluginAdapter 经 LifecycleHost.load_plugin 加载，工具注册到共享 registry。"""
        from omni_sdk.lifecycle import LifecycleHost
        from omni_sdk.manifest import parse_manifest

        adapter = LegacyPluginAdapter(
            register_fn=_make_legacy_register(),
            name="omni_demo",
            version="0.1.0",
            description="演示插件",
        )
        manifest = parse_manifest({
            "name": "omni_demo",
            "version": "0.1.0",
            "description": "演示插件",
            "permissions": ["tools.register"],
            "tools": ["demo_status", "demo_ping"],
        })

        tool_registry = ToolRegistry()
        host = LifecycleHost(
            event_bus=EventBus(),
            tool_registry=tool_registry,
            permission_checker=PermissionChecker(allowed=["tools.register"]),
        )

        asyncio.run(host.load_plugin(adapter, manifest))
        assert "omni_demo" in host.list_loaded_plugins()
        # on_load 调用 register(ctx)，工具已注册到共享 tool_registry
        assert "demo_status" in tool_registry.list_tools()
        assert "demo_ping" in tool_registry.list_tools()

        asyncio.run(host.unload_plugin("omni_demo"))
        assert "omni_demo" not in host.list_loaded_plugins()
        # LifecycleHost 的 before_tools 快照在 on_load 前拍摄，
        # 因此 on_load 期间注册的工具被 _plugin_tools 跟踪，unload 时正确注销
        assert "demo_status" not in tool_registry.list_tools()
        assert "demo_ping" not in tool_registry.list_tools()
