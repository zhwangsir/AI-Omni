"""omni_office 文档管理（documents.py）单元测试。

版本控制契约：
- 创建即 v1；每次 update 产生新版本；``current_version`` 指向最新
- ``get(version=N)`` 可取历史快照；缺省取当前版本
- rollback 把目标版本内容复制为新版本（历史不可变，审计链完整）
- 不存在的文档/版本抛 :class:`OfficeNotFoundError`
"""

from __future__ import annotations

import pytest

from omni_office.db import OfficeDB
from omni_office.documents import DocumentManager
from omni_office.errors import OfficeNotFoundError, OfficeValidationError


@pytest.fixture()
def mgr():
    db = OfficeDB(":memory:")
    db.init_schema()
    yield DocumentManager(db)
    db.close()


class TestCreate:
    def test_create_returns_v1(self, mgr: DocumentManager) -> None:
        doc = mgr.create(title="周报", content="第一周")
        assert doc["id"].startswith("doc_")
        assert doc["current_version"] == 1
        assert doc["title"] == "周报"

    def test_create_with_tags(self, mgr: DocumentManager) -> None:
        doc = mgr.create(title="方案", content="...", tags=["工作", "Q3"])
        assert doc["tags"] == ["工作", "Q3"]

    def test_create_empty_title_rejected(self, mgr: DocumentManager) -> None:
        with pytest.raises(OfficeValidationError):
            mgr.create(title="  ", content="x")

    def test_create_empty_content_allowed(self, mgr: DocumentManager) -> None:
        doc = mgr.create(title="空文档", content="")
        assert doc["current_version"] == 1


class TestUpdate:
    def test_update_increments_version(self, mgr: DocumentManager) -> None:
        doc = mgr.create(title="t", content="v1 内容")
        updated = mgr.update(doc["id"], content="v2 内容")
        assert updated["current_version"] == 2
        again = mgr.update(doc["id"], content="v3 内容", note="第三次")
        assert again["current_version"] == 3

    def test_update_missing_doc_raises(self, mgr: DocumentManager) -> None:
        with pytest.raises(OfficeNotFoundError):
            mgr.update("doc_nope", content="x")

    def test_update_records_note(self, mgr: DocumentManager) -> None:
        doc = mgr.create(title="t", content="a")
        mgr.update(doc["id"], content="b", note="修订说明")
        versions = mgr.versions(doc["id"])
        assert versions[-1]["note"] == "修订说明"


class TestGet:
    def test_get_defaults_to_current(self, mgr: DocumentManager) -> None:
        doc = mgr.create(title="t", content="old")
        mgr.update(doc["id"], content="new")
        got = mgr.get(doc["id"])
        assert got["content"] == "new"
        assert got["version"] == 2

    def test_get_specific_version(self, mgr: DocumentManager) -> None:
        doc = mgr.create(title="t", content="old")
        mgr.update(doc["id"], content="new")
        got = mgr.get(doc["id"], version=1)
        assert got["content"] == "old"
        assert got["version"] == 1

    def test_get_missing_doc_raises(self, mgr: DocumentManager) -> None:
        with pytest.raises(OfficeNotFoundError):
            mgr.get("doc_nope")

    def test_get_missing_version_raises(self, mgr: DocumentManager) -> None:
        doc = mgr.create(title="t", content="a")
        with pytest.raises(OfficeNotFoundError):
            mgr.get(doc["id"], version=99)


class TestList:
    def test_list_all(self, mgr: DocumentManager) -> None:
        mgr.create(title="甲", content="")
        mgr.create(title="乙", content="")
        assert len(mgr.list_documents()) == 2

    def test_list_filter_by_tag(self, mgr: DocumentManager) -> None:
        mgr.create(title="甲", content="", tags=["工作"])
        mgr.create(title="乙", content="", tags=["生活"])
        docs = mgr.list_documents(tag="工作")
        assert [d["title"] for d in docs] == ["甲"]

    def test_list_keyword_matches_title(self, mgr: DocumentManager) -> None:
        mgr.create(title="Q3 规划", content="")
        mgr.create(title="购物清单", content="")
        docs = mgr.list_documents(keyword="规划")
        assert [d["title"] for d in docs] == ["Q3 规划"]

    def test_list_respects_limit(self, mgr: DocumentManager) -> None:
        for i in range(5):
            mgr.create(title=f"d{i}", content="")
        assert len(mgr.list_documents(limit=3)) == 3


class TestVersions:
    def test_versions_returns_full_history(self, mgr: DocumentManager) -> None:
        doc = mgr.create(title="t", content="a")
        mgr.update(doc["id"], content="b")
        mgr.update(doc["id"], content="c")
        versions = mgr.versions(doc["id"])
        assert [v["version"] for v in versions] == [1, 2, 3]
        assert [v["content"] for v in versions] == ["a", "b", "c"]

    def test_versions_missing_doc_raises(self, mgr: DocumentManager) -> None:
        with pytest.raises(OfficeNotFoundError):
            mgr.versions("doc_nope")


class TestRollback:
    def test_rollback_creates_new_version_with_old_content(
        self, mgr: DocumentManager
    ) -> None:
        doc = mgr.create(title="t", content="初稿")
        mgr.update(doc["id"], content="改坏了")
        result = mgr.rollback(doc["id"], version=1)
        assert result["current_version"] == 3
        assert result["rolled_back_to"] == 1
        assert mgr.get(doc["id"])["content"] == "初稿"

    def test_rollback_preserves_history(self, mgr: DocumentManager) -> None:
        doc = mgr.create(title="t", content="a")
        mgr.update(doc["id"], content="b")
        mgr.rollback(doc["id"], version=1)
        versions = mgr.versions(doc["id"])
        assert [v["content"] for v in versions] == ["a", "b", "a"]

    def test_rollback_missing_version_raises(self, mgr: DocumentManager) -> None:
        doc = mgr.create(title="t", content="a")
        with pytest.raises(OfficeNotFoundError):
            mgr.rollback(doc["id"], version=7)
