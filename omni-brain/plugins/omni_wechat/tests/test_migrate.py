"""omni_wechat OpenClaw 凭据迁移测试。

验证从 OpenClaw ``~/.openclaw/openclaw-weixin/accounts/`` 扁平文件布局
迁移到 omni_wechat ``accounts/<account>/`` 目录布局，字段零损耗。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omni_wechat.accounts import AccountStore
from omni_wechat.migrate import migrate_from_openclaw


def _write_openclaw_account(
    src: Path,
    account: str,
    *,
    token: str = "tok-abc",
    base_url: str = "https://ilinkai.weixin.qq.com",
    user_id: str = "u1@im.wechat",
    sync_buf: str | None = "buf-xyz",
    context_tokens: dict[str, str] | None = None,
) -> None:
    """在 src 目录生成 OpenClaw 布局的凭据文件。"""
    src.mkdir(parents=True, exist_ok=True)
    (src / f"{account}.json").write_text(
        json.dumps({
            "token": token,
            "savedAt": "2026-07-24T15:24:42.630Z",
            "baseUrl": base_url,
            "userId": user_id,
        }),
        encoding="utf-8",
    )
    if sync_buf is not None:
        (src / f"{account}.sync.json").write_text(
            json.dumps({"get_updates_buf": sync_buf}), encoding="utf-8"
        )
    if context_tokens is not None:
        (src / f"{account}.context-tokens.json").write_text(
            json.dumps(context_tokens), encoding="utf-8"
        )


class TestMigrateBasic:
    def test_migrates_token_fields(self, tmp_path: Path) -> None:
        src = tmp_path / "openclaw"
        _write_openclaw_account(src, "acc-1", token="tok-secret", user_id="me@im.wechat")
        store = AccountStore(tmp_path / "dest")

        migrated = migrate_from_openclaw(src, store)

        assert migrated == ["acc-1"]
        data = store.load_token("acc-1")
        assert data["token"] == "tok-secret"
        assert data["baseUrl"] == "https://ilinkai.weixin.qq.com"
        assert data["userId"] == "me@im.wechat"

    def test_migrates_sync_buf(self, tmp_path: Path) -> None:
        src = tmp_path / "openclaw"
        _write_openclaw_account(src, "acc-1", sync_buf="buf-123")
        store = AccountStore(tmp_path / "dest")

        migrate_from_openclaw(src, store)

        assert store.load_sync_buf("acc-1") == "buf-123"

    def test_migrates_context_tokens(self, tmp_path: Path) -> None:
        src = tmp_path / "openclaw"
        _write_openclaw_account(
            src, "acc-1",
            context_tokens={"u1@im.wechat": "ctx-1", "u2@im.wechat": "ctx-2"},
        )
        store = AccountStore(tmp_path / "dest")

        migrate_from_openclaw(src, store)

        assert store.load_context_token("acc-1", "u1@im.wechat") == "ctx-1"
        assert store.load_context_token("acc-1", "u2@im.wechat") == "ctx-2"

    def test_account_listed_after_migration(self, tmp_path: Path) -> None:
        src = tmp_path / "openclaw"
        _write_openclaw_account(src, "acc-1")
        store = AccountStore(tmp_path / "dest")

        migrate_from_openclaw(src, store)

        assert store.has_account("acc-1")
        assert store.list_accounts() == ["acc-1"]


class TestMigrateEdgeCases:
    def test_missing_sync_and_context_files_tolerated(self, tmp_path: Path) -> None:
        """只有 token 文件时也能迁移。"""
        src = tmp_path / "openclaw"
        _write_openclaw_account(src, "acc-1", sync_buf=None, context_tokens=None)
        store = AccountStore(tmp_path / "dest")

        migrated = migrate_from_openclaw(src, store)

        assert migrated == ["acc-1"]
        assert store.load_sync_buf("acc-1") == ""
        assert store.load_context_tokens("acc-1") == {}

    def test_specific_account_only(self, tmp_path: Path) -> None:
        """指定 account 时只迁移该账户。"""
        src = tmp_path / "openclaw"
        _write_openclaw_account(src, "acc-1")
        _write_openclaw_account(src, "acc-2")
        store = AccountStore(tmp_path / "dest")

        migrated = migrate_from_openclaw(src, store, account="acc-2")

        assert migrated == ["acc-2"]
        assert not store.has_account("acc-1")
        assert store.has_account("acc-2")

    def test_multiple_accounts_via_accounts_json(self, tmp_path: Path) -> None:
        """存在 accounts.json 时按其列表迁移。"""
        src = tmp_path / "openclaw"
        _write_openclaw_account(src, "acc-1")
        _write_openclaw_account(src, "acc-2")
        (src / "accounts.json").write_text(
            json.dumps(["acc-1", "acc-2"]), encoding="utf-8"
        )
        store = AccountStore(tmp_path / "dest")

        migrated = migrate_from_openclaw(src, store)

        assert migrated == ["acc-1", "acc-2"]

    def test_empty_source_dir_returns_empty(self, tmp_path: Path) -> None:
        src = tmp_path / "openclaw"
        src.mkdir()
        store = AccountStore(tmp_path / "dest")

        assert migrate_from_openclaw(src, store) == []

    def test_nonexistent_source_dir_raises(self, tmp_path: Path) -> None:
        store = AccountStore(tmp_path / "dest")
        with pytest.raises(FileNotFoundError):
            migrate_from_openclaw(tmp_path / "no-such-dir", store)

    def test_corrupted_token_file_skipped(self, tmp_path: Path) -> None:
        """损坏的 token 文件跳过，不阻塞其他账户。"""
        src = tmp_path / "openclaw"
        src.mkdir()
        (src / "bad.json").write_text("{not json", encoding="utf-8")
        _write_openclaw_account(src, "good-1")
        store = AccountStore(tmp_path / "dest")

        migrated = migrate_from_openclaw(src, store)

        assert migrated == ["good-1"]

    def test_token_file_without_token_skipped(self, tmp_path: Path) -> None:
        """token 字段为空的文件不迁移。"""
        src = tmp_path / "openclaw"
        _write_openclaw_account(src, "acc-empty", token="")
        store = AccountStore(tmp_path / "dest")

        migrated = migrate_from_openclaw(src, store)

        assert migrated == []
        assert not store.has_account("acc-empty")
