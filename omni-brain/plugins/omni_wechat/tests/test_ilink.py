"""omni_wechat ILinkClient 测试。

全部使用 fake HTTP backend 注入，不访问真实网络。
验证：幽灵字段（message_type=2, message_state=2, base_info, client_id）、
请求头（Authorization, X-WECHAT-UIN, iLink-App-*）、
send_text / get_updates / notify_start / notify_stop 的完整响应处理。
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any
from unittest.mock import AsyncMock

import pytest

from omni_wechat.config import WechatConfig
from omni_wechat.ilink import (
    ILinkClient,
    MESSAGE_ITEM_TYPE_TEXT,
    MESSAGE_STATE_FINISH,
    MESSAGE_TYPE_BOT,
    generate_client_id,
    random_wechat_uin,
)


# ---------------------------------------------------------------------------
# Fake HTTP Backend
# ---------------------------------------------------------------------------
class FakeBackend:
    """预置响应的 fake HTTP backend。"""

    def __init__(self, responses: list[tuple[int, Any]] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[dict[str, Any]] = []
        self._call_count = 0

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> tuple[int, Any]:
        self.requests.append({"method": method, "path": path, **kwargs})
        if self._call_count < len(self.responses):
            resp = self.responses[self._call_count]
            self._call_count += 1
            return resp
        return (500, {"error": "no more responses"})

    async def close(self) -> None:
        pass


def _make_config(**overrides: Any) -> WechatConfig:
    defaults = {
        "account": "test-account",
        "token": "test-token-123",
        "default_target": "user@im.wechat",
    }
    defaults.update(overrides)
    return WechatConfig(**defaults)


def _make_client(
    responses: list[tuple[int, Any]] | None = None,
    config: WechatConfig | None = None,
) -> tuple[ILinkClient, FakeBackend]:
    backend = FakeBackend(responses)
    cfg = config or _make_config()
    client = ILinkClient(cfg, backend=backend)
    return client, backend


# ---------------------------------------------------------------------------
# 辅助函数测试
# ---------------------------------------------------------------------------
class TestHelpers:
    def test_random_wechat_uin_is_base64(self) -> None:
        uin = random_wechat_uin()
        # 应能 base64 解码
        decoded = base64.b64decode(uin)
        # 解码后是十进制数字字符串
        assert decoded.decode("utf-8").isdigit()

    def test_random_wechat_uin_unique(self) -> None:
        uins = {random_wechat_uin() for _ in range(100)}
        assert len(uins) == 100

    def test_generate_client_id_prefix(self) -> None:
        cid = generate_client_id("test-prefix")
        # 对齐 openclaw-weixin generateId：{prefix}:{timestamp_ms}-{8hex}
        assert cid.startswith("test-prefix:")
        assert len(cid) > len("test-prefix:")

    def test_generate_client_id_unique(self) -> None:
        ids = {generate_client_id() for _ in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# 请求头与 base_info
# ---------------------------------------------------------------------------
class TestHeaders:
    @pytest.mark.asyncio()
    async def test_headers_contain_required_fields(self) -> None:
        client, backend = _make_client([(200, {"ret": 0})])
        await client.send_text("user@im.wechat", "hello")

        headers = backend.requests[0]["headers"]
        assert headers["Content-Type"] == "application/json"
        assert headers["AuthorizationType"] == "ilink_bot_token"
        assert headers["Authorization"] == "Bearer test-token-123"
        assert headers["iLink-App-Id"] == "bot"
        assert headers["iLink-App-ClientVersion"] == str(WechatConfig().client_version_int)
        # X-WECHAT-UIN 是 base64
        assert base64.b64decode(headers["X-WECHAT-UIN"])

    @pytest.mark.asyncio()
    async def test_headers_no_auth_when_token_empty(self) -> None:
        cfg = _make_config(token="")
        client, backend = _make_client([(200, {"ret": 0})], config=cfg)
        # send_text 无 token 直接返回错误，不发请求
        result = await client.send_text("user@im.wechat", "hello")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_NO_TOKEN"
        assert len(backend.requests) == 0

    @pytest.mark.asyncio()
    async def test_base_info_in_payload(self) -> None:
        client, backend = _make_client([(200, {"ret": 0})])
        await client.send_text("user@im.wechat", "hello")

        body = backend.requests[0]["json"]
        assert "base_info" in body
        assert body["base_info"]["channel_version"] == "2.4.6"
        assert body["base_info"]["bot_agent"] == "OpenClaw/omni_wechat"


# ---------------------------------------------------------------------------
# send_text
# ---------------------------------------------------------------------------
class TestSendText:
    @pytest.mark.asyncio()
    async def test_send_success(self) -> None:
        client, backend = _make_client([(200, {"ret": 0})])
        result = await client.send_text("user@im.wechat", "hello world")
        assert result["ok"] is True
        assert result["message_id"]  # client_id
        assert result["to"] == "user@im.wechat"
        assert result["channel"] == "ilink"

    @pytest.mark.asyncio()
    async def test_send_ghost_fields(self) -> None:
        """验证幽灵字段：message_type=2, message_state=2。"""
        client, backend = _make_client([(200, {"ret": 0})])
        await client.send_text("user@im.wechat", "test")

        msg = backend.requests[0]["json"]["msg"]
        assert msg["message_type"] == MESSAGE_TYPE_BOT  # 2
        assert msg["message_state"] == MESSAGE_STATE_FINISH  # 2
        assert msg["from_user_id"] == ""
        assert msg["to_user_id"] == "user@im.wechat"
        assert msg["client_id"]  # 非空
        assert len(msg["item_list"]) == 1
        assert msg["item_list"][0]["type"] == MESSAGE_ITEM_TYPE_TEXT
        assert msg["item_list"][0]["text_item"]["text"] == "test"

    @pytest.mark.asyncio()
    async def test_send_with_context_token(self) -> None:
        client, backend = _make_client([(200, {"ret": 0})])
        await client.send_text("user@im.wechat", "reply", context_token="ctx-abc")
        msg = backend.requests[0]["json"]["msg"]
        assert msg["context_token"] == "ctx-abc"

    @pytest.mark.asyncio()
    async def test_send_without_context_token(self) -> None:
        client, backend = _make_client([(200, {"ret": 0})])
        await client.send_text("user@im.wechat", "hello")
        msg = backend.requests[0]["json"]["msg"]
        assert "context_token" not in msg

    @pytest.mark.asyncio()
    async def test_send_with_run_id(self) -> None:
        client, backend = _make_client([(200, {"ret": 0})])
        await client.send_text("user@im.wechat", "hello", run_id="run-123")
        msg = backend.requests[0]["json"]["msg"]
        assert msg["run_id"] == "run-123"

    @pytest.mark.asyncio()
    async def test_send_empty_to(self) -> None:
        client, _ = _make_client()
        result = await client.send_text("", "hello")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    @pytest.mark.asyncio()
    async def test_send_whitespace_to(self) -> None:
        client, _ = _make_client()
        result = await client.send_text("  ", "hello")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    @pytest.mark.asyncio()
    async def test_send_empty_text(self) -> None:
        client, _ = _make_client()
        result = await client.send_text("user@im.wechat", "")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    @pytest.mark.asyncio()
    async def test_send_whitespace_text(self) -> None:
        client, _ = _make_client()
        result = await client.send_text("user@im.wechat", "   ")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    @pytest.mark.asyncio()
    async def test_send_ret_nonzero(self) -> None:
        client, _ = _make_client([(200, {"ret": -2, "errmsg": "prepare failed"})])
        result = await client.send_text("user@im.wechat", "hello")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_ILINK_SEND_FAILED"
        assert result["error"]["ret"] == -2
        assert "prepare failed" in result["error"]["message"]

    @pytest.mark.asyncio()
    async def test_send_http_error(self) -> None:
        client, _ = _make_client([(500, "Internal Server Error")])
        result = await client.send_text("user@im.wechat", "hello")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_ILINK_ERROR"
        assert result["error"]["status_code"] == 500

    @pytest.mark.asyncio()
    async def test_send_network_error(self) -> None:
        class FailingBackend:
            async def request(self, *a: Any, **kw: Any) -> tuple[int, Any]:
                raise OSError("Connection refused")

        cfg = _make_config()
        client = ILinkClient(cfg, backend=FailingBackend())
        result = await client.send_text("user@im.wechat", "hello")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_ILINK_UNAVAILABLE"

    @pytest.mark.asyncio()
    async def test_send_timeout_error(self) -> None:
        class TimeoutBackend:
            async def request(self, *a: Any, **kw: Any) -> tuple[int, Any]:
                raise TimeoutError("Request timeout")

        cfg = _make_config()
        client = ILinkClient(cfg, backend=TimeoutBackend())
        result = await client.send_text("user@im.wechat", "hello")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_ILINK_UNAVAILABLE"

    @pytest.mark.asyncio()
    async def test_send_unexpected_error(self) -> None:
        class CrashBackend:
            async def request(self, *a: Any, **kw: Any) -> tuple[int, Any]:
                raise RuntimeError("unexpected")

        cfg = _make_config()
        client = ILinkClient(cfg, backend=CrashBackend())
        result = await client.send_text("user@im.wechat", "hello")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_ILINK_ERROR"

    @pytest.mark.asyncio()
    async def test_send_endpoint_path(self) -> None:
        client, backend = _make_client([(200, {"ret": 0})])
        await client.send_text("user@im.wechat", "hello")
        assert backend.requests[0]["path"] == "/ilink/bot/sendmessage"
        assert backend.requests[0]["method"] == "POST"


# ---------------------------------------------------------------------------
# get_updates
# ---------------------------------------------------------------------------
class TestGetUpdates:
    @pytest.mark.asyncio()
    async def test_get_updates_success_with_msgs(self) -> None:
        msgs = [
            {"from_user_id": "user1", "item_list": [{"type": 1, "text_item": {"text": "hi"}}]},
        ]
        client, _ = _make_client([(200, {"ret": 0, "msgs": msgs, "get_updates_buf": "buf-001"})])
        result = await client.get_updates("")
        assert result["ok"] is True
        assert len(result["msgs"]) == 1
        assert result["get_updates_buf"] == "buf-001"

    @pytest.mark.asyncio()
    async def test_get_updates_empty_msgs(self) -> None:
        client, _ = _make_client([(200, {"ret": 0, "msgs": [], "get_updates_buf": "buf-002"})])
        result = await client.get_updates("buf-001")
        assert result["ok"] is True
        assert result["msgs"] == []
        assert result["get_updates_buf"] == "buf-002"

    @pytest.mark.asyncio()
    async def test_get_updates_preserves_buf_on_empty_response(self) -> None:
        client, _ = _make_client([(200, {"ret": 0})])
        result = await client.get_updates("buf-old")
        assert result["get_updates_buf"] == "buf-old"

    @pytest.mark.asyncio()
    async def test_get_updates_longpolling_timeout(self) -> None:
        client, _ = _make_client([
            (200, {"ret": 0, "msgs": [], "get_updates_buf": "b", "longpolling_timeout_ms": 40000})
        ])
        result = await client.get_updates("")
        assert result["longpolling_timeout_ms"] == 40000

    @pytest.mark.asyncio()
    async def test_get_updates_no_token(self) -> None:
        cfg = _make_config(token="")
        client, _ = _make_client(config=cfg)
        result = await client.get_updates("")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_NO_TOKEN"

    @pytest.mark.asyncio()
    async def test_get_updates_sends_buf(self) -> None:
        client, backend = _make_client([(200, {"ret": 0, "msgs": [], "get_updates_buf": "new"})])
        await client.get_updates("my-buf-123")
        body = backend.requests[0]["json"]
        assert body["get_updates_buf"] == "my-buf-123"

    @pytest.mark.asyncio()
    async def test_get_updates_endpoint_path(self) -> None:
        client, backend = _make_client([(200, {"ret": 0, "msgs": [], "get_updates_buf": ""})])
        await client.get_updates("")
        assert backend.requests[0]["path"] == "/ilink/bot/getupdates"

    @pytest.mark.asyncio()
    async def test_get_updates_timeout_returns_empty(self) -> None:
        class TimeoutBackend:
            async def request(self, *a: Any, **kw: Any) -> tuple[int, Any]:
                raise asyncio.TimeoutError()

        cfg = _make_config()
        client = ILinkClient(cfg, backend=TimeoutBackend())
        result = await client.get_updates("buf-1")
        assert result["ok"] is True
        assert result["msgs"] == []
        assert result["timed_out"] is True
        assert result["get_updates_buf"] == "buf-1"

    @pytest.mark.asyncio()
    async def test_get_updates_ret_nonzero(self) -> None:
        client, _ = _make_client([(200, {"ret": -1, "errcode": 10001, "errmsg": "token expired"})])
        result = await client.get_updates("")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_ILINK_GET_UPDATES_FAILED"
        assert result["error"]["ret"] == -1
        assert result["error"]["errcode"] == 10001

    @pytest.mark.asyncio()
    async def test_get_updates_network_error(self) -> None:
        class FailBackend:
            async def request(self, *a: Any, **kw: Any) -> tuple[int, Any]:
                raise OSError("Network unreachable")

        cfg = _make_config()
        client = ILinkClient(cfg, backend=FailBackend())
        result = await client.get_updates("")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_ILINK_UNAVAILABLE"

    @pytest.mark.asyncio()
    async def test_get_updates_http_error(self) -> None:
        client, _ = _make_client([(502, "Bad Gateway")])
        result = await client.get_updates("")
        assert result["ok"] is False
        assert result["error"]["status_code"] == 502


# ---------------------------------------------------------------------------
# notify_start / notify_stop
# ---------------------------------------------------------------------------
class TestNotifyLifecycle:
    @pytest.mark.asyncio()
    async def test_notify_start_success(self) -> None:
        client, backend = _make_client([(200, {"ret": 0})])
        result = await client.notify_start()
        assert result["ok"] is True
        assert backend.requests[0]["path"] == "/ilink/bot/msg/notifystart"

    @pytest.mark.asyncio()
    async def test_notify_start_no_token(self) -> None:
        cfg = _make_config(token="")
        client, _ = _make_client(config=cfg)
        result = await client.notify_start()
        assert result["ok"] is False
        assert result["error"]["code"] == "E_NO_TOKEN"

    @pytest.mark.asyncio()
    async def test_notify_start_ret_nonzero(self) -> None:
        client, _ = _make_client([(200, {"ret": -1})])
        result = await client.notify_start()
        assert result["ok"] is False

    @pytest.mark.asyncio()
    async def test_notify_start_network_error(self) -> None:
        class FailBackend:
            async def request(self, *a: Any, **kw: Any) -> tuple[int, Any]:
                raise OSError("fail")

        cfg = _make_config()
        client = ILinkClient(cfg, backend=FailBackend())
        result = await client.notify_start()
        assert result["ok"] is False

    @pytest.mark.asyncio()
    async def test_notify_stop_success(self) -> None:
        client, backend = _make_client([(200, {"ret": 0})])
        result = await client.notify_stop()
        assert result["ok"] is True
        assert backend.requests[0]["path"] == "/ilink/bot/msg/notifystop"

    @pytest.mark.asyncio()
    async def test_notify_stop_no_token(self) -> None:
        cfg = _make_config(token="")
        client, _ = _make_client(config=cfg)
        result = await client.notify_stop()
        assert result["ok"] is False
        assert result["error"]["code"] == "E_NO_TOKEN"

    @pytest.mark.asyncio()
    async def test_notify_stop_network_error(self) -> None:
        class FailBackend:
            async def request(self, *a: Any, **kw: Any) -> tuple[int, Any]:
                raise OSError("fail")

        cfg = _make_config()
        client = ILinkClient(cfg, backend=FailBackend())
        result = await client.notify_stop()
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# close / context manager
# ---------------------------------------------------------------------------
class TestClose:
    @pytest.mark.asyncio()
    async def test_close_owned_backend(self) -> None:
        """自有 backend 应被关闭。"""
        cfg = _make_config()
        client = ILinkClient(cfg, backend=FakeBackend())
        # 不抛异常即可
        await client.close()

    @pytest.mark.asyncio()
    async def test_close_not_owned_backend(self) -> None:
        """注入的 backend 不拥有，不调用 close。"""
        backend = FakeBackend()
        backend.close = AsyncMock()  # type: ignore[assignment]
        cfg = _make_config()
        client = ILinkClient(cfg, backend=backend)
        await client.close()
        # _owns_backend=False, 不调用 backend.close
        backend.close.assert_not_called()  # type: ignore[union-attr]

    @pytest.mark.asyncio()
    async def test_context_manager(self) -> None:
        cfg = _make_config()
        backend = FakeBackend([(200, {"ret": 0})])
        async with ILinkClient(cfg, backend=backend) as client:
            result = await client.send_text("user@im.wechat", "hi")
            assert result["ok"] is True
