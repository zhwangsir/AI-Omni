"""omni_openclaw OpenClaw HTTP 客户端。

提供真实 HTTP backend（基于 httpx）与可注入的抽象 backend，
方便单元测试使用 fake 后端。
"""

from __future__ import annotations

from typing import Any, Protocol

from omni_openclaw.config import OpenClawConfig
from omni_openclaw.errors import error_response, success_response
from omni_openclaw.multimodal import (
    build_audio_message,
    build_vision_message,
    build_video_message,
    parse_chat_response,
)


class HttpBackend(Protocol):
    """HTTP backend 抽象协议。"""

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
        config: OpenClawConfig,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.config = config
        # 惰性导入：避免模块加载时拉入 httpx
        import httpx

        self._client = httpx.AsyncClient(
            base_url=(base_url or config.gateway).rstrip("/"),
            timeout=timeout if timeout is not None else config.timeout_s,
        )
        self._httpx = httpx

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> tuple[int, Any]:
        """执行 HTTP 请求。"""
        response = await self._client.request(method, path, **kwargs)
        body: Any
        try:
            body = response.json()
        except Exception:
            body = response.text
        return response.status_code, body

    async def close(self) -> None:
        """关闭底层 HTTP 连接。"""
        await self._client.aclose()


class OpenClawClient:
    """OpenClaw 网关客户端。

    封装健康检查、微信消息收发等常用 API。
    """

    def __init__(
        self,
        config: OpenClawConfig | None = None,
        backend: HttpBackend | None = None,
        llm_backend: HttpBackend | None = None,
        wechat_bridge_backend: HttpBackend | None = None,
    ) -> None:
        self.config = config or OpenClawConfig()
        if backend is None:
            self._backend: HttpBackend = HttpxBackend(self.config)
            self._owns_backend = True
        else:
            self._backend = backend
            self._owns_backend = False

        if llm_backend is None:
            # LLM 请求默认直连配置中的 L1 端点，不经过 OpenClaw 网关，
            # 避免网关与模型服务之间的额外跳转与负载。
            llm_config = OpenClawConfig(
                gateway=self.config.llm_l1_endpoint,
                timeout_s=self.config.timeout_s,
            )
            self._llm_backend: HttpBackend = HttpxBackend(llm_config)
            self._owns_llm_backend = True
        else:
            self._llm_backend = llm_backend
            self._owns_llm_backend = False

        if wechat_bridge_backend is None:
            self._wechat_backend: HttpBackend = HttpxBackend(
                self.config,
                base_url=self.config.wechat_bridge_endpoint,
                timeout=30.0,
            )
            self._owns_wechat_backend = True
        else:
            self._wechat_backend = wechat_bridge_backend
            self._owns_wechat_backend = False

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> tuple[int, Any]:
        """透传到 backend。"""
        return await self._backend.request(method, path, **kwargs)

    async def _llm_request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> tuple[int, Any]:
        """透传到 LLM backend。"""
        return await self._llm_backend.request(method, path, **kwargs)

    async def _chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """调用 OpenAI 兼容的 LLM chat completions。"""
        model = model or self.config.llm_l1_model
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            status, body = await self._llm_request("POST", "/chat/completions", json=payload)
        except (TimeoutError, OSError):
            return error_response(
                "E_LLM_UNAVAILABLE",
                f"无法连接到 LLM 端点 {self.config.llm_l1_endpoint}",
            )
        except Exception as exc:
            return error_response(
                "E_LLM_UNAVAILABLE",
                f"请求 LLM 端点时出错: {exc}",
            )

        if status == 200 and isinstance(body, dict):
            return success_response(
                content=parse_chat_response(body),
                model=model,
                raw=body,
            )
        return {
            "ok": False,
            "error": {
                "code": "E_LLM_ERROR",
                "message": f"LLM 返回错误 (HTTP {status})",
                "status_code": status,
                "body": body,
            },
            "status_code": status,
        }

    async def vision_chat(
        self,
        prompt: str,
        image_base64_or_url: str,
        detail: str = "auto",
    ) -> dict[str, Any]:
        """单图视觉理解。"""
        if not prompt or not str(prompt).strip():
            return error_response("E_INVALID_PARAMS", "prompt 不能为空")
        if not image_base64_or_url or not str(image_base64_or_url).strip():
            return error_response("E_INVALID_PARAMS", "image 不能为空")
        message = build_vision_message(prompt, image_base64_or_url, detail)
        return await self._chat_completion([message])

    async def audio_chat(
        self,
        prompt: str,
        audio_base64: str,
        format_: str = "wav",
    ) -> dict[str, Any]:
        """音频理解。"""
        if not prompt or not str(prompt).strip():
            return error_response("E_INVALID_PARAMS", "prompt 不能为空")
        if not audio_base64 or not str(audio_base64).strip():
            return error_response("E_INVALID_PARAMS", "audio 不能为空")
        message = build_audio_message(prompt, audio_base64, format_)
        return await self._chat_completion([message])

    async def video_chat(
        self,
        prompt: str,
        video_base64_or_url: str,
        frames: list[str] | None = None,
    ) -> dict[str, Any]:
        """视频理解（支持 URL / data URL / 关键帧序列）。"""
        if not prompt or not str(prompt).strip():
            return error_response("E_INVALID_PARAMS", "prompt 不能为空")
        if not video_base64_or_url or not str(video_base64_or_url).strip():
            return error_response("E_INVALID_PARAMS", "video 不能为空")
        message = build_video_message(prompt, video_base64_or_url, frames)
        return await self._chat_completion([message])

    async def health_check(self) -> dict[str, Any]:
        """检查 OpenClaw 网关健康状态。"""
        try:
            status, body = await self._request("GET", "/health")
        except (TimeoutError, OSError):
            return error_response(
                "E_GATEWAY_UNAVAILABLE",
                f"无法连接到 OpenClaw 网关 {self.config.gateway}",
            )
        except Exception as exc:
            return error_response(
                "E_GATEWAY_UNAVAILABLE",
                f"请求 OpenClaw 网关时出错: {exc}",
            )

        if status == 200 and isinstance(body, dict):
            return success_response(
                gateway=self.config.gateway,
                status=body.get("status", "ok"),
                version=body.get("version", "unknown"),
            )
        return {
            "ok": False,
            "error": {
                "code": "E_GATEWAY_DEGRADED",
                "message": "OpenClaw 网关返回非健康状态",
                "status_code": status,
                "body": body,
            },
            "status_code": status,
        }

    async def send_wechat_message(
        self,
        message: str,
        target: str | None = None,
        account: str | None = None,
    ) -> dict[str, Any]:
        """通过 wechat-bridge 发送微信消息。

        OpenClaw 网关本身没有暴露发送微信的 REST 端点；wechat-bridge
        （openclaw01:9095）接收 Alertmanager 格式告警并调用 OpenClaw agent
        完成微信投递。这里把用户消息包装成单条 info 级别告警发给 bridge。
        """
        if not message or not str(message).strip():
            return error_response("E_INVALID_PARAMS", "message 不能为空")

        from datetime import datetime, timezone

        resolved_target = target or self.config.wechat_default_target
        resolved_account = account or self.config.wechat_account
        payload = {
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "AI-Omni",
                        "severity": "info",
                        "instance": "ai-omni",
                        "target": resolved_target,
                        "account": resolved_account,
                    },
                    "annotations": {
                        "summary": message,
                        "description": message,
                    },
                    "startsAt": datetime.now(timezone.utc).isoformat().replace("+", "Z"),
                }
            ]
        }
        try:
            status, body = await self._wechat_backend.request(
                "POST", "/wechat", json=payload
            )
        except (TimeoutError, OSError):
            return error_response(
                "E_WECHAT_BRIDGE_UNAVAILABLE",
                f"无法连接到 wechat-bridge {self.config.wechat_bridge_endpoint}",
            )
        except Exception as exc:
            return error_response(
                "E_WECHAT_BRIDGE_ERROR",
                f"请求 wechat-bridge 时出错: {exc}",
            )

        if status == 200 and isinstance(body, dict):
            return success_response(
                status=body.get("status", "sent"),
                channel="openclaw-weixin",
                target=resolved_target,
                account=resolved_account,
            )
        return error_response(
            "E_WECHAT_BRIDGE_ERROR",
            f"wechat-bridge 返回错误 (HTTP {status})",
            status_code=status,
            body=body,
        )

    async def close(self) -> None:
        """释放 backend 资源。"""
        if self._owns_backend and hasattr(self._backend, "close"):
            await self._backend.close()
        if self._owns_llm_backend and hasattr(self._llm_backend, "close"):
            await self._llm_backend.close()
        if self._owns_wechat_backend and hasattr(self._wechat_backend, "close"):
            await self._wechat_backend.close()
