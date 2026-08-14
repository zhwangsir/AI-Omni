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
    "wake_max_record_s",
    "tts_backend",
    "tts_voice",
    "tts_speed",
    "tts_style",
    "tts_ref_audio",
    "tts_emo_text",
    "tts_emo_alpha",
    "system_prompt",
    "llm_model",
    "llm_endpoint",
    "asr_endpoint",
    "tts_endpoint",
    "asr_model",
    "asr_prompt",
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


def _default_ref_audio() -> str:
    """默认参考音频：固定到项目根目录 ``models/tts_ref/default.wav``。

    使用用户确认过的灰原哀风格参考音频组合（M32.20：emotion_01 + emotion_03 +
    emotion_09）作为 IndexTTS2 音色克隆参考；通过 ``__file__`` 计算绝对路径，
    避免宿主进程 / CLI 因工作目录不同而找不到相对路径，导致服务降级为默认音色
    （用户听感接近系统 TTS）。
    """
    return str(Path(__file__).resolve().parents[3] / "models" / "tts_ref" / "default.wav")


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
    wake_word: str = "雪莉"
    wake_aliases: list[str] = dataclasses.field(default_factory=lambda: list(get_identity().wake_aliases))
    wake_threshold: float = 0.5
    vad_threshold: float = 0.5
    vad_silence_ms: int = 1200
    max_record_s: float = 30.0
    #: M32.29：首轮（热词校验前）录音上限。首轮录音是投机性的——嘈杂环境中
    #: 可能录到的是媒体音而非用户语音——用更短上限减少 ASR 空转、提高回到
    #: 监听状态的占空比；热词校验通过后的续听录音仍用 max_record_s。
    wake_max_record_s: float = 8.0
    follow_up_timeout_s: float = 4.0
    #: ASR 模型名，透传给 faster-whisper 服务。
    asr_model: str = "whisper-1"
    #: M32.29：ASR 识别偏置（映射 whisper initial_prompt）。注入唤醒词上下文
    #: 可显著降低同音误识别（「雪莉」被转写为 Siri/雪梨）。置空则关闭偏置。
    asr_prompt: str = dataclasses.field(
        default_factory=lambda: (
            f"语音助手名叫{get_identity().display_name}（{get_identity().english_name}），"
            f"用户会喊「{get_identity().display_name}」唤醒。"
        )
    )
    #: TTS 后端类型：indextts2（默认，非 OpenAI 兼容 /tts）或 openai（OpenAI 兼容 /audio/speech）。
    tts_backend: str = "indextts2"
    tts_voice: str = "zh"
    #: TTS 语速倍率，仅部分后端支持；<=0 非法。
    tts_speed: float = 1.0
    #: M32.30：IndexTTS2 情感风格（见 tts_styles.TTS_STYLES）。未显式设置
    #: tts_emo_text 时，风格预设提供语气提示词与情感强度；显式设置
    #: tts_emo_text 则覆盖风格提示词（此时强度用 tts_emo_alpha）。
    tts_style: str = "calm"
    #: M32.15：IndexTTS2 参考音频路径。指向存在的 WAV 文件时，服务以该音色克隆；
    #: 不存在或为空时降级为服务默认参考音频。
    tts_ref_audio: str = dataclasses.field(default_factory=_default_ref_audio)
    #: M32.16：IndexTTS2 情感/风格提示文本。为空时不上传该字段，TTS 仅做音色
    #: 克隆而不叠加额外情感色彩，适合日常对话。特定场景（如表达忧伤、温柔）
    #: 可通过 voice_config set tts_emo_text "..." 临时开启。
    #: 推荐情感提示示例：清冷温柔，略带忧伤，像灰原哀，少女音色，语速自然，咬字清晰
    tts_emo_text: str = ""
    #: M32.17：IndexTTS2 情感强度，默认 0.95；仅在 emo_text 非空时生效。
    tts_emo_alpha: float = 0.95
    #: M6.3：True 时管道跳过 TTS 合成与播放（状态机/事件/reply 写入照走）——
    #: OpenTalking 模式下由 OpenTalking 独家发声，omni_voice 本地静音。
    tts_muted: bool = False
    #: LLM 端点：Workstation 上的 Nemotron vLLM（OpenAI 兼容 /chat/completions）。
    llm_endpoint: str = "http://192.168.71.127:8000/v1"
    #: ASR 端点：Workstation GPU2 上的 faster-whisper（OpenAI 兼容 /audio/transcriptions）。
    asr_endpoint: str = "http://192.168.71.127:9210/v1"
    #: TTS 端点：Workstation 上的 IndexTTS2 服务（POST /tts multipart）。
    tts_endpoint: str = "http://192.168.71.127:9200"
    llm_model: str = "Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16"
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
        if self.tts_speed <= 0:
            raise ValueError("tts_speed 必须 > 0")
        valid_tts_backends = {"indextts2", "openai"}
        if self.tts_backend not in valid_tts_backends:
            raise ValueError(
                f"tts_backend 必须是 {valid_tts_backends} 之一，当前={self.tts_backend!r}"
            )
        from .tts_styles import TTS_STYLES

        if self.tts_style not in TTS_STYLES:
            valid_styles = "、".join(sorted(TTS_STYLES))
            raise ValueError(f"tts_style 必须是 {valid_styles} 之一，当前={self.tts_style!r}")
        for name in (
            "wake_word",
            "asr_model",
            "tts_backend",
            "tts_voice",
            "llm_model",
            "llm_endpoint",
            "asr_endpoint",
            "tts_endpoint",
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
