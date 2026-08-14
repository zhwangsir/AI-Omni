"""omni_wechat 工具实现：5 个 wechat_* 工具。

- ``wechat_send``         发送文本消息
- ``wechat_status``       查询插件状态（账户、token、监听）
- ``wechat_set_target``   设置默认接收人（持久化到 context-tokens.json 同级）
- ``wechat_start_listen`` 启动长轮询监听
- ``wechat_stop_listen``  停止长轮询监听

handler 返回 JSON 字符串 ``{"ok": bool, ...}``。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from omni_wechat.accounts import AccountStore
from omni_wechat.config import WechatConfig
from omni_wechat.ilink import ILinkClient
from omni_wechat.monitor import MonitorLoop

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 后台事件循环线程
# ---------------------------------------------------------------------------
class _LoopThread:
    """守护线程内运行独立 event loop，承载长轮询后台 task。

    工具 handler 是同步函数；若用 ``asyncio.run(monitor.start())`` 启动监听，
    loop 随 run 返回立即关闭并取消后台 task——监听实际上从未存活。
    因此监听循环必须运行在独立线程的长驻 event loop 上。
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for t in pending:
                t.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    def ensure_started(self) -> asyncio.AbstractEventLoop:
        """启动线程（幂等）并返回其 event loop。"""
        if self._loop is not None:
            return self._loop
        self._thread = threading.Thread(
            target=self._run, name="omni-wechat-loop", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=5.0) or self._loop is None:
            raise RuntimeError("omni_wechat 后台事件循环启动超时")
        return self._loop

    def submit(self, coro: Any, timeout: float = 10.0) -> Any:
        """从任意线程提交 coroutine 到后台 loop 并同步等待结果。"""
        loop = self.ensure_started()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=timeout)

    def shutdown(self) -> None:
        """停止 loop 并回收线程（幂等）。"""
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._loop = None
        self._thread = None
        self._ready.clear()


# ---------------------------------------------------------------------------
# 运行时单例
# ---------------------------------------------------------------------------
class Runtime:
    """进程内运行时：持有 client / monitor / store / config / 事件发布器 / 后台 loop。"""

    def __init__(self) -> None:
        self.config: WechatConfig | None = None
        self.store: AccountStore | None = None
        self.client: ILinkClient | None = None
        self.monitor: MonitorLoop | None = None
        self.event_publisher: Any = None
        self.loop_thread: _LoopThread | None = None
        # 测试用：注入 fake backend（ILinkClient HttpBackend 协议）
        self.backend: Any = None


_runtime = Runtime()


def _reset_runtime(runtime: Runtime | None = None) -> Runtime:
    """替换进程内运行时（测试隔离用），返回新实例。"""
    global _runtime
    _runtime = runtime or Runtime()
    return _runtime


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------
def _get_config(rt: Runtime) -> WechatConfig:
    """获取或构建配置。"""
    if rt.config is None:
        rt.config = WechatConfig.from_env()
    return rt.config


def _get_store(rt: Runtime) -> AccountStore:
    """获取或构建账户存储。"""
    if rt.store is None:
        cfg = _get_config(rt)
        rt.store = AccountStore(Path(cfg.state_dir).expanduser())
    return rt.store


def _get_client(rt: Runtime) -> ILinkClient:
    """获取或构建 iLink 客户端。"""
    if rt.client is None:
        cfg = _get_config(rt)
        # 若 token 为空但 account 已配置，尝试从 store 加载
        if not cfg.token and cfg.account:
            store = _get_store(rt)
            token_data = store.load_token(cfg.account)
            if token_data.get("token"):
                cfg.token = token_data["token"]
            if not cfg.default_target and token_data.get("userId"):
                cfg.default_target = token_data["userId"]
        rt.client = ILinkClient(cfg, backend=rt.backend)
    return rt.client


def _run_async(coro: Any) -> Any:
    """同步执行 async coroutine（CLI/工具 handler 上下文）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # 已有运行中 loop：创建 task 并同步等待（仅在某些场景有效，记录警告）
    logger.warning("在运行中的事件循环内同步等待 async coroutine，可能阻塞")
    return loop.run_until_complete(coro) if not loop.is_running() else asyncio.run(coro)


def _publish(rt: Runtime, event_type: str, payload: dict[str, Any]) -> None:
    """向事件总线发布事件（未接入总线时静默跳过）。"""
    bus = rt.event_publisher
    if bus is None or not callable(getattr(bus, "publish", None)):
        return
    try:
        result = bus.publish(event_type, payload)
        if asyncio.iscoroutine(result):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(result)
            except RuntimeError:
                asyncio.run(result)
    except Exception:  # noqa: BLE001
        logger.debug("事件发布失败: %s", event_type, exc_info=True)


def _ok(data: Any) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False)


def _err(message: str, code: str = "E_INTERNAL") -> str:
    return json.dumps(
        {"ok": False, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Tool 元数据注册表
# ---------------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = []


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    required: list[str] | None = None,
    emoji: str = "",
) -> Callable:
    """@tool 装饰器：为函数附加 tool schema 元数据并登记到 TOOLS。"""

    def decorator(func: Callable) -> Callable:
        TOOLS.append(
            {
                "name": name,
                "description": description,
                "emoji": emoji,
                "schema": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": parameters,
                        "required": list(required or []),
                    },
                },
                "handler_func": func,
            }
        )
        return func

    return decorator


# ---------------------------------------------------------------------------
# Tool 1：发送消息
# ---------------------------------------------------------------------------
@tool(
    name="wechat_send",
    description="发送微信文本消息给指定用户（默认发往配置的 default_target）。直连腾讯 iLink Bot API。",
    parameters={
        "text": {
            "type": "string",
            "description": "消息文本内容",
        },
        "target": {
            "type": "string",
            "description": "目标用户 ID（如 xxx@im.wechat）；不传则使用 default_target",
        },
    },
    required=["text"],
    emoji="💬",
)
def wechat_send(text: str, target: str | None = None) -> str:
    """发送微信文本消息。"""
    try:
        rt = _runtime
        cfg = _get_config(rt)
        client = _get_client(rt)
        store = _get_store(rt)

        resolved_target = (target or cfg.default_target or "").strip()
        if not resolved_target:
            return _err(
                "未指定 target 且 default_target 为空",
                code="E_NO_TARGET",
            )
        # 取 context_token（如有）
        context_token = store.load_context_token(cfg.account, resolved_target)

        result = _run_async(
            client.send_text(
                resolved_target,
                text,
                context_token=context_token,
            )
        )
        if not result.get("ok"):
            err = result.get("error", {})
            return _err(err.get("message", "发送失败"), code=err.get("code", "E_SEND_FAILED"))

        _publish(rt, "wechat.message_sent", {
            "target": resolved_target,
            "message_id": result.get("message_id"),
            "text_preview": text[:50],
        })
        return _ok({
            "message_id": result.get("message_id"),
            "target": resolved_target,
            "channel": "ilink",
        })
    except Exception as exc:  # noqa: BLE001
        logger.debug("wechat_send 失败: %s", exc, exc_info=True)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 2：状态查询
# ---------------------------------------------------------------------------
@tool(
    name="wechat_status",
    description="查询微信插件状态：账户、token 是否配置、监听是否运行、sync_buf 长度等。",
    parameters={},
    emoji="📊",
)
def wechat_status() -> str:
    """查询插件状态。"""
    try:
        rt = _runtime
        cfg = _get_config(rt)
        store = _get_store(rt)

        sync_buf = ""
        if cfg.account:
            sync_buf = store.load_sync_buf(cfg.account)

        is_listening = rt.monitor is not None and rt.monitor.is_running

        return _ok({
            "account": cfg.account or None,
            "default_target": cfg.default_target or None,
            "has_token": bool(cfg.token),
            "base_url": cfg.base_url,
            "channel_version": cfg.channel_version,
            "client_version_int": cfg.client_version_int,
            "listening": is_listening,
            "sync_buf_len": len(sync_buf),
            "state_dir": str(store.root),
            "registered_accounts": store.list_accounts(),
        })
    except Exception as exc:  # noqa: BLE001
        logger.debug("wechat_status 失败: %s", exc, exc_info=True)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 3：设置默认接收人
# ---------------------------------------------------------------------------
@tool(
    name="wechat_set_target",
    description="设置默认微信消息接收人（持久化到 token.json 的 userId 字段）。",
    parameters={
        "target": {
            "type": "string",
            "description": "目标用户 ID（如 xxx@im.wechat）",
        },
    },
    required=["target"],
    emoji="🎯",
)
def wechat_set_target(target: str) -> str:
    """设置默认接收人。"""
    try:
        if not target or not str(target).strip():
            return _err("target 不能为空", code="E_INVALID_PARAMS")
        rt = _runtime
        cfg = _get_config(rt)
        store = _get_store(rt)
        if not cfg.account:
            return _err("未配置 account，无法持久化", code="E_NO_ACCOUNT")

        # 更新内存中的 config
        cfg.default_target = target.strip()

        # 持久化到 token.json
        token_data = store.load_token(cfg.account)
        if token_data:
            store.save_token(
                cfg.account,
                token=token_data.get("token", cfg.token),
                base_url=token_data.get("baseUrl", cfg.base_url),
                user_id=cfg.default_target,
            )
        return _ok({"default_target": cfg.default_target})
    except Exception as exc:  # noqa: BLE001
        logger.debug("wechat_set_target 失败: %s", exc, exc_info=True)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 4：启动监听
# ---------------------------------------------------------------------------
@tool(
    name="wechat_start_listen",
    description="启动微信长轮询监听（后台 asyncio task），收到消息发布 wechat.message_received 事件。",
    parameters={},
    emoji="👂",
)
def wechat_start_listen() -> str:
    """启动监听循环。"""
    try:
        rt = _runtime
        cfg = _get_config(rt)
        if not cfg.token:
            return _err("未配置 token，无法启动监听", code="E_NO_TOKEN")
        if not cfg.account:
            return _err("未配置 account，无法启动监听", code="E_NO_ACCOUNT")

        if rt.monitor is not None and rt.monitor.is_running:
            return _ok({"listening": True, "message": "监听已在运行"})

        client = _get_client(rt)
        store = _get_store(rt)

        # 构造消息回调：发布到事件总线
        def on_message(msg: dict[str, Any]) -> None:
            _publish(rt, "wechat.message_received", {
                "from_user_id": msg.get("from_user_id"),
                "to_user_id": msg.get("to_user_id"),
                "client_id": msg.get("client_id"),
                "message_type": msg.get("message_type"),
                "item_list": msg.get("item_list"),
                "context_token": msg.get("context_token"),
            })
            # 顺手保存 context_token（用于后续回复）
            from_user = msg.get("from_user_id")
            ctx_token = msg.get("context_token")
            if from_user and ctx_token:
                try:
                    store.save_context_token(cfg.account, from_user, ctx_token)
                except Exception:
                    logger.debug("保存 context_token 失败", exc_info=True)

        rt.monitor = MonitorLoop(client, store, cfg.account, on_message=on_message)
        # 监听 task 必须跑在长驻后台 loop 上（asyncio.run 会在返回时取消它）
        if rt.loop_thread is None:
            rt.loop_thread = _LoopThread()
        rt.loop_thread.submit(rt.monitor.start())

        _publish(rt, "wechat.listen_started", {"account": cfg.account})
        return _ok({"listening": True, "account": cfg.account})
    except Exception as exc:  # noqa: BLE001
        logger.debug("wechat_start_listen 失败: %s", exc, exc_info=True)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 5：停止监听
# ---------------------------------------------------------------------------
@tool(
    name="wechat_stop_listen",
    description="停止微信长轮询监听（幂等）。",
    parameters={},
    emoji="🛑",
)
def wechat_stop_listen() -> str:
    """停止监听循环。"""
    try:
        rt = _runtime
        if rt.monitor is None:
            return _ok({"listening": False, "message": "监听未启动"})
        monitor = rt.monitor
        rt.monitor = None
        if rt.loop_thread is not None:
            rt.loop_thread.submit(monitor.stop())
        else:
            _run_async(monitor.stop())
        _publish(rt, "wechat.listen_stopped", {})
        return _ok({"listening": False})
    except Exception as exc:  # noqa: BLE001
        logger.debug("wechat_stop_listen 失败: %s", exc, exc_info=True)
        return _err(str(exc))


def shutdown_runtime(timeout: float = 10.0) -> None:
    """停止监听 + 关闭客户端 + 关停后台事件循环线程（幂等，供插件卸载调用）。"""
    rt = _runtime
    lt = rt.loop_thread
    try:
        if rt.monitor is not None:
            monitor = rt.monitor
            rt.monitor = None
            if lt is not None:
                lt.submit(monitor.stop(), timeout=timeout)
            else:
                _run_async(monitor.stop())
        if rt.client is not None:
            client = rt.client
            rt.client = None
            if lt is not None:
                lt.submit(client.close(), timeout=timeout)
            else:
                _run_async(client.close())
    except Exception:  # noqa: BLE001
        logger.debug("shutdown_runtime 清理异常", exc_info=True)
    finally:
        if lt is not None:
            lt.shutdown()
            rt.loop_thread = None
        rt.event_publisher = None


# ---------------------------------------------------------------------------
# 注册（对齐 WeBrain 插件契约：ctx.register_tool + 可选事件总线接入）
# ---------------------------------------------------------------------------
def _make_handler(func: Callable) -> Callable:
    """把工具函数适配为 registry handler：``(args: dict, **kw) -> JSON 字符串``。"""

    def handler(args: dict[str, Any], **_: Any) -> str:
        try:
            return func(**(args or {}))
        except Exception as exc:  # 参数错误等，统一为 ok:false
            logger.debug("wechat tool %s 调用失败: %s", getattr(func, "__name__", "?"), exc)
            return _err(str(exc))

    return handler


def register(ctx) -> None:
    """把 5 个 wechat_* 工具注册到插件上下文；若 ctx 携带事件总线则接入。"""
    for meta in TOOLS:
        ctx.register_tool(
            name=meta["name"],
            description=meta["description"],
            emoji=meta["emoji"],
            schema=meta["schema"],
            handler_func=_make_handler(meta["handler_func"]),
        )
    bus = getattr(ctx, "event_bus", None)
    if bus is not None and callable(getattr(bus, "publish", None)):
        _runtime.event_publisher = bus
    logger.info("omni_wechat 插件已注册 %d 个 tools", len(TOOLS))
