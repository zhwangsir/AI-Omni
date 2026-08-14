"""omni_office 工具实现：20 个 ``office_*`` 工具。

工具清单：
- 文档：``office_doc_create`` / ``office_doc_update`` / ``office_doc_get`` /
  ``office_doc_list`` / ``office_doc_versions`` / ``office_doc_rollback``
- 邮件：``office_email_send`` / ``office_email_inbox`` / ``office_email_mark_read`` /
  ``office_email_template_save`` / ``office_email_template_list`` /
  ``office_email_auto_reply`` / ``office_email_process_inbox``
- 日程：``office_event_create`` / ``office_event_list`` /
  ``office_event_reminders`` / ``office_event_check_conflicts``
- 工作流：``office_meeting_prep`` / ``office_email_to_event`` / ``office_status``

工具统一返回 JSON 字符串 ``{"ok": true, "data": ...}`` /
``{"ok": false, "error": {"code": "E_XXX", "message": "..."}}``。

领域异常 → 错误码映射：
``OfficeValidationError`` → E_INVALID_PARAMS；``OfficeNotFoundError`` → E_NOT_FOUND；
``OfficeConflictError`` → E_EVENT_CONFLICT；``OfficeTemplateError`` → E_TEMPLATE_ERROR；
``OfficeBackendError`` → E_BACKEND_UNAVAILABLE；其他未预期异常 → E_INTERNAL。

事件总线发布：``office.doc_created`` / ``office.doc_updated`` /
``office.email_sent`` / ``office.email_auto_replied`` / ``office.event_created`` /
``office.event_reminder`` / ``office.workflow_completed``。

库路径默认 ``~/.ai-omni/office/office.db``（env ``AI_OMNI_OFFICE_DB`` 可覆盖）；
运行时 ``db`` 未注入时按默认路径惰性打开。邮件后端未注入时按
``use_fake_backends`` 标志选择 Fake / SMTP（SMTP 未配置 → E_BACKEND_UNAVAILABLE）。
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
from typing import Any, Callable

from .backends import FakeEmailBackend, SmtpEmailBackend
from .db import OfficeDB, default_db_path
from .documents import DocumentManager
from .emails import EmailManager
from .errors import (
    OfficeBackendError,
    OfficeConflictError,
    OfficeError,
    OfficeNotFoundError,
    OfficeTemplateError,
    OfficeValidationError,
)
from .events import CalendarManager
from .workflows import OfficeWorkflows

try:
    from omni_sdk.utils import TaskTracker

    _HAS_TASK_TRACKER = True
except ImportError:
    _HAS_TASK_TRACKER = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 运行时单例
# ---------------------------------------------------------------------------
class Runtime:
    """进程内运行时：持有 db 连接、邮件后端、事件发布器。

    ``db`` 为 ``None`` 时，首个工具调用按 :func:`default_db_path` 惰性打开；
    测试与插件 ``on_load`` 可显式注入（如 ``:memory:``）。
    """

    def __init__(self) -> None:
        self.db: OfficeDB | None = None
        self.email_backend: Any = None
        self.event_publisher: Any = None
        self.use_fake_backends: bool = False
        self.task_tracker: Any = TaskTracker() if _HAS_TASK_TRACKER else None


_runtime = Runtime()


def _reset_runtime(runtime: Runtime | None = None) -> Runtime:
    """替换进程内运行时（测试隔离用），返回新实例。"""
    global _runtime
    _runtime = runtime or Runtime()
    return _runtime


def _get_db(rt: Runtime) -> OfficeDB:
    """取 db；未注入时按默认路径惰性打开并建表。"""
    if rt.db is None:
        rt.db = OfficeDB(default_db_path())
        rt.db.init_schema()
    return rt.db


def _get_backend(rt: Runtime) -> Any:
    """取邮件后端；未注入时按 use_fake_backends 标志创建。"""
    if rt.email_backend is None:
        rt.email_backend = (
            FakeEmailBackend() if rt.use_fake_backends else SmtpEmailBackend()
        )
    return rt.email_backend


def _documents(rt: Runtime) -> DocumentManager:
    return DocumentManager(_get_db(rt))


def _emails(rt: Runtime) -> EmailManager:
    return EmailManager(_get_db(rt), _get_backend(rt))


def _calendar(rt: Runtime) -> CalendarManager:
    return CalendarManager(_get_db(rt))


def _workflows(rt: Runtime) -> OfficeWorkflows:
    db = _get_db(rt)
    return OfficeWorkflows(
        db=db,
        documents=DocumentManager(db),
        emails=EmailManager(db, _get_backend(rt)),
        calendar=CalendarManager(db),
    )


# ---------------------------------------------------------------------------
# JSON 响应约定
# ---------------------------------------------------------------------------
def _ok(data: Any) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False)


def _err(code: str, message: str) -> str:
    return json.dumps(
        {"ok": False, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )


#: 领域异常 → 错误码
_ERROR_CODES: tuple[tuple[type[OfficeError], str], ...] = (
    (OfficeValidationError, "E_INVALID_PARAMS"),
    (OfficeNotFoundError, "E_NOT_FOUND"),
    (OfficeConflictError, "E_EVENT_CONFLICT"),
    (OfficeTemplateError, "E_TEMPLATE_ERROR"),
    (OfficeBackendError, "E_BACKEND_UNAVAILABLE"),
)


def _guard(func: Callable) -> Callable:
    """把领域异常映射为错误信封；未预期异常兜底 E_INTERNAL。"""

    @functools.wraps(func)
    def wrapper(**kwargs: Any) -> str:
        try:
            return func(**kwargs)
        except OfficeError as exc:
            code = next(
                (c for cls, c in _ERROR_CODES if isinstance(exc, cls)), "E_INTERNAL"
            )
            return _err(code, str(exc))
        except Exception as exc:  # noqa: BLE001 - 工具边界不允许抛异常
            logger.debug("office tool %s 未预期异常", func.__name__, exc_info=True)
            return _err("E_INTERNAL", str(exc))

    return wrapper


def _publish(rt: Runtime, event_type: str, payload: dict[str, Any]) -> None:
    """向事件总线发布事件（未接入总线时静默跳过）。

    兼容同步 publish 与 async publish（omni_sdk.EventBus）；
    总线异常不拖垮工具调用。
    """
    bus = rt.event_publisher
    if bus is None or not callable(getattr(bus, "publish", None)):
        return
    import copy

    payload_snapshot = copy.deepcopy(payload)
    try:
        result = bus.publish(event_type, payload_snapshot)
        if asyncio.iscoroutine(result):
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(result)
                if rt.task_tracker is not None and hasattr(rt.task_tracker, "add"):
                    rt.task_tracker.add(task)
            except RuntimeError:
                asyncio.run(result)
    except Exception:  # noqa: BLE001
        logger.debug("事件发布失败: %s", event_type, exc_info=True)


# ---------------------------------------------------------------------------
# 工具元数据注册表
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


_STR = {"type": "string"}
_TIME = {
    "type": ["string", "number"],
    "description": "ISO8601 字符串（naive 按本地时区）或 epoch 秒。",
}
_STR_LIST = {"type": "array", "items": {"type": "string"}}
_BOOL = {"type": "boolean"}


# ---------------------------------------------------------------------------
# 文档工具
# ---------------------------------------------------------------------------
@tool(
    name="office_doc_create",
    description="创建文档（初始版本 v1）；标题非空，支持标签。",
    parameters={
        "title": _STR,
        "content": _STR,
        "tags": _STR_LIST,
    },
    required=["title"],
    emoji="📄",
)
@_guard
def office_doc_create(
    title: str, content: str = "", tags: list[str] | None = None
) -> str:
    rt = _runtime
    doc = _documents(rt).create(title=title, content=content, tags=tags)
    _publish(rt, "office.doc_created", {"doc_id": doc["id"], "title": doc["title"]})
    return _ok({"doc_id": doc["id"], "doc": doc})


@tool(
    name="office_doc_update",
    description="追加文档新版本（current_version 推进）；可附修订说明。",
    parameters={"doc_id": _STR, "content": _STR, "note": _STR},
    required=["doc_id", "content"],
    emoji="✏️",
)
@_guard
def office_doc_update(doc_id: str, content: str, note: str | None = None) -> str:
    rt = _runtime
    doc = _documents(rt).update(doc_id, content=content, note=note)
    _publish(
        rt,
        "office.doc_updated",
        {"doc_id": doc_id, "version": doc["current_version"]},
    )
    return _ok({"doc_id": doc_id, "version": doc["current_version"]})


@tool(
    name="office_doc_get",
    description="读取文档内容；缺省取当前版本，version=N 取历史快照。",
    parameters={"doc_id": _STR, "version": {"type": "integer"}},
    required=["doc_id"],
    emoji="📖",
)
@_guard
def office_doc_get(doc_id: str, version: int | None = None) -> str:
    doc = _documents(_runtime).get(doc_id, version=version)
    return _ok(doc)


@tool(
    name="office_doc_list",
    description="列出文档摘要；支持 tag / 标题 keyword 过滤与 limit 上限。",
    parameters={
        "tag": _STR,
        "keyword": _STR,
        "limit": {"type": "integer"},
    },
    emoji="🗂️",
)
@_guard
def office_doc_list(
    tag: str | None = None, keyword: str | None = None, limit: int | None = None
) -> str:
    docs = _documents(_runtime).list_documents(tag=tag, keyword=keyword, limit=limit)
    return _ok({"documents": docs})


@tool(
    name="office_doc_versions",
    description="列出文档完整版本历史（升序，含每版内容与修订说明）。",
    parameters={"doc_id": _STR},
    required=["doc_id"],
    emoji="🕘",
)
@_guard
def office_doc_versions(doc_id: str) -> str:
    versions = _documents(_runtime).versions(doc_id)
    return _ok({"versions": versions})


@tool(
    name="office_doc_rollback",
    description="回滚文档到指定版本：把目标版本内容复制为新版本（历史不可变）。",
    parameters={"doc_id": _STR, "version": {"type": "integer"}},
    required=["doc_id", "version"],
    emoji="⏪",
)
@_guard
def office_doc_rollback(doc_id: str, version: int) -> str:
    rt = _runtime
    result = _documents(rt).rollback(doc_id, version=version)
    _publish(
        rt,
        "office.doc_updated",
        {"doc_id": doc_id, "version": result["current_version"], "rollback": True},
    )
    return _ok(result)


# ---------------------------------------------------------------------------
# 邮件工具
# ---------------------------------------------------------------------------
@tool(
    name="office_email_send",
    description="发送邮件：直接 body 或 template+vars 渲染；成功写入本地 sent 文件夹。",
    parameters={
        "to": _STR_LIST,
        "subject": _STR,
        "body": _STR,
        "template": _STR,
        "vars": {"type": "object"},
    },
    required=["to"],
    emoji="📤",
)
@_guard
def office_email_send(
    to: list[str],
    subject: str | None = None,
    body: str | None = None,
    template: str | None = None,
    vars: dict[str, Any] | None = None,
) -> str:
    rt = _runtime
    mail = _emails(rt).send(
        to=to, subject=subject, body=body, template=template, vars=vars
    )
    _publish(
        rt,
        "office.email_sent",
        {"email_id": mail["id"], "to": mail["to"], "subject": mail["subject"]},
    )
    return _ok({"email_id": mail["id"], "email": mail})


@tool(
    name="office_email_inbox",
    description="查看收件箱；fetch=true 时先经后端拉取新邮件（按 uid 去重入库）。",
    parameters={"fetch": _BOOL, "unread_only": _BOOL},
    emoji="📥",
)
@_guard
def office_email_inbox(fetch: bool = False, unread_only: bool = False) -> str:
    mgr = _emails(_runtime)
    if fetch:
        mgr.fetch_inbox()
    emails = mgr.list_emails(folder="inbox", unread_only=unread_only)
    return _ok({"emails": emails})


@tool(
    name="office_email_mark_read",
    description="把指定邮件标记为已读。",
    parameters={"email_id": _STR},
    required=["email_id"],
    emoji="✅",
)
@_guard
def office_email_mark_read(email_id: str) -> str:
    result = _emails(_runtime).mark_read(email_id)
    return _ok(result)


@tool(
    name="office_email_template_save",
    description="保存（或覆盖）邮件模板；模板用 {{ var }} 占位符。",
    parameters={"name": _STR, "subject": _STR, "body": _STR},
    required=["name", "subject", "body"],
    emoji="📝",
)
@_guard
def office_email_template_save(name: str, subject: str, body: str) -> str:
    tpl = _emails(_runtime).save_template(name, subject=subject, body=body)
    return _ok({"template": tpl})


@tool(
    name="office_email_template_list",
    description="列出全部邮件模板。",
    parameters={},
    emoji="📋",
)
@_guard
def office_email_template_list() -> str:
    templates = _emails(_runtime).list_templates()
    return _ok({"templates": templates})


@tool(
    name="office_email_auto_reply",
    description="管理自动回复规则：action=add（name+template+keyword/sender_match）"
    " / list / remove（name）。",
    parameters={
        "action": {"type": "string", "enum": ["add", "list", "remove"]},
        "name": _STR,
        "keyword": _STR,
        "sender_match": _STR,
        "template": _STR,
        "enabled": _BOOL,
    },
    required=["action"],
    emoji="🤖",
)
@_guard
def office_email_auto_reply(
    action: str,
    name: str | None = None,
    keyword: str | None = None,
    sender_match: str | None = None,
    template: str | None = None,
    enabled: bool = True,
) -> str:
    mgr = _emails(_runtime)
    if action == "add":
        rule = mgr.add_auto_reply_rule(
            name=name or "",
            keyword=keyword,
            sender_match=sender_match,
            template=template,
            enabled=enabled,
        )
        return _ok({"rule": rule})
    if action == "list":
        return _ok({"rules": mgr.list_auto_reply_rules()})
    if action == "remove":
        result = mgr.remove_auto_reply_rule(name or "")
        return _ok(result)
    return _err("E_INVALID_PARAMS", f"未知 action: {action!r}（支持 add/list/remove）")


@tool(
    name="office_email_process_inbox",
    description="对未读且未自动回复的收件箱邮件应用启用的自动回复规则；"
    "fetch=true 时先拉取新邮件。",
    parameters={"fetch": _BOOL},
    emoji="⚙️",
)
@_guard
def office_email_process_inbox(fetch: bool = False) -> str:
    rt = _runtime
    mgr = _emails(rt)
    if fetch:
        mgr.fetch_inbox()
    result = mgr.process_inbox()
    for mail_id in result["replied"]:
        _publish(rt, "office.email_auto_replied", {"email_id": mail_id})
    return _ok(result)


# ---------------------------------------------------------------------------
# 日程工具
# ---------------------------------------------------------------------------
@tool(
    name="office_event_create",
    description="创建日程；冲突且 force=false 返回 E_EVENT_CONFLICT，force=true 强制创建。",
    parameters={
        "title": _STR,
        "start": _TIME,
        "end": _TIME,
        "attendees": _STR_LIST,
        "reminder_minutes": {"type": "integer"},
        "location": _STR,
        "notes": _STR,
        "doc_id": _STR,
        "force": _BOOL,
    },
    required=["title", "start", "end"],
    emoji="📅",
)
@_guard
def office_event_create(
    title: str,
    start: str | int | float,
    end: str | int | float,
    attendees: list[str] | None = None,
    reminder_minutes: int | None = None,
    location: str | None = None,
    notes: str | None = None,
    doc_id: str | None = None,
    force: bool = False,
) -> str:
    rt = _runtime
    event = _calendar(rt).create(
        title=title,
        start=start,
        end=end,
        attendees=attendees,
        reminder_minutes=reminder_minutes,
        location=location,
        notes=notes,
        doc_id=doc_id,
        force=force,
    )
    _publish(
        rt,
        "office.event_created",
        {"event_id": event["id"], "title": event["title"], "start_iso": event["start_iso"]},
    )
    return _ok({"event": event, "conflicts": event.get("conflicts", [])})


@tool(
    name="office_event_list",
    description="列出日程；给定 start/end 时按区间重叠过滤，否则返回全部。",
    parameters={"start": _TIME, "end": _TIME},
    emoji="🗓️",
)
@_guard
def office_event_list(
    start: str | int | float | None = None, end: str | int | float | None = None
) -> str:
    events = _calendar(_runtime).list_events(start=start, end=end)
    return _ok({"events": events})


@tool(
    name="office_event_reminders",
    description="取到期提醒（start - reminder_minutes <= now < end 且未提醒过），"
    "命中后标记已提醒。",
    parameters={"now": _TIME},
    emoji="⏰",
)
@_guard
def office_event_reminders(now: str | int | float | None = None) -> str:
    rt = _runtime
    due = _calendar(rt).due_reminders(now=now, mark=True)
    for evt in due:
        _publish(
            rt,
            "office.event_reminder",
            {"event_id": evt["id"], "title": evt["title"], "start_iso": evt["start_iso"]},
        )
    return _ok({"reminders": due})


@tool(
    name="office_event_check_conflicts",
    description="检查给定时间段与现有日程的冲突列表（空列表 = 无冲突）。",
    parameters={"start": _TIME, "end": _TIME, "exclude_id": _STR},
    required=["start", "end"],
    emoji="🔍",
)
@_guard
def office_event_check_conflicts(
    start: str | int | float,
    end: str | int | float,
    exclude_id: str | None = None,
) -> str:
    conflicts = _calendar(_runtime).check_conflicts(start, end, exclude_id=exclude_id)
    return _ok({"conflicts": conflicts})


# ---------------------------------------------------------------------------
# 工作流工具
# ---------------------------------------------------------------------------
@tool(
    name="office_meeting_prep",
    description="会议准备一条龙：冲突预检（原子拒绝）→ 建档会议纪要文档 → "
    "创建日程并回链 doc_id → 逐位参会人发送邀请邮件。",
    parameters={
        "title": _STR,
        "start": _TIME,
        "end": _TIME,
        "attendees": _STR_LIST,
        "agenda": _STR,
        "reminder_minutes": {"type": "integer"},
        "force": _BOOL,
    },
    required=["title", "start", "end", "attendees"],
    emoji="🤝",
)
@_guard
def office_meeting_prep(
    title: str,
    start: str | int | float,
    end: str | int | float,
    attendees: list[str],
    agenda: str | None = None,
    reminder_minutes: int | None = 15,
    force: bool = False,
) -> str:
    rt = _runtime
    result = _workflows(rt).meeting_prep(
        title=title,
        start=start,
        end=end,
        attendees=attendees,
        agenda=agenda,
        reminder_minutes=reminder_minutes,
        force=force,
    )
    _publish(
        rt,
        "office.workflow_completed",
        {"workflow": "meeting_prep", **result},
    )
    return _ok(result)


@tool(
    name="office_email_to_event",
    description="邮件 → 日程：从收件箱邮件快速建档日程（标题取邮件主题、备注回链邮件 id），"
    "向发件人回复确认，原邮件置为已读。",
    parameters={
        "email_uid": _STR,
        "start": _TIME,
        "end": _TIME,
        "reply_template": _STR,
        "force": _BOOL,
    },
    required=["email_uid", "start", "end"],
    emoji="📥",
)
@_guard
def office_email_to_event(
    email_uid: str,
    start: str | int | float,
    end: str | int | float,
    reply_template: str | None = None,
    force: bool = False,
) -> str:
    rt = _runtime
    result = _workflows(rt).email_to_event(
        email_uid=email_uid,
        start=start,
        end=end,
        reply_template=reply_template,
        force=force,
    )
    _publish(
        rt,
        "office.workflow_completed",
        {"workflow": "email_to_event", **result},
    )
    return _ok(result)


@tool(
    name="office_status",
    description="办公插件状态：文档 / 日程 / 邮件计数与库路径。",
    parameters={},
    emoji="📊",
)
@_guard
def office_status() -> str:
    db = _get_db(_runtime)
    counts = {
        "documents": db.conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"],
        "events": db.conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"],
        "emails": db.conn.execute("SELECT COUNT(*) AS n FROM emails").fetchone()["n"],
    }
    return _ok({**counts, "db_path": db.path})


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------
def _make_handler(func: Callable) -> Callable:
    """把工具函数适配为 registry handler：``(args: dict, **kw) -> JSON 字符串``。"""

    def handler(args: dict[str, Any], **_: Any) -> str:
        try:
            return func(**(args or {}))
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "office tool %s 调用失败: %s", getattr(func, "__name__", "?"), exc
            )
            return _err("E_INTERNAL", str(exc))

    return handler


def register(ctx) -> None:
    """把全部工具（office_* + schedule_*）注册到插件上下文；若 ctx 携带事件总线则接入。"""
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
    logger.info("omni_office 插件已注册 %d 个 tools", len(TOOLS))


# ---------------------------------------------------------------------------
# 移动端日程桥接（M34.2）：import 即把 4 个 schedule_* 工具登记进 TOOLS。
# 放在模块末尾避免循环导入（schedule_bridge 依赖本模块的 tool/_guard/_ok 等）。
# ---------------------------------------------------------------------------
from . import schedule_bridge  # noqa: E402,F401
