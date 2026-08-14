"""omni_office SQLite 存储层（db.py）单元测试。

契约：
- ``:memory:`` 与文件路径两种模式；父目录自动创建
- ``init_schema`` 幂等（重复调用不报错）
- 上下文管理器自动 init_schema + commit + close
- 六张表：documents / document_versions / emails / email_templates /
  auto_reply_rules / events
- 默认路径 ``~/.ai-omni/office/office.db``，env ``AI_OMNI_OFFICE_DB`` 可覆盖
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from omni_office.db import OfficeDB, default_db_path

EXPECTED_TABLES = {
    "documents",
    "document_versions",
    "emails",
    "email_templates",
    "auto_reply_rules",
    "events",
}


def _table_names(db: OfficeDB) -> set[str]:
    rows = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {r["name"] for r in rows}


class TestSchema:
    def test_init_schema_creates_all_tables(self) -> None:
        db = OfficeDB(":memory:")
        db.init_schema()
        assert EXPECTED_TABLES <= _table_names(db)
        db.close()

    def test_init_schema_idempotent(self) -> None:
        db = OfficeDB(":memory:")
        db.init_schema()
        db.init_schema()  # 第二次不报错
        assert EXPECTED_TABLES <= _table_names(db)
        db.close()

    def test_foreign_keys_enabled(self) -> None:
        db = OfficeDB(":memory:")
        db.init_schema()
        row = db.conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1
        db.close()


class TestContextManager:
    def test_context_manager_auto_init_and_close(self) -> None:
        with OfficeDB(":memory:") as db:
            assert EXPECTED_TABLES <= _table_names(db)
        assert db._conn is None

    def test_file_db_parent_dir_created(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "dir" / "office.db"
        with OfficeDB(target) as db:
            db.conn.execute("SELECT 1")
        assert target.is_file()


class TestDefaultPath:
    def test_default_db_path(self) -> None:
        assert default_db_path() == Path.home() / ".ai-omni" / "office" / "office.db"

    def test_env_override(self, monkeypatch, tmp_path: Path) -> None:
        custom = tmp_path / "custom.db"
        monkeypatch.setenv("AI_OMNI_OFFICE_DB", str(custom))
        assert default_db_path() == custom


class TestConnection:
    def test_conn_lazy_connect(self) -> None:
        db = OfficeDB(":memory:")
        assert db._conn is None
        _ = db.conn
        assert isinstance(db._conn, sqlite3.Connection)
        db.close()

    def test_close_idempotent(self) -> None:
        db = OfficeDB(":memory:")
        db.init_schema()
        db.close()
        db.close()
        assert db._conn is None

    def test_row_factory_dict_like(self) -> None:
        with OfficeDB(":memory:") as db:
            db.conn.execute(
                "INSERT INTO documents (id, title, created_at, updated_at) "
                "VALUES ('d1', 't', 0, 0)"
            )
            row = db.conn.execute("SELECT * FROM documents WHERE id='d1'").fetchone()
            assert row["title"] == "t"


#: M34.2 之前的旧 events 表 schema（无 completed / updated_at 列）
_LEGACY_EVENTS_SCHEMA = """
CREATE TABLE events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    start_ts REAL NOT NULL,
    end_ts REAL NOT NULL,
    attendees TEXT NOT NULL DEFAULT '[]',
    reminder_minutes INTEGER,
    reminded INTEGER NOT NULL DEFAULT 0,
    location TEXT,
    notes TEXT,
    doc_id TEXT REFERENCES documents(id),
    created_at REAL NOT NULL DEFAULT 0
);
"""


def _event_columns(db: OfficeDB) -> set[str]:
    rows = db.conn.execute("PRAGMA table_info(events)").fetchall()
    return {r["name"] for r in rows}


class TestEventsSchemaMigration:
    """M34.2：events 表补 completed / updated_at 列（移动端完成态同步）。"""

    def test_fresh_schema_has_completed_and_updated_at(self) -> None:
        db = OfficeDB(":memory:")
        db.init_schema()
        cols = _event_columns(db)
        assert "completed" in cols
        assert "updated_at" in cols
        db.close()

    def test_legacy_db_migrated(self, tmp_path: Path) -> None:
        """旧库（无新列）init_schema 后自动补列，已有数据保留。"""
        target = tmp_path / "legacy.db"
        conn = sqlite3.connect(target)
        conn.executescript(_LEGACY_EVENTS_SCHEMA)
        conn.execute(
            "INSERT INTO events (id, title, start_ts, end_ts, created_at) "
            "VALUES ('evt_old', '旧日程', 1000, 2000, 500)"
        )
        conn.commit()
        conn.close()

        db = OfficeDB(target)
        db.init_schema()
        cols = _event_columns(db)
        assert "completed" in cols
        assert "updated_at" in cols
        row = db.conn.execute(
            "SELECT * FROM events WHERE id = 'evt_old'"
        ).fetchone()
        assert row["title"] == "旧日程"
        assert row["completed"] == 0  # 默认未完成
        assert row["updated_at"] == 0
        db.close()

    def test_migration_idempotent(self, tmp_path: Path) -> None:
        target = tmp_path / "mig.db"
        conn = sqlite3.connect(target)
        conn.executescript(_LEGACY_EVENTS_SCHEMA)
        conn.close()
        db = OfficeDB(target)
        db.init_schema()
        db.init_schema()  # 第二次不报错
        assert "completed" in _event_columns(db)
        db.close()
