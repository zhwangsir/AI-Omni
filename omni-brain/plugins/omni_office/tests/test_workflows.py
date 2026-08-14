"""omni_office 跨模块工作流（workflows.py）单元测试。

``meeting_prep`` 契约（文档 × 日程 × 邮件 三模块衔接）：
1. 冲突预检（force=False 且冲突 → 整体拒绝，不产生任何记录）
2. 创建会议纪要文档（内置模板，含议程/参会人/时间）
3. 创建日程并回链 ``doc_id``
4. 向全部参会人发送邀请邮件（模板渲染会议信息 + 纪要文档引用）
5. 返回 {event_id, doc_id, emails_sent, conflicts}
"""

from __future__ import annotations

import pytest

from omni_office.backends import FakeEmailBackend
from omni_office.db import OfficeDB
from omni_office.documents import DocumentManager
from omni_office.emails import EmailManager
from omni_office.errors import OfficeConflictError, OfficeValidationError
from omni_office.events import CalendarManager
from omni_office.workflows import OfficeWorkflows


@pytest.fixture()
def backend() -> FakeEmailBackend:
    return FakeEmailBackend()


@pytest.fixture()
def wf(backend: FakeEmailBackend):
    db = OfficeDB(":memory:")
    db.init_schema()
    wf = OfficeWorkflows(
        db=db,
        documents=DocumentManager(db),
        emails=EmailManager(db, backend),
        calendar=CalendarManager(db),
    )
    yield wf
    db.close()


class TestMeetingPrep:
    def test_full_chain(self, wf: OfficeWorkflows, backend: FakeEmailBackend) -> None:
        result = wf.meeting_prep(
            title="Q3 规划评审",
            start="2026-08-07T14:00",
            end="2026-08-07T15:00",
            attendees=["a@x.com", "b@x.com"],
            agenda="1. 目标对齐\n2. 排期",
        )
        assert result["event_id"].startswith("evt_")
        assert result["doc_id"].startswith("doc_")
        assert result["emails_sent"] == 2
        assert result["conflicts"] == []

        # 日程回链纪要文档
        event = wf.calendar.get(result["event_id"])
        assert event["doc_id"] == result["doc_id"]

        # 纪要文档内容包含会议信息
        doc = wf.documents.get(result["doc_id"])
        assert "Q3 规划评审" in doc["title"]
        assert "目标对齐" in doc["content"]
        assert "a@x.com" in doc["content"]

        # 邀请邮件已发出并引用文档 id
        assert len(backend.outbox) == 2
        recipients = sorted(m.to[0] for m in backend.outbox)
        assert recipients == ["a@x.com", "b@x.com"]
        assert result["doc_id"] in backend.outbox[0].body
        assert "Q3 规划评审" in backend.outbox[0].subject

    def test_conflict_rejects_atomically(
        self, wf: OfficeWorkflows, backend: FakeEmailBackend
    ) -> None:
        wf.calendar.create(title="已有", start="2026-08-07T14:00", end="2026-08-07T15:00")
        with pytest.raises(OfficeConflictError):
            wf.meeting_prep(
                title="冲突会议",
                start="2026-08-07T14:30",
                end="2026-08-07T15:30",
                attendees=["a@x.com"],
            )
        # 原子性：不产生文档 / 邮件 / 新日程
        assert wf.documents.list_documents() == []
        assert backend.outbox == []
        assert len(wf.calendar.list_events()) == 1

    def test_force_creates_with_conflicts(self, wf: OfficeWorkflows) -> None:
        wf.calendar.create(title="已有", start="2026-08-07T14:00", end="2026-08-07T15:00")
        result = wf.meeting_prep(
            title="挤一挤",
            start="2026-08-07T14:30",
            end="2026-08-07T15:30",
            attendees=["a@x.com"],
            force=True,
        )
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["title"] == "已有"

    def test_empty_attendees_rejected(self, wf: OfficeWorkflows) -> None:
        with pytest.raises(OfficeValidationError):
            wf.meeting_prep(
                title="t",
                start="2026-08-07T14:00",
                end="2026-08-07T15:00",
                attendees=[],
            )

    def test_default_agenda_when_omitted(
        self, wf: OfficeWorkflows, backend: FakeEmailBackend
    ) -> None:
        result = wf.meeting_prep(
            title="晨会",
            start="2026-08-07T09:00",
            end="2026-08-07T09:15",
            attendees=["a@x.com"],
        )
        doc = wf.documents.get(result["doc_id"])
        assert "议程" in doc["content"]


class TestEmailToEvent:
    """邮件 → 日程 衔接：从邮件内容快速建档日程并回复确认。"""

    def test_email_to_event(self, wf: OfficeWorkflows, backend: FakeEmailBackend) -> None:
        backend.queue_incoming(
            uid="u1", sender="client@x.com", subject="约个评审", body="下周聊"
        )
        wf.emails.fetch_inbox()
        result = wf.email_to_event(
            email_uid="u1",
            start="2026-08-10T10:00",
            end="2026-08-10T11:00",
            reply_template=None,
        )
        assert result["event_id"].startswith("evt_")
        event = wf.calendar.get(result["event_id"])
        # 日程标题取自邮件主题，备注引用邮件 id
        assert "约个评审" in event["title"]
        assert result["email_id"] in (event["notes"] or "")
        # 确认回复发给发件人
        assert backend.outbox[0].to == ["client@x.com"]
        # 原邮件已读
        mail = wf.emails.list_emails(folder="inbox")[0]
        assert mail["read"] is True

    def test_email_to_event_unknown_uid_raises(self, wf: OfficeWorkflows) -> None:
        from omni_office.errors import OfficeNotFoundError

        with pytest.raises(OfficeNotFoundError):
            wf.email_to_event(
                email_uid="ghost",
                start="2026-08-10T10:00",
                end="2026-08-10T11:00",
            )
