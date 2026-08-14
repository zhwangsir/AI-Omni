"""omni_wechat iLink 协议客户端。

直连腾讯 iLink Bot API（``https://ilinkai.weixin.qq.com``），协议字段对齐
``@tencent-weixin/openclaw-weixin@2.4.6``：

- ``POST /ilink/bot/sendmessage``   发送消息
- ``POST /ilink/bot/getupdates``    长轮询接收消息
- ``POST /ilink/bot/msg/notifystart`` 通知服务端客户端上线
- ``POST /ilink/bot/msg/notifystop``  通知服务端客户端下线

请求头必须包含：

- ``Content-Type: application/json``
- ``AuthorizationType: ilink_bot_token``
- ``Authorization: Bearer <token>``
- ``X-WECHAT-UIN: <base64 of decimal uint32>``（每请求随机）
- ``iLink-App-Id: bot``
- ``iLink-App-ClientVersion: <uint32>``（(major<<16)|(minor<<8)|patch）

请求体必须携带 ``base_info``::

    {"channel_version": "2.4.6", "bot_agent": "OpenClaw/omni_wechat"}

发送消息的 ``msg`` 必须含 ``message_type=2 (BOT)`` 与 ``message_state=2 (FINISH)``，
否则服务端返回 ``ret=-2 errmsg=prepare failed``。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import secrets
import time
from typing import Any, Protocol

from omni_wechat.config import WechatConfig
from omni_wechat.errors import error_response, success_response

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 协议常量（与 openclaw-weixin 对齐）
# ---------------------------------------------------------------------------

#: MessageType.BOT — 机器人发出的消息
MESSAGE_TYPE_BOT = 2
#: MessageState.FINISH — 已完成状态
MESSAGE_STATE_FINISH = 2
#: MessageItemType.TEXT — 文本消息项
MESSAGE_ITEM_TYPE_TEXT = 1


# ---------------------------------------------------------------------------
# HTTP backend 抽象
# ---------------------------------------------------------------------------
class HttpBackend(Protocol):
    """HTTP backend 抽象协议（用于测试注入 fake）。"""

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> tuple[int, Any]:
        """执行 HTTP 请求，返回 (status_code, body)。"""
        ...


class HttpxBackend:
    """基于 httpx 的真实 HTTP backend。"""

    def __init__(
        self,
        config: WechatConfig,
        timeout: float | None = None,
    ) -> None:
        self.config = config
        # 惰性导入：避免模块加载时拉入 httpx
        import httpx

        self._client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            timeout=timeout if timeout is not None else config.timeout_s,
        )
        self._httpx = httpx

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> tuple[int, Any]:
        """执行 HTTP 请求。

        将 httpx 异常翻译为内建异常，保持 ILinkClient 的异常契约与 backend 无关：
        - ``httpx.TimeoutException`` → ``TimeoutError``（长轮询超时是正常控制流）
        - 其余 ``httpx.TransportError`` → ``OSError``（连接失败等）
        """
        try:
            response = await self._client.request(method, path, **kwargs)
        except self._httpx.TimeoutException as exc:
            raise TimeoutError(str(exc)) from exc
        except self._httpx.TransportError as exc:
            raise OSError(str(exc)) from exc
        body: Any
        try:
            body = response.json()
        except Exception:
            body = response.text
        return response.status_code, body

    async def close(self) -> None:
        """关闭底层 HTTP 连接。"""
        await self._client.aclose()


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def random_wechat_uin() -> str:
    """生成 X-WECHAT-UIN：随机 uint32 → 十进制字符串 → base64。"""
    uint32 = secrets.randbits(32)
    return base64.b64encode(str(uint32).encode("utf-8")).decode("ascii")


def generate_client_id(prefix: str = "omni-wechat") -> str:
    """生成 client_id：``<prefix>:<timestamp_ms>-<8位hex>``（对齐 openclaw-weixin generateId）。"""
    ts_ms = int(time.time() * 1000)
    return f"{prefix}:{ts_ms}-{secrets.token_hex(4)}"


# ---------------------------------------------------------------------------
# ILinkClient
# ---------------------------------------------------------------------------
class ILinkClient:
    """iLink Bot API 客户端。

    所有方法返回 ``{"ok": True, ...}`` 或 ``{"ok": False, "error": {...}}``，
    不抛异常（网络异常在内部捕获并转为错误响应）。
    """

    def __init__(
        self,
        config: WechatConfig,
        backend: HttpBackend | None = None,
    ) -> None:
        """构造客户端。

        :param config: 微信配置（含 token / account / channel_version 等）
        :param backend: 可选注入的 HTTP backend（测试用 fake）
        """
        self.config = config
        if backend is None:
            self._backend: HttpBackend = HttpxBackend(config)
            self._owns_backend = True
        else:
            self._backend = backend
            self._owns_backend = False

    # ------------------------------------------------------------------
    # 内部构造
    # ------------------------------------------------------------------
    def _build_headers(self) -> dict[str, str]:
        """构造请求头（含随机 X-WECHAT-UIN）。"""
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": random_wechat_uin(),
            "iLink-App-Id": self.config.ilink_app_id,
            "iLink-App-ClientVersion": str(self.config.client_version_int),
        }
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        return headers

    def _base_info(self) -> dict[str, str]:
        """构造 base_info（每个请求体都必须携带）。"""
        return {
            "channel_version": self.config.channel_version,
            "bot_agent": self.config.bot_agent,
        }

    async def _post(
        self,
        endpoint: str,
        payload: dict[str, Any],
        timeout_s: float | None = None,
    ) -> tuple[int, Any]:
        """统一 POST 请求：注入 headers + base_info。"""
        body = {**payload, "base_info": self._base_info()}
        headers = self._build_headers()
        return await self._backend.request(
            "POST",
            endpoint,
            json=body,
            headers=headers,
            timeout=timeout_s,
        )

    # ------------------------------------------------------------------
    # 发送消息
    # ------------------------------------------------------------------
    async def send_text(
        self,
        to: str,
        text: str,
        *,
        context_token: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """发送文本消息。

        :param to: 接收方 user_id（如 ``xxx@im.wechat``）
        :param text: 文本内容
        :param context_token: 会话上下文 token（可选；首次对话可空）
        :param run_id: 运行 ID（可选）
        :return: 成功 ``{"ok": True, "message_id": "...", "to": "..."}``；失败错误响应
        """
        if not to or not str(to).strip():
            return error_response("E_INVALID_PARAMS", "to 不能为空")
        if not text or not str(text).strip():
            return error_response("E_INVALID_PARAMS", "text 不能为空")
        if not self.config.token:
            return error_response(
                "E_NO_TOKEN",
                "未配置 iLink token，请先通过 wechat_status 或 accounts 注入凭据",
            )

        client_id = generate_client_id()
        msg: dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": to,
            "client_id": client_id,
            "message_type": MESSAGE_TYPE_BOT,
            "message_state": MESSAGE_STATE_FINISH,
            "item_list": [
                {"type": MESSAGE_ITEM_TYPE_TEXT, "text_item": {"text": text}},
            ],
        }
        if context_token:
            msg["context_token"] = context_token
        if run_id:
            msg["run_id"] = run_id

        try:
            status, body = await self._post(
                "/ilink/bot/sendmessage",
                {"msg": msg},
                timeout_s=self.config.timeout_s,
            )
        except (TimeoutError, OSError) as exc:
            return error_response(
                "E_ILINK_UNAVAILABLE",
                f"无法连接到 iLink {self.config.base_url}: {exc}",
            )
        except Exception as exc:
            return error_response(
                "E_ILINK_ERROR",
                f"请求 iLink 时出错: {exc}",
            )

        if status == 200 and isinstance(body, dict):
            ret = body.get("ret", 0)
            if ret == 0:
                return success_response(
                    message_id=client_id,
                    to=to,
                    channel="ilink",
                )
            return error_response(
                "E_ILINK_SEND_FAILED",
                f"iLink 返回 ret={ret} errmsg={body.get('errmsg', '')}",
                ret=ret,
                errmsg=body.get("errmsg", ""),
            )
        return error_response(
            "E_ILINK_ERROR",
            f"iLink 返回 HTTP {status}",
            status_code=status,
            body=body,
        )

    # ------------------------------------------------------------------
    # 长轮询接收
    # ------------------------------------------------------------------
    async def get_updates(
        self,
        get_updates_buf: str = "",
        *,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        """长轮询拉取消息。

        :param get_updates_buf: 上次轮询返回的 buf（空字符串表示首次/重置）
        :param timeout_s: 长轮询超时；默认取 config.long_poll_timeout_s
        :return: 成功 ``{"ok": True, "msgs": [...], "get_updates_buf": "...", "longpolling_timeout_ms": ...}``
        """
        if not self.config.token:
            return error_response(
                "E_NO_TOKEN",
                "未配置 iLink token",
            )

        timeout = timeout_s if timeout_s is not None else self.config.long_poll_timeout_s
        try:
            status, body = await self._post(
                "/ilink/bot/getupdates",
                {"get_updates_buf": get_updates_buf},
                timeout_s=timeout,
            )
        except (asyncio.TimeoutError, TimeoutError):
            # 长轮询客户端超时是正常控制流：返回空 msgs，调用方重试
            return success_response(
                msgs=[],
                get_updates_buf=get_updates_buf,
                timed_out=True,
            )
        except OSError as exc:
            return error_response(
                "E_ILINK_UNAVAILABLE",
                f"无法连接到 iLink {self.config.base_url}: {exc}",
            )
        except Exception as exc:
            return error_response(
                "E_ILINK_ERROR",
                f"请求 iLink 时出错: {exc}",
            )

        if status == 200 and isinstance(body, dict):
            ret = body.get("ret", 0)
            if ret == 0:
                return success_response(
                    msgs=body.get("msgs", []) or [],
                    get_updates_buf=body.get("get_updates_buf", get_updates_buf),
                    longpolling_timeout_ms=body.get("longpolling_timeout_ms"),
                )
            return error_response(
                "E_ILINK_GET_UPDATES_FAILED",
                f"iLink getupdates 返回 ret={ret} errcode={body.get('errcode')} errmsg={body.get('errmsg', '')}",
                ret=ret,
                errcode=body.get("errcode"),
                errmsg=body.get("errmsg", ""),
            )
        return error_response(
            "E_ILINK_ERROR",
            f"iLink 返回 HTTP {status}",
            status_code=status,
            body=body,
        )

    # ------------------------------------------------------------------
    # 生命周期通知
    # ------------------------------------------------------------------
    async def notify_start(self) -> dict[str, Any]:
        """通知服务端客户端上线（开始监听）。"""
        if not self.config.token:
            return error_response("E_NO_TOKEN", "未配置 iLink token")
        try:
            status, body = await self._post(
                "/ilink/bot/msg/notifystart",
                {},
                timeout_s=self.config.timeout_s,
            )
        except Exception as exc:
            return error_response("E_ILINK_ERROR", f"notifystart 失败: {exc}")
        if status == 200 and isinstance(body, dict) and body.get("ret", 0) == 0:
            return success_response()
        return error_response(
            "E_ILINK_ERROR",
            f"notifystart 返回异常 (HTTP {status})",
            status_code=status,
            body=body,
        )

    async def notify_stop(self) -> dict[str, Any]:
        """通知服务端客户端下线（停止监听）。"""
        if not self.config.token:
            return error_response("E_NO_TOKEN", "未配置 iLink token")
        try:
            status, body = await self._post(
                "/ilink/bot/msg/notifystop",
                {},
                timeout_s=self.config.timeout_s,
            )
        except Exception as exc:
            return error_response("E_ILINK_ERROR", f"notifystop 失败: {exc}")
        if status == 200 and isinstance(body, dict) and body.get("ret", 0) == 0:
            return success_response()
        return error_response(
            "E_ILINK_ERROR",
            f"notifystop 返回异常 (HTTP {status})",
            status_code=status,
            body=body,
        )

    # ------------------------------------------------------------------
    # 资源管理
    # ------------------------------------------------------------------
    async def close(self) -> None:
        """释放 backend 资源。"""
        if self._owns_backend and hasattr(self._backend, "close"):
            await self._backend.close()

    async def __aenter__(self) -> "ILinkClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()
