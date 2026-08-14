"""omni_office HTTP 工具桥：把 ``office_*`` / ``schedule_*`` 工具暴露为 HTTP API。

背景：UniHub 移动端远程同步走 ``POST /v1/tools/call``（body ``{name, arguments}``），
而 OpenClaw 网关（Node 侧）只暴露自家工具，够不到 WeBrain Python 侧的
omni_office 工具。本模块在插件进程内起一个轻量 HTTP 服务，直接把
``tools.TOOLS`` 注册表（office_* 19 个 + schedule_* 4 个）按名分发，
让 UniHub 零改动打通真实远程同步。

端点：

- ``GET  /v1/health``     → ``{"ok": true, "result": {...}}``（公开，供探活）
- ``POST /v1/tools/call`` → 成功 ``200 {"ok": true, "result": ...}``；
  领域错误 ``200 {"ok": false, "error": {...}}``（UniHub 按 ``data.error`` 判定）；
  未知工具 404 / 参数错误 400 / 鉴权失败 401。

鉴权：``--token`` 或 env ``OMNI_OFFICE_HTTP_TOKEN``；配置后要求
``Authorization: Bearer <token>``，未配置则开放（建议仅监听回环）。

线程模型：刻意使用单线程 ``HTTPServer``——``OfficeDB`` 的 sqlite3 连接
默认 ``check_same_thread=True``，多线程跨用连接会抛 ``ProgrammingError``；
工具调用均为本地 SQLite 毫秒级操作，单客户端串行足够。
"""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

logger = logging.getLogger(__name__)

#: 默认监听地址（移动端经 LAN 访问，故默认 0.0.0.0）
DEFAULT_HOST = "0.0.0.0"
#: 默认端口（AI-Omni 47XX 段：4701 omni-hud / 4702 UniHub dev，4703 本桥）
DEFAULT_PORT = 4703
#: Bearer token 环境变量名
ENV_TOKEN = "OMNI_OFFICE_HTTP_TOKEN"

_MAX_BODY_BYTES = 2 * 1024 * 1024


def resolve_token(cli_token: str | None) -> str | None:
    """解析鉴权 token：CLI 参数优先，缺省回落 env ``OMNI_OFFICE_HTTP_TOKEN``。"""
    if cli_token:
        return cli_token
    env = os.environ.get(ENV_TOKEN)
    return env if env else None


def _err_envelope(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


class ToolDispatcher:
    """按名分发到 omni_office 工具注册表，并把工具的 JSON 字符串信封解包。

    工具 handler 返回 ``{"ok": true, "data": ...}`` JSON 字符串；
    本类统一转 HTTP 语义：``(status, body_dict)``，成功时 ``data`` 解包为 ``result``。
    """

    def __init__(self, tools_registry: list[dict[str, Any]] | None = None) -> None:
        if tools_registry is None:
            from .tools import TOOLS

            tools_registry = TOOLS
        self._handlers = {meta["name"]: meta["handler_func"] for meta in tools_registry}

    @property
    def tool_names(self) -> list[str]:
        return sorted(self._handlers)

    def dispatch(self, name: Any, arguments: Any) -> tuple[int, dict[str, Any]]:
        """分发一次工具调用，返回 (HTTP 状态码, 响应体)。"""
        if not isinstance(name, str) or not name.strip():
            return 400, _err_envelope("E_INVALID_ARGS", "name 必须是非空字符串")
        name = name.strip()
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return 400, _err_envelope("E_INVALID_ARGS", "arguments 必须是 JSON 对象")
        handler = self._handlers.get(name)
        if handler is None:
            return 404, _err_envelope("E_TOOL_NOT_FOUND", f"未知工具: {name}")
        # handler 由 @_guard 包裹，领域异常已映射为错误信封，不会上抛
        raw = handler(**arguments)
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            return 500, _err_envelope("E_INTERNAL", "工具返回非 JSON")
        if not isinstance(payload, dict):
            return 500, _err_envelope("E_INTERNAL", "工具返回非 JSON 对象")
        if payload.get("ok"):
            return 200, {"ok": True, "result": payload.get("data")}
        error = payload.get("error")
        if not isinstance(error, dict):
            error = {"code": "E_INTERNAL", "message": "未知错误"}
        return 200, {"ok": False, "error": error}


def make_handler_class(
    dispatcher: ToolDispatcher, token: str | None
) -> type[BaseHTTPRequestHandler]:
    """构造绑定 dispatcher/token 的请求处理类（工厂模式便于测试注入）。"""

    class ToolHttpHandler(BaseHTTPRequestHandler):
        server_version = "omni-office-http/0.1"

        # -- 工具方法 -----------------------------------------------------
        def _authorized(self) -> bool:
            if not token:
                return True
            auth = self.headers.get("Authorization", "")
            return auth == f"Bearer {token}"

        def _send(self, status: int, obj: dict[str, Any]) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:  # 降噪：转 logger
            logger.debug("http_bridge %s", fmt % args)

        # -- 路由 ---------------------------------------------------------
        def do_GET(self) -> None:
            if self.path == "/v1/health":
                self._send(
                    200,
                    {
                        "ok": True,
                        "result": {
                            "service": "omni_office",
                            "tools": len(dispatcher.tool_names),
                        },
                    },
                )
            elif self.path == "/v1/tools/call":
                self.send_error(405)  # 方法不允许
            else:
                self._send(404, _err_envelope("E_NOT_FOUND", f"未知路径: {self.path}"))

        def do_POST(self) -> None:
            if self.path != "/v1/tools/call":
                self._send(404, _err_envelope("E_NOT_FOUND", f"未知路径: {self.path}"))
                return
            if not self._authorized():
                self._send(401, _err_envelope("E_UNAUTHORIZED", "缺少或非法 Bearer token"))
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length > _MAX_BODY_BYTES:
                self._send(413, _err_envelope("E_BODY_TOO_LARGE", "请求体超过 2MB 上限"))
                return
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                self._send(400, _err_envelope("E_INVALID_JSON", "请求体不是合法 JSON"))
                return
            if not isinstance(body, dict):
                self._send(400, _err_envelope("E_INVALID_ARGS", "请求体顶层必须是 JSON 对象"))
                return
            status, obj = dispatcher.dispatch(body.get("name"), body.get("arguments"))
            self._send(status, obj)

    return ToolHttpHandler


def create_server(
    host: str,
    port: int,
    token: str | None = None,
    dispatcher: ToolDispatcher | None = None,
) -> HTTPServer:
    """创建（未启动的）HTTP 服务实例；测试传 port=0 取 ephemeral 端口。"""
    dispatcher = dispatcher or ToolDispatcher()
    handler_cls = make_handler_class(dispatcher, token)
    return HTTPServer((host, port), handler_cls)


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    token: str | None = None,
    use_fake: bool = False,
) -> int:
    """启动 HTTP 工具桥（阻塞，Ctrl-C 退出返回 0）。"""
    from . import tools

    if use_fake:
        tools._runtime.use_fake_backends = True
    dispatcher = ToolDispatcher()
    server = create_server(host, port, token=token, dispatcher=dispatcher)
    bound_host, bound_port = server.server_address[:2]
    if token is None and bound_host not in ("127.0.0.1", "::1", "localhost"):
        logger.warning(
            "omni_office HTTP 桥监听非回环地址 %s 且未配置 token，LAN 内任意主机可调用全部工具；"
            "建议经 --token 或环境变量 %s 配置 Bearer 鉴权",
            bound_host,
            ENV_TOKEN,
        )
    auth_note = "Bearer 鉴权" if token else "未配置 token（开放访问）"
    print(
        json.dumps(
            {
                "ok": True,
                "data": {
                    "listening": f"http://{bound_host}:{bound_port}",
                    "tools": len(dispatcher.tool_names),
                    "auth": auth_note,
                },
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
