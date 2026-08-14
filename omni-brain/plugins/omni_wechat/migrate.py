"""omni_wechat OpenClaw 凭据迁移。

将 OpenClaw ``~/.openclaw/openclaw-weixin/accounts/`` 的扁平文件布局::

    <account>.json                  # {"token","savedAt","baseUrl","userId"}
    <account>.sync.json             # {"get_updates_buf"}
    <account>.context-tokens.json   # {"<user_id>": "<context_token>"}
    accounts.json                   # ["<account>", ...]（可选）

迁移到 omni_wechat 的 ``accounts/<account>/`` 目录布局（见 :mod:`omni_wechat.accounts`）。
字段名完全一致，迁移为零损耗拷贝。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from omni_wechat.accounts import AccountStore

logger = logging.getLogger(__name__)


def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    """读取 JSON 文件；不存在或解析失败返回 None。"""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("迁移源 JSON 解析失败: %s", path, exc_info=True)
        return None


def _discover_accounts(src: Path) -> list[str]:
    """发现源目录中的账户 ID：优先 accounts.json，否则扫描 ``*.json`` 主文件。"""
    raw = _read_json(src / "accounts.json")
    if isinstance(raw, list):
        return sorted(str(a) for a in raw)
    accounts: set[str] = set()
    for f in src.glob("*.json"):
        name = f.name
        if name == "accounts.json" or name.endswith(".sync.json") or name.endswith(".context-tokens.json"):
            continue
        accounts.add(f.stem)
    return sorted(accounts)


def migrate_from_openclaw(
    src_dir: str | Path,
    store: AccountStore,
    account: str | None = None,
) -> list[str]:
    """从 OpenClaw 凭据目录迁移账户到 omni_wechat 存储。

    :param src_dir: OpenClaw ``openclaw-weixin/accounts/`` 目录
    :param store: 目标 :class:`AccountStore`
    :param account: 指定单个账户 ID；为 None 时迁移发现的全部账户
    :return: 成功迁移的账户 ID 列表
    :raises FileNotFoundError: 源目录不存在
    """
    src = Path(src_dir).expanduser()
    if not src.is_dir():
        raise FileNotFoundError(f"OpenClaw 凭据目录不存在: {src}")

    candidates = [account] if account else _discover_accounts(src)
    migrated: list[str] = []
    for acc in candidates:
        raw = _read_json(src / f"{acc}.json")
        if not isinstance(raw, dict):
            logger.warning("跳过 %s：token 文件缺失或损坏", acc)
            continue
        token = raw.get("token")
        if not isinstance(token, str) or not token:
            logger.warning("跳过 %s：token 字段为空", acc)
            continue

        store.save_token(
            acc,
            token=token,
            base_url=str(raw.get("baseUrl") or "https://ilinkai.weixin.qq.com"),
            user_id=str(raw.get("userId") or ""),
        )

        sync = _read_json(src / f"{acc}.sync.json")
        if isinstance(sync, dict) and isinstance(sync.get("get_updates_buf"), str):
            store.save_sync_buf(acc, sync["get_updates_buf"])

        ctx = _read_json(src / f"{acc}.context-tokens.json")
        if isinstance(ctx, dict):
            for user_id, ctx_token in ctx.items():
                if isinstance(user_id, str) and isinstance(ctx_token, str):
                    store.save_context_token(acc, user_id, ctx_token)

        migrated.append(acc)
        logger.info("已迁移账户 %s", acc)

    return migrated
