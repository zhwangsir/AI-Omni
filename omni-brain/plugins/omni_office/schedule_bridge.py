"""omni_office 移动端日程桥接：``schedule_*`` 工具集（UniHub 远程同步入口）。

UniHub 移动端（``UniHub/utils/schedule.js``）经 OpenClaw ``/v1/tools/call``
调用 ``schedule_*`` 工具集做远程同步。本模块把 UniHub 的扁平日程模型
（``date`` + ``time`` + ``completed``）映射到 omni_office 的区间日程模型
（``start_ts`` ~ ``end_ts``），两端共享 events 表存储——桌面端
``office_event_*`` 创建的日程同样会被 ``schedule_list_events`` 读出。

字段映射：
- ``date`` + ``time`` → ``start_ts``/``end_ts``：定时日程默认 30 分钟；
  ``time=None`` 为全天（00:00 ~ 23:59 本地时区）
- ``note`` ↔ ``notes``；``completed`` ↔ ``events.completed`` 列
- ``createdAt``/``updatedAt``（毫秒）↔ ``created_at``/``updated_at``（秒）
- UniHub 传入的 ``id`` 原样保留（两端 id 一致，update/delete 才能对上）

移动端快速记事项语义：不做冲突拒绝（``force=True``），不参与提醒。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .errors import OfficeValidationError
from .tools import _calendar, _guard, _ok, tool

#: 定时日程默认时长（秒）
DEFAULT_DURATION_SEC = 30 * 60

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")

#: schedule_update_event 的 time 哨兵：未传 = 不改；显式 null = 转全天
_UNSET: Any = object()


def _rt() -> Any:
    """动态取 ``tools._runtime``。

    测试与插件宿主会经 ``tools._reset_runtime`` 替换该全局实例；
    模块级 ``from .tools import _runtime`` 会在 import 时固化旧绑定，
    导致桥接工具误开真实磁盘库，必须调用时动态查找。
    """
    from . import tools

    return tools._runtime


def _validate_date(date: str) -> str:
    """校验 YYYY-MM-DD 且为真实日期；非法抛 :class:`OfficeValidationError`。"""
    if not isinstance(date, str) or not _DATE_RE.match(date):
        raise OfficeValidationError(f"日程日期格式无效: {date!r}（需 YYYY-MM-DD）")
    try:
        datetime.fromisoformat(f"{date}T00:00")
    except ValueError as exc:
        raise OfficeValidationError(f"日程日期格式无效: {date!r}") from exc
    return date


def _validate_time(time_str: str) -> str:
    """校验 HH:MM 且时分在界；非法抛 :class:`OfficeValidationError`。"""
    if not isinstance(time_str, str) or not _TIME_RE.match(time_str):
        raise OfficeValidationError(f"日程时间格式无效: {time_str!r}（需 HH:MM）")
    try:
        datetime.fromisoformat(f"2000-01-01T{time_str}")
    except ValueError as exc:
        raise OfficeValidationError(f"日程时间格式无效: {time_str!r}") from exc
    return time_str


def uni_to_interval(date: str, time_str: str | None) -> tuple[float, float]:
    """UniHub ``date`` + ``time`` → (start_ts, end_ts)。

    定时：start = 本地 ``date time``，end = start + 30 分钟；
    全天（``time_str=None``）：00:00 ~ 23:59 本地。
    """
    _validate_date(date)
    if time_str is None:
        start = datetime.fromisoformat(f"{date}T00:00").timestamp()
        end = datetime.fromisoformat(f"{date}T23:59").timestamp()
        return start, end
    _validate_time(time_str)
    start = datetime.fromisoformat(f"{date}T{time_str}").timestamp()
    return start, start + DEFAULT_DURATION_SEC


def _is_all_day(start_ts: float, end_ts: float) -> bool:
    """区间是否为「全天」：同日 00:00 ~ 23:59（bridge 创建的语义逆映射）。"""
    start_dt = datetime.fromtimestamp(start_ts)
    end_dt = datetime.fromtimestamp(end_ts)
    return (
        start_dt.date() == end_dt.date()
        and (start_dt.hour, start_dt.minute) == (0, 0)
        and (end_dt.hour, end_dt.minute) == (23, 59)
    )


def event_to_uni(event: dict[str, Any]) -> dict[str, Any]:
    """omni event dict（``CalendarManager._row_to_event`` 输出）→ UniHub 结构。

    ``createdAt``/``updatedAt`` 为毫秒整数；``notes=None`` 归一为 ``""``。
    """
    start_dt = datetime.fromtimestamp(event["start_ts"])
    all_day = _is_all_day(event["start_ts"], event["end_ts"])
    return {
        "id": event["id"],
        "title": event["title"],
        "date": start_dt.strftime("%Y-%m-%d"),
        "time": None if all_day else start_dt.strftime("%H:%M"),
        "completed": bool(event.get("completed", False)),
        "note": event.get("notes") or "",
        "createdAt": round(event["created_at"] * 1000),
        "updatedAt": round((event.get("updated_at") or event["created_at"]) * 1000),
    }


def _ms_to_sec(ms: Any) -> float | None:
    """UniHub 毫秒时间戳 → 秒；非数字返回 None。"""
    if isinstance(ms, bool):
        return None
    if isinstance(ms, (int, float)) and ms > 0:
        return float(ms) / 1000.0
    return None


# ---------------------------------------------------------------------------
# schedule_* 工具（OpenClaw 网关路由入口）
# ---------------------------------------------------------------------------
@tool(
    name="schedule_list_events",
    description="列出全部日程（UniHub 扁平结构：date/time/completed/note，毫秒时间戳）。",
    parameters={},
    emoji="🗓️",
)
@_guard
def schedule_list_events() -> str:
    events = _calendar(_rt()).list_events()
    return _ok({"events": [event_to_uni(e) for e in events]})


@tool(
    name="schedule_create_event",
    description="创建移动端日程：date(YYYY-MM-DD) 必填，time(HH:MM) 缺省为全天；"
    "id 原样保留，定时日程默认 30 分钟。",
    parameters={
        "id": {"type": "string"},
        "title": {"type": "string"},
        "date": {"type": "string"},
        "time": {"type": ["string", "null"]},
        "completed": {"type": "boolean"},
        "note": {"type": "string"},
        "createdAt": {"type": "number", "description": "毫秒时间戳"},
        "updatedAt": {"type": "number", "description": "毫秒时间戳"},
    },
    required=["title"],
    emoji="📅",
)
@_guard
def schedule_create_event(
    title: str,
    id: str | None = None,
    date: str | None = None,
    time: str | None = None,
    completed: bool = False,
    note: str | None = None,
    createdAt: int | float | None = None,
    updatedAt: int | float | None = None,  # noqa: ARG001 - 协议字段，由服务端管理
) -> str:
    title = (title or "").strip()
    if not title:
        raise OfficeValidationError("日程标题不能为空")
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    start_ts, end_ts = uni_to_interval(date, time)
    event = _calendar(_rt()).create(
        title=title,
        start=start_ts,
        end=end_ts,
        notes=note or None,
        force=True,
        event_id=id or None,
        completed=bool(completed),
        created_at=_ms_to_sec(createdAt),
    )
    return _ok({"event": event_to_uni(event)})


@tool(
    name="schedule_update_event",
    description="局部更新移动端日程：title/date/time/completed/note 可选；"
    "time 显式 null 转全天，未传则保留原时刻。",
    parameters={
        "id": {"type": "string"},
        "title": {"type": "string"},
        "date": {"type": "string"},
        "time": {"type": ["string", "null"]},
        "completed": {"type": "boolean"},
        "note": {"type": "string"},
    },
    required=["id"],
    emoji="✏️",
)
@_guard
def schedule_update_event(
    id: str,
    title: str | None = None,
    date: str | None = None,
    time: str | None = _UNSET,
    completed: bool | None = None,
    note: str | None = None,
) -> str:
    cal = _calendar(_rt())
    current = cal.get(id)  # 不存在 → OfficeNotFoundError
    patch: dict[str, Any] = {}
    if title is not None:
        patch["title"] = title
    if completed is not None:
        patch["completed"] = bool(completed)
    if note is not None:
        patch["notes"] = note
    # date / time 任一显式给出 → 合并后重算区间（time 未传保留原时刻）
    if date is not None or time is not _UNSET:
        cur = event_to_uni(current)
        new_date = date if date is not None else cur["date"]
        new_time = cur["time"] if time is _UNSET else time
        start_ts, end_ts = uni_to_interval(new_date, new_time)
        patch["start"] = start_ts
        patch["end"] = end_ts
        patch["force"] = True
    updated = cal.update(id, **patch)
    return _ok({"event": event_to_uni(updated)})


@tool(
    name="schedule_delete_event",
    description="按 id 删除移动端日程。",
    parameters={"id": {"type": "string"}},
    required=["id"],
    emoji="🗑️",
)
@_guard
def schedule_delete_event(id: str) -> str:
    _calendar(_rt()).delete(id)
    return _ok({"id": id})


#: 供 tools.register 之外的本模块自检用
_BRIDGE_TOOLS = (
    "schedule_list_events",
    "schedule_create_event",
    "schedule_update_event",
    "schedule_delete_event",
)
