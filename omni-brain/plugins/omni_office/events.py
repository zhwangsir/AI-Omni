"""omni_office 日程管理：创建 / 冲突检测 / 区间查询 / 到期提醒。

时间契约：
- 输入接受 ISO8601 字符串（naive 按本地时区解释）或 epoch 秒（int/float）
- 库内统一存 epoch 秒（REAL），输出同时携带 ``start_ts`` 与 ``start_iso``

冲突判定：标准区间重叠 —— ``existing.start < new.end 且 existing.end > new.start``；
首尾相接（``end == start``）不算冲突。

提醒判定：``start - reminder_minutes <= now < end`` 且未提醒过；
``mark=True`` 时把命中事件标记为 ``reminded``（同一事件只提醒一次）。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any

from .db import OfficeDB
from .errors import (
    OfficeConflictError,
    OfficeNotFoundError,
    OfficeValidationError,
)


def _new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


def parse_time(value: str | int | float) -> float:
    """把 ISO8601 字符串或 epoch 秒解析为 epoch 秒（float）。

    naive ISO8601 按本地时区解释；无法解析抛 :class:`OfficeValidationError`。
    """
    if isinstance(value, bool):
        raise OfficeValidationError(f"不支持的时间类型: bool（{value!r}）")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise OfficeValidationError(
                f"无法解析时间: {value!r}（需 ISO8601 字符串或 epoch 秒）"
            ) from exc
        return dt.timestamp()
    raise OfficeValidationError(f"不支持的时间类型: {type(value).__name__}")


def _iso(ts: float) -> str:
    """epoch 秒 → 本地 ISO8601 字符串（分钟精度）。"""
    return datetime.fromtimestamp(ts).isoformat(timespec="minutes")


class CalendarManager:
    """日程管理器。"""

    def __init__(self, db: OfficeDB) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_event(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "start_ts": row["start_ts"],
            "end_ts": row["end_ts"],
            "start_iso": _iso(row["start_ts"]),
            "end_iso": _iso(row["end_ts"]),
            "attendees": json.loads(row["attendees"]),
            "reminder_minutes": row["reminder_minutes"],
            "reminded": bool(row["reminded"]),
            "location": row["location"],
            "notes": row["notes"],
            "doc_id": row["doc_id"],
            "completed": bool(row["completed"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _conflicts_between(
        self, start_ts: float, end_ts: float, exclude_id: str | None = None
    ) -> list[dict[str, Any]]:
        """区间重叠查询：返回与 [start_ts, end_ts) 冲突的事件摘要。"""
        sql = "SELECT * FROM events WHERE start_ts < ? AND end_ts > ?"
        params: list[Any] = [end_ts, start_ts]
        if exclude_id is not None:
            sql += " AND id != ?"
            params.append(exclude_id)
        sql += " ORDER BY start_ts ASC"
        rows = self._db.conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def create(
        self,
        title: str,
        start: str | int | float,
        end: str | int | float,
        attendees: list[str] | None = None,
        reminder_minutes: int | None = None,
        location: str | None = None,
        notes: str | None = None,
        doc_id: str | None = None,
        force: bool = False,
        event_id: str | None = None,
        completed: bool = False,
        created_at: float | None = None,
    ) -> dict[str, Any]:
        """创建日程；冲突且 ``force=False`` 抛 :class:`OfficeConflictError`。

        ``force=True`` 时照常创建，返回 dict 附带 ``conflicts`` 列表。
        ``event_id`` 可显式指定（移动端桥接保留 UniHub id）；
        ``completed`` 标记完成态（M34.2）；``created_at`` 缺省取当前时间。
        """
        title = (title or "").strip()
        if not title:
            raise OfficeValidationError("日程标题不能为空")
        start_ts = parse_time(start)
        end_ts = parse_time(end)
        if end_ts <= start_ts:
            raise OfficeValidationError("结束时间必须晚于开始时间")
        conflicts = self._conflicts_between(start_ts, end_ts)
        if conflicts and not force:
            names = "、".join(c["title"] for c in conflicts)
            raise OfficeConflictError(f"日程冲突: 与「{names}」时间重叠", conflicts=conflicts)
        new_id = event_id or _new_event_id()
        now = time.time()
        created = float(created_at) if created_at is not None else now
        attendee_list = [str(a) for a in (attendees or [])]
        self._db.conn.execute(
            "INSERT INTO events (id, title, start_ts, end_ts, attendees, reminder_minutes,"
            " reminded, location, notes, doc_id, completed, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)",
            (
                new_id,
                title,
                start_ts,
                end_ts,
                json.dumps(attendee_list, ensure_ascii=False),
                reminder_minutes,
                location,
                notes,
                doc_id,
                1 if completed else 0,
                created,
                created,
            ),
        )
        self._db.conn.commit()
        event = {
            "id": new_id,
            "title": title,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "start_iso": _iso(start_ts),
            "end_iso": _iso(end_ts),
            "attendees": attendee_list,
            "reminder_minutes": reminder_minutes,
            "reminded": False,
            "location": location,
            "notes": notes,
            "doc_id": doc_id,
            "completed": completed,
            "created_at": created,
            "updated_at": created,
        }
        if conflicts:
            event["conflicts"] = conflicts
        return event

    def get(self, event_id: str) -> dict[str, Any]:
        """按 id 取日程；不存在抛 :class:`OfficeNotFoundError`。"""
        row = self._db.conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise OfficeNotFoundError(f"日程不存在: {event_id}")
        return self._row_to_event(row)

    def check_conflicts(
        self,
        start: str | int | float,
        end: str | int | float,
        exclude_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """检查给定时间段与现有日程的冲突列表（空列表 = 无冲突）。"""
        start_ts = parse_time(start)
        end_ts = parse_time(end)
        return self._conflicts_between(start_ts, end_ts, exclude_id=exclude_id)

    def list_events(
        self,
        start: str | int | float | None = None,
        end: str | int | float | None = None,
    ) -> list[dict[str, Any]]:
        """列出日程；给定 ``start``/``end`` 时按区间重叠过滤，否则返回全部。"""
        if start is None and end is None:
            rows = self._db.conn.execute(
                "SELECT * FROM events ORDER BY start_ts ASC"
            ).fetchall()
            return [self._row_to_event(r) for r in rows]
        start_ts = parse_time(start) if start is not None else float("-inf")
        end_ts = parse_time(end) if end is not None else float("inf")
        return self._conflicts_between(start_ts, end_ts)

    def due_reminders(
        self, now: str | int | float | None = None, mark: bool = True
    ) -> list[dict[str, Any]]:
        """取到期提醒：``start - reminder_minutes <= now < end`` 且未提醒过。

        :param now: 缺省取当前时间
        :param mark: 为 True 时把命中事件标记为已提醒（下次不再返回）
        """
        now_ts = parse_time(now) if now is not None else time.time()
        rows = self._db.conn.execute(
            "SELECT * FROM events WHERE reminder_minutes IS NOT NULL AND reminded = 0"
            " AND (start_ts - reminder_minutes * 60) <= ? AND end_ts > ?"
            " ORDER BY start_ts ASC",
            (now_ts, now_ts),
        ).fetchall()
        events = [self._row_to_event(r) for r in rows]
        if mark and events:
            conn = self._db.conn
            for evt in events:
                conn.execute("UPDATE events SET reminded = 1 WHERE id = ?", (evt["id"],))
                evt["reminded"] = True
            conn.commit()
        return events

    # ------------------------------------------------------------------
    # 更新 / 删除（M34.2：移动端桥接）
    # ------------------------------------------------------------------
    def update(
        self,
        event_id: str,
        *,
        title: str | None = None,
        start: str | int | float | None = None,
        end: str | int | float | None = None,
        completed: bool | None = None,
        notes: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """按 id 局部更新日程；不存在抛 :class:`OfficeNotFoundError`。

        仅 ``None`` 以外的参数参与更新；``start``/``end`` 同时给出才重排时间，
        新时间区间与其他日程冲突且 ``force=False`` 抛 :class:`OfficeConflictError`
        （排除自身）。``updated_at`` 自动刷新，``created_at`` 不动。
        """
        current = self.get(event_id)
        sets: list[str] = []
        params: list[Any] = []
        if title is not None:
            title = title.strip()
            if not title:
                raise OfficeValidationError("日程标题不能为空")
            sets.append("title = ?")
            params.append(title)
        if start is not None or end is not None:
            if start is None or end is None:
                raise OfficeValidationError("start 与 end 必须同时提供")
            start_ts = parse_time(start)
            end_ts = parse_time(end)
            if end_ts <= start_ts:
                raise OfficeValidationError("结束时间必须晚于开始时间")
            conflicts = self._conflicts_between(start_ts, end_ts, exclude_id=event_id)
            if conflicts and not force:
                names = "、".join(c["title"] for c in conflicts)
                raise OfficeConflictError(
                    f"日程冲突: 与「{names}」时间重叠", conflicts=conflicts
                )
            sets.append("start_ts = ?")
            params.append(start_ts)
            sets.append("end_ts = ?")
            params.append(end_ts)
        if completed is not None:
            sets.append("completed = ?")
            params.append(1 if completed else 0)
        if notes is not None:
            sets.append("notes = ?")
            params.append(notes)
        if not sets:
            return current
        sets.append("updated_at = ?")
        params.append(time.time())
        params.append(event_id)
        self._db.conn.execute(
            f"UPDATE events SET {', '.join(sets)} WHERE id = ?", params
        )
        self._db.conn.commit()
        updated = self.get(event_id)
        if (start is not None) and self._conflicts_between(
            updated["start_ts"], updated["end_ts"], exclude_id=event_id
        ):
            updated["conflicts"] = self._conflicts_between(
                updated["start_ts"], updated["end_ts"], exclude_id=event_id
            )
        return updated

    def delete(self, event_id: str) -> None:
        """按 id 删除日程；不存在抛 :class:`OfficeNotFoundError`。"""
        cursor = self._db.conn.execute(
            "DELETE FROM events WHERE id = ?", (event_id,)
        )
        self._db.conn.commit()
        if cursor.rowcount == 0:
            raise OfficeNotFoundError(f"日程不存在: {event_id}")
