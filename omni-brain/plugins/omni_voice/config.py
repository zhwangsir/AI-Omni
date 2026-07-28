"""omni_voice 配置模型。

提供 :class:`VoiceConfig` 数据类及三种加载方式：

- ``from_dict``    ：字典加载（未知键 / 非法值抛 ``ValueError``）
- ``from_yaml``    ：YAML 文件加载；无 PyYAML 时降级为 JSON / 简易 YAML 解析
- ``from_env``     ：``OMNI_VOICE_`` 前缀环境变量覆盖

所有数值/非空校验集中在 ``validate()``，构造（``__post_init__``）即触发。
"""

from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omni_sdk.identity import get_identity

#: 环境变量前缀
ENV_PREFIX = "OMNI_VOICE_"

#: 运行时可通过 voice_config set 调整的字段
RUNTIME_SETTABLE: tuple[str, ...] = (
    "wake_threshold",
    "vad_threshold",
    "vad_silence_ms",
    "max_record_s",
    "tts_voice",
    "system_prompt",
    "llm_model",
    "llm_endpoint",
    "asr_model",
    "tts_muted",
)


def _coerce(target: type, value: Any) -> Any:
    """把外部输入（常为字符串）强转为目标类型，失败抛 ValueError。"""
    if target is bool:
        # bool 必须先于 int 分支：bool 是 int 子类，且 str(False)="False" 为真值，
        # 走默认 str() 强转会得到恒 True 的陷阱。
        if isinstance(value, bool):
            return value
        lowered = str(value).strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"无法解析为布尔: {value!r}")
    if target is int:
        return int(float(value))  # 容忍 "16000.0" 这类输入
    if target is float:
        return float(value)
    return str(value)


def _scalar(text: str) -> Any:
    """简易 YAML 标量解析：去引号后依次尝试 int / float / 布尔 / 字符串。"""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """解析 YAML 的简单子集：扁平 ``key: value`` 与一级 ``- item`` 列表。

    仅作为无 PyYAML 时的降级解析器，不追求完整 YAML 语义。
    """
    result: dict[str, Any] = {}
    current_key: str | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        stripped = raw.strip()
        if stripped.startswith("- ") and current_key is not None:
            result[current_key].append(_scalar(stripped[2:]))
            continue
        key, sep, value = raw.partition(":")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if value:
            result[key] = _scalar(value)
            current_key = None
        else:
            result[key] = []
            current_key = key
    return result


@dataclass
class VoiceConfig:
    """语音管道配置。

    采样格式固定为 PCM16（小端有符号 16 位）。
    """

    sample_rate: int = 16000
    channels: int = 1
    frame_ms: int = 32
    wake_word: str = "hey_omni"
    wake_aliases: list[str] = dataclasses.field(default_factory=lambda: list(get_identity().wake_aliases))
    wake_threshold: float = 0.5
    vad_threshold: float = 0.5
    vad_silence_ms: int = 1200
    max_record_s: float = 30.0
    follow_up_timeout_s: float = 4.0
    #: ASR 走 OpenClaw 网关 OpenAI 兼容端点（/audio/transcriptions），模型名透传。
    asr_model: str = "whisper-1"
    tts_voice: str = "alloy"
    #: M6.3：True 时管道跳过 TTS 合成与播放（状态机/事件/reply 写入照走）——
    #: OpenTalking 模式下由 OpenTalking 独家发声，omni_voice 本地静音。
    tts_muted: bool = False
    #: OpenClaw 网关 OpenAI 兼容 base URL：ASR/TTS/LLM 统一经此接入
    #:（/audio/transcriptions、/audio/speech、/chat/completions）。
    llm_endpoint: str = "http://localhost:18789/v1"
    llm_model: str = "qwen3.6-uncensored"
    system_prompt: str = get_identity().system_prompt
    wake_response: str = get_identity().wake_response

    def __post_init__(self) -> None:
        self.validate()

    @property
    def frame_bytes(self) -> int:
        """单帧字节数 = 采样率 * 帧长 * 2 字节(PCM16) * 声道数。"""
        return self.sample_rate * self.frame_ms // 1000 * 2 * self.channels

    def validate(self) -> None:
        """校验所有字段，非法值抛 ``ValueError``。"""
        if self.sample_rate <= 0:
            raise ValueError("sample_rate 必须 > 0")
        if self.channels < 1:
            raise ValueError("channels 必须 >= 1")
        if self.frame_ms <= 0:
            raise ValueError("frame_ms 必须 > 0")
        if not 0.0 <= self.wake_threshold <= 1.0:
            raise ValueError("wake_threshold 必须在 [0, 1] 区间")
        if not 0.0 <= self.vad_threshold <= 1.0:
            raise ValueError("vad_threshold 必须在 [0, 1] 区间")
        if self.vad_silence_ms < 0:
            raise ValueError("vad_silence_ms 必须 >= 0")
        if self.max_record_s <= 0:
            raise ValueError("max_record_s 必须 > 0")
        if self.follow_up_timeout_s < 0:
            raise ValueError("follow_up_timeout_s 必须 >= 0")
        for name in (
            "wake_word",
            "asr_model",
            "tts_voice",
            "llm_model",
            "llm_endpoint",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} 不能为空")

    def summary(self) -> dict[str, Any]:
        """返回可 JSON 序列化的配置摘要。"""
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "VoiceConfig":
        """从字典构建；未知键或非法值抛 ``ValueError``。"""
        fields = {f.name: f for f in dataclasses.fields(cls)}
        kwargs: dict[str, Any] = {}
        for key, value in (data or {}).items():
            field = fields.get(key)
            if field is None:
                raise ValueError(f"未知配置项: {key}")
            target = type(field.default)
            try:
                kwargs[key] = _coerce(target, value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"配置项 {key} 的值非法: {value!r}") from exc
        return cls(**kwargs)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "VoiceConfig":
        """从 YAML 文件加载；无 PyYAML 时依次降级为 JSON / 简易 YAML 解析。"""
        text = Path(path).read_text(encoding="utf-8")
        data: dict[str, Any] | None = None
        try:
            import yaml  # type: ignore[import-not-found]

            data = yaml.safe_load(text)
        except ImportError:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = parse_simple_yaml(text)
        return cls.from_dict(data or {})

    @classmethod
    def from_env(
        cls,
        environ: dict[str, str] | None = None,
        base: "VoiceConfig | None" = None,
    ) -> "VoiceConfig":
        """以 ``OMNI_VOICE_`` 前缀环境变量覆盖 base（默认默认值）构建配置。"""
        env = os.environ if environ is None else environ
        merged = (base or cls()).summary()
        for field in dataclasses.fields(cls):
            key = ENV_PREFIX + field.name.upper()
            if key in env:
                merged[field.name] = env[key]
        return cls.from_dict(merged)
