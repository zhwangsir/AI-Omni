"""omni_office 日程管理（events.py）单元测试。

契约：
- 时间输入接受 ISO8601 字符串（naive 按本地时区）或 epoch 秒
- 冲突判定：标准区间重叠（new_start < existing_end 且 new_end > existing_start）；
  首尾相接（end == start）不算冲突
- create 遇冲突且 force=False 抛 :class:`OfficeConflictError`（携带 conflicts）
- reminders：``start - reminder_minutes <= now < end`` 且未提醒过的事件为到期；
  ``mark=True`` 时标记 reminded
"""

from __future__ import annotations

import pytest

from omni_office.db import OfficeDB
from omni_office.errors import (
    OfficeConflictError,
    OfficeNotFoundError,
    OfficeValidationError,
)
from omni_office.events import CalendarManager


@pytest.fixture()
def mgr():
    db = OfficeDB(":memory:")
    db.init_schema()
    yield CalendarManager(db)
    db.close()


class TestCreate:
    def test_create_basic(self, mgr: CalendarManager) -> None:
        evt = mgr.create(
            title="站会", start="2026-08-07T09:30", end="2026-08-07T09:45"
        )
        assert evt["id"].startswith("evt_")
        assert evt["title"] == "站会"
        assert isinstance(evt["start_ts"], float)
        assert evt["start_ts"] < evt["end_ts"]
        assert "start_iso" in evt

    def test_create_with_attendees_and_reminder(self, mgr: CalendarManager) -> None:
        evt = mgr.create(
            title="评审",
            start="2026-08-07T14:00",
            end="2026-08-07T15:00",
            attendees=["a@x.com", "b@x.com"],
            reminder_minutes=30,
            location="3F 会议室",
        )
        assert evt["attendees"] == ["a@x.com", "b@x.com"]
        assert evt["reminder_minutes"] == 30

    def test_create_end_before_start_rejected(self, mgr: CalendarManager) -> None:
        with pytest.raises(OfficeValidationError):
            mgr.create(title="t", start="2026-08-07T15:00", end="2026-08-07T14:00")

    def test_create_empty_title_rejected(self, mgr: CalendarManager) -> None:
        with pytest.raises(OfficeValidationError):
            mgr.create(title="", start="2026-08-07T14:00", end="2026-08-07T15:00")

    def test_create_bad_time_format_rejected(self, mgr: CalendarManager) -> None:
        with pytest.raises(OfficeValidationError):
            mgr.create(title="t", start="下周三下午", end="2026-08-07T15:00")

    def test_create_accepts_epoch(self, mgr: CalendarManager) -> None:
        evt = mgr.create(title="t", start=1_786_000_000, end=1_786_000_600)
        assert evt["end_ts"] - evt["start_ts"] == 600.0


class TestConflicts:
    def test_partial_overlap_detected(self, mgr: CalendarManager) -> None:
        mgr.create(title="A", start="2026-08-07T14:00", end="2026-08-07T15:00")
        conflicts = mgr.check_conflicts("2026-08-07T14:30", "2026-08-07T15:30")
        assert [c["title"] for c in conflicts] == ["A"]

    def test_containment_detected(self, mgr: CalendarManager) -> None:
        mgr.create(title="A", start="2026-08-07T14:00", end="2026-08-07T16:00")
        conflicts = mgr.check_conflicts("2026-08-07T14:30", "2026-08-07T15:00")
        assert len(conflicts) == 1

    def test_adjacent_not_conflict(self, mgr: CalendarManager) -> None:
        mgr.create(title="A", start="2026-08-07T14:00", end="2026-08-07T15:00")
        assert mgr.check_conflicts("2026-08-07T15:00", "2026-08-07T16:00") == []
        assert mgr.check_conflicts("2026-08-07T13:00", "2026-08-07T14:00") == []

    def test_create_conflict_raises_with_details(self, mgr: CalendarManager) -> None:
        mgr.create(title="A", start="2026-08-07T14:00", end="2026-08-07T15:00")
        with pytest.raises(OfficeConflictError) as exc_info:
            mgr.create(title="B", start="2026-08-07T14:30", end="2026-08-07T15:30")
        assert len(exc_info.value.conflicts) == 1
        assert exc_info.value.conflicts[0]["title"] == "A"

    def test_create_conflict_force_succeeds(self, mgr: CalendarManager) -> None:
        mgr.create(title="A", start="2026-08-07T14:00", end="2026-08-07T15:00")
        evt = mgr.create(
            title="B",
            start="2026-08-07T14:30",
            end="2026-08-07T15:30",
            force=True,
        )
        assert evt["id"].startswith("evt_")
        assert len(evt["conflicts"]) == 1

    def test_check_conflicts_exclude_id(self, mgr: CalendarManager) -> None:
        evt = mgr.create(title="A", start="2026-08-07T14:00", end="2026-08-07T15:00")
        conflicts = mgr.check_conflicts(
            "2026-08-07T14:00", "2026-08-07T15:00", exclude_id=evt["id"]
        )
        assert conflicts == []


class TestList:
    def test_list_range_filter(self, mgr: CalendarManager) -> None:
        mgr.create(title="早", start="2026-08-07T09:00", end="2026-08-07T09:30")
        mgr.create(title="晚", start="2026-08-07T20:00", end="2026-08-07T21:00")
        events = mgr.list_events(
            start="2026-08-07T00:00", end="2026-08-07T12:00"
        )
        assert [e["title"] for e in events] == ["早"]

    def test_list_all_when_no_range(self, mgr: CalendarManager) -> None:
        mgr.create(title="a", start="2026-08-07T09:00", end="2026-08-07T09:30")
        mgr.create(title="b", start="2026-08-09T09:00", end="2026-08-09T09:30")
        assert len(mgr.list_events()) == 2


class TestGet:
    def test_get_existing(self, mgr: CalendarManager) -> None:
        evt = mgr.create(title="t", start="2026-08-07T09:00", end="2026-08-07T09:30")
        got = mgr.get(evt["id"])
        assert got["title"] == "t"

    def test_get_missing_raises(self, mgr: CalendarManager) -> None:
        with pytest.raises(OfficeNotFoundError):
            mgr.get("evt_nope")


class TestReminders:
    def test_due_reminder_returned_and_marked(self, mgr: CalendarManager) -> None:
        # 14:00 开始，提前 15 分钟提醒 → 13:50 已到期
        mgr.create(
            title="评审",
            start="2026-08-07T14:00",
            end="2026-08-07T15:00",
            reminder_minutes=15,
        )
        due = mgr.due_reminders(now="2026-08-07T13:50")
        assert [d["title"] for d in due] == ["评审"]
        # 已标记 reminded，再次查询为空
        assert mgr.due_reminders(now="2026-08-07T13:51") == []

    def test_not_yet_due(self, mgr: CalendarManager) -> None:
        mgr.create(
            title="评审",
            start="2026-08-07T14:00",
            end="2026-08-07T15:00",
            reminder_minutes=15,
        )
        assert mgr.due_reminders(now="2026-08-07T13:00") == []

    def test_past_event_not_reminded(self, mgr: CalendarManager) -> None:
        mgr.create(
            title="旧事",
            start="2026-08-07T14:00",
            end="2026-08-07T15:00",
            reminder_minutes=15,
        )
        assert mgr.due_reminders(now="2026-08-07T16:00") == []

    def test_mark_false_keeps_pending(self, mgr: CalendarManager) -> None:
        mgr.create(
            title="评审",
            start="2026-08-07T14:00",
            end="2026-08-07T15:00",
            reminder_minutes=15,
        )
        mgr.due_reminders(now="2026-08-07T13:50", mark=False)
        assert len(mgr.due_reminders(now="2026-08-07T13:51")) == 1

    def test_zero_reminder_minutes_reminds_at_start(self, mgr: CalendarManager) -> None:
        mgr.create(
            title="准点",
            start="2026-08-07T14:00",
            end="2026-08-07T15:00",
            reminder_minutes=0,
        )
        assert mgr.due_reminders(now="2026-08-07T13:59") == []
        assert len(mgr.due_reminders(now="2026-08-07T14:00")) == 1


class TestCreateExtended:
    """M34.2：create 支持指定 id 与 completed（移动端桥接用）。"""

    def test_create_with_explicit_id(self, mgr: CalendarManager) -> None:
        evt = mgr.create(
            title="t",
            start="2026-08-07T09:00",
            end="2026-08-07T09:30",
            event_id="evt_custom_123",
        )
        assert evt["id"] == "evt_custom_123"

    def test_create_default_not_completed(self, mgr: CalendarManager) -> None:
        evt = mgr.create(title="t", start="2026-08-07T09:00", end="2026-08-07T09:30")
        assert evt["completed"] is False
        assert isinstance(evt["updated_at"], float)

    def test_create_completed(self, mgr: CalendarManager) -> None:
        evt = mgr.create(
            title="t",
            start="2026-08-07T09:00",
            end="2026-08-07T09:30",
            completed=True,
        )
        assert evt["completed"] is True
        # 读回一致
        assert mgr.get(evt["id"])["completed"] is True


class TestUpdate:
    """M34.2：CalendarManager.update（title/start/end/completed/notes 可选 patch）。"""

    def test_update_title(self, mgr: CalendarManager) -> None:
        evt = mgr.create(title="旧", start="2026-08-07T09:00", end="2026-08-07T09:30")
        updated = mgr.update(evt["id"], title="新")
        assert updated["title"] == "新"
        assert mgr.get(evt["id"])["title"] == "新"

    def test_update_time_range(self, mgr: CalendarManager) -> None:
        evt = mgr.create(title="t", start="2026-08-07T09:00", end="2026-08-07T09:30")
        updated = mgr.update(
            evt["id"], start="2026-08-08T14:00", end="2026-08-08T15:00"
        )
        assert updated["start_iso"].startswith("2026-08-08T14:00")
        assert updated["end_iso"].startswith("2026-08-08T15:00")

    def test_update_completed_flag(self, mgr: CalendarManager) -> None:
        evt = mgr.create(title="t", start="2026-08-07T09:00", end="2026-08-07T09:30")
        assert mgr.update(evt["id"], completed=True)["completed"] is True
        assert mgr.update(evt["id"], completed=False)["completed"] is False

    def test_update_notes(self, mgr: CalendarManager) -> None:
        evt = mgr.create(title="t", start="2026-08-07T09:00", end="2026-08-07T09:30")
        updated = mgr.update(evt["id"], notes="备注内容")
        assert updated["notes"] == "备注内容"

    def test_update_refreshes_updated_at(self, mgr: CalendarManager) -> None:
        evt = mgr.create(title="t", start="2026-08-07T09:00", end="2026-08-07T09:30")
        original = evt["updated_at"]
        updated = mgr.update(evt["id"], title="t2")
        assert updated["updated_at"] >= original
        assert updated["created_at"] == evt["created_at"]  # created_at 不动

    def test_update_missing_raises(self, mgr: CalendarManager) -> None:
        with pytest.raises(OfficeNotFoundError):
            mgr.update("evt_ghost", title="t")

    def test_update_empty_title_rejected(self, mgr: CalendarManager) -> None:
        evt = mgr.create(title="t", start="2026-08-07T09:00", end="2026-08-07T09:30")
        with pytest.raises(OfficeValidationError):
            mgr.update(evt["id"], title="   ")

    def test_update_inverted_range_rejected(self, mgr: CalendarManager) -> None:
        evt = mgr.create(title="t", start="2026-08-07T09:00", end="2026-08-07T09:30")
        with pytest.raises(OfficeValidationError):
            mgr.update(evt["id"], start="2026-08-07T10:00", end="2026-08-07T09:00")

    def test_update_conflict_rejected_without_force(self, mgr: CalendarManager) -> None:
        mgr.create(title="A", start="2026-08-07T14:00", end="2026-08-07T15:00")
        evt_b = mgr.create(
            title="B", start="2026-08-07T16:00", end="2026-08-07T17:00"
        )
        with pytest.raises(OfficeConflictError):
            mgr.update(evt_b["id"], start="2026-08-07T14:30", end="2026-08-07T15:30")

    def test_update_conflict_force_succeeds(self, mgr: CalendarManager) -> None:
        mgr.create(title="A", start="2026-08-07T14:00", end="2026-08-07T15:00")
        evt_b = mgr.create(
            title="B", start="2026-08-07T16:00", end="2026-08-07T17:00"
        )
        updated = mgr.update(
            evt_b["id"], start="2026-08-07T14:30", end="2026-08-07T15:30", force=True
        )
        assert updated["start_iso"].startswith("2026-08-07T14:30")
        assert len(updated["conflicts"]) == 1

    def test_update_self_overlap_not_conflict(self, mgr: CalendarManager) -> None:
        """更新时间时排除自身（同一时刻微调不误判冲突）。"""
        evt = mgr.create(title="t", start="2026-08-07T09:00", end="2026-08-07T09:30")
        updated = mgr.update(evt["id"], start="2026-08-07T09:00", end="2026-08-07T09:45")
        assert updated["end_iso"].startswith("2026-08-07T09:45")


class TestDelete:
    """M34.2：CalendarManager.delete。"""

    def test_delete_existing(self, mgr: CalendarManager) -> None:
        evt = mgr.create(title="t", start="2026-08-07T09:00", end="2026-08-07T09:30")
        mgr.delete(evt["id"])
        with pytest.raises(OfficeNotFoundError):
            mgr.get(evt["id"])

    def test_delete_missing_raises(self, mgr: CalendarManager) -> None:
        with pytest.raises(OfficeNotFoundError):
            mgr.delete("evt_ghost")
