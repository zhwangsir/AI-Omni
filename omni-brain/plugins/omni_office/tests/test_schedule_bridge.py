"""omni_office 移动端日程桥接（schedule_bridge.py）单元测试。

契约：
- UniHub 扁平模型（``date`` + ``time`` + ``completed``）↔ omni 区间模型
  （``start_ts`` ~ ``end_ts``）互转
- 定时日程默认 30 分钟；``time=None`` 全天（00:00 ~ 23:59 本地时区）
- ``schedule_create_event`` 保留 UniHub 传入的 id；
  ``createdAt``/``updatedAt``（毫秒）↔ ``created_at``/``updated_at``（秒）
- ``schedule_update_event`` 的 time 哨兵：未传 = 不改，null = 转全天，
  "HH:MM" = 定时；只传 date 时保留原时刻
- 共享 events 表：``office_event_create`` 建的日程也能被
  ``schedule_list_events`` 读出（映射为 UniHub 结构）
- 错误码：非法参数 E_INVALID_PARAMS；事件不存在 E_NOT_FOUND
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytest

from omni_office import tools
from omni_office.db import OfficeDB

SCHEDULE_TOOLS = {
    "schedule_list_events",
    "schedule_create_event",
    "schedule_update_event",
    "schedule_delete_event",
}


@pytest.fixture()
def rt():
    runtime = tools._reset_runtime()
    runtime.db = OfficeDB(":memory:")
    runtime.db.init_schema()
    yield runtime
    runtime.db.close()
    tools._reset_runtime()


def _call(tool_name: str, **kwargs: Any) -> dict[str, Any]:
    """按名调用工具函数并解析 JSON 信封。"""
    meta = next(m for m in tools.TOOLS if m["name"] == tool_name)
    return json.loads(meta["handler_func"](**kwargs))


def _ts(date: str, time_str: str) -> float:
    """本地日期+时刻 → epoch 秒（测试期望值用）。"""
    return datetime.fromisoformat(f"{date}T{time_str}").timestamp()


class TestRegistry:
    def test_schedule_tools_registered(self) -> None:
        names = {m["name"] for m in tools.TOOLS}
        assert SCHEDULE_TOOLS <= names


class TestCreate:
    def test_create_timed_event(self, rt) -> None:  # noqa: ANN001
        res = _call(
            "schedule_create_event",
            id="evt_uni_001",
            title="团队晨会",
            date="2026-08-07",
            time="09:30",
        )
        assert res["ok"] is True
        evt = res["data"]["event"]
        assert evt["id"] == "evt_uni_001"  # UniHub id 原样保留
        assert evt["title"] == "团队晨会"
        assert evt["date"] == "2026-08-07"
        assert evt["time"] == "09:30"
        assert evt["completed"] is False
        assert evt["note"] == ""
        assert isinstance(evt["createdAt"], int)  # 毫秒
        assert evt["updatedAt"] >= evt["createdAt"]

    def test_create_all_day_event(self, rt) -> None:  # noqa: ANN001
        res = _call(
            "schedule_create_event",
            id="evt_uni_002",
            title="提交周报",
            date="2026-08-07",
            time=None,
        )
        assert res["ok"] is True
        assert res["data"]["event"]["time"] is None

    def test_create_maps_to_interval_30min(self, rt) -> None:  # noqa: ANN001
        """定时日程入库为 30 分钟区间（共享 events 表，office 侧可读）。"""
        _call(
            "schedule_create_event",
            id="evt_uni_003",
            title="评审",
            date="2026-08-07",
            time="14:00",
        )
        got = _call("office_event_list")
        evt = next(e for e in got["data"]["events"] if e["id"] == "evt_uni_003")
        assert evt["start_ts"] == pytest.approx(_ts("2026-08-07", "14:00"))
        assert evt["end_ts"] == pytest.approx(_ts("2026-08-07", "14:00") + 1800)

    def test_create_all_day_maps_to_full_day_interval(self, rt) -> None:  # noqa: ANN001
        """全天日程入库为 00:00 ~ 23:59 区间。"""
        _call(
            "schedule_create_event",
            id="evt_uni_004",
            title="周报",
            date="2026-08-07",
            time=None,
        )
        got = _call("office_event_list")
        evt = next(e for e in got["data"]["events"] if e["id"] == "evt_uni_004")
        assert evt["start_ts"] == pytest.approx(_ts("2026-08-07", "00:00"))
        assert evt["end_ts"] == pytest.approx(_ts("2026-08-07", "23:59"))

    def test_create_with_note_and_completed(self, rt) -> None:  # noqa: ANN001
        res = _call(
            "schedule_create_event",
            id="evt_uni_005",
            title="已办事项",
            date="2026-08-07",
            time="10:00",
            completed=True,
            note="已完成备注",
        )
        assert res["ok"] is True
        evt = res["data"]["event"]
        assert evt["completed"] is True
        assert evt["note"] == "已完成备注"

    def test_create_preserves_created_at_ms(self, rt) -> None:  # noqa: ANN001
        """UniHub 传入 createdAt（毫秒）→ 库内秒级 created_at。"""
        ms = 1_786_000_000_000
        res = _call(
            "schedule_create_event",
            id="evt_uni_006",
            title="带时间戳",
            date="2026-08-07",
            time="10:00",
            createdAt=ms,
        )
        assert res["ok"] is True
        assert res["data"]["event"]["createdAt"] == ms

    def test_create_empty_title_rejected(self, rt) -> None:  # noqa: ANN001
        res = _call("schedule_create_event", title="  ", date="2026-08-07")
        assert res["ok"] is False
        assert res["error"]["code"] == "E_INVALID_PARAMS"

    def test_create_bad_date_rejected(self, rt) -> None:  # noqa: ANN001
        res = _call(
            "schedule_create_event", title="t", date="2026-13-45", time="10:00"
        )
        assert res["ok"] is False
        assert res["error"]["code"] == "E_INVALID_PARAMS"

    def test_create_bad_time_rejected(self, rt) -> None:  # noqa: ANN001
        res = _call(
            "schedule_create_event", title="t", date="2026-08-07", time="25:99"
        )
        assert res["ok"] is False
        assert res["error"]["code"] == "E_INVALID_PARAMS"


class TestList:
    def test_list_empty(self, rt) -> None:  # noqa: ANN001
        res = _call("schedule_list_events")
        assert res["ok"] is True
        assert res["data"]["events"] == []

    def test_list_returns_uni_schema(self, rt) -> None:  # noqa: ANN001
        _call(
            "schedule_create_event",
            id="evt_a",
            title="A",
            date="2026-08-07",
            time="09:00",
            note="na",
        )
        _call(
            "schedule_create_event",
            id="evt_b",
            title="B",
            date="2026-08-08",
            time=None,
        )
        res = _call("schedule_list_events")
        events = res["data"]["events"]
        assert len(events) == 2
        by_id = {e["id"]: e for e in events}
        assert by_id["evt_a"]["time"] == "09:00"
        assert by_id["evt_a"]["note"] == "na"
        assert by_id["evt_b"]["time"] is None  # 全天
        for e in events:
            assert set(e) >= {
                "id",
                "title",
                "date",
                "time",
                "completed",
                "note",
                "createdAt",
                "updatedAt",
            }

    def test_list_includes_office_created_events(self, rt) -> None:  # noqa: ANN001
        """office_event_create 建的日程同样映射为 UniHub 结构。"""
        _call(
            "office_event_create",
            title="桌面端会议",
            start="2026-08-07T14:00",
            end="2026-08-07T15:00",
            notes="办公室创建",
        )
        res = _call("schedule_list_events")
        evt = res["data"]["events"][0]
        assert evt["title"] == "桌面端会议"
        assert evt["date"] == "2026-08-07"
        assert evt["time"] == "14:00"
        assert evt["note"] == "办公室创建"
        assert evt["completed"] is False


class TestUpdate:
    def test_update_title_and_note(self, rt) -> None:  # noqa: ANN001
        _call(
            "schedule_create_event",
            id="evt_u1",
            title="原标题",
            date="2026-08-07",
            time="09:00",
        )
        res = _call(
            "schedule_update_event", id="evt_u1", title="新标题", note="新备注"
        )
        assert res["ok"] is True
        evt = res["data"]["event"]
        assert evt["title"] == "新标题"
        assert evt["note"] == "新备注"
        assert evt["date"] == "2026-08-07"  # 未传字段不变
        assert evt["time"] == "09:00"

    def test_update_completed_toggle(self, rt) -> None:  # noqa: ANN001
        _call(
            "schedule_create_event",
            id="evt_u2",
            title="t",
            date="2026-08-07",
            time=None,
        )
        res = _call("schedule_update_event", id="evt_u2", completed=True)
        assert res["ok"] is True
        assert res["data"]["event"]["completed"] is True
        res2 = _call("schedule_update_event", id="evt_u2", completed=False)
        assert res2["data"]["event"]["completed"] is False

    def test_update_time_to_all_day(self, rt) -> None:  # noqa: ANN001
        """time 显式传 null → 转全天。"""
        _call(
            "schedule_create_event",
            id="evt_u3",
            title="t",
            date="2026-08-07",
            time="09:00",
        )
        res = _call("schedule_update_event", id="evt_u3", time=None)
        assert res["ok"] is True
        assert res["data"]["event"]["time"] is None

    def test_update_all_day_to_timed(self, rt) -> None:  # noqa: ANN001
        """全天 → 定时。"""
        _call(
            "schedule_create_event",
            id="evt_u4",
            title="t",
            date="2026-08-07",
            time=None,
        )
        res = _call("schedule_update_event", id="evt_u4", time="15:30")
        assert res["ok"] is True
        assert res["data"]["event"]["time"] == "15:30"

    def test_update_date_keeps_time(self, rt) -> None:  # noqa: ANN001
        """只改 date 时保留原时刻。"""
        _call(
            "schedule_create_event",
            id="evt_u5",
            title="t",
            date="2026-08-07",
            time="09:30",
        )
        res = _call("schedule_update_event", id="evt_u5", date="2026-08-10")
        assert res["ok"] is True
        evt = res["data"]["event"]
        assert evt["date"] == "2026-08-10"
        assert evt["time"] == "09:30"

    def test_update_refreshes_updated_at(self, rt) -> None:  # noqa: ANN001
        _call(
            "schedule_create_event",
            id="evt_u6",
            title="t",
            date="2026-08-07",
            time="09:00",
            createdAt=1_000_000_000_000,
        )
        res = _call("schedule_update_event", id="evt_u6", title="t2")
        evt = res["data"]["event"]
        assert evt["createdAt"] == 1_000_000_000_000  # createdAt 不动
        assert evt["updatedAt"] > 1_000_000_000_000  # updatedAt 刷新

    def test_update_not_found(self, rt) -> None:  # noqa: ANN001
        res = _call("schedule_update_event", id="evt_ghost", title="t")
        assert res["ok"] is False
        assert res["error"]["code"] == "E_NOT_FOUND"

    def test_update_empty_title_rejected(self, rt) -> None:  # noqa: ANN001
        _call(
            "schedule_create_event",
            id="evt_u7",
            title="t",
            date="2026-08-07",
            time=None,
        )
        res = _call("schedule_update_event", id="evt_u7", title="  ")
        assert res["ok"] is False
        assert res["error"]["code"] == "E_INVALID_PARAMS"

    def test_update_bad_date_rejected(self, rt) -> None:  # noqa: ANN001
        _call(
            "schedule_create_event",
            id="evt_u8",
            title="t",
            date="2026-08-07",
            time=None,
        )
        res = _call("schedule_update_event", id="evt_u8", date="2026-08-32")
        assert res["ok"] is False
        assert res["error"]["code"] == "E_INVALID_PARAMS"


class TestDelete:
    def test_delete_existing(self, rt) -> None:  # noqa: ANN001
        _call(
            "schedule_create_event",
            id="evt_d1",
            title="t",
            date="2026-08-07",
            time=None,
        )
        res = _call("schedule_delete_event", id="evt_d1")
        assert res["ok"] is True
        listed = _call("schedule_list_events")
        assert listed["data"]["events"] == []

    def test_delete_not_found(self, rt) -> None:  # noqa: ANN001
        res = _call("schedule_delete_event", id="evt_ghost")
        assert res["ok"] is False
        assert res["error"]["code"] == "E_NOT_FOUND"


class TestRoundTrip:
    def test_create_list_roundtrip(self, rt) -> None:  # noqa: ANN001
        """UniHub 完整事件结构 create → list 读回字段一致。"""
        src = {
            "id": "evt_rt_1",
            "title": "方案评审",
            "date": "2026-08-08",
            "time": "14:00",
            "completed": False,
            "note": "带文档",
        }
        _call("schedule_create_event", **src)
        res = _call("schedule_list_events")
        evt = next(e for e in res["data"]["events"] if e["id"] == "evt_rt_1")
        for key, value in src.items():
            assert evt[key] == value
