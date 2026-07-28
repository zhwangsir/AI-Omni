"""OpenAI 兼容 TTS 后端：经 OpenClaw 网关（:18789）调用 /audio/speech。

仅使用标准库（urllib），零第三方依赖；
AI-Omni 不自行加载本地 TTS 模型（AGENTS.md §四 项目隔离纪律）。

请求 ``response_format="pcm"``，OpenAI 兼容端点返回裸 PCM16（单声道小端，
采样率固定 24 kHz——与 OpenAI 官方 PCM 输出一致），可直接交给播放器。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..errors import VoiceBackendError
from .base import TTSBackend

#: OpenAI 兼容端点 PCM 输出的固定采样率（16-bit little-endian mono）
OPENAI_PCM_SAMPLE_RATE = 24000


class OpenAITTS(TTSBackend):
    """OpenAI 兼容 /audio/speech 端点的 TTS 后端。

    ``endpoint`` 为 OpenAI 兼容 base URL（如 ``http://localhost:18789/v1``）；
    合成结果暴露 ``sample_rate`` 属性（24000），tools/pipeline 播放时按此采样率播放。
    """

    def __init__(
        self,
        endpoint: str,
        voice: str = "alloy",
        model: str = "tts-1",
        api_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.voice = voice
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        #: 播放器按此采样率播放合成结果（tools.py 经 getattr 读取）
        self.sample_rate = OPENAI_PCM_SAMPLE_RATE

    def synthesize(self, text: str) -> bytes:
        if not text or not text.strip():
            return b""
        payload = {
            "model": self.model,
            "voice": self.voice,
            "input": text,
            "response_format": "pcm",
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.endpoint}/audio/speech",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise VoiceBackendError(f"TTS 请求失败 HTTP {exc.code}（网关 {self.endpoint}）") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise VoiceBackendError(f"TTS 网关不可达（{self.endpoint}）: {exc}") from exc
