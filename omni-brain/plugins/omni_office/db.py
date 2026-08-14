"""omni_office SQLite 存储层。

单库六表：documents / document_versions / emails / email_templates /
auto_reply_rules / events。默认落盘 ``~/.ai-omni/office/office.db``，
可用环境变量 ``AI_OMNI_OFFICE_DB`` 覆盖（测试与 CLI 隔离用）；
``:memory:`` 走纯内存库，不触盘。

设计要点：
- 连接惰性建立（``conn`` 属性首次访问时才 connect）
- 行工厂 ``sqlite3.Row``，支持 ``row["col"]`` 按名取值
- 外键约束默认开启（document_versions → documents 级联删除）
- ``init_schema`` 幂等（CREATE TABLE IF NOT EXISTS），上下文管理器自动调用
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

#: 默认库路径环境变量名
ENV_DB_PATH = "AI_OMNI_OFFICE_DB"


def default_db_path() -> Path:
    """返回默认库路径；``AI_OMNI_OFFICE_DB`` 环境变量优先。"""
    env = os.environ.get(ENV_DB_PATH)
    if env:
        return Path(env)
    return Path.home() / ".ai-omni" / "office" / "office.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    current_version INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS document_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    note TEXT,
    created_at REAL NOT NULL DEFAULT 0,
    UNIQUE (doc_id, version)
);

CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY,
    uid TEXT,
    folder TEXT NOT NULL DEFAULT 'inbox',
    sender TEXT,
    recipients TEXT NOT NULL DEFAULT '[]',
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    read INTEGER NOT NULL DEFAULT 0,
    auto_replied INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_emails_folder ON emails(folder);
CREATE INDEX IF NOT EXISTS idx_emails_uid ON emails(uid);

CREATE TABLE IF NOT EXISTS email_templates (
    name TEXT PRIMARY KEY,
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS auto_reply_rules (
    name TEXT PRIMARY KEY,
    keyword TEXT,
    sender_match TEXT,
    template TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
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
    completed INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_range ON events(start_ts, end_ts);
"""

#: M34.2 增量列：旧库（无 completed / updated_at）经 ALTER TABLE 幂等补齐。
_EVENTS_PATCH_COLUMNS: tuple[tuple[str, str], ...] = (
    ("completed", "INTEGER NOT NULL DEFAULT 0"),
    ("updated_at", "REAL NOT NULL DEFAULT 0"),
)


class OfficeDB:
    """omni_office 的 SQLite 连接封装。

    :param path: 库文件路径、``:memory:`` 或 ``None``（取 :func:`default_db_path`）
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path: str = str(path) if path is not None else str(default_db_path())
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """惰性建立连接；文件库的父目录自动创建。"""
        if self._conn is None:
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            self._conn = conn
        return self._conn

    def init_schema(self) -> None:
        """建表（幂等）；对既有 events 表幂等补齐 M34.2 增量列。"""
        self.conn.executescript(_SCHEMA)
        existing = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(events)").fetchall()
        }
        for column, ddl in _EVENTS_PATCH_COLUMNS:
            if column not in existing:
                self.conn.execute(
                    f"ALTER TABLE events ADD COLUMN {column} {ddl}"
                )
        self.conn.commit()

    def close(self) -> None:
        """关闭连接（幂等）。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> OfficeDB:
        """进入上下文：自动建表。"""
        self.init_schema()
        return self

    def __exit__(self, *_exc: object) -> None:
        """退出上下文：提交并关闭。"""
        if self._conn is not None:
            self._conn.commit()
        self.close()
