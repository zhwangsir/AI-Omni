"""register(ctx) 兼容适配层：把旧式插件入口包装为 ``OmniPlugin`` 子类（M15.9/M15.10）。

背景：M15 之前 ``omni_voice`` / ``omni_home`` 等插件经 ``register(ctx)`` 函数挂载到
WeBrain/Hermes 插件机制（见 CLAUDE.md §二）。M15 正式化 ``OmniPlugin`` 基类后，
为避免一次性重写既有插件破坏 537+ 既有测试，提供本适配层：

- :class:`LegacyPluginAdapter`：``OmniPlugin`` 子类，构造时接收 ``register_fn``
  （或向后兼容的 ``register_func``）；``on_load(ctx)`` 构造 :class:`_LegacyCtxAdapter`
  调用 ``register_fn(adapter)``，使工具注册到 ``ctx.tool_registry``、事件总线接入
  ``_runtime.event_publisher``。支持两种构造方式：
  
  1. 直接构造：``LegacyPluginAdapter(register_fn=..., name=..., version=..., ...)``
  2. 子类化：设置类属性后 ``super().__init__(register_fn=...)``
  
- :func:`wrap_legacy_plugin`：从模块对象提取 ``register`` 函数 + 元数据
  （``__plugin_name__`` / ``__plugin_version__`` / ``__version__`` / ``__doc__`` /
  ``__plugin_emoji__``），构造 :class:`LegacyPluginAdapter`。
- :class:`_LegacyCtxAdapter`：把 :class:`PluginContext` 适配为旧式 ctx 鸭子类型——
  ``register_tool(**kwargs)`` 接受 ``toolset`` / ``handler`` 等旧参数，
  转发到 :meth:`PluginContext.register_tool`（``handler`` → ``handler_func``）。
- :class:`_LegacyEventBusAdapter`：把 :class:`EventBus` 的 async ``publish`` 适配为
  sync ``publish``（旧契约），便于既有运行时线程同步发布事件。

向后兼容别名：
- ``RegisterCompatPlugin`` = :class:`LegacyPluginAdapter`（M15.9 早期命名，保留以兼容
  既有 ``VoicePlugin`` / ``HomePlugin`` 子类）
- ``_LegacyContextAdapter`` = :class:`_LegacyCtxAdapter`（规范命名别名）

迁移期间 ``register(ctx)`` 入口保持原状可独立调用，本适配层只在 ``OmniPlugin`` 装载
路径上激活。参考 AGENTS.md §7 / CLAUDE.md §2.1。
"""

from __future__ import annotations

import asyncio
import logging
from types import ModuleType
from typing import TYPE_CHECKING, Any, Callable

from omni_sdk.event_bus import EventBus
from omni_sdk.plugin import OmniPlugin

if TYPE_CHECKING:
    from omni_sdk.context import PluginContext


class _LegacyEventBusAdapter:
    """把 async :class:`EventBus` 适配为 sync ``publish`` 接口（旧契约）。

    旧式 ``register(ctx)`` 把 ``ctx.event_bus`` 赋给 ``_runtime.event_publisher``，
    运行时线程随后调用 ``bus.publish(event_type, payload)`` 同步发布事件。
    本适配器把 sync 调用桥接到 :meth:`EventBus.publish` 的协程：
    - 若当前线程有运行中的事件循环，``create_task`` 调度（非阻塞）
    - 否则用 :func:`asyncio.run` 同步执行（阻塞至完成）
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """同步发布事件：调度到运行中的事件循环，或新建循环跑一次。"""
        coro = self._bus.publish(event_type, payload)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            # 当前线程无运行中的事件循环，同步执行
            asyncio.run(coro)

    def subscribe(self, event_type: str, callback: Callable[[dict[str, Any]], Any]) -> str:
        """订阅事件，委托 :meth:`EventBus.subscribe`。"""
        return self._bus.subscribe(event_type, callback)

    def unsubscribe(self, sub_id: str) -> bool:
        """取消订阅，委托 :meth:`EventBus.unsubscribe`。"""
        return self._bus.unsubscribe(sub_id)


class _LegacyCtxAdapter:
    """把 :class:`PluginContext` 适配为旧式 ``register(ctx)`` 契约的 ctx 鸭子类型。

    旧式 ctx 接口（见 CLAUDE.md §二）：
    - ``register_tool(name=, toolset=, schema=, handler=, description=, emoji=)``
    - ``event_bus`` 属性携带 sync ``publish(event_type, payload)`` 方法

    新式 :class:`PluginContext`：
    - ``register_tool(name, description, emoji, schema, handler_func)``
    - ``event_bus`` 为 :class:`EventBus`（async publish）

    本适配器做参数翻译：``handler`` → ``handler_func``，``toolset`` 丢弃
    （新 :class:`ToolRegistry` 不区分 toolset），其余字段一一对应。
    """

    def __init__(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        # event_bus 适配为 sync publish；若 ctx 无 event_bus 则保持 None（旧契约兼容）
        self.event_bus: _LegacyEventBusAdapter | None = (
            _LegacyEventBusAdapter(ctx.event_bus) if ctx.event_bus is not None else None
        )

    def register_tool(self, **kwargs: Any) -> None:
        """旧式 register_tool 签名转新式 PluginContext.register_tool。

        :param kwargs: 旧式参数 ``name`` / ``toolset`` / ``schema`` / ``handler`` /
            ``description`` / ``emoji``；``handler`` 映射到新式 ``handler_func``；
            额外 kwargs（如 ``toolset``）静默丢弃
        """
        # handler 旧参数 → handler_func 新参数；优先 handler_func（双兼容）
        handler = kwargs.get("handler_func", kwargs.get("handler"))
        self._ctx.register_tool(
            name=kwargs["name"],
            description=kwargs.get("description", ""),
            emoji=kwargs.get("emoji", ""),
            schema=kwargs.get("schema", {}),
            handler_func=handler,
        )


# 规范命名别名（供外部 import 使用更直观的名称）
_LegacyContextAdapter = _LegacyCtxAdapter


class LegacyPluginAdapter(OmniPlugin):
    """把 ``register(ctx)`` 函数包装为 ``OmniPlugin`` 子类的适配基类。

    用法一（直接构造）::

        adapter = LegacyPluginAdapter(
            register_fn=register,
            name="omni_voice",
            version="0.1.0",
            description="语音插件",
            emoji="🎙️",
        )

    用法二（子类化，元数据作为类属性）::

        class VoicePlugin(LegacyPluginAdapter):
            name = "omni_voice"
            version = "0.1.0"
            description = "语音插件"
            emoji = "🎙️"

            def __init__(self) -> None:
                super().__init__(register_fn=register)

    ``on_load(ctx)`` 构造 :class:`_LegacyCtxAdapter` 调用 ``register_fn(adapter)``，
    使既有 ``register(ctx)`` 实现将工具注册到 ``ctx.tool_registry``，
    事件总线经 :class:`_LegacyEventBusAdapter` 接入运行时 ``event_publisher``。

    :param register_fn: 旧式 ``register(ctx)`` 函数，签名 ``(ctx) -> None``
    :param register_func: ``register_fn`` 的向后兼容别名（等价）
    :param name: 可选，覆盖类属性 ``name``
    :param version: 可选，覆盖类属性 ``version``
    :param description: 可选，覆盖类属性 ``description``
    :param emoji: 可选，覆盖类属性 ``emoji``
    """

    def __init__(
        self,
        register_fn: Callable[[Any], None] | None = None,
        *,
        register_func: Callable[[Any], None] | None = None,
        name: str | None = None,
        version: str | None = None,
        description: str | None = None,
        emoji: str | None = None,
    ) -> None:
        """构造兼容适配插件。

        :param register_fn: 旧式 ``register(ctx)`` 函数（规范命名）
        :param register_func: ``register_fn`` 的兼容别名（等价；优先级低于 ``register_fn``）
        :param name: 可选，覆盖类属性 ``name``
        :param version: 可选，覆盖类属性 ``version``
        :param description: 可选，覆盖类属性 ``description``
        :param emoji: 可选，覆盖类属性 ``emoji``
        :raises ValueError: 未提供 ``register_fn`` 或 ``register_func``
        """
        # register_fn 优先；回退到 register_func（向后兼容 RegisterCompatPlugin 旧名）
        func = register_fn if register_fn is not None else register_func
        if func is None:
            raise ValueError(
                "LegacyPluginAdapter 必须提供 register_fn 或 register_func 参数"
            )
        # 双名存储：_register_func（兼容旧代码）/ _register_fn（规范命名）
        self._register_func: Callable[[Any], None] = func
        self._register_fn: Callable[[Any], None] = func
        # 元数据覆盖（None 时沿用类属性默认值）
        if name is not None:
            self.name = name
        if version is not None:
            self.version = version
        if description is not None:
            self.description = description
        if emoji is not None:
            self.emoji = emoji
        # logger 在子类按 name 命名空间构造
        self._logger: logging.Logger = logging.getLogger(f"omni.{self.name}")

    async def on_load(self, ctx: PluginContext) -> None:
        """构造 legacy ctx 适配器并调用 ``register_fn(adapter)``。

        :param ctx: PluginContext，由 LifecycleHost 注入
        """
        adapter = _LegacyCtxAdapter(ctx)
        self._register_func(adapter)
        self._logger.info("兼容适配插件 %s 已通过 register(ctx) 注册工具", self.name)

    def register_tools(self, ctx: PluginContext) -> None:
        """工具注册已在 :meth:`on_load` 中经 ``register(ctx)`` 完成，此处空实现避免重复。

        LifecycleHost 在 ``on_load`` 之后调用 ``register_tools``；若此处再调
        ``register(ctx)`` 会重复注册同名工具（虽然 ToolRegistry 同名覆盖语义安全，
        但会产生多余日志与潜在副作用），故显式空实现。
        """
        return None


# 向后兼容别名：M15.9 早期使用 RegisterCompatPlugin 命名，保留以兼容既有子类
RegisterCompatPlugin = LegacyPluginAdapter


def wrap_legacy_plugin(module: ModuleType) -> LegacyPluginAdapter:
    """从模块对象提取 ``register`` 函数 + 元数据，构造 :class:`LegacyPluginAdapter`。

    元数据读取优先级：
    - ``name``：``__plugin_name__`` → 模块名最后一段（``omni_voice`` from ``omni_voice``）
    - ``version``：``__plugin_version__`` → ``__version__`` → ``"0.1.0"``
    - ``description``：``__doc__`` 第一行（已 strip）
    - ``emoji``：``__plugin_emoji__`` → ``""``

    :param module: 已 import 的模块对象，必须暴露 ``register(ctx)`` 函数
    :return: :class:`LegacyPluginAdapter` 实例
    :raises ValueError: 模块缺少 ``register`` 属性或该属性不可调用
    """
    register_fn = getattr(module, "register", None)
    if not callable(register_fn):
        raise ValueError(
            f"模块 {getattr(module, '__name__', '?')} 缺少可调用的 register(ctx) 函数"
        )

    # name: 优先 __plugin_name__，否则取模块名最后一段
    name = getattr(module, "__plugin_name__", None)
    if not name:
        mod_name = getattr(module, "__name__", "")
        name = mod_name.split(".")[-1] if mod_name else "omni_unknown"

    # version: 优先 __plugin_version__，回退 __version__，再回退 "0.1.0"
    version = (
        getattr(module, "__plugin_version__", None)
        or getattr(module, "__version__", None)
        or "0.1.0"
    )

    # description: __doc__ 第一行（去除首尾空白）
    doc = (getattr(module, "__doc__", None) or "").strip()
    description = doc.split("\n", 1)[0].strip() if doc else ""

    # emoji: __plugin_emoji__
    emoji = getattr(module, "__plugin_emoji__", "") or ""

    return LegacyPluginAdapter(
        register_fn=register_fn,
        name=name,
        version=version,
        description=description,
        emoji=emoji,
    )
