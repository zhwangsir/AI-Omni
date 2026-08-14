"""omni_office：办公自动化插件（文档 / 邮件 / 日程 + 跨模块工作流）。

直接继承 ``OmniPlugin``（M15 SDK），在 ``on_load(ctx)`` 中把 19 个 ``office_*``
与 4 个 ``schedule_*``（M34.2 移动端日程桥接）工具注册到 ``ctx.tool_registry``，
按 ``ctx.config["db_path"]`` 打开 SQLite 库
（缺省 ``~/.ai-omni/office/office.db``，env ``AI_OMNI_OFFICE_DB`` 可覆盖），
并接入事件总线（发布 ``office.doc_created`` / ``office.email_sent`` /
``office.event_created`` / ``office.workflow_completed`` 等）。

工具清单：
- 文档：``office_doc_create`` / ``office_doc_update`` / ``office_doc_get`` /
  ``office_doc_list`` / ``office_doc_versions`` / ``office_doc_rollback``
- 邮件：``office_email_send`` / ``office_email_inbox`` / ``office_email_mark_read`` /
  ``office_email_template_save`` / ``office_email_template_list`` /
  ``office_email_auto_reply`` / ``office_email_process_inbox``
- 日程：``office_event_create`` / ``office_event_list`` /
  ``office_event_reminders`` / ``office_event_check_conflicts``
- 工作流：``office_meeting_prep`` / ``office_status``
- 移动端桥接：``schedule_list_events`` / ``schedule_create_event`` /
  ``schedule_update_event`` / ``schedule_delete_event``

无重型依赖（SQLite 走标准库）；SMTP/IMAP 仅在真实发送时惰性导入，
测试全用 FakeEmailBackend，不访问真实网络。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from omni_sdk.plugin import OmniPlugin

if TYPE_CHECKING:
    from omni_sdk.context import PluginContext

__all__ = ["OfficePlugin", "register"]


logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """旧式 register(ctx) 入口：注册 19 个 office_* 工具到上下文。

    保留此函数用于向后兼容与外部直接调用；
    ``OfficePlugin.on_load`` 内部也复用本函数完成工具注册。
    """
    from .tools import register as _register

    _register(ctx)


class OfficePlugin(OmniPlugin):
    """omni_office 的 ``OmniPlugin`` 子类。

    ``on_load(ctx)`` 调用 ``register(ctx)`` 把 19 个 office_* 工具注册到
    ``ctx.tool_registry``，按 config 打开 SQLite 库并建表，把事件总线接入
    运行时（供发布 ``office.*`` 事件）。
    """

    name: str = "omni_office"
    version: str = "0.1.0"
    description: str = (
        "办公自动化：文档版本管理 / 邮件收发与自动回复 / "
        "日程冲突检测与提醒 / 会议准备跨模块工作流"
    )
    emoji: str = "🗂️"

    def __init__(self) -> None:
        self._logger: logging.Logger = logging.getLogger(f"omni.{self.name}")

    async def on_load(self, ctx: PluginContext) -> None:
        """注册 19 个 office_* 工具，打开 db，接入事件总线。

        :param ctx: PluginContext，由 LifecycleHost 注入；
            ``ctx.config["db_path"]`` 可指定库路径（如 ``:memory:``）
        """
        register(ctx)
        from . import tools
        from .db import OfficeDB, default_db_path

        db_path = ctx.config.get("db_path") or str(default_db_path())
        tools._runtime.db = OfficeDB(db_path)
        tools._runtime.db.init_schema()

        bus = getattr(ctx, "event_bus", None)
        if bus is not None and callable(getattr(bus, "publish", None)):
            tools._runtime.event_publisher = bus
        self._logger.info("omni_office 插件已加载，注册 %d 个工具", len(tools.TOOLS))

    async def on_unload(self) -> None:
        """关闭 db 并清空运行时引用（幂等）。"""
        from . import tools

        try:
            if tools._runtime.db is not None:
                tools._runtime.db.close()
            tools._runtime.event_publisher = None
        except Exception:  # noqa: BLE001
            self._logger.debug("omni_office on_unload 清理异常", exc_info=True)
        self._logger.info("omni_office 插件已卸载")

    async def on_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """事件路由；当前 omni_office 不订阅外部事件，默认空实现。"""
        return None
