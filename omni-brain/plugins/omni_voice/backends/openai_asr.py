"""OpenAI 兼容 ASR 后端：经 OpenClaw 网关（:18789）调用 /audio/transcriptions。

仅使用标准库（urllib + 手工 multipart/form-data），零第三方依赖；
AI-Omni 不自行加载本地 ASR 模型（AGENTS.md §四 项目隔离纪律）。

输入 PCM16 字节会先封装为标准 RIFF/WAV 容器再上传，服务端按普通音频文件解析。
"""

from __future__ import annotations

import json
import struct
import urllib.error
import urllib.request
import uuid

from ..errors import VoiceBackendError
from .base import ASRBackend


def _wrap_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """把裸 PCM16 字节封装为 RIFF/WAV 容器（44 字节标准头）。"""
    byte_rate = sample_rate * channels * 2
    block_align = channels * 2
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
    )
    return header + pcm


def _multipart_body(fields: dict[str, str], file_field: str, filename: str, content_type: str, payload: bytes) -> tuple[bytes, str]:
    """构造 multipart/form-data 请求体，返回 (body, boundary)。"""
    boundary = f"----omnivoice-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
        f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode("utf-8")
        + payload
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


class OpenAIASR(ASRBackend):
    """OpenAI 兼容 /audio/transcriptions 端点的 ASR 后端。

    ``endpoint`` 为 OpenAI 兼容 base URL（如 ``http://localhost:18789/v1``）；
    网络/协议/结构错误统一映射为 :class:`VoiceBackendError`。

    ``prompt`` 为可选识别偏置（映射 whisper initial_prompt）：注入唤醒词等
    上下文可显著降低同音误识别（如「雪莉」被写成 Siri/雪梨）。缺省 None
    时不上传该字段，与旧行为一致。
    """

    def __init__(
        self,
        endpoint: str,
        model: str = "whisper-1",
        api_key: str | None = None,
        timeout_s: float = 60.0,
        prompt: str | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.prompt = prompt

    def transcribe(self, pcm: bytes, sample_rate: int, language: str | None = None) -> str:
        if not pcm:
            return ""
        wav = _wrap_wav(pcm, sample_rate)
        fields = {"model": self.model, "response_format": "json"}
        if self.prompt:
            fields["prompt"] = self.prompt
        if language:
            fields["language"] = language
        body, boundary = _multipart_body(fields, "file", "audio.wav", "audio/wav", wav)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.endpoint}/audio/transcriptions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            code = exc.code
            # M32.23：关闭异常持有的底层响应资源（Python 3.14 起未关闭触发
            # ResourceWarning；真实运行时对应未释放的 socket 连接）。
            exc.close()
            raise VoiceBackendError(f"ASR 请求失败 HTTP {code}（网关 {self.endpoint}）") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise VoiceBackendError(f"ASR 网关不可达（{self.endpoint}）: {exc}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise VoiceBackendError(f"ASR 返回非 JSON 内容: {exc}") from exc
        text = data.get("text")
        if not isinstance(text, str):
            raise VoiceBackendError(f"ASR 返回结构异常: {data!r}")
        return text
