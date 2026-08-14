"""omni_wechat 账户凭据持久化。

目录结构（默认 ``~/.omni_wechat/``）::

    ~/.omni_wechat/
    └── accounts/
        └── <account_id>/
            ├── token.json             # {"token": "...", "baseUrl": "...", "userId": "..."}
            ├── context-tokens.json    # {"<user_id>": "<context_token>", ...}
            └── sync.json              # {"get_updates_buf": "..."}

与 OpenClaw ``~/.openclaw/openclaw-weixin/accounts/`` 布局保持一致，
便于从 OpenClaw 迁移凭据（M38.3）。

写入采用临时文件 + ``os.replace`` 原子替换，避免读到半截 JSON。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AccountStore:
    """账户凭据存储：token / context_token / sync_buf。"""

    def __init__(self, state_dir: str | Path) -> None:
        """构造存储实例。

        :param state_dir: 状态目录根（``~`` 会自动展开）
        """
        self._root = Path(state_dir).expanduser()

    @property
    def root(self) -> Path:
        """状态目录根路径。"""
        return self._root

    def _account_dir(self, account: str) -> Path:
        return self._root / "accounts" / account

    def _token_path(self, account: str) -> Path:
        return self._account_dir(account) / "token.json"

    def _context_tokens_path(self, account: str) -> Path:
        return self._account_dir(account) / "context-tokens.json"

    def _sync_path(self, account: str) -> Path:
        return self._account_dir(account) / "sync.json"

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        """读取 JSON 文件；文件不存在或解析失败返回空 dict。"""
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.debug("读取 JSON 失败: %s", path, exc_info=True)
            return {}

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        """原子写入 JSON 文件；父目录自动创建。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp: Path | None = None
        try:
            tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, path)
        except Exception:
            logger.debug("写入 JSON 失败: %s", path, exc_info=True)
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    # ------------------------------------------------------------------
    # token.json
    # ------------------------------------------------------------------
    def load_token(self, account: str) -> dict[str, Any]:
        """读取账户 token.json；不存在返回空 dict。

        返回结构：``{"token": "...", "baseUrl": "...", "userId": "...", "savedAt": "..."}``
        """
        return self._read_json(self._token_path(account))

    def save_token(
        self,
        account: str,
        *,
        token: str,
        base_url: str,
        user_id: str = "",
    ) -> None:
        """写入账户 token.json。

        :param account: 账户 ID
        :param token: iLink Bearer token
        :param base_url: iLink base URL
        :param user_id: 默认目标用户 ID（可选）
        """
        from datetime import datetime, timezone

        data = {
            "token": token,
            "baseUrl": base_url,
            "userId": user_id,
            "savedAt": datetime.now(timezone.utc).isoformat(),
        }
        self._write_json(self._token_path(account), data)

    # ------------------------------------------------------------------
    # context-tokens.json
    # ------------------------------------------------------------------
    def load_context_tokens(self, account: str) -> dict[str, str]:
        """读取所有 context_token；返回 ``{user_id: context_token}``。"""
        raw = self._read_json(self._context_tokens_path(account))
        return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}

    def load_context_token(self, account: str, user_id: str) -> str | None:
        """读取指定用户的 context_token；不存在返回 None。"""
        return self.load_context_tokens(account).get(user_id)

    def save_context_token(self, account: str, user_id: str, context_token: str) -> None:
        """保存指定用户的 context_token（合并到现有映射）。"""
        tokens = self.load_context_tokens(account)
        tokens[user_id] = context_token
        self._write_json(self._context_tokens_path(account), tokens)

    # ------------------------------------------------------------------
    # sync.json
    # ------------------------------------------------------------------
    def load_sync_buf(self, account: str) -> str:
        """读取 get_updates_buf；不存在返回空字符串。"""
        data = self._read_json(self._sync_path(account))
        buf = data.get("get_updates_buf", "")
        return buf if isinstance(buf, str) else ""

    def save_sync_buf(self, account: str, buf: str) -> None:
        """保存 get_updates_buf。"""
        self._write_json(self._sync_path(account), {"get_updates_buf": buf})

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def list_accounts(self) -> list[str]:
        """列出所有已注册账户 ID（按目录名）。"""
        accounts_dir = self._root / "accounts"
        if not accounts_dir.exists():
            return []
        return sorted(
            d.name
            for d in accounts_dir.iterdir()
            if d.is_dir() and (d / "token.json").exists()
        )

    def has_account(self, account: str) -> bool:
        """判断账户是否已注册（token.json 存在）。"""
        return self._token_path(account).exists()
