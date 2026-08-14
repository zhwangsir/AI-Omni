"""omni_office 邮件后端抽象。

后端契约仅两个同步方法：``send(msg)`` 与 ``fetch()``。

- :class:`FakeEmailBackend`：进程内模拟，``outbox`` 收集外发邮件，
  ``queue_incoming`` 注入收件；测试与 CLI ``--fake`` 专用，零网络依赖。
- :class:`SmtpEmailBackend`：真实 SMTP/IMAP 后端，stdlib ``smtplib`` /
  ``imaplib`` 惰性导入（CLAUDE.md §三）；配置来自环境变量
  ``AI_OMNI_SMTP_*`` / ``AI_OMNI_IMAP_*``，未配置时抛
  :class:`OfficeBackendError`（tools 层映射为 ``E_BACKEND_UNAVAILABLE``）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .errors import OfficeBackendError


@dataclass
class EmailMessage:
    """外发邮件。"""

    to: list[str]
    subject: str
    body: str
    sender: str = ""


@dataclass
class IncomingEmail:
    """收件箱邮件（后端拉取的原始结构，``uid`` 为后端侧唯一标识）。"""

    uid: str
    sender: str
    subject: str
    body: str


class EmailBackend:
    """邮件后端协议基类。"""

    def send(self, msg: EmailMessage) -> None:
        """发送邮件；失败抛 :class:`OfficeBackendError`。"""
        raise NotImplementedError

    def fetch(self) -> list[IncomingEmail]:
        """拉取收件箱邮件列表；失败抛 :class:`OfficeBackendError`。"""
        raise NotImplementedError


class FakeEmailBackend(EmailBackend):
    """进程内 fake 后端：不访问网络，全部数据落内存。"""

    def __init__(self) -> None:
        self.outbox: list[EmailMessage] = []
        self._incoming: list[IncomingEmail] = []

    def queue_incoming(self, uid: str, sender: str, subject: str, body: str) -> None:
        """注入一封收件箱邮件（测试 / 演示用）。"""
        self._incoming.append(
            IncomingEmail(uid=uid, sender=sender, subject=subject, body=body)
        )

    def send(self, msg: EmailMessage) -> None:
        self.outbox.append(msg)

    def fetch(self) -> list[IncomingEmail]:
        return list(self._incoming)


class SmtpEmailBackend(EmailBackend):
    """真实 SMTP/IMAP 后端（stdlib 实现，惰性导入）。

    环境变量配置：
    - 发送：``AI_OMNI_SMTP_HOST`` / ``_PORT``（默认 465，SSL）/ ``_USER`` / ``_PASS`` / ``_FROM``
    - 接收：``AI_OMNI_IMAP_HOST`` / ``_PORT``（默认 993，SSL）/ ``_USER`` / ``_PASS``

    未配置主机时所有操作抛 :class:`OfficeBackendError`。
    """

    def __init__(self, config: dict[str, str] | None = None) -> None:
        cfg = config or {}
        self.smtp_host = cfg.get("smtp_host") or os.environ.get("AI_OMNI_SMTP_HOST", "")
        self.smtp_port = int(cfg.get("smtp_port") or os.environ.get("AI_OMNI_SMTP_PORT", "465"))
        self.smtp_user = cfg.get("smtp_user") or os.environ.get("AI_OMNI_SMTP_USER", "")
        self.smtp_pass = cfg.get("smtp_pass") or os.environ.get("AI_OMNI_SMTP_PASS", "")
        self.from_addr = cfg.get("from_addr") or os.environ.get(
            "AI_OMNI_SMTP_FROM", self.smtp_user
        )
        self.imap_host = cfg.get("imap_host") or os.environ.get("AI_OMNI_IMAP_HOST", "")
        self.imap_port = int(cfg.get("imap_port") or os.environ.get("AI_OMNI_IMAP_PORT", "993"))
        self.imap_user = cfg.get("imap_user") or os.environ.get("AI_OMNI_IMAP_USER", "")
        self.imap_pass = cfg.get("imap_pass") or os.environ.get("AI_OMNI_IMAP_PASS", "")

    def send(self, msg: EmailMessage) -> None:
        """经 SMTP_SSL 发送；未配置或连接失败抛 :class:`OfficeBackendError`。"""
        if not self.smtp_host:
            raise OfficeBackendError(
                "SMTP 未配置：请设置 AI_OMNI_SMTP_HOST / AI_OMNI_SMTP_USER / AI_OMNI_SMTP_PASS"
            )
        import smtplib  # 惰性导入
        from email.message import EmailMessage as StdEmailMessage

        std_msg = StdEmailMessage()
        std_msg["From"] = msg.sender or self.from_addr
        std_msg["To"] = ", ".join(msg.to)
        std_msg["Subject"] = msg.subject
        std_msg.set_content(msg.body)
        try:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=15) as smtp:
                if self.smtp_user:
                    smtp.login(self.smtp_user, self.smtp_pass)
                smtp.send_message(std_msg)
        except (OSError, smtplib.SMTPException) as exc:
            raise OfficeBackendError(f"SMTP 发送失败: {exc}") from exc

    def fetch(self) -> list[IncomingEmail]:
        """经 IMAP_SSL 拉取未读邮件；未配置或连接失败抛 :class:`OfficeBackendError`。"""
        if not self.imap_host:
            raise OfficeBackendError(
                "IMAP 未配置：请设置 AI_OMNI_IMAP_HOST / AI_OMNI_IMAP_USER / AI_OMNI_IMAP_PASS"
            )
        import imaplib  # 惰性导入

        try:
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port) as imap:
                imap.login(self.imap_user, self.imap_pass)
                imap.select("INBOX")
                _, data = imap.search(None, "UNSEEN")
                ids = data[0].split() if data and data[0] else []
                mails: list[IncomingEmail] = []
                for num in ids[-50:]:  # 最多取最近 50 封未读
                    _, msg_data = imap.fetch(num, "(RFC822)")
                    raw = msg_data[0][1] if msg_data and msg_data[0] else b""
                    mails.append(self._parse_raw(num.decode(), raw))
                return mails
        except (OSError, imaplib.IMAP4.error) as exc:
            raise OfficeBackendError(f"IMAP 拉取失败: {exc}") from exc

    @staticmethod
    def _parse_raw(uid: str, raw: bytes) -> IncomingEmail:
        """把 RFC822 字节流解析为 :class:`IncomingEmail`（取纯文本正文）。"""
        from email import message_from_bytes
        from email.header import decode_header

        msg = message_from_bytes(raw)

        def _decode(value: str | None) -> str:
            if not value:
                return ""
            parts = decode_header(value)
            return "".join(
                p.decode(enc or "utf-8", errors="replace") if isinstance(p, bytes) else p
                for p, enc in parts
            )

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        body = payload.decode("utf-8", errors="replace")
                        break
        else:
            payload = msg.get_payload(decode=True)
            if isinstance(payload, bytes):
                body = payload.decode("utf-8", errors="replace")
        return IncomingEmail(
            uid=uid,
            sender=_decode(msg.get("From")),
            subject=_decode(msg.get("Subject")),
            body=body,
        )
