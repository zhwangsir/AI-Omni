"""omni_office 文档管理：创建 / 更新 / 版本快照 / 回滚 / 检索。

版本控制模型：
- 创建即 v1；每次 :meth:`DocumentManager.update` 追加新版本并推进
  ``documents.current_version`` 指针
- 历史版本不可变（审计链完整）；回滚 = 把目标版本内容复制为新版本，
  而不是移动指针
- 标签以 JSON 数组落库，检索时应用层过滤（库小，无需 LIKE 拆词）
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .db import OfficeDB
from .errors import OfficeNotFoundError, OfficeValidationError


def _new_doc_id() -> str:
    return f"doc_{uuid.uuid4().hex[:12]}"


class DocumentManager:
    """文档 + 版本管理器。"""

    def __init__(self, db: OfficeDB) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _require_doc(self, doc_id: str) -> dict[str, Any]:
        """取文档主行；不存在抛 :class:`OfficeNotFoundError`。"""
        row = self._db.conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            raise OfficeNotFoundError(f"文档不存在: {doc_id}")
        return dict(row)

    @staticmethod
    def _version_dict(row: Any) -> dict[str, Any]:
        return {
            "doc_id": row["doc_id"],
            "version": row["version"],
            "content": row["content"],
            "note": row["note"],
            "created_at": row["created_at"],
        }

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def create(
        self, title: str, content: str = "", tags: list[str] | None = None
    ) -> dict[str, Any]:
        """创建文档（初始版本 v1）。

        :param title: 标题（去空白后非空）
        :param content: 初始内容（允许为空）
        :param tags: 标签列表
        :raises OfficeValidationError: 标题为空
        """
        title = (title or "").strip()
        if not title:
            raise OfficeValidationError("文档标题不能为空")
        doc_id = _new_doc_id()
        now = time.time()
        tag_list = [str(t) for t in (tags or [])]
        conn = self._db.conn
        conn.execute(
            "INSERT INTO documents (id, title, tags, current_version, created_at, updated_at)"
            " VALUES (?, ?, ?, 1, ?, ?)",
            (doc_id, title, json.dumps(tag_list, ensure_ascii=False), now, now),
        )
        conn.execute(
            "INSERT INTO document_versions (doc_id, version, content, note, created_at)"
            " VALUES (?, 1, ?, NULL, ?)",
            (doc_id, content, now),
        )
        conn.commit()
        return {
            "id": doc_id,
            "title": title,
            "tags": tag_list,
            "current_version": 1,
            "created_at": now,
            "updated_at": now,
        }

    def update(self, doc_id: str, content: str, note: str | None = None) -> dict[str, Any]:
        """追加新版本；``current_version`` 推进到最新。

        :raises OfficeNotFoundError: 文档不存在
        """
        doc = self._require_doc(doc_id)
        new_version = int(doc["current_version"]) + 1
        now = time.time()
        conn = self._db.conn
        conn.execute(
            "INSERT INTO document_versions (doc_id, version, content, note, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (doc_id, new_version, content, note, now),
        )
        conn.execute(
            "UPDATE documents SET current_version = ?, updated_at = ? WHERE id = ?",
            (new_version, now, doc_id),
        )
        conn.commit()
        doc["current_version"] = new_version
        doc["updated_at"] = now
        doc["tags"] = json.loads(doc["tags"])
        return doc

    def get(self, doc_id: str, version: int | None = None) -> dict[str, Any]:
        """取文档内容；缺省取当前版本，``version=N`` 取历史快照。

        :raises OfficeNotFoundError: 文档或版本不存在
        """
        doc = self._require_doc(doc_id)
        target = int(doc["current_version"]) if version is None else int(version)
        row = self._db.conn.execute(
            "SELECT * FROM document_versions WHERE doc_id = ? AND version = ?",
            (doc_id, target),
        ).fetchone()
        if row is None:
            raise OfficeNotFoundError(f"文档 {doc_id} 不存在版本 v{target}")
        return {
            "id": doc_id,
            "title": doc["title"],
            "tags": json.loads(doc["tags"]),
            "version": target,
            "current_version": doc["current_version"],
            "content": row["content"],
            "note": row["note"],
            "created_at": doc["created_at"],
            "updated_at": doc["updated_at"],
        }

    def list_documents(
        self,
        tag: str | None = None,
        keyword: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """列出文档摘要；支持标签 / 标题关键词过滤与数量上限。"""
        rows = self._db.conn.execute(
            "SELECT * FROM documents ORDER BY created_at ASC, id ASC"
        ).fetchall()
        docs: list[dict[str, Any]] = []
        for row in rows:
            tags = json.loads(row["tags"])
            if tag and tag not in tags:
                continue
            if keyword and keyword not in row["title"]:
                continue
            docs.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "tags": tags,
                    "current_version": row["current_version"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        if limit is not None:
            docs = docs[: int(limit)]
        return docs

    def versions(self, doc_id: str) -> list[dict[str, Any]]:
        """取完整版本历史（按版本号升序）。

        :raises OfficeNotFoundError: 文档不存在
        """
        self._require_doc(doc_id)
        rows = self._db.conn.execute(
            "SELECT * FROM document_versions WHERE doc_id = ? ORDER BY version ASC",
            (doc_id,),
        ).fetchall()
        return [self._version_dict(r) for r in rows]

    def rollback(self, doc_id: str, version: int) -> dict[str, Any]:
        """回滚：把目标版本内容复制为新版本（历史不可变）。

        :raises OfficeNotFoundError: 文档或目标版本不存在
        """
        doc = self._require_doc(doc_id)
        row = self._db.conn.execute(
            "SELECT * FROM document_versions WHERE doc_id = ? AND version = ?",
            (doc_id, int(version)),
        ).fetchone()
        if row is None:
            raise OfficeNotFoundError(f"文档 {doc_id} 不存在版本 v{version}")
        new_version = int(doc["current_version"]) + 1
        now = time.time()
        conn = self._db.conn
        conn.execute(
            "INSERT INTO document_versions (doc_id, version, content, note, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (doc_id, new_version, row["content"], f"回滚到 v{version}", now),
        )
        conn.execute(
            "UPDATE documents SET current_version = ?, updated_at = ? WHERE id = ?",
            (new_version, now, doc_id),
        )
        conn.commit()
        return {
            "id": doc_id,
            "current_version": new_version,
            "rolled_back_to": int(version),
        }
