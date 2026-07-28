"""omni_volume 工具实现：4 个 system_* 工具与 register(ctx) 注册入口。

工具统一返回 JSON 字符串 ``{"ok": bool, "data": ..., "error": ...}``：

- ``system_set_volume``  ：设置音量 0-100
- ``system_get_volume``  ：查询当前音量与静音状态
- ``system_mute``        ：静音
- ``system_unmute``      ：取消静音

进程内 :class:`Runtime` 单例持有后端实例与事件发布器；
所有工具接受 ``fake=True`` 使用 FakeVolumeBackend（测试/演示，无需 macOS）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from .backends import FakeVolumeBackend, MacVolumeBackend

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 运行时单例
# ---------------------------------------------------------------------------
class Runtime:
    """进程内运行时：持有后端实例、fake 模式标记与事件发布器。

    ``backend`` 可由测试/CLI 预置为脚本化 fake 后端；
    ``fake_mode`` 标记当前是否处于 fake 模式（影响 ``system_status`` 上报）。
    """

    def __init__(self) -> None:
        self.backend: Any = None
        self.fake_mode: bool = False
        self.event_publisher: Any = None


_runtime = Runtime()


def _reset_runtime(runtime: Runtime | None = None) -> Runtime:
    """替换进程内运行时（测试隔离用），返回新实例。"""
    global _runtime
    _runtime = runtime or Runtime()
    return _runtime


# ---------------------------------------------------------------------------
# 后端选择
# ---------------------------------------------------------------------------
def _backend(rt: Runtime, fake: bool) -> Any:
    """取后端实例；未预置时按 fake/真实构建并缓存。

    :param rt: 运行时单例
    :param fake: True 使用 FakeVolumeBackend；False 使用 MacVolumeBackend
    """
    if fake:
        rt.fake_mode = True
    if rt.backend is not None:
        return rt.backend
    if fake:
        rt.backend = FakeVolumeBackend()
    else:
        rt.backend = MacVolumeBackend()
    return rt.backend


# ---------------------------------------------------------------------------
# JSON 响应约定
# ---------------------------------------------------------------------------
def _ok(data: Any) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False)


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _publish(rt: Runtime, event_type: str, payload: dict[str, Any]) -> None:
    """向事件总线发布事件（未接入总线时静默跳过）。

    兼容同步 publish（鸭子类型旧式 ctx）与 async publish（omni_sdk.EventBus）：
    若 ``bus.publish`` 返回 coroutine，按运行中事件循环情况调度或同步执行。
    """
    bus = rt.event_publisher
    if bus is None or not callable(getattr(bus, "publish", None)):
        return
    try:
        result = bus.publish(event_type, payload)
        # omni_sdk.EventBus.publish 是 async 方法，返回 coroutine
        if asyncio.iscoroutine(result):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(result)
            except RuntimeError:
                # 当前线程无运行中的事件循环，同步执行
                asyncio.run(result)
    except Exception:  # noqa: BLE001 - 总线异常不应拖垮控制结果
        logger.debug("事件发布失败: %s", event_type)


# ---------------------------------------------------------------------------
# Tool 元数据注册表
# ---------------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = []


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    required: list[str] | None = None,
    emoji: str = "",
) -> Callable:
    """@tool 装饰器：为函数附加 tool schema 元数据并登记到 TOOLS。"""

    def decorator(func: Callable) -> Callable:
        TOOLS.append(
            {
                "name": name,
                "description": description,
                "emoji": emoji,
                "schema": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": parameters,
                        "required": list(required or []),
                    },
                },
                "handler_func": func,
            }
        )
        return func

    return decorator


_FAKE_PARAM = {
    "type": "boolean",
    "description": "为 true 时使用 fake 后端（演示/测试，不执行真实系统命令）。",
}


# ---------------------------------------------------------------------------
# Tool 1：设置音量
# ---------------------------------------------------------------------------
@tool(
    name="system_set_volume",
    description="设置系统音量，level 取值 0-100，0 为静音，100 为最大音量。",
    parameters={
        "level": {
            "type": "integer",
            "description": "音量百分比 0-100（整数），macOS 内部映射为 0-7 刻度。",
            "minimum": 0,
            "maximum": 100,
        },
        "fake": _FAKE_PARAM,
    },
    required=["level"],
    emoji="🔊",
)
def system_set_volume(level: int, fake: bool = False) -> str:
    """设置系统音量；返回新音量与静音状态。"""
    try:
        rt = _runtime
        result = _backend(rt, fake).set_volume(level)
        if result.get("ok"):
            payload = {"volume": result["volume"], "muted": result["muted"]}
            _publish(rt, "system.volume_changed", {"action": "set", **payload})
            return _ok(payload)
        err = result.get("error", {})
        return _err(err.get("message", "设置音量失败"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("system_set_volume 失败: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 2：查询音量
# ---------------------------------------------------------------------------
@tool(
    name="system_get_volume",
    description="查询当前系统音量（0-100）与静音状态。",
    parameters={"fake": _FAKE_PARAM},
    emoji="🎚️",
)
def system_get_volume(fake: bool = False) -> str:
    """返回当前音量与静音状态。"""
    try:
        rt = _runtime
        result = _backend(rt, fake).get_volume()
        if result.get("ok"):
            return _ok({"volume": result["volume"], "muted": result["muted"]})
        err = result.get("error", {})
        return _err(err.get("message", "查询音量失败"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("system_get_volume 失败: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 3：静音
# ---------------------------------------------------------------------------
@tool(
    name="system_mute",
    description="静音系统输出（保留当前音量值，仅切换静音状态）。",
    parameters={"fake": _FAKE_PARAM},
    emoji="🔇",
)
def system_mute(fake: bool = False) -> str:
    """静音；返回当前音量与 muted=True。"""
    try:
        rt = _runtime
        result = _backend(rt, fake).mute()
        if result.get("ok"):
            payload = {"volume": result["volume"], "muted": True}
            _publish(rt, "system.volume_changed", {"action": "mute", **payload})
            return _ok(payload)
        err = result.get("error", {})
        return _err(err.get("message", "静音失败"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("system_mute 失败: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 4：取消静音
# ---------------------------------------------------------------------------
@tool(
    name="system_unmute",
    description="取消静音（恢复到静音前的音量值）。",
    parameters={"fake": _FAKE_PARAM},
    emoji="🔈",
)
def system_unmute(fake: bool = False) -> str:
    """取消静音；返回当前音量与 muted=False。"""
    try:
        rt = _runtime
        result = _backend(rt, fake).unmute()
        if result.get("ok"):
            payload = {"volume": result["volume"], "muted": False}
            _publish(rt, "system.volume_changed", {"action": "unmute", **payload})
            return _ok(payload)
        err = result.get("error", {})
        return _err(err.get("message", "取消静音失败"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("system_unmute 失败: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# 注册（对齐 WeBrain 插件契约：ctx.register_tool + 可选事件总线接入）
# ---------------------------------------------------------------------------
def _make_handler(func: Callable) -> Callable:
    """把工具函数适配为 registry handler：``(args: dict, **kw) -> JSON 字符串``。"""

    def handler(args: dict[str, Any], **_: Any) -> str:
        try:
            return func(**(args or {}))
        except Exception as exc:  # 参数错误等，统一为 ok:false
            logger.debug("volume tool %s 调用失败: %s", getattr(func, "__name__", "?"), exc)
            return _err(str(exc))

    return handler


def register(ctx) -> None:
    """把 4 个 system_* tools 注册到插件上下文；若 ctx 携带事件总线则接入。

    使用 M15 新式 ``ctx.register_tool(name, description, emoji, schema, handler_func)``
    签名（不传 ``toolset`` / ``handler`` 旧式参数），兼容 :class:`PluginContext`
    与鸭子类型的旧式 ctx（旧式 ctx 通常也接受这些参数）。
    """
    for meta in TOOLS:
        ctx.register_tool(
            name=meta["name"],
            description=meta["description"],
            emoji=meta["emoji"],
            schema=meta["schema"],
            handler_func=_make_handler(meta["handler_func"]),
        )
    bus = getattr(ctx, "event_bus", None)
    if bus is not None and callable(getattr(bus, "publish", None)):
        _runtime.event_publisher = bus
    logger.info("omni_volume 插件已注册 %d 个 tools", len(TOOLS))
