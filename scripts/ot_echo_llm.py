#!/usr/bin/env python3
"""OpenTalking speakText 直读 shim（M6.3 真机联调工具）。

OpenTalking ``POST /sessions/{id}/speak`` 恒走 ``text → LLM → TTS`` 管道，
无直读（verbatim）模式；而 HUD speakText(reply) 语义要求数字人**逐字朗读**
omni_voice 的回复文本。本 shim 是一个极简 OpenAI 兼容 chat/completions
端点：把最后一条 user 消息原样作为 assistant delta 流式返回，使 OpenTalking
管道"复读"输入文本而非应答。

用法::

    python3 scripts/ot_echo_llm.py [--port 8211]

然后把 OpenTalking 的 LLM 指向本服务（免重启，经官方 runtime-config API）::

    curl -X POST http://127.0.0.1:8210/runtime-config/apply \\
        -H 'Content-Type: application/json' \\
        -d '{"llm_base_url": "http://127.0.0.1:8211/v1"}'

仅用于本机 mock 渲染档联调；GPU 节点正式部署后应改回真实 LLM 或评估
OpenTalking 上游的直读接口。
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _extract_last_user_text(body: bytes) -> str:
    """取 messages 中最后一条 user 消息的文本内容；缺失返回空串。"""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return ""
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str):
                return content
            # OpenAI 多段内容（list[part]）场景拼文本段。
            if isinstance(content, list):
                return "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
    return ""


def _chunk(model: str, content: str | None, finish: str | None) -> str:
    delta: dict[str, str] = {}
    if content is not None:
        delta["content"] = content
    return "data: " + json.dumps(
        {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        },
        ensure_ascii=False,
    ) + "\n\n"


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib 命名契约
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        text = _extract_last_user_text(self.rfile.read(length))
        body = (
            _chunk("echo", text, None)
            + _chunk("echo", None, "stop")
            + "data: [DONE]\n\n"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # 静默：联调工具不刷日志


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenTalking speakText 直读 echo LLM shim")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8211)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    print(f"[echo-llm] listening on http://{args.host}:{args.port}/v1")
    server.serve_forever()


if __name__ == "__main__":
    main()
