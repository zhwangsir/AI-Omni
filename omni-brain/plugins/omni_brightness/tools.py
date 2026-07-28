"""omni_brightness 工具实现：2 个 system_* 工具与 register(ctx) 注册入口。

工具统一返回 JSON 字符串 ``{"ok": bool, "data": ..., "error": ...}``：

- ``system_set_brightness``  ：设置屏幕亮度 0-100
- ``system_get_brightness``  ：查询当前屏幕亮度

进程内 :class:`Runtime` 单例持有后端实例与事件发布器；
所有工具接受 ``fake=True`` 使用 FakeBrightnessBackend（测试/演示，无需 macOS）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from .backends import FakeBrightnessBackend, MacBrightnessBackend

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 运行时单例
# ---------------------------------------------------------------------------
class Runtime:
    """进程内运行时：持有后端实例、fake 模式标记与事件发布器。"""

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
    """取后端实例；未预置时按 fake/真实构建并缓存。"""
    if fake:
        rt.fake_mode = True
    if rt.backend is not None:
        return rt.backend
    if fake:
        rt.backend = FakeBrightnessBackend()
    else:
        rt.backend = MacBrightnessBackend()
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
        if asyncio.iscoroutine(result):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(result)
            except RuntimeError:
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
# Tool 1：设置亮度
# ---------------------------------------------------------------------------
@tool(
    name="system_set_brightness",
    description="设置屏幕亮度，level 取值 0-100，0 为最暗，100 为最亮。",
    parameters={
        "level": {
            "type": "integer",
            "description": "亮度百分比 0-100（整数），macOS brightness CLI 映射为 0-1 浮点。",
            "minimum": 0,
            "maximum": 100,
        },
        "fake": _FAKE_PARAM,
    },
    required=["level"],
    emoji="🔆",
)
def system_set_brightness(level: int, fake: bool = False) -> str:
    """设置屏幕亮度；返回新亮度。"""
    try:
        rt = _runtime
        result = _backend(rt, fake).set_brightness(level)
        if result.get("ok"):
            payload = {"brightness": result["brightness"]}
            _publish(rt, "system.brightness_changed", {"action": "set", **payload})
            return _ok(payload)
        err = result.get("error", {})
        return _err(err.get("message", "设置亮度失败"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("system_set_brightness 失败: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 2：查询亮度
# ---------------------------------------------------------------------------
@tool(
    name="system_get_brightness",
    description="查询当前屏幕亮度（0-100）。",
    parameters={"fake": _FAKE_PARAM},
    emoji="💡",
)
def system_get_brightness(fake: bool = False) -> str:
    """返回当前亮度。"""
    try:
        rt = _runtime
        result = _backend(rt, fake).get_brightness()
        if result.get("ok"):
            return _ok({"brightness": result["brightness"]})
        err = result.get("error", {})
        return _err(err.get("message", "查询亮度失败"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("system_get_brightness 失败: %s", exc)
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
            logger.debug("brightness tool %s 调用失败: %s", getattr(func, "__name__", "?"), exc)
            return _err(str(exc))

    return handler


def register(ctx) -> None:
    """把 2 个 system_* tools 注册到插件上下文；若 ctx 携带事件总线则接入。

    使用 M15 新式 ``ctx.register_tool(name, description, emoji, schema, handler_func)`` 签名。
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
    logger.info("omni_brightness 插件已注册 %d 个 tools", len(TOOLS))
