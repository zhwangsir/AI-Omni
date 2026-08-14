"""omni_office 邮件处理（emails.py）单元测试。

契约：
- send：支持直接 body 或 template+vars 渲染；成功写入 sent 文件夹
- fetch_inbox：经 backend 拉取并存入 inbox 文件夹（按 backend 邮件 uid 去重）
- mark_read：标记已读
- 自动回复规则：keyword（主题/正文子串，大小写不敏感）+ sender_match（发件人子串）
- process_inbox：对未读且未自动回复的邮件应用启用规则，经 backend 发送回复，
  原邮件标记 auto_replied；规则模板可引用 {{sender}} / {{subject}} 变量
"""

from __future__ import annotations

import pytest

from omni_office.backends import FakeEmailBackend
from omni_office.db import OfficeDB
from omni_office.emails import EmailManager
from omni_office.errors import (
    OfficeBackendError,
    OfficeNotFoundError,
    OfficeTemplateError,
    OfficeValidationError,
)


@pytest.fixture()
def backend() -> FakeEmailBackend:
    return FakeEmailBackend()


@pytest.fixture()
def mgr(backend: FakeEmailBackend):
    db = OfficeDB(":memory:")
    db.init_schema()
    yield EmailManager(db, backend)
    db.close()


class TestTemplates:
    def test_save_and_list(self, mgr: EmailManager) -> None:
        mgr.save_template("welcome", subject="欢迎 {{name}}", body="你好 {{name}}")
        templates = mgr.list_templates()
        assert [t["name"] for t in templates] == ["welcome"]
        assert templates[0]["subject"] == "欢迎 {{name}}"

    def test_save_upserts(self, mgr: EmailManager) -> None:
        mgr.save_template("t1", subject="旧", body="旧")
        mgr.save_template("t1", subject="新", body="新")
        templates = mgr.list_templates()
        assert len(templates) == 1
        assert templates[0]["subject"] == "新"

    def test_save_empty_name_rejected(self, mgr: EmailManager) -> None:
        with pytest.raises(OfficeValidationError):
            mgr.save_template(" ", subject="s", body="b")


class TestSend:
    def test_send_plain_body(self, mgr: EmailManager, backend: FakeEmailBackend) -> None:
        mail = mgr.send(to=["a@x.com"], subject="主题", body="正文")
        assert mail["id"].startswith("mail_")
        assert len(backend.outbox) == 1
        assert backend.outbox[0].subject == "主题"

    def test_send_persists_to_sent_folder(self, mgr: EmailManager) -> None:
        mgr.send(to=["a@x.com"], subject="s", body="b")
        sent = mgr.list_emails(folder="sent")
        assert len(sent) == 1
        assert sent[0]["subject"] == "s"
        assert sent[0]["folder"] == "sent"

    def test_send_with_template(self, mgr: EmailManager) -> None:
        mgr.save_template("notice", subject="提醒：{{title}}", body="{{name}} 请查收")
        mail = mgr.send(
            to=["b@x.com"], template="notice", vars={"title": "周报", "name": "王工"}
        )
        assert mail["subject"] == "提醒：周报"
        assert mail["body"] == "王工 请查收"

    def test_send_template_missing_var_raises(self, mgr: EmailManager) -> None:
        mgr.save_template("t", subject="{{a}}", body="b")
        with pytest.raises(OfficeTemplateError):
            mgr.send(to=["x@x.com"], template="t", vars={})

    def test_send_unknown_template_raises(self, mgr: EmailManager) -> None:
        with pytest.raises(OfficeNotFoundError):
            mgr.send(to=["x@x.com"], template="nope", vars={})

    def test_send_requires_body_or_template(self, mgr: EmailManager) -> None:
        with pytest.raises(OfficeValidationError):
            mgr.send(to=["x@x.com"], subject="s")

    def test_send_requires_recipient(self, mgr: EmailManager) -> None:
        with pytest.raises(OfficeValidationError):
            mgr.send(to=[], subject="s", body="b")

    def test_send_backend_failure_propagates(self) -> None:
        class FailingBackend(FakeEmailBackend):
            def send(self, msg):  # noqa: ANN001, ANN202
                raise OfficeBackendError("SMTP 未配置")

        db = OfficeDB(":memory:")
        db.init_schema()
        mgr = EmailManager(db, FailingBackend())
        with pytest.raises(OfficeBackendError):
            mgr.send(to=["x@x.com"], subject="s", body="b")
        db.close()


class TestInbox:
    def test_fetch_inbox_stores_mails(self, mgr: EmailManager, backend: FakeEmailBackend) -> None:
        backend.queue_incoming(uid="u1", sender="boss@x.com", subject="周报呢", body="催")
        fetched = mgr.fetch_inbox()
        assert len(fetched) == 1
        assert fetched[0]["subject"] == "周报呢"
        assert fetched[0]["read"] is False
        # 已入本地库
        local = mgr.list_emails(folder="inbox")
        assert len(local) == 1

    def test_fetch_inbox_dedup_by_uid(self, mgr: EmailManager, backend: FakeEmailBackend) -> None:
        backend.queue_incoming(uid="u1", sender="a@x.com", subject="s", body="b")
        mgr.fetch_inbox()
        mgr.fetch_inbox()  # 第二次拉取不重复入库
        assert len(mgr.list_emails(folder="inbox")) == 1

    def test_list_unread_only(self, mgr: EmailManager, backend: FakeEmailBackend) -> None:
        backend.queue_incoming(uid="u1", sender="a@x.com", subject="m1", body="")
        backend.queue_incoming(uid="u2", sender="a@x.com", subject="m2", body="")
        mgr.fetch_inbox()
        mail = mgr.list_emails(folder="inbox")[0]
        mgr.mark_read(mail["id"])
        unread = mgr.list_emails(folder="inbox", unread_only=True)
        assert len(unread) == 1

    def test_mark_read(self, mgr: EmailManager, backend: FakeEmailBackend) -> None:
        backend.queue_incoming(uid="u1", sender="a@x.com", subject="s", body="b")
        mail = mgr.fetch_inbox()[0]
        result = mgr.mark_read(mail["id"])
        assert result["read"] is True
        assert mgr.list_emails(folder="inbox", unread_only=True) == []

    def test_mark_read_missing_raises(self, mgr: EmailManager) -> None:
        with pytest.raises(OfficeNotFoundError):
            mgr.mark_read("mail_nope")


class TestAutoReplyRules:
    def test_add_and_list_rule(self, mgr: EmailManager) -> None:
        mgr.save_template("away", subject="自动回复", body="{{sender}} 您好，我在忙")
        rule = mgr.add_auto_reply_rule(
            name="休假", keyword="报价", template="away"
        )
        assert rule["enabled"] is True
        rules = mgr.list_auto_reply_rules()
        assert [r["name"] for r in rules] == ["休假"]

    def test_add_rule_unknown_template_raises(self, mgr: EmailManager) -> None:
        with pytest.raises(OfficeNotFoundError):
            mgr.add_auto_reply_rule(name="r", keyword="k", template="ghost")

    def test_add_rule_requires_condition(self, mgr: EmailManager) -> None:
        mgr.save_template("t", subject="s", body="b")
        with pytest.raises(OfficeValidationError):
            mgr.add_auto_reply_rule(name="r", template="t")

    def test_remove_rule(self, mgr: EmailManager) -> None:
        mgr.save_template("t", subject="s", body="b")
        mgr.add_auto_reply_rule(name="r", keyword="k", template="t")
        mgr.remove_auto_reply_rule("r")
        assert mgr.list_auto_reply_rules() == []

    def test_remove_missing_rule_raises(self, mgr: EmailManager) -> None:
        with pytest.raises(OfficeNotFoundError):
            mgr.remove_auto_reply_rule("nope")


class TestProcessInbox:
    def test_keyword_match_sends_reply(
        self, mgr: EmailManager, backend: FakeEmailBackend
    ) -> None:
        mgr.save_template("away", subject="Re: {{subject}}", body="{{sender}} 稍候回复您")
        mgr.add_auto_reply_rule(name="报价", keyword="报价", template="away")
        backend.queue_incoming(uid="u1", sender="client@x.com", subject="请提供报价", body="急需")
        mgr.fetch_inbox()
        result = mgr.process_inbox()
        assert result["replies_sent"] == 1
        # 回复内容经模板渲染
        reply = backend.outbox[0]
        assert reply.to == ["client@x.com"]
        assert "请提供报价" in reply.subject
        assert "client@x.com" in reply.body
        # 原邮件已标记
        mail = mgr.list_emails(folder="inbox")[0]
        assert mail["auto_replied"] is True
        assert mail["read"] is True

    def test_sender_match_sends_reply(
        self, mgr: EmailManager, backend: FakeEmailBackend
    ) -> None:
        mgr.save_template("vip", subject="收到", body="VIP 通道")
        mgr.add_auto_reply_rule(name="vip", sender_match="boss", template="vip")
        backend.queue_incoming(uid="u1", sender="boss@x.com", subject="任意", body="")
        mgr.fetch_inbox()
        result = mgr.process_inbox()
        assert result["replies_sent"] == 1

    def test_no_match_no_reply(
        self, mgr: EmailManager, backend: FakeEmailBackend
    ) -> None:
        mgr.save_template("away", subject="s", body="b")
        mgr.add_auto_reply_rule(name="报价", keyword="报价", template="away")
        backend.queue_incoming(uid="u1", sender="a@x.com", subject="闲聊", body="")
        mgr.fetch_inbox()
        result = mgr.process_inbox()
        assert result["replies_sent"] == 0
        assert backend.outbox == []

    def test_disabled_rule_skipped(
        self, mgr: EmailManager, backend: FakeEmailBackend
    ) -> None:
        mgr.save_template("away", subject="s", body="b")
        mgr.add_auto_reply_rule(name="报价", keyword="报价", template="away", enabled=False)
        backend.queue_incoming(uid="u1", sender="a@x.com", subject="报价", body="")
        mgr.fetch_inbox()
        assert mgr.process_inbox()["replies_sent"] == 0

    def test_already_replied_not_repeated(
        self, mgr: EmailManager, backend: FakeEmailBackend
    ) -> None:
        mgr.save_template("away", subject="s", body="b")
        mgr.add_auto_reply_rule(name="报价", keyword="报价", template="away")
        backend.queue_incoming(uid="u1", sender="a@x.com", subject="报价", body="")
        mgr.fetch_inbox()
        mgr.process_inbox()
        # 第二次不再回复（auto_replied 已标记）
        assert mgr.process_inbox()["replies_sent"] == 0
        assert len(backend.outbox) == 1

    def test_keyword_match_case_insensitive(
        self, mgr: EmailManager, backend: FakeEmailBackend
    ) -> None:
        mgr.save_template("t", subject="s", body="b")
        mgr.add_auto_reply_rule(name="urgent", keyword="URGENT", template="t")
        backend.queue_incoming(uid="u1", sender="a@x.com", subject="urgent: 救命", body="")
        mgr.fetch_inbox()
        assert mgr.process_inbox()["replies_sent"] == 1
