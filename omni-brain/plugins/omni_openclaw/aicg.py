"""omni_openclaw AICG 四层流水线封装。

提供 LLM chat（L1/L4 路由与降级）、ComfyUI 文生图、IndexTTS2 语音合成的
高层接口；所有 HTTP backend 可注入，便于单元测试使用 fake 后端。
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Protocol

from omni_openclaw.config import OpenClawConfig
from omni_openclaw.errors import error_response, success_response
from omni_openclaw.multimodal import parse_chat_response


class AicgBackend(Protocol):
    """AICG 流水线 HTTP backend 抽象协议。

    与 ``client.HttpBackend`` 不同，这里需要向多个独立端点发起请求，
    因此 ``request`` 额外接收 ``endpoint`` 基地址。
    """

    async def request(
        self,
        method: str,
        endpoint: str,
        path: str,
        **kwargs: Any,
    ) -> tuple[int, Any]:
        """执行 HTTP 请求，返回 ``(status_code, body)``。"""
        ...


class HttpxAicgBackend:
    """基于 httpx 的真实 AICG backend。"""

    def __init__(self, timeout_s: float = 15.0) -> None:
        """初始化异步 HTTP 客户端。"""
        # 惰性导入：避免模块加载时拉入 httpx
        import httpx

        self._client = httpx.AsyncClient(timeout=timeout_s)
        self._httpx = httpx

    async def request(
        self,
        method: str,
        endpoint: str,
        path: str,
        **kwargs: Any,
    ) -> tuple[int, Any]:
        """向指定 endpoint 发起 HTTP 请求。"""
        url = endpoint.rstrip("/") + "/" + path.lstrip("/")
        response = await self._client.request(method, url, **kwargs)
        body: Any
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            body = response.json()
        elif "audio" in content_type or "octet-stream" in content_type:
            body = response.content
        else:
            body = response.text
        return response.status_code, body

    async def close(self) -> None:
        """关闭底层 HTTP 连接。"""
        await self._client.aclose()


class AicgPipeline:
    """AICG 四层流水线：文本生成、图像生成、语音合成。"""

    def __init__(
        self,
        config: OpenClawConfig | None = None,
        llm_backend: AicgBackend | None = None,
        comfyui_backend: AicgBackend | None = None,
        tts_backend: AicgBackend | None = None,
    ) -> None:
        """初始化流水线；未提供 backend 时创建真实 httpx backend。"""
        self.config = config or OpenClawConfig()

        if llm_backend is None:
            self._llm_backend: AicgBackend = HttpxAicgBackend(self.config.timeout_s)
            self._owns_llm_backend = True
        else:
            self._llm_backend = llm_backend
            self._owns_llm_backend = False

        if comfyui_backend is None:
            self._comfyui_backend: AicgBackend = HttpxAicgBackend(self.config.timeout_s)
            self._owns_comfyui_backend = True
        else:
            self._comfyui_backend = comfyui_backend
            self._owns_comfyui_backend = False

        if tts_backend is None:
            self._tts_backend: AicgBackend = HttpxAicgBackend(self.config.timeout_s)
            self._owns_tts_backend = True
        else:
            self._tts_backend = tts_backend
            self._owns_tts_backend = False

    async def chat(
        self,
        prompt: str,
        level: str = "L1",
        nsfw: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """调用 LLM chat completions。

        - ``L1`` 使用 ``llm_l1_endpoint`` + ``llm_l1_model``；
        - ``L4`` 使用 ``llm_l4_endpoint`` + ``llm_l4_model``；
        - 当 ``nsfw=True`` 或 L1 失败且 ``nsfw=False`` 时，自动降级到 L4。
        """
        if not prompt or not str(prompt).strip():
            return error_response("E_INVALID_PARAMS", "prompt 不能为空")

        level = (level or "L1").upper()
        if level not in ("L1", "L4"):
            return error_response("E_INVALID_PARAMS", f"不支持的 level: {level}")

        if level == "L4":
            return await self._chat_with_endpoint(
                endpoint=self.config.llm_l4_endpoint,
                model=self.config.llm_l4_model,
                prompt=prompt,
                **kwargs,
            )

        # L1 主路径
        result = await self._chat_with_endpoint(
            endpoint=self.config.llm_l1_endpoint,
            model=self.config.llm_l1_model,
            prompt=prompt,
            **kwargs,
        )
        if result["ok"] and not nsfw:
            return result

        # 降级到 L4：nsfw=True 或 L1 失败
        fallback = await self._chat_with_endpoint(
            endpoint=self.config.llm_l4_endpoint,
            model=self.config.llm_l4_model,
            prompt=prompt,
            **kwargs,
        )
        if fallback["ok"]:
            extras: dict[str, Any] = {"fallback_from": "L1"}
            if nsfw:
                extras["nsfw"] = True
            return success_response(
                content=fallback.get("content", ""),
                model=self.config.llm_l4_model,
                raw=fallback.get("raw"),
                **extras,
            )
        return fallback

    async def _chat_with_endpoint(
        self,
        endpoint: str,
        model: str,
        prompt: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """向指定 LLM 端点发起 OpenAI 兼容 chat completion 请求。"""
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 1024),
        }
        for key in ("top_p", "stream", "stop", "frequency_penalty", "presence_penalty"):
            if key in kwargs:
                payload[key] = kwargs[key]

        try:
            status, body = await self._llm_backend.request(
                "POST",
                endpoint,
                "/chat/completions",
                json=payload,
            )
        except (TimeoutError, OSError) as exc:
            return error_response(
                "E_LLM_UNAVAILABLE",
                f"无法连接到 LLM 端点: {exc}",
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

    async def generate_image(
        self,
        prompt: str,
        workflow: dict[str, Any] | None = None,
        width: int = 1024,
        height: int = 1024,
    ) -> dict[str, Any]:
        """调用 ComfyUI 提交文生图工作流。

        未提供 ``workflow`` 时，构造默认工作流（KSampler + EmptyLatentImage +
        CLIPTextEncode + SaveImage），并用 ``prompt`` 填充正/负提示词。
        """
        if not prompt or not str(prompt).strip():
            return error_response("E_INVALID_PARAMS", "prompt 不能为空")
        if width <= 0 or height <= 0:
            return error_response("E_INVALID_PARAMS", "width 与 height 必须为正整数")

        workflow = workflow or self._build_default_workflow(prompt, width, height)

        try:
            status, body = await self._comfyui_backend.request(
                "POST",
                self.config.comfyui_endpoint,
                "/prompt",
                json={"prompt": workflow},
            )
        except (TimeoutError, OSError) as exc:
            return error_response(
                "E_COMFYUI_UNAVAILABLE",
                f"无法连接到 ComfyUI: {exc}",
            )
        except Exception as exc:
            return error_response(
                "E_COMFYUI_UNAVAILABLE",
                f"请求 ComfyUI 时出错: {exc}",
            )

        if status == 200 and isinstance(body, dict):
            return success_response(
                prompt_id=body.get("prompt_id", ""),
                status="queued",
                comfyui=self.config.comfyui_endpoint,
            )
        return {
            "ok": False,
            "error": {
                "code": "E_COMFYUI_ERROR",
                "message": f"ComfyUI 返回错误 (HTTP {status})",
                "status_code": status,
                "body": body,
            },
            "status_code": status,
        }

    def _build_default_workflow(
        self,
        prompt: str,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        """构造简单默认文生图工作流。"""
        return {
            "3": {
                "inputs": {
                    "seed": 0,
                    "steps": 20,
                    "cfg": 8.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
                "class_type": "KSampler",
            },
            "4": {
                "inputs": {"ckpt_name": "default.safetensors"},
                "class_type": "CheckpointLoaderSimple",
            },
            "5": {
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": 1,
                },
                "class_type": "EmptyLatentImage",
            },
            "6": {
                "inputs": {"text": prompt, "clip": ["4", 1]},
                "class_type": "CLIPTextEncode",
            },
            "7": {
                "inputs": {"text": "nsfw, blurry, low quality", "clip": ["4", 1]},
                "class_type": "CLIPTextEncode",
            },
            "8": {
                "inputs": {
                    "filename_prefix": "omni_openclaw",
                    "images": ["3", 0],
                },
                "class_type": "SaveImage",
            },
        }

    async def text_to_speech(
        self,
        text: str,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """调用 IndexTTS2 语音合成端点。

        依次尝试 ``/tts`` 与 ``/`` 端点；``output_path`` 为 ``None`` 时返回
        base64 编码音频，否则写入文件并返回路径。
        """
        if not text or not str(text).strip():
            return error_response("E_INVALID_PARAMS", "text 不能为空")

        payload = {"text": text}
        paths = ["/tts", "/"]
        last_error: dict[str, Any] | None = None

        for path in paths:
            try:
                status, body = await self._tts_backend.request(
                    "POST",
                    self.config.tts_endpoint,
                    path,
                    json=payload,
                )
            except (TimeoutError, OSError) as exc:
                last_error = error_response(
                    "E_TTS_UNAVAILABLE",
                    f"无法连接到 TTS 端点: {exc}",
                )
                continue
            except Exception as exc:
                last_error = error_response(
                    "E_TTS_UNAVAILABLE",
                    f"请求 TTS 端点时出错: {exc}",
                )
                continue

            if status != 200:
                last_error = {
                    "ok": False,
                    "error": {
                        "code": "E_TTS_ERROR",
                        "message": f"TTS 返回错误 (HTTP {status})",
                        "status_code": status,
                        "body": body,
                    },
                    "status_code": status,
                }
                continue

            audio_bytes = self._extract_audio_bytes(body)
            if audio_bytes is None:
                last_error = error_response(
                    "E_TTS_INVALID_RESPONSE",
                    "TTS 返回无法解析的音频数据",
                )
                continue

            if output_path:
                Path(output_path).write_bytes(audio_bytes)
                return success_response(path=output_path, format="wav")
            return success_response(
                audio=base64.b64encode(audio_bytes).decode("utf-8"),
                format="wav",
            )

        return last_error or error_response("E_TTS_ERROR", "TTS 调用失败")

    def _extract_audio_bytes(self, body: Any) -> bytes | None:
        """从 TTS 响应中解析音频字节。"""
        if isinstance(body, bytes):
            return body
        if isinstance(body, str):
            try:
                return base64.b64decode(body)
            except Exception:
                return body.encode("utf-8")
        if isinstance(body, dict):
            for key in ("audio", "data", "wav"):
                value = body.get(key)
                if isinstance(value, bytes):
                    return value
                if isinstance(value, str):
                    try:
                        return base64.b64decode(value)
                    except Exception:
                        return value.encode("utf-8")
        return None

    async def close(self) -> None:
        """释放 backend 资源。"""
        if self._owns_llm_backend and hasattr(self._llm_backend, "close"):
            await self._llm_backend.close()
        if self._owns_comfyui_backend and hasattr(self._comfyui_backend, "close"):
            await self._comfyui_backend.close()
        if self._owns_tts_backend and hasattr(self._tts_backend, "close"):
            await self._tts_backend.close()
