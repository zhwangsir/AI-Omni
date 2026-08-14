"""omni_wechat 5 个 wechat_* 工具测试。

全部 fake backend 驱动，不访问真实网络。
每个测试用 ``_reset_runtime()`` 隔离进程内单例，用 tmp_path 隔离状态目录。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from omni_wechat import tools
from omni_wechat.config import WechatConfig


# ---------------------------------------------------------------------------
# Fake HTTP Backend（与 test_ilink.py 相同模式）
# ---------------------------------------------------------------------------
class FakeBackend:
    def __init__(self, responses: list[tuple[int, Any]] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[dict[str, Any]] = []
        self._call_count = 0

    async def request(self, method: str, path: str, **kwargs: Any) -> tuple[int, Any]:
        self.requests.append({"method": method, "path": path, **kwargs})
        if self._call_count < len(self.responses):
            resp = self.responses[self._call_count]
            self._call_count += 1
            return resp
        return (500, {"error": "no more responses"})

    async def close(self) -> None:
        pass


def _parse(result: str) -> dict[str, Any]:
    """工具返回 JSON 字符串 → dict。"""
    assert isinstance(result, str)
    return json.loads(result)


@pytest.fixture(autouse=True)
def fresh_runtime(tmp_path: Path):
    """每个测试重置运行时单例 + 隔离状态目录。"""
    rt = tools._reset_runtime()
    # 注入测试配置
    rt.config = WechatConfig(
        account="test-acc",
        token="test-token",
        default_target="target@im.wechat",
        state_dir=str(tmp_path),
    )
    rt.backend = FakeBackend([(200, {"ret": 0})])
    yield rt
    # 回收后台事件循环线程，避免跨测试泄漏
    tools.shutdown_runtime()
    tools._reset_runtime()


# ---------------------------------------------------------------------------
# wechat_send
# ---------------------------------------------------------------------------
class TestWechatSend:
    def test_send_success(self, fresh_runtime: tools.Runtime) -> None:
        rt = fresh_runtime
        rt.backend = FakeBackend([(200, {"ret": 0})])
        result = _parse(tools.wechat_send("hello"))
        assert result["ok"] is True
        assert result["data"]["target"] == "target@im.wechat"
        assert result["data"]["channel"] == "ilink"
        assert result["data"]["message_id"]

    def test_send_with_explicit_target(self, fresh_runtime: tools.Runtime) -> None:
        rt = fresh_runtime
        rt.backend = FakeBackend([(200, {"ret": 0})])
        result = _parse(tools.wechat_send("hi", target="other@im.wechat"))
        assert result["ok"] is True
        assert result["data"]["target"] == "other@im.wechat"

    def test_send_no_target(self) -> None:
        rt = tools._reset_runtime()
        rt.config = WechatConfig(account="acc", token="tok", state_dir="/tmp/test")
        rt.backend = FakeBackend()
        result = _parse(tools.wechat_send("hello"))
        assert result["ok"] is False
        assert result["error"]["code"] == "E_NO_TARGET"

    def test_send_ilink_error(self, fresh_runtime: tools.Runtime) -> None:
        rt = fresh_runtime
        rt.backend = FakeBackend([(200, {"ret": -2, "errmsg": "prepare failed"})])
        result = _parse(tools.wechat_send("hello"))
        assert result["ok"] is False
        assert "prepare failed" in result["error"]["message"]

    def test_send_publishes_event(self, fresh_runtime: tools.Runtime) -> None:
        rt = fresh_runtime
        rt.backend = FakeBackend([(200, {"ret": 0})])
        events: list[tuple[str, dict]] = []

        class FakeBus:
            def publish(self, event_type: str, payload: dict) -> None:
                events.append((event_type, payload))

        rt.event_publisher = FakeBus()
        tools.wechat_send("test message")
        assert len(events) == 1
        assert events[0][0] == "wechat.message_sent"
        assert events[0][1]["target"] == "target@im.wechat"


# ---------------------------------------------------------------------------
# wechat_status
# ---------------------------------------------------------------------------
class TestWechatStatus:
    def test_status_basic(self, fresh_runtime: tools.Runtime) -> None:
        result = _parse(tools.wechat_status())
        assert result["ok"] is True
        data = result["data"]
        assert data["account"] == "test-acc"
        assert data["has_token"] is True
        assert data["base_url"] == "https://ilinkai.weixin.qq.com"
        assert data["channel_version"] == "2.4.6"
        assert isinstance(data["client_version_int"], int)
        assert data["listening"] is False
        assert data["sync_buf_len"] == 0
        assert isinstance(data["registered_accounts"], list)

    def test_status_no_account(self) -> None:
        rt = tools._reset_runtime()
        rt.config = WechatConfig(state_dir="/tmp/test")
        rt.backend = FakeBackend()
        result = _parse(tools.wechat_status())
        assert result["ok"] is True
        assert result["data"]["account"] is None
        assert result["data"]["has_token"] is False


# ---------------------------------------------------------------------------
# wechat_set_target
# ---------------------------------------------------------------------------
class TestWechatSetTarget:
    def test_set_target_success(self, fresh_runtime: tools.Runtime) -> None:
        rt = fresh_runtime
        # 先保存 token 使持久化生效
        store = tools._get_store(rt)
        store.save_token("test-acc", token="tok", base_url="https://api.com", user_id="old@im.wechat")

        result = _parse(tools.wechat_set_target("new@im.wechat"))
        assert result["ok"] is True
        assert result["data"]["default_target"] == "new@im.wechat"
        assert rt.config.default_target == "new@im.wechat"

        # 持久化验证
        token_data = store.load_token("test-acc")
        assert token_data["userId"] == "new@im.wechat"

    def test_set_target_empty(self, fresh_runtime: tools.Runtime) -> None:
        result = _parse(tools.wechat_set_target(""))
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    def test_set_target_whitespace(self, fresh_runtime: tools.Runtime) -> None:
        result = _parse(tools.wechat_set_target("   "))
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAMS"

    def test_set_target_no_account(self) -> None:
        rt = tools._reset_runtime()
        rt.config = WechatConfig(token="tok", state_dir="/tmp/test")
        rt.backend = FakeBackend()
        result = _parse(tools.wechat_set_target("user@im.wechat"))
        assert result["ok"] is False
        assert result["error"]["code"] == "E_NO_ACCOUNT"


# ---------------------------------------------------------------------------
# wechat_start_listen / wechat_stop_listen
# ---------------------------------------------------------------------------
class TestListenLifecycle:
    def test_start_listen_success(self, fresh_runtime: tools.Runtime) -> None:
        rt = fresh_runtime
        rt.backend = FakeBackend([(200, {"ret": 0})] * 10)
        result = _parse(tools.wechat_start_listen())
        assert result["ok"] is True
        assert result["data"]["listening"] is True
        # 清理
        tools.wechat_stop_listen()

    def test_start_listen_no_token(self) -> None:
        rt = tools._reset_runtime()
        rt.config = WechatConfig(account="acc", state_dir="/tmp/test")
        rt.backend = FakeBackend()
        result = _parse(tools.wechat_start_listen())
        assert result["ok"] is False
        assert result["error"]["code"] == "E_NO_TOKEN"

    def test_start_listen_no_account(self) -> None:
        rt = tools._reset_runtime()
        rt.config = WechatConfig(token="tok", state_dir="/tmp/test")
        rt.backend = FakeBackend()
        result = _parse(tools.wechat_start_listen())
        assert result["ok"] is False
        assert result["error"]["code"] == "E_NO_ACCOUNT"

    def test_start_listen_already_running(self, fresh_runtime: tools.Runtime) -> None:
        rt = fresh_runtime
        rt.backend = FakeBackend([(200, {"ret": 0})] * 10)
        tools.wechat_start_listen()
        result = _parse(tools.wechat_start_listen())
        assert result["ok"] is True
        assert "已在运行" in result["data"]["message"]
        tools.wechat_stop_listen()

    def test_stop_listen_not_started(self, fresh_runtime: tools.Runtime) -> None:
        result = _parse(tools.wechat_stop_listen())
        assert result["ok"] is True
        assert result["data"]["listening"] is False

    def test_stop_listen_after_start(self, fresh_runtime: tools.Runtime) -> None:
        rt = fresh_runtime
        rt.backend = FakeBackend([(200, {"ret": 0})] * 10)
        tools.wechat_start_listen()
        result = _parse(tools.wechat_stop_listen())
        assert result["ok"] is True
        assert result["data"]["listening"] is False

    def test_start_publishes_event(self, fresh_runtime: tools.Runtime) -> None:
        rt = fresh_runtime
        rt.backend = FakeBackend([(200, {"ret": 0})] * 10)
        events: list[str] = []

        class FakeBus:
            def publish(self, event_type: str, payload: dict) -> None:
                events.append(event_type)

        rt.event_publisher = FakeBus()
        tools.wechat_start_listen()
        assert "wechat.listen_started" in events
        tools.wechat_stop_listen()

    def test_stop_publishes_event(self, fresh_runtime: tools.Runtime) -> None:
        rt = fresh_runtime
        rt.backend = FakeBackend([(200, {"ret": 0})] * 10)
        events: list[str] = []

        class FakeBus:
            def publish(self, event_type: str, payload: dict) -> None:
                events.append(event_type)

        rt.event_publisher = FakeBus()
        tools.wechat_start_listen()
        tools.wechat_stop_listen()
        assert "wechat.listen_stopped" in events


# ---------------------------------------------------------------------------
# register(ctx)
# ---------------------------------------------------------------------------
class TestRegister:
    def test_register_five_tools(self) -> None:
        class FakeCtx:
            def __init__(self) -> None:
                self.registered: list[dict] = []
                self.event_bus = None

            def register_tool(self, **kwargs: Any) -> None:
                self.registered.append(kwargs)

        ctx = FakeCtx()
        tools.register(ctx)
        assert len(ctx.registered) == 5
        names = {t["name"] for t in ctx.registered}
        assert names == {
            "wechat_send",
            "wechat_status",
            "wechat_set_target",
            "wechat_start_listen",
            "wechat_stop_listen",
        }

    def test_register_tools_have_schema(self) -> None:
        class FakeCtx:
            def __init__(self) -> None:
                self.registered: list[dict] = []
                self.event_bus = None

            def register_tool(self, **kwargs: Any) -> None:
                self.registered.append(kwargs)

        ctx = FakeCtx()
        tools.register(ctx)
        for t in ctx.registered:
            assert t["description"]
            assert t["emoji"]
            assert t["schema"]["parameters"]["type"] == "object"
            assert callable(t["handler_func"])

    def test_register_wires_event_bus(self) -> None:
        class FakeBus:
            def publish(self, event_type: str, payload: dict) -> None:
                pass

        class FakeCtx:
            def __init__(self) -> None:
                self.registered: list[dict] = []
                self.event_bus = FakeBus()

            def register_tool(self, **kwargs: Any) -> None:
                self.registered.append(kwargs)

        ctx = FakeCtx()
        tools.register(ctx)
        assert tools._runtime.event_publisher is ctx.event_bus

    def test_handler_adapter(self) -> None:
        """_make_handler 包装后的 handler 接受 dict 参数。"""
        handler = tools._make_handler(tools.wechat_status)
        result = handler({})
        parsed = json.loads(result)
        assert "ok" in parsed

    def test_handler_adapter_with_args(self) -> None:
        rt = tools._reset_runtime()
        rt.config = WechatConfig(
            account="acc", token="tok", default_target="t@im.wechat", state_dir="/tmp/test"
        )
        rt.backend = FakeBackend([(200, {"ret": 0})])
        handler = tools._make_handler(tools.wechat_send)
        result = handler({"text": "hello"})
        parsed = json.loads(result)
        assert parsed["ok"] is True

    def test_handler_adapter_error(self) -> None:
        handler = tools._make_handler(tools.wechat_send)
        result = handler({})  # 缺 text 参数
        parsed = json.loads(result)
        assert parsed["ok"] is False


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------
class TestInternalHelpers:
    def test_ok_format(self) -> None:
        result = json.loads(tools._ok({"key": "value"}))
        assert result == {"ok": True, "data": {"key": "value"}}

    def test_err_format(self) -> None:
        result = json.loads(tools._err("fail msg", "E_CODE"))
        assert result == {"ok": False, "error": {"code": "E_CODE", "message": "fail msg"}}

    def test_reset_runtime(self) -> None:
        rt1 = tools._reset_runtime()
        assert rt1.config is None
        assert rt1.client is None
        rt2 = tools._reset_runtime()
        assert tools._runtime is rt2
        assert rt1 is not rt2
