"""IndexTTS2 TTS 后端：对接 Workstation 上的 ToIV TTS Service。

ToIV TTS Service 提供 ``POST /tts`` multipart/form-data 接口，返回 RIFF/WAV 音频。
真实接口参数为 ``text``、``language``、``emo_text``、``emo_alpha``、``ref_audio``；
本后端将 ``voice`` 视为 ``language`` 透传，并支持上传 ``ref_audio`` 参考音频以切换音色。

本后端仅使用标准库（urllib + wave），零第三方深度学习依赖；
AI-Omni 不自行加载本地 TTS 模型（AGENTS.md §四 项目隔离纪律）。
"""

from __future__ import annotations

import io
import logging
import pathlib
import urllib.error
import urllib.request
import uuid
import wave

from ..errors import VoiceBackendError
from ..text_segment import DEFAULT_MAX_LEN, segment_text
from ..tts_styles import get_style
from .base import TTSBackend

logger = logging.getLogger(__name__)


class IndexTTS2(TTSBackend):
    """IndexTTS2 服务后端。

    ``endpoint`` 为服务 base URL（如 ``http://192.168.71.127:9200``）；
    合成结果暴露 ``sample_rate`` 属性（由返回 WAV 头决定，通常为 22050）。

    ``voice`` 字段映射为服务 ``language`` 参数（如 ``"zh"``、``"en"``）；
    ``ref_audio`` 为参考音频：可传文件路径（``str``）或 WAV 字节（``bytes``），
    服务以此克隆音色。参考音频不存在或读取失败时降级为不上传，避免直接报错。

    ``speed`` 由旧接口保留，但当前服务不支持语速调节，构造时接受、请求中忽略。

    M32.30：``style`` 情感风格预设（见 ``tts_styles``）。提供 ``style`` 时，
    未显式指定的 ``emo_text`` / ``emo_alpha`` / ``top_p`` / ``temperature``
    取自预设；显式参数始终优先。``top_p`` / ``temperature`` 随请求透传——
    服务端未升级时 FastAPI 静默忽略多余表单字段，行为安全。

    M32.30：长文本按 ``max_segment_len``（默认 70 字，指南规范）分段合成并
    拼接 PCM，分段器贴合台配说话节奏（句末标点 > 逗号/顿号 > 硬切）。
    """

    def __init__(
        self,
        endpoint: str,
        voice: str = "zh",
        speed: float = 1.0,
        ref_audio: str | bytes | None = None,
        emo_text: str | None = None,
        emo_alpha: float | None = None,
        timeout_s: float = 60.0,
        style: str | None = None,
        top_p: float | None = None,
        temperature: float | None = None,
        max_segment_len: int = DEFAULT_MAX_LEN,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.voice = voice
        self.speed = speed
        self.ref_audio = ref_audio
        # M32.30：style 预设为默认值来源；显式参数优先。
        preset = get_style(style) if style else None
        if emo_text is not None:
            self.emo_text = emo_text
        elif preset is not None:
            self.emo_text = preset.emo_text
        else:
            self.emo_text = None
        if emo_alpha is not None:
            self.emo_alpha = emo_alpha
        elif preset is not None:
            self.emo_alpha = preset.emo_alpha
        else:
            self.emo_alpha = 0.8
        if top_p is not None:
            self.top_p = top_p
        elif preset is not None:
            self.top_p = preset.top_p
        else:
            self.top_p = 0.75
        if temperature is not None:
            self.temperature = temperature
        elif preset is not None:
            self.temperature = preset.temperature
        else:
            self.temperature = 0.65
        self.max_segment_len = max_segment_len
        self.timeout_s = timeout_s
        #: 由返回 WAV 头决定，默认 22050；解码后更新。
        self.sample_rate = 22050

    def synthesize(self, text: str) -> bytes:
        """合成文本为 PCM16 字节；长文本按 ≤max_segment_len 字分段合成拼接。"""
        if not text or not text.strip():
            return b""
        segments = segment_text(text, self.max_segment_len)
        if not segments:
            return b""
        pcm_parts = [self._synthesize_segment(segment) for segment in segments]
        return b"".join(pcm_parts)

    def _synthesize_segment(self, text: str) -> bytes:
        """合成单个分段为 PCM16 字节。"""
        logger.info(
            "IndexTTS2 合成请求: endpoint=%s, language=%s, emo_text=%s, emo_alpha=%s, "
            "top_p=%s, temperature=%s, ref_audio=%s, text_len=%d",
            self.endpoint,
            self.voice,
            (self.emo_text[:20] + "…") if self.emo_text and len(self.emo_text) > 20 else (self.emo_text or "<none>"),
            self.emo_alpha,
            self.top_p,
            self.temperature,
            self.ref_audio or "<default>",
            len(text),
        )
        body, boundary = self._multipart_body(text)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        request = urllib.request.Request(
            f"{self.endpoint}/tts",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                wav_bytes = response.read()
        except urllib.error.HTTPError as exc:
            code = exc.code
            # M32.23：关闭异常持有的底层响应资源（Python 3.14 起未关闭触发
            # ResourceWarning；真实运行时对应未释放的 socket 连接）。
            exc.close()
            raise VoiceBackendError(f"TTS 请求失败 HTTP {code}（服务 {self.endpoint}）") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise VoiceBackendError(f"TTS 服务不可达（{self.endpoint}）: {exc}") from exc
        return self._decode_wav(wav_bytes)

    def _multipart_body(self, text: str) -> tuple[bytes, str]:
        """构造 multipart/form-data 请求体。"""
        boundary = f"----omnivoice-{uuid.uuid4().hex}"
        parts: list[bytes] = []
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="text"\r\n\r\n{text}\r\n'.encode("utf-8")
        )
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\n{self.voice}\r\n'.encode(
                "utf-8"
            )
        )
        if self.emo_text is not None:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="emo_text"\r\n\r\n{self.emo_text}\r\n'.encode(
                    "utf-8"
                )
            )
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="emo_alpha"\r\n\r\n{self.emo_alpha}\r\n'.encode(
                "utf-8"
            )
        )
        # M32.30：采样参数透传（服务端未升级时 FastAPI 静默忽略，安全）
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="top_p"\r\n\r\n{self.top_p}\r\n'.encode("utf-8")
        )
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="temperature"\r\n\r\n{self.temperature}\r\n'.encode(
                "utf-8"
            )
        )
        ref_bytes = self._load_ref_audio()
        if ref_bytes:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="ref_audio"; filename="ref.wav"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8")
                + ref_bytes
                + b"\r\n"
            )
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(parts), boundary

    def _load_ref_audio(self) -> bytes | None:
        """加载参考音频；路径不存在或读取失败时返回 None（降级为默认音色）。"""
        if self.ref_audio is None:
            logger.debug("ref_audio 未设置，使用服务默认音色")
            return None
        if isinstance(self.ref_audio, bytes):
            if self.ref_audio:
                logger.debug("使用传入的参考音频字节 (%d bytes)", len(self.ref_audio))
                return self.ref_audio
            logger.debug("参考音频字节为空，使用服务默认音色")
            return None
        path = pathlib.Path(self.ref_audio)
        try:
            data = path.read_bytes()
            logger.info("已加载参考音频: %s (%d bytes)", path, len(data))
            return data
        except (OSError, ValueError) as exc:
            logger.warning("参考音频加载失败，使用服务默认音色: %s (原因: %s)", path, exc)
            return None

    def _decode_wav(self, wav_bytes: bytes) -> bytes:
        """把 RIFF/WAV 解码为裸 PCM16 字节，并更新 sample_rate。"""
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
                self.sample_rate = wav.getframerate()
                frames = wav.readframes(wav.getnframes())
        except (wave.Error, EOFError) as exc:
            raise VoiceBackendError(f"TTS 返回非 WAV 音频: {exc}") from exc
        return frames
