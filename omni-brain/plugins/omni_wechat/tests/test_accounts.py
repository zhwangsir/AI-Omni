"""omni_wechat AccountStore 凭据持久化测试。

使用 tmp_path 隔离文件系统，不触碰真实 ~/.omni_wechat。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from omni_wechat.accounts import AccountStore


@pytest.fixture()
def store(tmp_path: Path) -> AccountStore:
    """每个测试用独立 tmp_path 构造 AccountStore。"""
    return AccountStore(tmp_path)


class TestTokenCRUD:
    """token.json 读写测试。"""

    def test_load_token_not_exists(self, store: AccountStore) -> None:
        assert store.load_token("acc1") == {}

    def test_save_and_load_token(self, store: AccountStore) -> None:
        store.save_token("acc1", token="tok-123", base_url="https://api.example.com", user_id="user1")
        data = store.load_token("acc1")
        assert data["token"] == "tok-123"
        assert data["baseUrl"] == "https://api.example.com"
        assert data["userId"] == "user1"
        assert "savedAt" in data

    def test_save_token_without_user_id(self, store: AccountStore) -> None:
        store.save_token("acc2", token="tok-456", base_url="https://api.example.com")
        data = store.load_token("acc2")
        assert data["token"] == "tok-456"
        assert data["userId"] == ""

    def test_overwrite_token(self, store: AccountStore) -> None:
        store.save_token("acc1", token="old", base_url="https://old.com")
        store.save_token("acc1", token="new", base_url="https://new.com")
        data = store.load_token("acc1")
        assert data["token"] == "new"
        assert data["baseUrl"] == "https://new.com"

    def test_multiple_accounts_isolated(self, store: AccountStore) -> None:
        store.save_token("acc_a", token="tok-a", base_url="https://a.com")
        store.save_token("acc_b", token="tok-b", base_url="https://b.com")
        assert store.load_token("acc_a")["token"] == "tok-a"
        assert store.load_token("acc_b")["token"] == "tok-b"


class TestContextTokens:
    """context-tokens.json 读写测试。"""

    def test_load_context_tokens_empty(self, store: AccountStore) -> None:
        assert store.load_context_tokens("acc1") == {}

    def test_save_and_load_context_token(self, store: AccountStore) -> None:
        store.save_context_token("acc1", "user1@im.wechat", "ctx-tok-1")
        assert store.load_context_token("acc1", "user1@im.wechat") == "ctx-tok-1"

    def test_load_context_token_not_exists(self, store: AccountStore) -> None:
        assert store.load_context_token("acc1", "nonexistent") is None

    def test_save_multiple_context_tokens(self, store: AccountStore) -> None:
        store.save_context_token("acc1", "user1", "ctx1")
        store.save_context_token("acc1", "user2", "ctx2")
        tokens = store.load_context_tokens("acc1")
        assert tokens == {"user1": "ctx1", "user2": "ctx2"}

    def test_update_context_token(self, store: AccountStore) -> None:
        store.save_context_token("acc1", "user1", "old-ctx")
        store.save_context_token("acc1", "user1", "new-ctx")
        assert store.load_context_token("acc1", "user1") == "new-ctx"

    def test_context_tokens_isolated_by_account(self, store: AccountStore) -> None:
        store.save_context_token("acc1", "user1", "ctx-a")
        store.save_context_token("acc2", "user1", "ctx-b")
        assert store.load_context_token("acc1", "user1") == "ctx-a"
        assert store.load_context_token("acc2", "user1") == "ctx-b"


class TestSyncBuf:
    """sync.json 读写测试。"""

    def test_load_sync_buf_not_exists(self, store: AccountStore) -> None:
        assert store.load_sync_buf("acc1") == ""

    def test_save_and_load_sync_buf(self, store: AccountStore) -> None:
        store.save_sync_buf("acc1", "buf-abc-123")
        assert store.load_sync_buf("acc1") == "buf-abc-123"

    def test_overwrite_sync_buf(self, store: AccountStore) -> None:
        store.save_sync_buf("acc1", "buf-old")
        store.save_sync_buf("acc1", "buf-new")
        assert store.load_sync_buf("acc1") == "buf-new"

    def test_sync_buf_empty_string(self, store: AccountStore) -> None:
        store.save_sync_buf("acc1", "")
        assert store.load_sync_buf("acc1") == ""


class TestAccountDiscovery:
    """账户发现测试。"""

    def test_list_accounts_empty(self, store: AccountStore) -> None:
        assert store.list_accounts() == []

    def test_list_accounts_with_tokens(self, store: AccountStore) -> None:
        store.save_token("acc_b", token="t", base_url="https://b.com")
        store.save_token("acc_a", token="t", base_url="https://a.com")
        accounts = store.list_accounts()
        assert accounts == ["acc_a", "acc_b"]  # sorted

    def test_has_account_false(self, store: AccountStore) -> None:
        assert store.has_account("nonexistent") is False

    def test_has_account_true(self, store: AccountStore) -> None:
        store.save_token("acc1", token="t", base_url="https://a.com")
        assert store.has_account("acc1") is True


class TestPathExpansion:
    """路径展开测试。"""

    def test_tilde_expansion(self) -> None:
        store = AccountStore("~/.omni_wechat_test")
        assert "~" not in str(store.root)
        assert store.root.is_absolute()

    def test_root_property(self, tmp_path: Path) -> None:
        store = AccountStore(tmp_path)
        assert store.root == tmp_path


class TestCorruptedFiles:
    """损坏文件容错测试。"""

    def test_corrupted_token_json(self, store: AccountStore) -> None:
        token_path = store._token_path("acc1")
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text("not json!!!", encoding="utf-8")
        assert store.load_token("acc1") == {}

    def test_corrupted_sync_json(self, store: AccountStore) -> None:
        sync_path = store._sync_path("acc1")
        sync_path.parent.mkdir(parents=True, exist_ok=True)
        sync_path.write_text("{invalid", encoding="utf-8")
        assert store.load_sync_buf("acc1") == ""

    def test_corrupted_context_tokens_json(self, store: AccountStore) -> None:
        ctx_path = store._context_tokens_path("acc1")
        ctx_path.parent.mkdir(parents=True, exist_ok=True)
        ctx_path.write_text("bad json", encoding="utf-8")
        assert store.load_context_tokens("acc1") == {}
