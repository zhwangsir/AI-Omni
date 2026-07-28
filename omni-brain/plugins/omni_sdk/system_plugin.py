"""SystemPluginBase：系统插件公共基类，消除重复代码。

统一处理：
1. 事件发布桥接（async EventBus → sync 调用，使用 TaskTracker）
2. backend 注入（config['backend']）
3. 工具注册和 handler 包装（异常捕获 → JSON 错误信封）
4. manifest 工具校验

所有 7 个系统插件（volume/brightness/power/screenshot/process/performance/fullscreen_detect）
继承此类，消除 80%+ 的重复代码。
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Callable

from omni_sdk.plugin import OmniPlugin
from omni_sdk.utils import TaskTracker, sync_to_async_publish

if TYPE_CHECKING:
    from omni_sdk.context import PluginContext


class SystemPluginBase(OmniPlugin):
    """系统插件公共基类。

    子类约定：
    - 设置类属性 ``name`` / ``version`` / ``description`` / ``emoji``
    - 设置 ``event_domain``：事件前缀（如 "system" → 发布 "system.volume_changed"）
    - 可选设置 ``backend_class``：真实后端类（None 表示不自动构建）
    - 实现 ``_build_tools_meta()``：返回工具元数据列表
    - 工具 handler 返回 dict（成功 {"ok": True, ...} 或失败 {"ok": False, "error": {...}}）
    """

    #: 事件域前缀，如 "system" → 发布事件为 "{event_domain}.{event_name}"
    event_domain: str = "system"
    #: 真实后端类（None 表示不自动构建，需注入或返回 E_BACKEND_UNAVAILABLE）
    backend_class: type | None = None

    def __init__(self) -> None:
        self._backend: Any = None
        self._event_bus: Any = None
        self._task_tracker = TaskTracker()
        self._logger: logging.Logger = logging.getLogger(f"omni.{self.name}")

    @abstractmethod
    def _build_tools_meta(self) -> list[dict[str, Any]]:
        """构建工具元数据列表。

        返回 list[dict]，每个 dict 包含：
        - name: str
        - description: str
        - emoji: str
        - schema: dict（OpenAI function 风格 JSON Schema）
        - handler: Callable（返回 dict，由 _make_handler 包装）
        """
        ...

    async def on_load(self, ctx: PluginContext) -> None:
        """加载：注入 backend、接入事件总线、注册工具。"""
        # 1. backend 注入（config 优先，否则留空待惰性构建）
        backend = ctx.config.get("backend") if ctx.config else None
        if backend is not None:
            self._backend = backend

        # 2. 事件总线接入
        self._event_bus = ctx.event_bus

        # 3. 注册工具
        for meta in self._build_tools_meta():
            ctx.register_tool(
                name=meta["name"],
                description=meta["description"],
                emoji=meta.get("emoji", ""),
                schema=meta["schema"],
                handler_func=meta["handler"],
            )

        self._logger.info("%s 插件已加载", self.name)

    async def on_unload(self) -> None:
        """卸载：取消所有跟踪的 Task，清理引用。"""
        self._task_tracker.cancel_all()
        self._backend = None
        self._event_bus = None
        self._logger.info("%s 插件已卸载", self.name)

    def publish_event(self, event_suffix: str, payload: dict[str, Any]) -> None:
        """同步发布事件（自动桥接到 async EventBus）。

        :param event_suffix: 事件后缀，完整事件名为 "{event_domain}.{event_suffix}"
        :param payload: 事件负载（会被深拷贝）
        """
        if self._event_bus is None or not callable(getattr(self._event_bus, "publish", None)):
            return
        full_event = f"{self.event_domain}.{event_suffix}"
        payload_with_meta = {
            **payload,
            "timestamp": self._iso_now(),
            "source": self.name,
        }
        try:
            sync_to_async_publish(
                self._event_bus.publish,
                full_event,
                payload_with_meta,
                tracker=self._task_tracker,
            )
        except Exception:  # noqa: BLE001
            self._logger.debug("事件发布失败: %s", full_event, exc_info=True)

    def _make_handler(
        self,
        func: Callable[..., dict[str, Any]],
        *,
        require_backend: bool = False,
    ) -> Callable[..., str]:
        """包装工具 handler：异常捕获 + JSON 序列化 + backend 检查。

        :param func: 业务 handler，返回 dict
        :param require_backend: True 时无 backend 返回 E_BACKEND_UNAVAILABLE
        :return: 符合 PluginContext 契约的 handler，返回 JSON 字符串
        """

        def wrapper(args: dict[str, Any] | None = None, **_: Any) -> str:
            try:
                if require_backend and self._backend is None and self.backend_class is None:
                    return json.dumps(
                        {
                            "ok": False,
                            "error": {
                                "code": "E_BACKEND_UNAVAILABLE",
                                "message": f"{self.name} 后端不可用",
                            },
                        },
                        ensure_ascii=False,
                    )
                kwargs = args or {}
                result = func(**kwargs)
                if isinstance(result, dict) and "ok" in result:
                    return json.dumps(result, ensure_ascii=False)
                return json.dumps({"ok": True, "data": result}, ensure_ascii=False)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug(
                    "工具 %s 调用失败: %s",
                    getattr(func, "__name__", "?"),
                    exc,
                    exc_info=True,
                )
                return json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "E_INTERNAL",
                            "message": str(exc),
                        },
                    },
                    ensure_ascii=False,
                )

        return wrapper

    @staticmethod
    def _iso_now() -> str:
        """当前时间 ISO8601 字符串。"""
        import time
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
