"""omni_office 跨模块工作流：文档 × 日程 × 邮件 的流程衔接。

- :meth:`OfficeWorkflows.meeting_prep`：会议准备一条龙 —— 冲突预检（原子拒绝）
  → 建档会议纪要文档 → 创建日程并回链 ``doc_id`` → 向全部参会人发送邀请邮件
- :meth:`OfficeWorkflows.email_to_event`：邮件 → 日程 —— 从收件箱邮件快速建档
  日程（标题取邮件主题、备注引用邮件 id），并向发件人回复确认、原邮件置已读
"""

from __future__ import annotations

from typing import Any

from .db import OfficeDB
from .documents import DocumentManager
from .emails import EmailManager
from .errors import (
    OfficeConflictError,
    OfficeNotFoundError,
    OfficeValidationError,
)
from .events import CalendarManager, _iso, parse_time
from .templates import render_template

#: 会议纪要文档内置模板
_MEETING_DOC_TEMPLATE = """# 会议纪要：{{title}}

- 时间：{{start_iso}} ~ {{end_iso}}
- 参会人：{{attendees}}

## 议程
{{agenda}}

## 讨论记录

（待补充）

## 行动项

（待补充）
"""

#: 会议邀请邮件内置模板
_MEETING_INVITE_SUBJECT = "会议邀请：{{title}}"
_MEETING_INVITE_BODY = """您好：

诚邀您参加「{{title}}」。

- 时间：{{start_iso}} ~ {{end_iso}}
- 议程：
{{agenda}}

会议纪要已建档（文档编号 {{doc_id}}），会后可查阅更新。

—— AI-Omni 办公助手
"""

#: 邮件转日程的默认确认回复模板
_EMAIL_TO_EVENT_REPLY_SUBJECT = "已为您建档日程：{{subject}}"
_EMAIL_TO_EVENT_REPLY_BODY = """{{sender}} 您好：

您的邮件「{{subject}}」已建档为日程：
- 时间：{{start_iso}} ~ {{end_iso}}

如需调整请直接回复本邮件。

—— AI-Omni 办公助手
"""


class OfficeWorkflows:
    """跨模块工作流编排器。"""

    def __init__(
        self,
        db: OfficeDB,
        documents: DocumentManager,
        emails: EmailManager,
        calendar: CalendarManager,
    ) -> None:
        self.db = db
        self.documents = documents
        self.emails = emails
        self.calendar = calendar

    # ------------------------------------------------------------------
    # 会议准备：文档 × 日程 × 邮件
    # ------------------------------------------------------------------
    def meeting_prep(
        self,
        title: str,
        start: str | int | float,
        end: str | int | float,
        attendees: list[str],
        agenda: str | None = None,
        reminder_minutes: int | None = 15,
        force: bool = False,
    ) -> dict[str, Any]:
        """会议准备一条龙。

        步骤：冲突预检（``force=False`` 且有冲突时整体拒绝，不产生任何记录）
        → 创建会议纪要文档 → 创建日程并回链 ``doc_id`` → 逐位参会人发送邀请邮件。

        :return: ``{"event_id", "doc_id", "emails_sent", "conflicts"}``
        :raises OfficeValidationError: 参会人为空 / 标题为空 / 时间非法
        :raises OfficeConflictError: 时间冲突且未 force
        """
        title = (title or "").strip()
        if not title:
            raise OfficeValidationError("会议标题不能为空")
        attendee_list = [str(a).strip() for a in (attendees or []) if str(a).strip()]
        if not attendee_list:
            raise OfficeValidationError("参会人不能为空")
        # 先解析时间（非法时间在任何写入前暴露）
        start_ts = parse_time(start)
        end_ts = parse_time(end)
        if end_ts <= start_ts:
            raise OfficeValidationError("结束时间必须晚于开始时间")
        # 冲突预检：原子拒绝
        conflicts = self.calendar.check_conflicts(start_ts, end_ts)
        if conflicts and not force:
            names = "、".join(c["title"] for c in conflicts)
            raise OfficeConflictError(f"日程冲突: 与「{names}」时间重叠", conflicts=conflicts)

        start_iso = _iso(start_ts)
        end_iso = _iso(end_ts)
        template_vars = {
            "title": title,
            "start_iso": start_iso,
            "end_iso": end_iso,
            "attendees": ", ".join(attendee_list),
            "agenda": agenda or "（待定）",
        }

        # 1. 建档会议纪要文档
        doc = self.documents.create(
            title=f"会议纪要：{title}",
            content=render_template(_MEETING_DOC_TEMPLATE, template_vars),
            tags=["会议"],
        )
        # 2. 创建日程并回链文档
        event = self.calendar.create(
            title=title,
            start=start_ts,
            end=end_ts,
            attendees=attendee_list,
            reminder_minutes=reminder_minutes,
            doc_id=doc["id"],
            force=True,  # 冲突已在上方预检，此处不再重复拦截
        )
        # 3. 逐位参会人发送邀请邮件
        for attendee in attendee_list:
            self.emails.send(
                to=[attendee],
                subject=render_template(_MEETING_INVITE_SUBJECT, template_vars),
                body=render_template(
                    _MEETING_INVITE_BODY, {**template_vars, "doc_id": doc["id"]}
                ),
            )
        return {
            "event_id": event["id"],
            "doc_id": doc["id"],
            "emails_sent": len(attendee_list),
            "conflicts": conflicts,
        }

    # ------------------------------------------------------------------
    # 邮件 → 日程
    # ------------------------------------------------------------------
    def email_to_event(
        self,
        email_uid: str,
        start: str | int | float,
        end: str | int | float,
        reply_template: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """从收件箱邮件快速建档日程并回复确认。

        日程标题取自邮件主题，备注引用本地邮件 id；确认回复发给发件人，
        原邮件置为已读。

        :param email_uid: 后端邮件 uid（先经 ``fetch_inbox`` 入库）
        :param reply_template: 自定义回复正文模板（可引用 ``{{sender}}`` /
            ``{{subject}}`` / ``{{start_iso}}`` / ``{{end_iso}}``）；缺省用内置模板
        :return: ``{"event_id", "email_id"}``
        :raises OfficeNotFoundError: 给定 uid 的收件箱邮件不存在
        """
        row = self.db.conn.execute(
            "SELECT id, sender, subject FROM emails WHERE folder = 'inbox' AND uid = ?",
            (email_uid,),
        ).fetchone()
        if row is None:
            raise OfficeNotFoundError(f"收件箱中不存在 uid 为 {email_uid} 的邮件")
        email_id: str = row["id"]
        sender: str = row["sender"] or ""
        subject: str = row["subject"] or ""

        start_ts = parse_time(start)
        end_ts = parse_time(end)
        start_iso = _iso(start_ts)
        end_iso = _iso(end_ts)

        event = self.calendar.create(
            title=f"邮件日程：{subject}",
            start=start_ts,
            end=end_ts,
            attendees=[sender] if sender else [],
            notes=f"来源邮件：{email_id}（发件人 {sender}）",
            force=force,
        )
        vars = {
            "sender": sender,
            "subject": subject,
            "start_iso": start_iso,
            "end_iso": end_iso,
        }
        reply_subject = render_template(_EMAIL_TO_EVENT_REPLY_SUBJECT, vars)
        reply_body = render_template(reply_template or _EMAIL_TO_EVENT_REPLY_BODY, vars)
        if sender:
            self.emails.send(to=[sender], subject=reply_subject, body=reply_body)
        self.emails.mark_read(email_id)
        return {"event_id": event["id"], "email_id": email_id}
