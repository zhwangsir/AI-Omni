"""omni_office backends.py 单元测试。

SMTP/IMAP 全部 mock（``smtplib.SMTP_SSL`` / ``imaplib.IMAP4_SSL`` 替换为
MagicMock 上下文管理器），不访问真实网络。覆盖：基类契约、Fake 后端、
SMTP 配置与发送、IMAP 拉取、RFC822 解析。
"""

from __future__ import annotations

import imaplib
import smtplib
from email.message import EmailMessage as StdEmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

import pytest

from omni_office.backends import (
    EmailBackend,
    EmailMessage,
    FakeEmailBackend,
    IncomingEmail,
    SmtpEmailBackend,
)
from omni_office.errors import OfficeBackendError

#: 测试用到的全部环境变量（每个用例先清掉，避免受开发机环境污染）
_ENV_VARS = (
    "AI_OMNI_SMTP_HOST",
    "AI_OMNI_SMTP_PORT",
    "AI_OMNI_SMTP_USER",
    "AI_OMNI_SMTP_PASS",
    "AI_OMNI_SMTP_FROM",
    "AI_OMNI_IMAP_HOST",
    "AI_OMNI_IMAP_PORT",
    "AI_OMNI_IMAP_USER",
    "AI_OMNI_IMAP_PASS",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _smtp_ctx(mock_cls: MagicMock) -> MagicMock:
    """取 SMTP_SSL 上下文管理器内部对象。"""
    return mock_cls.return_value.__enter__.return_value


def _imap_ctx(mock_cls: MagicMock) -> MagicMock:
    """取 IMAP4_SSL 上下文管理器内部对象。"""
    return mock_cls.return_value.__enter__.return_value


# ---------------------------------------------------------------------------
# 基类契约
# ---------------------------------------------------------------------------
class TestEmailBackendBase:
    def test_send_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            EmailBackend().send(EmailMessage(to=["a@x.com"], subject="s", body="b"))

    def test_fetch_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            EmailBackend().fetch()


# ---------------------------------------------------------------------------
# FakeEmailBackend
# ---------------------------------------------------------------------------
class TestFakeEmailBackend:
    def test_send_appends_outbox(self) -> None:
        backend = FakeEmailBackend()
        backend.send(EmailMessage(to=["a@x.com"], subject="主题", body="正文"))
        assert len(backend.outbox) == 1
        assert backend.outbox[0].subject == "主题"

    def test_queue_incoming_then_fetch(self) -> None:
        backend = FakeEmailBackend()
        backend.queue_incoming("u1", "alice@x.com", "你好", "正文")
        mails = backend.fetch()
        assert mails == [
            IncomingEmail(uid="u1", sender="alice@x.com", subject="你好", body="正文")
        ]

    def test_fetch_returns_copy(self) -> None:
        backend = FakeEmailBackend()
        backend.queue_incoming("u1", "a@x.com", "s", "b")
        backend.fetch().clear()
        assert len(backend.fetch()) == 1


# ---------------------------------------------------------------------------
# SmtpEmailBackend 配置
# ---------------------------------------------------------------------------
class TestSmtpConfig:
    def test_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_OMNI_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("AI_OMNI_SMTP_PORT", "587")
        monkeypatch.setenv("AI_OMNI_SMTP_USER", "u@x.com")
        monkeypatch.setenv("AI_OMNI_SMTP_PASS", "secret")
        monkeypatch.setenv("AI_OMNI_IMAP_HOST", "imap.example.com")
        backend = SmtpEmailBackend()
        assert backend.smtp_host == "smtp.example.com"
        assert backend.smtp_port == 587
        assert backend.smtp_user == "u@x.com"
        assert backend.smtp_pass == "secret"
        assert backend.imap_host == "imap.example.com"
        assert backend.imap_port == 993

    def test_config_dict_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_OMNI_SMTP_HOST", "env-host")
        backend = SmtpEmailBackend({"smtp_host": "dict-host", "smtp_port": "2525"})
        assert backend.smtp_host == "dict-host"
        assert backend.smtp_port == 2525

    def test_from_addr_defaults_to_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_OMNI_SMTP_USER", "u@x.com")
        backend = SmtpEmailBackend()
        assert backend.from_addr == "u@x.com"

    def test_defaults_empty(self) -> None:
        backend = SmtpEmailBackend()
        assert backend.smtp_host == ""
        assert backend.smtp_port == 465
        assert backend.imap_port == 993


# ---------------------------------------------------------------------------
# SMTP 发送
# ---------------------------------------------------------------------------
class TestSmtpSend:
    def _msg(self, **kwargs: object) -> EmailMessage:
        base: dict[str, object] = {"to": ["a@x.com", "b@x.com"], "subject": "主题", "body": "正文"}
        base.update(kwargs)
        return EmailMessage(**base)  # type: ignore[arg-type]

    def test_send_without_config_raises(self) -> None:
        with pytest.raises(OfficeBackendError, match="SMTP 未配置"):
            SmtpEmailBackend().send(self._msg())

    def test_send_success(self) -> None:
        backend = SmtpEmailBackend(
            {
                "smtp_host": "smtp.example.com",
                "smtp_port": "465",
                "smtp_user": "u@x.com",
                "smtp_pass": "pw",
                "from_addr": "bot@x.com",
            }
        )
        with patch("smtplib.SMTP_SSL") as mock_cls:
            backend.send(self._msg())
        mock_cls.assert_called_once_with("smtp.example.com", 465, timeout=15)
        smtp = _smtp_ctx(mock_cls)
        smtp.login.assert_called_once_with("u@x.com", "pw")
        smtp.send_message.assert_called_once()
        sent: StdEmailMessage = smtp.send_message.call_args[0][0]
        assert sent["From"] == "bot@x.com"
        assert sent["To"] == "a@x.com, b@x.com"
        assert sent["Subject"] == "主题"
        assert "正文" in sent.get_content()

    def test_send_uses_msg_sender_over_from_addr(self) -> None:
        backend = SmtpEmailBackend({"smtp_host": "h", "from_addr": "bot@x.com"})
        with patch("smtplib.SMTP_SSL") as mock_cls:
            backend.send(self._msg(sender="human@x.com"))
        sent: StdEmailMessage = _smtp_ctx(mock_cls).send_message.call_args[0][0]
        assert sent["From"] == "human@x.com"

    def test_send_skips_login_without_user(self) -> None:
        backend = SmtpEmailBackend({"smtp_host": "h"})
        with patch("smtplib.SMTP_SSL") as mock_cls:
            backend.send(self._msg())
        _smtp_ctx(mock_cls).login.assert_not_called()

    def test_send_connect_failure_wrapped(self) -> None:
        backend = SmtpEmailBackend({"smtp_host": "h"})
        with patch("smtplib.SMTP_SSL", side_effect=OSError("conn refused")):
            with pytest.raises(OfficeBackendError, match="SMTP 发送失败"):
                backend.send(self._msg())

    def test_send_login_failure_wrapped(self) -> None:
        backend = SmtpEmailBackend({"smtp_host": "h", "smtp_user": "u", "smtp_pass": "bad"})
        with patch("smtplib.SMTP_SSL") as mock_cls:
            _smtp_ctx(mock_cls).login.side_effect = smtplib.SMTPAuthenticationError(
                535, b"auth failed"
            )
            with pytest.raises(OfficeBackendError, match="SMTP 发送失败"):
                backend.send(self._msg())


# ---------------------------------------------------------------------------
# IMAP 拉取
# ---------------------------------------------------------------------------
class TestImapFetch:
    def test_fetch_without_config_raises(self) -> None:
        with pytest.raises(OfficeBackendError, match="IMAP 未配置"):
            SmtpEmailBackend().fetch()

    @staticmethod
    def _raw(sender: str, subject: str, body: str) -> bytes:
        msg = StdEmailMessage()
        msg["From"] = sender
        msg["Subject"] = subject
        msg.set_content(body)
        return msg.as_bytes()

    def test_fetch_success(self) -> None:
        backend = SmtpEmailBackend(
            {"imap_host": "imap.example.com", "imap_user": "u@x.com", "imap_pass": "pw"}
        )
        raw1 = self._raw("alice@x.com", "周报", "请看附件")
        raw2 = self._raw("bob@x.com", "提醒", "明天开会")
        with patch("imaplib.IMAP4_SSL") as mock_cls:
            imap = _imap_ctx(mock_cls)
            imap.search.return_value = ("OK", [b"1 2"])
            imap.fetch.side_effect = [
                ("OK", [(b"1 (RFC822)", raw1)]),
                ("OK", [(b"2 (RFC822)", raw2)]),
            ]
            mails = backend.fetch()
        mock_cls.assert_called_once_with("imap.example.com", 993)
        imap.login.assert_called_once_with("u@x.com", "pw")
        imap.select.assert_called_once_with("INBOX")
        assert [m.uid for m in mails] == ["1", "2"]
        assert mails[0].sender == "alice@x.com"
        assert mails[0].subject == "周报"
        assert "请看附件" in mails[0].body
        assert mails[1].sender == "bob@x.com"

    def test_fetch_empty_inbox(self) -> None:
        backend = SmtpEmailBackend({"imap_host": "h"})
        with patch("imaplib.IMAP4_SSL") as mock_cls:
            _imap_ctx(mock_cls).search.return_value = ("OK", [b""])
            assert backend.fetch() == []

    def test_fetch_connect_failure_wrapped(self) -> None:
        backend = SmtpEmailBackend({"imap_host": "h"})
        with patch("imaplib.IMAP4_SSL", side_effect=OSError("timeout")):
            with pytest.raises(OfficeBackendError, match="IMAP 拉取失败"):
                backend.fetch()

    def test_fetch_login_failure_wrapped(self) -> None:
        backend = SmtpEmailBackend({"imap_host": "h"})
        with patch("imaplib.IMAP4_SSL") as mock_cls:
            _imap_ctx(mock_cls).login.side_effect = imaplib.IMAP4.error("auth failed")
            with pytest.raises(OfficeBackendError, match="IMAP 拉取失败"):
                backend.fetch()


# ---------------------------------------------------------------------------
# RFC822 解析
# ---------------------------------------------------------------------------
class TestParseRaw:
    def test_plain_text_message(self) -> None:
        raw = (
            b"From: alice@x.com\r\n"
            b"Subject: Hello\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"\r\n"
            b"plain body"
        )
        mail = SmtpEmailBackend._parse_raw("42", raw)
        assert mail.uid == "42"
        assert mail.sender == "alice@x.com"
        assert mail.subject == "Hello"
        assert mail.body == "plain body"

    def test_multipart_prefers_text_plain(self) -> None:
        msg = StdEmailMessage()
        msg["From"] = "bob@x.com"
        msg["Subject"] = "多部分"
        msg.set_content("纯文本正文")
        msg.add_attachment(b"bin", maintype="application", subtype="octet-stream", filename="a.bin")
        mail = SmtpEmailBackend._parse_raw("7", msg.as_bytes())
        assert mail.sender == "bob@x.com"
        assert mail.subject == "多部分"
        assert "纯文本正文" in mail.body

    def test_multipart_without_text_plain_gives_empty_body(self) -> None:
        msg = MIMEMultipart("alternative")
        msg["From"] = "c@x.com"
        msg["Subject"] = "s"
        msg.attach(MIMEText("<p>仅 HTML</p>", "html", "utf-8"))
        mail = SmtpEmailBackend._parse_raw("9", msg.as_bytes())
        assert mail.body == ""

    def test_missing_headers_decode_to_empty(self) -> None:
        mail = SmtpEmailBackend._parse_raw("1", b"\r\n\r\n")
        assert mail.sender == ""
        assert mail.subject == ""

    def test_encoded_word_headers(self) -> None:
        raw = (
            "From: =?utf-8?b?5ZGo5L2c5aSn5a2m?= <bot@x.com>\r\n"
            "Subject: =?utf-8?b?5rWL6K+V6YKu5Lu2?=\r\n"
            "\r\n"
            "body"
        ).encode("utf-8")
        mail = SmtpEmailBackend._parse_raw("3", raw)
        assert "bot@x.com" in mail.sender
        assert mail.subject == "测试邮件"
