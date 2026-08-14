"""omni_office 邮件处理：收发 / 模板 / 自动回复规则。

- 发送：直接 ``body`` 或 ``template + vars`` 渲染；成功写入本地 ``sent`` 文件夹
- 收件：:meth:`EmailManager.fetch_inbox` 经后端拉取并按后端 ``uid`` 去重入库
- 自动回复：规则 = ``keyword``（主题/正文子串，大小写不敏感）或
  ``sender_match``（发件人子串）；:meth:`process_inbox` 对未读且未自动回复的
  邮件应用启用规则，模板可引用 ``{{sender}}`` / ``{{subject}}`` 变量
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .backends import EmailBackend, EmailMessage
from .db import OfficeDB
from .errors import OfficeNotFoundError, OfficeValidationError
from .templates import render_template


def _new_mail_id() -> str:
    return f"mail_{uuid.uuid4().hex[:12]}"


class EmailManager:
    """邮件管理器（本地库 + 后端收发）。"""

    def __init__(self, db: OfficeDB, backend: EmailBackend) -> None:
        self._db = db
        self._backend = backend

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_mail(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "uid": row["uid"],
            "folder": row["folder"],
            "sender": row["sender"],
            "to": json.loads(row["recipients"]),
            "subject": row["subject"],
            "body": row["body"],
            "read": bool(row["read"]),
            "auto_replied": bool(row["auto_replied"]),
            "created_at": row["created_at"],
        }

    def _get_template(self, name: str) -> dict[str, Any]:
        row = self._db.conn.execute(
            "SELECT * FROM email_templates WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            raise OfficeNotFoundError(f"邮件模板不存在: {name}")
        return dict(row)

    # ------------------------------------------------------------------
    # 模板
    # ------------------------------------------------------------------
    def save_template(self, name: str, subject: str, body: str) -> dict[str, Any]:
        """保存（或覆盖）邮件模板。"""
        name = (name or "").strip()
        if not name:
            raise OfficeValidationError("模板名不能为空")
        now = time.time()
        self._db.conn.execute(
            "INSERT INTO email_templates (name, subject, body, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET subject = excluded.subject,"
            " body = excluded.body, updated_at = excluded.updated_at",
            (name, subject, body, now, now),
        )
        self._db.conn.commit()
        return {"name": name, "subject": subject, "body": body, "updated_at": now}

    def list_templates(self) -> list[dict[str, Any]]:
        """列出全部邮件模板（按名称升序）。"""
        rows = self._db.conn.execute(
            "SELECT * FROM email_templates ORDER BY name ASC"
        ).fetchall()
        return [
            {
                "name": r["name"],
                "subject": r["subject"],
                "body": r["body"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------
    def send(
        self,
        to: list[str],
        subject: str | None = None,
        body: str | None = None,
        template: str | None = None,
        vars: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """发送邮件并写入本地 ``sent`` 文件夹。

        ``template`` 优先：主题与正文均由模板 + ``vars`` 渲染；
        否则必须显式给出 ``body``。

        :raises OfficeValidationError: 缺收件人 / 缺正文
        :raises OfficeNotFoundError: 模板不存在
        :raises OfficeTemplateError: 模板变量缺失
        :raises OfficeBackendError: 后端不可用
        """
        recipients = [str(addr).strip() for addr in (to or []) if str(addr).strip()]
        if not recipients:
            raise OfficeValidationError("收件人不能为空")
        if template is not None:
            tpl = self._get_template(template)
            subject = render_template(tpl["subject"], vars)
            body = render_template(tpl["body"], vars)
        elif body is None:
            raise OfficeValidationError("body 与 template 至少提供一个")
        final_subject = subject or ""
        final_body = body or ""
        self._backend.send(
            EmailMessage(to=recipients, subject=final_subject, body=final_body)
        )
        mail_id = _new_mail_id()
        now = time.time()
        self._db.conn.execute(
            "INSERT INTO emails (id, uid, folder, sender, recipients, subject, body,"
            " read, auto_replied, created_at) VALUES (?, NULL, 'sent', '', ?, ?, ?, 1, 0, ?)",
            (
                mail_id,
                json.dumps(recipients, ensure_ascii=False),
                final_subject,
                final_body,
                now,
            ),
        )
        self._db.conn.commit()
        return {
            "id": mail_id,
            "folder": "sent",
            "to": recipients,
            "subject": final_subject,
            "body": final_body,
            "created_at": now,
        }

    # ------------------------------------------------------------------
    # 收件箱
    # ------------------------------------------------------------------
    def fetch_inbox(self) -> list[dict[str, Any]]:
        """经后端拉取收件箱并按 ``uid`` 去重入库；返回本次新入库的邮件。"""
        incoming = self._backend.fetch()
        fetched: list[dict[str, Any]] = []
        conn = self._db.conn
        for mail in incoming:
            if mail.uid:
                exists = conn.execute(
                    "SELECT id FROM emails WHERE folder = 'inbox' AND uid = ?",
                    (mail.uid,),
                ).fetchone()
                if exists is not None:
                    continue
            mail_id = _new_mail_id()
            now = time.time()
            conn.execute(
                "INSERT INTO emails (id, uid, folder, sender, recipients, subject, body,"
                " read, auto_replied, created_at)"
                " VALUES (?, ?, 'inbox', ?, '[]', ?, ?, 0, 0, ?)",
                (mail_id, mail.uid, mail.sender, mail.subject, mail.body, now),
            )
            fetched.append(
                {
                    "id": mail_id,
                    "uid": mail.uid,
                    "folder": "inbox",
                    "sender": mail.sender,
                    "to": [],
                    "subject": mail.subject,
                    "body": mail.body,
                    "read": False,
                    "auto_replied": False,
                    "created_at": now,
                }
            )
        conn.commit()
        return fetched

    def list_emails(
        self, folder: str | None = None, unread_only: bool = False
    ) -> list[dict[str, Any]]:
        """列出本地邮件；支持文件夹过滤与仅未读。"""
        sql = "SELECT * FROM emails"
        clauses: list[str] = []
        params: list[Any] = []
        if folder is not None:
            clauses.append("folder = ?")
            params.append(folder)
        if unread_only:
            clauses.append("read = 0")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC, id ASC"
        rows = self._db.conn.execute(sql, params).fetchall()
        return [self._row_to_mail(r) for r in rows]

    def mark_read(self, email_id: str) -> dict[str, Any]:
        """标记已读；邮件不存在抛 :class:`OfficeNotFoundError`。"""
        cur = self._db.conn.execute(
            "UPDATE emails SET read = 1 WHERE id = ?", (email_id,)
        )
        self._db.conn.commit()
        if cur.rowcount == 0:
            raise OfficeNotFoundError(f"邮件不存在: {email_id}")
        return {"id": email_id, "read": True}

    # ------------------------------------------------------------------
    # 自动回复规则
    # ------------------------------------------------------------------
    def add_auto_reply_rule(
        self,
        name: str,
        keyword: str | None = None,
        sender_match: str | None = None,
        template: str | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """新增自动回复规则（同名覆盖）。

        ``keyword`` 与 ``sender_match`` 至少提供一个；``template`` 必须已存在。
        """
        name = (name or "").strip()
        if not name:
            raise OfficeValidationError("规则名不能为空")
        if not keyword and not sender_match:
            raise OfficeValidationError("keyword 与 sender_match 至少提供一个")
        if not template:
            raise OfficeValidationError("规则必须引用模板")
        self._get_template(template)  # 不存在抛 OfficeNotFoundError
        now = time.time()
        self._db.conn.execute(
            "INSERT INTO auto_reply_rules (name, keyword, sender_match, template, enabled,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET keyword = excluded.keyword,"
            " sender_match = excluded.sender_match, template = excluded.template,"
            " enabled = excluded.enabled",
            (name, keyword, sender_match, template, 1 if enabled else 0, now),
        )
        self._db.conn.commit()
        return {
            "name": name,
            "keyword": keyword,
            "sender_match": sender_match,
            "template": template,
            "enabled": bool(enabled),
        }

    def list_auto_reply_rules(self) -> list[dict[str, Any]]:
        """列出全部自动回复规则（按名称升序）。"""
        rows = self._db.conn.execute(
            "SELECT * FROM auto_reply_rules ORDER BY name ASC"
        ).fetchall()
        return [
            {
                "name": r["name"],
                "keyword": r["keyword"],
                "sender_match": r["sender_match"],
                "template": r["template"],
                "enabled": bool(r["enabled"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def remove_auto_reply_rule(self, name: str) -> dict[str, Any]:
        """删除规则；不存在抛 :class:`OfficeNotFoundError`。"""
        cur = self._db.conn.execute(
            "DELETE FROM auto_reply_rules WHERE name = ?", (name,)
        )
        self._db.conn.commit()
        if cur.rowcount == 0:
            raise OfficeNotFoundError(f"自动回复规则不存在: {name}")
        return {"removed": name}

    # ------------------------------------------------------------------
    # 收件箱自动处理
    # ------------------------------------------------------------------
    @staticmethod
    def _rule_matches(rule: dict[str, Any], mail: dict[str, Any]) -> bool:
        """规则命中判定：keyword 匹配主题/正文（大小写不敏感）或 sender_match 匹配发件人。"""
        keyword = rule.get("keyword")
        if keyword:
            haystack = f"{mail['subject']}\n{mail['body']}".lower()
            if keyword.lower() in haystack:
                return True
        sender_match = rule.get("sender_match")
        if sender_match:
            if sender_match.lower() in (mail.get("sender") or "").lower():
                return True
        return False

    def process_inbox(self) -> dict[str, Any]:
        """对未读且未自动回复的收件箱邮件应用启用规则并发送回复。

        回复模板可引用 ``{{sender}}`` / ``{{subject}}``；命中后原邮件
        标记 ``auto_replied`` 并置为已读。
        """
        rules = [r for r in self.list_auto_reply_rules() if r["enabled"]]
        pending = [
            m
            for m in self.list_emails(folder="inbox")
            if not m["read"] and not m["auto_replied"]
        ]
        replied: list[str] = []
        conn = self._db.conn
        for mail in pending:
            for rule in rules:
                if not self._rule_matches(rule, mail):
                    continue
                tpl = self._get_template(rule["template"])
                vars = {"sender": mail["sender"] or "", "subject": mail["subject"]}
                reply_subject = render_template(tpl["subject"], vars)
                reply_body = render_template(tpl["body"], vars)
                self._backend.send(
                    EmailMessage(
                        to=[mail["sender"]], subject=reply_subject, body=reply_body
                    )
                )
                conn.execute(
                    "UPDATE emails SET auto_replied = 1, read = 1 WHERE id = ?",
                    (mail["id"],),
                )
                replied.append(mail["id"])
                break
        conn.commit()
        return {"replies_sent": len(replied), "replied": replied}
