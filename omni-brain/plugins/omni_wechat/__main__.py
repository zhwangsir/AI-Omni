"""omni_wechat CLI 入口：``python -m omni_wechat <subcommand>``。

子命令：
- ``send <text> [--target <user_id>]``   发送文本消息
- ``status``                              查询插件状态
- ``set-target <user_id>``                设置默认接收人
- ``listen``                              启动长轮询监听（前台运行，Ctrl+C 停止）
- ``config``                              打印当前配置摘要
- ``migrate --from-openclaw <dir>``       从 OpenClaw 凭据目录迁移账户
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from omni_wechat.accounts import AccountStore
from omni_wechat.config import WechatConfig
from omni_wechat.ilink import ILinkClient
from omni_wechat.migrate import migrate_from_openclaw
from omni_wechat.monitor import MonitorLoop


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="omni_wechat", description="微信消息收发 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    send = sub.add_parser("send", help="发送文本消息")
    send.add_argument("text", help="消息内容")
    send.add_argument("--target", default=None, help="目标用户 ID")

    sub.add_parser("status", help="查询插件状态")

    set_target = sub.add_parser("set-target", help="设置默认接收人")
    set_target.add_argument("target", help="目标用户 ID")

    sub.add_parser("listen", help="启动长轮询监听（前台）")

    sub.add_parser("config", help="打印配置摘要")

    migrate = sub.add_parser("migrate", help="从 OpenClaw 凭据目录迁移账户")
    migrate.add_argument(
        "--from-openclaw",
        required=True,
        dest="from_openclaw",
        help="OpenClaw openclaw-weixin/accounts 目录路径",
    )
    migrate.add_argument("--account", default=None, help="只迁移指定账户 ID")

    return p


def _load_config_and_client() -> tuple[WechatConfig, ILinkClient, AccountStore]:
    """加载配置并构建客户端。"""
    cfg = WechatConfig.from_env()
    store = AccountStore(cfg.state_dir)
    # 从 store 加载 token
    if not cfg.token and cfg.account:
        token_data = store.load_token(cfg.account)
        if token_data.get("token"):
            cfg.token = token_data["token"]
        if not cfg.default_target and token_data.get("userId"):
            cfg.default_target = token_data["userId"]
    client = ILinkClient(cfg)
    return cfg, client, store


async def _cmd_send(args: argparse.Namespace) -> int:
    cfg, client, store = _load_config_and_client()
    try:
        target = (args.target or cfg.default_target or "").strip()
        if not target:
            print(json.dumps({"ok": False, "error": "未指定 target 且 default_target 为空"}))
            return 1
        context_token = store.load_context_token(cfg.account, target)
        result = await client.send_text(target, args.text, context_token=context_token)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    finally:
        await client.close()


async def _cmd_status(_args: argparse.Namespace) -> int:
    cfg, client, store = _load_config_and_client()
    try:
        sync_buf = store.load_sync_buf(cfg.account) if cfg.account else ""
        print(json.dumps({
            "ok": True,
            "data": {
                "account": cfg.account or None,
                "default_target": cfg.default_target or None,
                "has_token": bool(cfg.token),
                "base_url": cfg.base_url,
                "channel_version": cfg.channel_version,
                "client_version_int": cfg.client_version_int,
                "sync_buf_len": len(sync_buf),
                "state_dir": str(store.root),
                "registered_accounts": store.list_accounts(),
            },
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        await client.close()


async def _cmd_set_target(args: argparse.Namespace) -> int:
    cfg, client, store = _load_config_and_client()
    try:
        if not cfg.account:
            print(json.dumps({"ok": False, "error": "未配置 account"}))
            return 1
        token_data = store.load_token(cfg.account)
        store.save_token(
            cfg.account,
            token=token_data.get("token", cfg.token),
            base_url=token_data.get("baseUrl", cfg.base_url),
            user_id=args.target,
        )
        print(json.dumps({"ok": True, "data": {"default_target": args.target}}, ensure_ascii=False))
        return 0
    finally:
        await client.close()


async def _cmd_listen(_args: argparse.Namespace) -> int:
    cfg, client, store = _load_config_and_client()
    if not cfg.token:
        print(json.dumps({"ok": False, "error": "未配置 token"}))
        return 1
    if not cfg.account:
        print(json.dumps({"ok": False, "error": "未配置 account"}))
        return 1

    def on_message(msg: dict) -> None:
        print(json.dumps({"event": "wechat.message_received", "msg": msg}, ensure_ascii=False))
        # 顺手保存 context_token
        from_user = msg.get("from_user_id")
        ctx_token = msg.get("context_token")
        if from_user and ctx_token:
            try:
                store.save_context_token(cfg.account, from_user, ctx_token)
            except Exception:
                pass

    monitor = MonitorLoop(client, store, cfg.account, on_message=on_message)
    await monitor.start()
    print(f"[omni_wechat] 监听已启动 account={cfg.account}", file=sys.stderr)
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n[omni_wechat] 停止监听...", file=sys.stderr)
        await monitor.stop()
    finally:
        await client.close()
    return 0


async def _cmd_config(_args: argparse.Namespace) -> int:
    cfg = WechatConfig.from_env()
    print(json.dumps({"ok": True, "data": cfg.summary()}, ensure_ascii=False, indent=2))
    return 0


async def _cmd_migrate(args: argparse.Namespace) -> int:
    cfg = WechatConfig.from_env()
    store = AccountStore(cfg.state_dir)
    try:
        migrated = migrate_from_openclaw(args.from_openclaw, store, account=args.account)
    except FileNotFoundError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "ok": True,
        "data": {"migrated": migrated, "state_dir": str(store.root)},
    }, ensure_ascii=False, indent=2))
    return 0 if migrated else 1


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "send": _cmd_send,
        "status": _cmd_status,
        "set-target": _cmd_set_target,
        "listen": _cmd_listen,
        "config": _cmd_config,
        "migrate": _cmd_migrate,
    }
    handler = handlers.get(args.cmd)
    if handler is None:
        parser.print_help()
        return 1
    return asyncio.run(handler(args))


if __name__ == "__main__":
    sys.exit(main())
