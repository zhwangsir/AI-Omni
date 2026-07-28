"""真实可用性验证：探测 OpenClaw 网关、wechat-bridge、L1 LLM 端点。

此脚本仅做只读/最小副作用探测：
- OpenClaw 网关 /health
- L1 LLM /v1/models
- wechat-bridge 连通性（默认不发送真实消息；--send-wechat 时发送一条测试消息）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from omni_openclaw.client import OpenClawClient
from omni_openclaw.config import OpenClawConfig


async def _probe() -> dict[str, Any]:
    cfg = OpenClawConfig.from_env()
    client = OpenClawClient(config=cfg)
    results: dict[str, Any] = {"config": cfg.summary()}

    # 1. OpenClaw 网关健康
    results["openclaw_health"] = await client.health_check()

    # 2. L1 LLM 模型列表（直连 L1 端点）
    try:
        status, body = await client._llm_request("GET", "/models")
        results["l1_models"] = {
            "ok": status == 200,
            "status_code": status,
            "model_count": len(body.get("data", [])) if isinstance(body, dict) else 0,
            "first_model": body.get("data", [{}])[0].get("id") if isinstance(body, dict) and body.get("data") else None,
        }
    except Exception as exc:
        results["l1_models"] = {"ok": False, "error": str(exc)}

    # 3. wechat-bridge 连通性（HEAD/GET 探测，不投递消息）
    try:
        status, body = await client._wechat_backend.request("GET", "/")
        results["wechat_bridge_probe"] = {
            "ok": status < 500,
            "status_code": status,
            "body": body if isinstance(body, str) else json.dumps(body, ensure_ascii=False),
        }
    except Exception as exc:
        results["wechat_bridge_probe"] = {"ok": False, "error": str(exc)}

    return client, results


async def main() -> int:
    parser = argparse.ArgumentParser(description="OpenClaw 真实可用性验证")
    parser.add_argument("--send-wechat", action="store_true", help="向默认目标发送一条测试微信消息")
    args = parser.parse_args()

    client, results = await _probe()

    if args.send_wechat:
        results["wechat_send"] = await client.send_wechat_message(
            message="AI-Omni OpenClaw 插件真实可用性验证",
        )

    await client.close()

    print(json.dumps(results, ensure_ascii=False, indent=2))

    # 判定可用性：health + l1_models 必须成功
    healthy = results["openclaw_health"].get("ok") is True and results["l1_models"].get("ok") is True
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
