"""omni_office 工具层（tools.py）契约测试。

验证：
- 20 个 office_* 工具全部登记在 TOOLS 注册表，schema 合法
- handler 返回统一 JSON 信封：ok:true + data / ok:false + error{code,message}
- 领域异常 → 错误码映射（E_VALIDATION→E_INVALID_PARAMS / E_NOT_FOUND /
  E_EVENT_CONFLICT / E_TEMPLATE_ERROR / E_BACKEND_UNAVAILABLE）
- 事件总线发布（doc_created / event_created / email_sent / workflow_completed）
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from omni_office import tools
from omni_office.backends import FakeEmailBackend
from omni_office.db import OfficeDB

EXPECTED_TOOLS = {
    # 文档
    "office_doc_create",
    "office_doc_update",
    "office_doc_get",
    "office_doc_list",
    "office_doc_versions",
    "office_doc_rollback",
    # 邮件
    "office_email_send",
    "office_email_inbox",
    "office_email_mark_read",
    "office_email_template_save",
    "office_email_template_list",
    "office_email_auto_reply",
    "office_email_process_inbox",
    # 日程
    "office_event_create",
    "office_event_list",
    "office_event_reminders",
    "office_event_check_conflicts",
    # 工作流
    "office_meeting_prep",
    "office_email_to_event",
    "office_status",
    # 移动端日程桥接（M34.2）
    "schedule_list_events",
    "schedule_create_event",
    "schedule_update_event",
    "schedule_delete_event",
}


class FakeBus:
    """同步事件总线 fake，收集 publish 调用。"""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


@pytest.fixture()
def rt():
    runtime = tools._reset_runtime()
    runtime.db = OfficeDB(":memory:")
    runtime.db.init_schema()
    runtime.email_backend = FakeEmailBackend()
    yield runtime
    runtime.db.close()
    tools._reset_runtime()


def _call(tool_name: str, **kwargs: Any) -> dict[str, Any]:
    """按名调用工具函数并解析 JSON 信封。"""
    meta = next(m for m in tools.TOOLS if m["name"] == tool_name)
    return json.loads(meta["handler_func"](**kwargs))


class TestRegistry:
    def test_all_expected_tools_registered(self) -> None:
        names = {m["name"] for m in tools.TOOLS}
        assert names == EXPECTED_TOOLS

    def test_schemas_are_valid(self) -> None:
        for meta in tools.TOOLS:
            schema = meta["schema"]
            assert schema["name"] == meta["name"]
            assert schema["description"]
            params = schema["parameters"]
            assert params["type"] == "object"
            assert isinstance(params["properties"], dict)
            assert meta["description"]
            assert meta["emoji"]


class TestDocTools:
    def test_doc_lifecycle(self, rt) -> None:  # noqa: ANN001
        created = _call("office_doc_create", title="周报", content="v1")
        assert created["ok"] is True
        doc_id = created["data"]["doc_id"]

        updated = _call("office_doc_update", doc_id=doc_id, content="v2")
        assert updated["data"]["version"] == 2

        got = _call("office_doc_get", doc_id=doc_id)
        assert got["data"]["content"] == "v2"

        versions = _call("office_doc_versions", doc_id=doc_id)
        assert len(versions["data"]["versions"]) == 2

        rolled = _call("office_doc_rollback", doc_id=doc_id, version=1)
        assert rolled["data"]["rolled_back_to"] == 1

        listed = _call("office_doc_list")
        assert len(listed["data"]["documents"]) == 1

    def test_doc_get_missing_returns_not_found(self, rt) -> None:  # noqa: ANN001
        result = _call("office_doc_get", doc_id="doc_nope")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_NOT_FOUND"

    def test_doc_create_empty_title_returns_invalid_params(self, rt) -> None:  # noqa: ANN001
        result = _call("office_doc_create", title="", content="x")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    def test_doc_create_publishes_event(self, rt) -> None:  # noqa: ANN001
        bus = FakeBus()
        rt.event_publisher = bus
        _call("office_doc_create", title="t", content="c")
        assert any(e[0] == "office.doc_created" for e in bus.events)


class TestEmailTools:
    def test_template_save_and_list(self, rt) -> None:  # noqa: ANN001
        saved = _call(
            "office_email_template_save", name="n1", subject="s {{x}}", body="b"
        )
        assert saved["ok"] is True
        listed = _call("office_email_template_list")
        assert [t["name"] for t in listed["data"]["templates"]] == ["n1"]

    def test_send_with_fake_backend(self, rt) -> None:  # noqa: ANN001
        result = _call(
            "office_email_send", to=["a@x.com"], subject="hi", body="yo"
        )
        assert result["ok"] is True
        assert result["data"]["email_id"].startswith("mail_")

    def test_send_backend_unavailable(self, rt) -> None:  # noqa: ANN001
        from omni_office.backends import SmtpEmailBackend

        rt.email_backend = SmtpEmailBackend()  # 无 SMTP 配置
        result = _call("office_email_send", to=["a@x.com"], subject="s", body="b")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"

    def test_inbox_fetch_and_mark_read(self, rt) -> None:  # noqa: ANN001
        rt.email_backend.queue_incoming(uid="u1", sender="s@x.com", subject="s", body="b")
        inbox = _call("office_email_inbox", fetch=True)
        assert inbox["ok"] is True
        assert len(inbox["data"]["emails"]) == 1
        email_id = inbox["data"]["emails"][0]["id"]

        marked = _call("office_email_mark_read", email_id=email_id)
        assert marked["ok"] is True

        unread = _call("office_email_inbox", unread_only=True)
        assert unread["data"]["emails"] == []

    def test_auto_reply_rule_actions(self, rt) -> None:  # noqa: ANN001
        _call("office_email_template_save", name="away", subject="s", body="b")
        added = _call(
            "office_email_auto_reply", action="add", name="r1",
            keyword="报价", template="away",
        )
        assert added["ok"] is True
        listed = _call("office_email_auto_reply", action="list")
        assert len(listed["data"]["rules"]) == 1
        removed = _call("office_email_auto_reply", action="remove", name="r1")
        assert removed["ok"] is True
        bad = _call("office_email_auto_reply", action="explode")
        assert bad["error"]["code"] == "E_INVALID_PARAMS"

    def test_process_inbox(self, rt) -> None:  # noqa: ANN001
        _call("office_email_template_save", name="away", subject="Re", body="收到")
        _call(
            "office_email_auto_reply", action="add", name="r1",
            keyword="报价", template="away",
        )
        rt.email_backend.queue_incoming(uid="u1", sender="c@x.com", subject="报价", body="")
        result = _call("office_email_process_inbox", fetch=True)
        assert result["ok"] is True
        assert result["data"]["replies_sent"] == 1


class TestEventTools:
    def test_event_create_and_list(self, rt) -> None:  # noqa: ANN001
        created = _call(
            "office_event_create",
            title="站会", start="2026-08-07T09:30", end="2026-08-07T09:45",
        )
        assert created["ok"] is True
        assert created["data"]["event"]["id"].startswith("evt_")

        listed = _call("office_event_list")
        assert len(listed["data"]["events"]) == 1

    def test_event_conflict_error_code(self, rt) -> None:  # noqa: ANN001
        _call("office_event_create", title="A", start="2026-08-07T14:00", end="2026-08-07T15:00")
        conflict = _call(
            "office_event_create", title="B",
            start="2026-08-07T14:30", end="2026-08-07T15:30",
        )
        assert conflict["ok"] is False
        assert conflict["error"]["code"] == "E_EVENT_CONFLICT"

        forced = _call(
            "office_event_create", title="B",
            start="2026-08-07T14:30", end="2026-08-07T15:30", force=True,
        )
        assert forced["ok"] is True
        assert len(forced["data"]["conflicts"]) == 1

    def test_check_conflicts_tool(self, rt) -> None:  # noqa: ANN001
        _call("office_event_create", title="A", start="2026-08-07T14:00", end="2026-08-07T15:00")
        result = _call(
            "office_event_check_conflicts",
            start="2026-08-07T14:30", end="2026-08-07T16:00",
        )
        assert result["ok"] is True
        assert len(result["data"]["conflicts"]) == 1

    def test_reminders_tool(self, rt) -> None:  # noqa: ANN001
        _call(
            "office_event_create", title="评审",
            start="2026-08-07T14:00", end="2026-08-07T15:00", reminder_minutes=15,
        )
        result = _call("office_event_reminders", now="2026-08-07T13:50")
        assert result["ok"] is True
        assert len(result["data"]["reminders"]) == 1

    def test_event_create_publishes_event(self, rt) -> None:  # noqa: ANN001
        bus = FakeBus()
        rt.event_publisher = bus
        _call("office_event_create", title="t", start="2026-08-07T09:00", end="2026-08-07T09:30")
        assert any(e[0] == "office.event_created" for e in bus.events)

    def test_bad_time_returns_invalid_params(self, rt) -> None:  # noqa: ANN001
        result = _call(
            "office_event_create", title="t", start="火星时间", end="2026-08-07T09:30"
        )
        assert result["error"]["code"] == "E_INVALID_PARAMS"


class TestWorkflowTools:
    def test_meeting_prep(self, rt) -> None:  # noqa: ANN001
        result = _call(
            "office_meeting_prep",
            title="评审", start="2026-08-07T14:00", end="2026-08-07T15:00",
            attendees=["a@x.com"], agenda="议题",
        )
        assert result["ok"] is True
        assert result["data"]["emails_sent"] == 1
        assert result["data"]["doc_id"].startswith("doc_")
        assert result["data"]["event_id"].startswith("evt_")

    def test_meeting_prep_conflict(self, rt) -> None:  # noqa: ANN001
        _call("office_event_create", title="A", start="2026-08-07T14:00", end="2026-08-07T15:00")
        result = _call(
            "office_meeting_prep", title="B",
            start="2026-08-07T14:30", end="2026-08-07T15:30", attendees=["a@x.com"],
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "E_EVENT_CONFLICT"

    def test_meeting_prep_publishes_workflow_event(self, rt) -> None:  # noqa: ANN001
        bus = FakeBus()
        rt.event_publisher = bus
        _call(
            "office_meeting_prep", title="t",
            start="2026-08-07T14:00", end="2026-08-07T15:00", attendees=["a@x.com"],
        )
        assert any(e[0] == "office.workflow_completed" for e in bus.events)

    def test_email_to_event(self, rt) -> None:  # noqa: ANN001
        rt.email_backend.queue_incoming(
            uid="u1", sender="client@x.com", subject="约个评审", body="下周聊"
        )
        tools._emails(rt).fetch_inbox()
        result = _call(
            "office_email_to_event",
            email_uid="u1", start="2026-08-10T10:00", end="2026-08-10T11:00",
        )
        assert result["ok"] is True
        assert result["data"]["event_id"].startswith("evt_")
        assert rt.email_backend.outbox[0].to == ["client@x.com"]

    def test_email_to_event_unknown_uid(self, rt) -> None:  # noqa: ANN001
        result = _call(
            "office_email_to_event",
            email_uid="ghost", start="2026-08-10T10:00", end="2026-08-10T11:00",
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "E_NOT_FOUND"


class TestStatusTool:
    def test_status_counts(self, rt) -> None:  # noqa: ANN001
        _call("office_doc_create", title="t", content="c")
        _call("office_event_create", title="e", start="2026-08-07T09:00", end="2026-08-07T09:30")
        result = _call("office_status")
        assert result["ok"] is True
        data = result["data"]
        assert data["documents"] == 1
        assert data["events"] == 1
        assert data["emails"] == 0
        assert "db_path" in data


class TestHandlerAdapter:
    def test_make_handler_wraps_args_dict(self, rt) -> None:  # noqa: ANN001
        handler = tools._make_handler(
            next(m for m in tools.TOOLS if m["name"] == "office_doc_create")["handler_func"]
        )
        out = json.loads(handler({"title": "经 dict 调用", "content": "x"}))
        assert out["ok"] is True

    def test_make_handler_unexpected_error_returns_json(self, rt) -> None:  # noqa: ANN001
        handler = tools._make_handler(
            next(m for m in tools.TOOLS if m["name"] == "office_doc_get")["handler_func"]
        )
        # doc_id 缺失 → TypeError → 错误信封而非异常
        out = json.loads(handler({}))
        assert out["ok"] is False
        assert "code" in out["error"]


class TestRegister:
    def test_register_populates_ctx(self) -> None:
        class Ctx:
            def __init__(self) -> None:
                self.tools: list[dict[str, Any]] = []
                self.event_bus: Any = None

            def register_tool(self, **kwargs: Any) -> None:
                self.tools.append(kwargs)

        ctx = Ctx()
        tools.register(ctx)
        assert len(ctx.tools) == len(EXPECTED_TOOLS)
        for t in ctx.tools:
            assert callable(t["handler_func"])
