"""omni_office HTTP 工具桥测试（M36）。

覆盖三层：
- ``ToolDispatcher``：纯分发逻辑（不碰 socket）；
- HTTP 层：真实回环 socket（ephemeral 端口），鉴权 / 错误映射 / 端到端回环；
- CLI：``serve`` 子命令注册与默认参数。

运行时隔离与 test_tools.py 一致：``:memory:`` 库 + FakeEmailBackend。
"""

from __future__ import annotations

import http.client
import json
import threading
from http.server import HTTPServer
from typing import Any

import pytest

from omni_office import tools
from omni_office.backends import FakeEmailBackend
from omni_office.db import OfficeDB
from omni_office.http_server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    ENV_TOKEN,
    ToolDispatcher,
    create_server,
    resolve_token,
)


@pytest.fixture()
def rt():
    """注入 :memory: 库与 fake 邮件后端的隔离运行时。"""
    runtime = tools._reset_runtime()
    runtime.db = OfficeDB(":memory:")
    runtime.db.init_schema()
    runtime.email_backend = FakeEmailBackend()
    yield runtime
    runtime.db.close()
    tools._reset_runtime()


@pytest.fixture()
def dispatcher(rt) -> ToolDispatcher:
    return ToolDispatcher()


def _post(
    conn: http.client.HTTPConnection,
    path: str,
    body: Any,
    token: str | None = None,
    raw_body: bytes | None = None,
) -> tuple[int, dict[str, Any]]:
    """POST 助手：返回 (status, parsed_json)。"""
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    payload = raw_body if raw_body is not None else json.dumps(body).encode("utf-8")
    conn.request("POST", path, body=payload, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    return resp.status, json.loads(data.decode("utf-8"))


class _RunningServer:
    def __init__(self, server: HTTPServer, thread: threading.Thread) -> None:
        self.server = server
        self.thread = thread
        host, port = server.server_address[:2]
        self.base = f"{host}:{port}"

    def conn(self) -> http.client.HTTPConnection:
        host, port = self.server.server_address[:2]
        return http.client.HTTPConnection(host, port, timeout=5)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture()
def running_server():
    """启动测试服务器（ephemeral 端口）。

    注意：sqlite3 连接默认 ``check_same_thread=True``，``:memory:`` 库的
    建连与建表必须在服务线程内完成（生产路径 ``serve()`` 主线程内惰性建连，
    天然满足）。本固件把 db 初始化挪进 serving 线程，并用 Event 同步就绪。
    """
    holder: list[_RunningServer] = []

    def factory(token: str | None = "secret") -> _RunningServer:
        runtime = tools._reset_runtime()
        runtime.email_backend = FakeEmailBackend()
        server = create_server("127.0.0.1", 0, token=token)
        ready = threading.Event()

        def _run() -> None:
            runtime.db = OfficeDB(":memory:")
            runtime.db.init_schema()
            ready.set()
            server.serve_forever()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        assert ready.wait(timeout=5)
        rs = _RunningServer(server, thread)
        holder.append(rs)
        return rs

    yield factory
    for rs in holder:
        rs.close()
    # 不在主线程 close db（跨线程会触发 sqlite3.ProgrammingError），:memory: 随连接回收
    tools._reset_runtime()


# ---------------------------------------------------------------------------
# ToolDispatcher
# ---------------------------------------------------------------------------
class TestToolDispatcher:
    def test_tool_names_cover_office_and_schedule(self, dispatcher: ToolDispatcher) -> None:
        names = dispatcher.tool_names
        assert "office_doc_list" in names
        assert "office_email_inbox" in names
        assert "schedule_list_events" in names
        assert "schedule_create_event" in names

    def test_dispatch_ok_unwraps_data(self, dispatcher: ToolDispatcher) -> None:
        status, body = dispatcher.dispatch(
            "office_doc_create", {"title": "周报", "content": "本周进展"}
        )
        assert status == 200
        assert body["ok"] is True
        assert "data" not in body  # data 已解包为 result
        assert body["result"]["doc"]["title"] == "周报"

    def test_dispatch_unknown_tool_404(self, dispatcher: ToolDispatcher) -> None:
        status, body = dispatcher.dispatch("no_such_tool", {})
        assert status == 404
        assert body["ok"] is False
        assert body["error"]["code"] == "E_TOOL_NOT_FOUND"

    def test_dispatch_non_dict_arguments_400(self, dispatcher: ToolDispatcher) -> None:
        status, body = dispatcher.dispatch("office_doc_list", ["not", "a", "dict"])
        assert status == 400
        assert body["error"]["code"] == "E_INVALID_ARGS"

    def test_dispatch_blank_name_400(self, dispatcher: ToolDispatcher) -> None:
        status, body = dispatcher.dispatch("  ", {})
        assert status == 400
        assert body["error"]["code"] == "E_INVALID_ARGS"

    def test_dispatch_none_arguments_defaults_empty(self, dispatcher: ToolDispatcher) -> None:
        status, body = dispatcher.dispatch("office_doc_list", None)
        assert status == 200
        assert body["ok"] is True

    def test_dispatch_domain_error_passthrough(self, dispatcher: ToolDispatcher) -> None:
        status, body = dispatcher.dispatch("office_doc_get", {"doc_id": "missing"})
        assert status == 200  # 领域错误走 200 + 错误信封（UniHub 按 data.error 判定）
        assert body["ok"] is False
        assert body["error"]["code"] == "E_NOT_FOUND"

    def test_dispatch_invalid_params_error_envelope(self, dispatcher: ToolDispatcher) -> None:
        # 缺必填 title → @_guard 映射 E_INVALID_PARAMS
        status, body = dispatcher.dispatch("office_doc_create", {})
        assert status == 200
        assert body["ok"] is False
        assert body["error"]["code"] in ("E_INVALID_PARAMS", "E_INTERNAL")


# ---------------------------------------------------------------------------
# HTTP 层
# ---------------------------------------------------------------------------
class TestHttpLayer:
    def test_health_public(self, running_server) -> None:
        rs = running_server()
        conn = rs.conn()
        conn.request("GET", "/v1/health")
        resp = conn.getresponse()
        body = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200
        assert body["ok"] is True
        assert body["result"]["service"] == "omni_office"
        assert body["result"]["tools"] > 0
        conn.close()

    def test_tools_call_requires_auth(self, running_server) -> None:
        rs = running_server(token="secret")
        status, body = _post(rs.conn(), "/v1/tools/call", {"name": "office_doc_list"})
        assert status == 401
        assert body["error"]["code"] == "E_UNAUTHORIZED"

    def test_tools_call_wrong_token(self, running_server) -> None:
        rs = running_server(token="secret")
        status, _ = _post(
            rs.conn(), "/v1/tools/call", {"name": "office_doc_list"}, token="wrong"
        )
        assert status == 401

    def test_tools_call_ok_with_token(self, running_server) -> None:
        rs = running_server(token="secret")
        status, body = _post(
            rs.conn(), "/v1/tools/call", {"name": "office_doc_list"}, token="secret"
        )
        assert status == 200
        assert body["ok"] is True
        assert body["result"]["documents"] == []

    def test_no_token_configured_allows_open_access(self, running_server) -> None:
        rs = running_server(token=None)
        status, body = _post(rs.conn(), "/v1/tools/call", {"name": "office_doc_list"})
        assert status == 200
        assert body["ok"] is True

    def test_malformed_json_400(self, running_server) -> None:
        rs = running_server(token=None)
        status, body = _post(
            rs.conn(), "/v1/tools/call", None, raw_body=b"{not-json"
        )
        assert status == 400
        assert body["error"]["code"] == "E_INVALID_JSON"

    def test_non_object_body_400(self, running_server) -> None:
        rs = running_server(token=None)
        status, body = _post(rs.conn(), "/v1/tools/call", [1, 2, 3])
        assert status == 400
        assert body["error"]["code"] == "E_INVALID_ARGS"

    def test_unknown_path_404(self, running_server) -> None:
        rs = running_server(token=None)
        status, body = _post(rs.conn(), "/v1/nope", {"name": "office_doc_list"})
        assert status == 404
        assert body["error"]["code"] == "E_NOT_FOUND"

    def test_get_on_tools_call_405(self, running_server) -> None:
        rs = running_server(token=None)
        conn = rs.conn()
        conn.request("GET", "/v1/tools/call")
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 405
        conn.close()

    def test_schedule_round_trip(self, running_server) -> None:
        """UniHub 日程远程同步核心链路：create → list 回读。"""
        rs = running_server(token="secret")
        status, body = _post(
            rs.conn(),
            "/v1/tools/call",
            {
                "name": "schedule_create_event",
                "arguments": {"title": "方案评审", "date": "2026-08-07", "time": "14:00"},
            },
            token="secret",
        )
        assert status == 200
        assert body["ok"] is True
        event_id = body["result"]["event"]["id"]

        status, body = _post(
            rs.conn(), "/v1/tools/call", {"name": "schedule_list_events"}, token="secret"
        )
        assert status == 200
        titles = [e["title"] for e in body["result"]["events"]]
        assert "方案评审" in titles
        ids = [e["id"] for e in body["result"]["events"]]
        assert event_id in ids


# ---------------------------------------------------------------------------
# CLI / 配置
# ---------------------------------------------------------------------------
class TestCliAndConfig:
    def test_serve_subcommand_defaults(self) -> None:
        from omni_office.cli import build_parser

        args = build_parser().parse_args(["serve"])
        assert args.command == "serve"
        assert args.host == DEFAULT_HOST
        assert args.port == DEFAULT_PORT
        assert args.token is None

    def test_serve_subcommand_custom(self) -> None:
        from omni_office.cli import build_parser

        args = build_parser().parse_args(
            ["serve", "--host", "127.0.0.1", "--port", "9999", "--token", "abc"]
        )
        assert args.host == "127.0.0.1"
        assert args.port == 9999
        assert args.token == "abc"

    def test_resolve_token_prefers_cli(self, monkeypatch) -> None:
        monkeypatch.setenv(ENV_TOKEN, "env-token")
        assert resolve_token("cli-token") == "cli-token"

    def test_resolve_token_env_fallback(self, monkeypatch) -> None:
        monkeypatch.setenv(ENV_TOKEN, "env-token")
        assert resolve_token(None) == "env-token"

    def test_resolve_token_none(self, monkeypatch) -> None:
        monkeypatch.delenv(ENV_TOKEN, raising=False)
        assert resolve_token(None) is None
