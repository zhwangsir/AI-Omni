"""omni_voice 插件 tools：7 个 voice_* 工具与 ``register(ctx)`` 注册入口。

工具统一返回 JSON 字符串 ``{"ok": bool, "data": ..., "error": ...}``；

- ``voice_status``         ：管道状态 + 配置摘要
- ``voice_speak``          ：一次性 TTS 合成并播放
- ``voice_listen_once``    ：一次性 录音→VAD→ASR→Agent→（可选）播报
- ``voice_pipeline_start`` ：启动常驻语音管道（唤醒循环）
- ``voice_pipeline_stop``  ：停止管道（幂等）
- ``voice_config``         ：get 配置摘要 / set 运行时可调项（原地生效）
- ``voice_interrupt``      ：打断当前播报（M7.5 控制文件反向通道）

进程内 :class:`Runtime` 单例持有配置、管道与组件缓存；
所有工具接受 ``fake=True`` 使用可编程 fake 后端（演示/测试，无需硬件）。
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from typing import Any, Callable

from .config import RUNTIME_SETTABLE, VoiceConfig
from .control_file import VoiceControlFile
from .errors import PipelineStateError
from .pipeline import VoicePipeline
from .state_file import PipelineStateWriter, VoiceStateFile
from omni_sdk.identity import get_identity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 运行时单例
# ---------------------------------------------------------------------------
class Runtime:
    """进程内运行时：持有配置、管道实例与后端组件缓存。

    ``components`` 可由测试/CLI 预置为脚本化 fake 组件；
    ``fake_audio_frames`` 为 fake 模式的音频帧脚本（None → 全静音帧）。
    """

    def __init__(self, config: VoiceConfig | None = None):
        if config is None:
            config = VoiceConfig(wake_response="我在")
        self.config = config
        self.pipeline: VoicePipeline | None = None
        self.fake_mode = False
        self.components: dict[str, Any] | None = None
        self.fake_audio_frames: list[bytes] | None = None
        self.event_publisher: Any = None


_runtime = Runtime()


def _reset_runtime(runtime: Runtime | None = None) -> Runtime:
    """替换进程内运行时（测试隔离用），返回新实例。"""
    global _runtime
    _runtime = runtime or Runtime()
    return _runtime


# ---------------------------------------------------------------------------
# 组件构建
# ---------------------------------------------------------------------------
def _build_fake_components(config: VoiceConfig) -> dict[str, Any]:
    """构建一整套可编程 fake 组件（不含音频帧源）。"""
    from .agent_bridge import FakeAgentBridge
    from .backends.fakes import FakeASR, FakePlayer, FakeTTS, FakeVAD, FakeWakeWord

    return {
        "wake": FakeWakeWord(),
        "vad": FakeVAD(),
        "asr": FakeASR(),
        "tts": FakeTTS(),
        "player": FakePlayer(),
        "agent": FakeAgentBridge(),
    }


def _build_real_components(config: VoiceConfig) -> dict[str, Any]:
    """构建真实后端组件（惰性导入）。

    ASR/TTS/LLM 统一走 OpenClaw 网关 OpenAI 兼容端点（AGENTS.md §四），
    本地仅保留纯 Python 能量 VAD（零依赖）；TTS 网关不可用时降级静音。
    """
    from .agent_bridge import LiteLLMBridge
    from .audio import SounddevicePlayer
    from .backends.energy_vad import EnergyVAD
    from .backends.openai_asr import OpenAIASR
    from .backends.vad_wake import VADWakeWord
    from .conversation import ConversationAgent

    tts: Any
    if config.tts_muted:
        from .backends.fakes import FakeTTS

        tts = FakeTTS()
    else:
        try:
            from .backends.openai_tts import OpenAITTS

            tts = OpenAITTS(endpoint=config.llm_endpoint, voice=config.tts_voice)
        except Exception as exc:
            logger.warning("TTS 网关后端不可用（%s），TTS 将静音", exc)
            from .backends.fakes import FakeTTS

            tts = FakeTTS()
            config.tts_muted = True

    vad = EnergyVAD(threshold=config.vad_threshold, sample_rate=config.sample_rate)
    wake: Any = VADWakeWord(
        vad=vad,
        sample_rate=config.sample_rate,
        frame_ms=config.frame_ms,
        speech_frames=15,
    )

    bridge: Any = LiteLLMBridge(
        endpoint=config.llm_endpoint,
        model=config.llm_model,
        system_prompt=config.system_prompt,
    )
    logger.info("LLM 后端：OpenClaw 网关 %s（模型=%s）", config.llm_endpoint, config.llm_model)
    agent: Any = ConversationAgent(bridge, system_prompt=config.system_prompt)
    return {
        "wake": wake,
        "vad": vad,
        "asr": OpenAIASR(endpoint=config.llm_endpoint, model=config.asr_model),
        "tts": tts,
        "player": SounddevicePlayer(sample_rate=config.sample_rate),
        "agent": agent,
    }


def _components(rt: Runtime, fake: bool) -> dict[str, Any]:
    """取组件缓存；未预置时按 fake/真实构建并缓存。"""
    if fake:
        rt.fake_mode = True  # 预置组件场景也如实上报 fake 模式
    if rt.components is not None:
        return rt.components
    if fake:
        rt.components = _build_fake_components(rt.config)
    else:
        rt.components = _build_real_components(rt.config)
    return rt.components


def _new_audio_source(rt: Runtime, fake: bool):
    """为一次操作创建新的音频帧源（不与管道共享，避免竞争）。"""
    if fake or rt.fake_mode:
        from .audio import FakeAudioSource

        return FakeAudioSource(
            frames=rt.fake_audio_frames,
            frame_bytes=rt.config.frame_bytes,
            silence_after=True,
        )
    from .audio import SounddeviceSource

    return SounddeviceSource(
        sample_rate=rt.config.sample_rate,
        channels=rt.config.channels,
        frame_ms=rt.config.frame_ms,
    )


# ---------------------------------------------------------------------------
# JSON 响应约定
# ---------------------------------------------------------------------------
def _ok(data: Any) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False)


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 录音辅助
# ---------------------------------------------------------------------------
def _record_utterance(source, vad, config: VoiceConfig, timeout_s: float) -> bytes:
    """录一段语音：VAD 连续静音达 vad_silence_ms 或超时即停。"""
    source.start()
    frames: list[bytes] = []
    silence_ms = 0
    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            frame = source.read_frame()
            if not frame:
                continue
            frames.append(frame)
            if vad.is_speech(frame, config.sample_rate):
                silence_ms = 0
            else:
                silence_ms += config.frame_ms
                if silence_ms >= config.vad_silence_ms:
                    break
    finally:
        source.stop()
    return b"".join(frames)


# ---------------------------------------------------------------------------
# Tool 元数据注册表
# ---------------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = []


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    required: list[str] | None = None,
    emoji: str = "",
) -> Callable:
    """@tool 装饰器：为函数附加 tool schema 元数据并登记到 TOOLS。"""

    def decorator(func: Callable) -> Callable:
        TOOLS.append(
            {
                "name": name,
                "description": description,
                "emoji": emoji,
                "schema": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": parameters,
                        "required": list(required or []),
                    },
                },
                "handler_func": func,
            }
        )
        return func

    return decorator


_FAKE_PARAM = {
    "type": "boolean",
    "description": "为 true 时使用可编程 fake 后端（演示/测试，无需音频硬件与模型）。",
}


# ---------------------------------------------------------------------------
# Tool 1：状态查询
# ---------------------------------------------------------------------------
@tool(
    name="voice_status",
    description=(
        "查询语音插件状态：管道状态机当前状态（idle/wake_listening/recording/"
        "transcribing/thinking/speaking）、是否在运行、是否 fake 模式、完整配置摘要。"
    ),
    parameters={},
    emoji="🎙️",
)
def voice_status() -> str:
    """返回管道状态与配置摘要。

    进程内管道存活时优先读进程内状态（source=process）；
    进程内无管道时回退读共享状态文件（source=state_file，M5.4 外部观察通道）——
    宿主外进程（CLI / HUD 轮询）由此看到宿主常驻管道的真实状态；
    文件缺失或损坏则按缺省 idle 上报（source=default）。
    """
    rt = _runtime
    pipeline = rt.pipeline
    if pipeline is not None:
        return _ok(
            {
                "state": pipeline.state.value,
                "running": bool(pipeline.is_running),
                "fake_mode": rt.fake_mode,
                "source": "process",
                "config": rt.config.summary(),
            }
        )
    observed = VoiceStateFile.read()
    if observed is not None:
        data: dict[str, Any] = {
            "state": observed["state"],
            "running": observed["running"],
            "fake_mode": observed["fake_mode"],
            "source": "state_file",
            "config": rt.config.summary(),
        }
        # M6.3：透传 SPEAKING 快照携带的本轮回复文本与轮次序号；
        # read() 约定 reply 键存在即字符串、reply_seq 键存在即 int，无键则不带出。
        # reply_seq 使 CLI 轮询兜底与 watcher 推送共用同一去重键空间（跨通道不重复播报）。
        if "reply" in observed:
            data["reply"] = observed["reply"]
        if "reply_seq" in observed:
            data["reply_seq"] = observed["reply_seq"]
        # M12：透传 window_mode（HUD 窗口形态），缺省不带出（前端按 Full 缺省）。
        if "window_mode" in observed:
            data["window_mode"] = observed["window_mode"]
        # M13.2：透传 tool_calls（Agent 可视化工具调用列表）。
        # read() 约定 tool_calls 键存在即 list（含空数组），无键则不带出。
        # 空数组表示「本轮工具链已结束」，与「无此字段」语义区分（前端据此决定是否渲染卡片）。
        if "tool_calls" in observed:
            data["tool_calls"] = observed["tool_calls"]
        return _ok(data)
    return _ok(
        {
            "state": "idle",
            "running": False,
            "fake_mode": rt.fake_mode,
            "source": "default",
            "config": rt.config.summary(),
        }
    )


# ---------------------------------------------------------------------------
# Tool 2：一次性播报
# ---------------------------------------------------------------------------
@tool(
    name="voice_speak",
    description="把一段文本合成为语音并立即播放（一次性 TTS，不经过唤醒与 ASR）。",
    parameters={
        "text": {"type": "string", "description": "要播报的文本，不能为空。"},
        "fake": _FAKE_PARAM,
    },
    required=["text"],
    emoji="🔊",
)
def voice_speak(text: str, fake: bool = False) -> str:
    """TTS 合成 + 播放，返回已播报文本与音频字节数。"""
    try:
        if not text or not text.strip():
            raise ValueError("text 不能为空")
        rt = _runtime
        comps = _components(rt, fake)
        pcm = comps["tts"].synthesize(text)
        tts_sr = getattr(comps["tts"], "sample_rate", rt.config.sample_rate)
        comps["player"].play(pcm, tts_sr)
        return _ok({"spoken": text, "pcm_bytes": len(pcm)})
    except Exception as exc:  # noqa: BLE001 - 统一映射为 ok:false
        logger.debug("voice_speak 失败: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 3：一次性监听
# ---------------------------------------------------------------------------
@tool(
    name="voice_listen_once",
    description=(
        "一次性语音交互：录音直到 VAD 判定静音（或超时），ASR 转写后发给 LLM Agent，"
        "可选把回复语音播报。返回 transcript/reply/spoken。"
        "若常驻管道正在运行，会先暂停管道、结束后再恢复。"
    ),
    parameters={
        "timeout_s": {
            "type": "number",
            "description": "最长录音秒数，默认 10，必须 > 0。",
        },
        "speak": {
            "type": "boolean",
            "description": "是否把 Agent 回复语音播报，默认 true。",
        },
        "fake": _FAKE_PARAM,
    },
    emoji="👂",
)
def voice_listen_once(timeout_s: float = 10.0, speak: bool = True, fake: bool = False) -> str:
    """录一段语音 → 转写 → 对话 →（可选）播报。"""
    try:
        if timeout_s <= 0:
            raise ValueError("timeout_s 必须 > 0")
        rt = _runtime
        comps = _components(rt, fake)
        pipeline = rt.pipeline
        was_running = pipeline is not None and pipeline.is_running
        if was_running:
            pipeline.pause()
        source = _new_audio_source(rt, fake)
        try:
            pcm = _record_utterance(source, comps["vad"], rt.config, timeout_s)
        finally:
            if was_running:
                pipeline.resume()
        transcript = comps["asr"].transcribe(pcm, rt.config.sample_rate, language=None)
        if not transcript or not transcript.strip():
            return _ok({"transcript": "", "reply": "", "spoken": False})
        reply = comps["agent"].chat(transcript)
        spoken = False
        if speak and reply:
            speech = comps["tts"].synthesize(reply)
            tts_sr = getattr(comps["tts"], "sample_rate", rt.config.sample_rate)
            comps["player"].play(speech, tts_sr)
            spoken = True
        return _ok({"transcript": transcript, "reply": reply, "spoken": spoken})
    except Exception as exc:  # noqa: BLE001
        logger.debug("voice_listen_once 失败: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 4/5：常驻管道生命周期
# ---------------------------------------------------------------------------
@tool(
    name="voice_pipeline_start",
    description=(
        "启动常驻语音管道：后台线程循环 等待唤醒词 → 录音 → ASR → LLM Agent → TTS 播报。"
        "事件（voice.wake_detected/voice.transcript/voice.reply/voice.error）"
        "发布到插件上下文的事件总线（若已接入）。重复启动返回错误。"
    ),
    parameters={"fake": _FAKE_PARAM},
    emoji="🚀",
)
def voice_pipeline_start(fake: bool = False) -> str:
    """构建并启动 VoicePipeline 后台线程。"""
    try:
        rt = _runtime
        if rt.pipeline is not None and rt.pipeline.is_running:
            raise PipelineStateError("语音管道已在运行")
        comps = _components(rt, fake)
        pipeline = VoicePipeline(
            config=rt.config,
            audio_source=_new_audio_source(rt, fake),
            wake_word=comps["wake"],
            vad=comps["vad"],
            asr=comps["asr"],
            tts=comps["tts"],
            agent=comps["agent"],
            player=comps["player"],
            event_publisher=rt.event_publisher,
            # M5.4：每次状态迁移写共享状态文件，供宿主外进程观察
            state_writer=PipelineStateWriter(fake_mode=rt.fake_mode),
        )
        entered = pipeline.start()
        rt.pipeline = pipeline
        return _ok({"state": entered.value, "running": True})
    except Exception as exc:  # noqa: BLE001
        logger.debug("voice_pipeline_start 失败: %s", exc)
        return _err(str(exc))


@tool(
    name="voice_pipeline_stop",
    description="停止常驻语音管道（幂等）：回收后台线程并释放音频资源。",
    parameters={},
    emoji="🛑",
)
def voice_pipeline_stop() -> str:
    """停止管道并清空引用；未启动时同样返回成功。"""
    rt = _runtime
    if rt.pipeline is not None:
        rt.pipeline.stop()
        rt.pipeline = None
    return _ok({"state": "idle", "running": False})


# ---------------------------------------------------------------------------
# Tool 6：配置读写
# ---------------------------------------------------------------------------
@tool(
    name="voice_config",
    description=(
        "语音配置读写：action=get 返回完整配置摘要；action=set 修改运行时可调项"
        "（wake_threshold/vad_threshold/vad_silence_ms/max_record_s/tts_voice/"
        "system_prompt/llm_model/llm_endpoint/tts_muted），原地生效、立即被运行中的管道感知。"
    ),
    parameters={
        "action": {
            "type": "string",
            "enum": ["get", "set"],
            "description": "操作类型，默认 get。",
        },
        "key": {
            "type": "string",
            "description": "配置项名（action=set 时必需，且必须在可调项名单内）。",
        },
        "value": {
            "type": "string",
            "description": "新值（数值型会自动做类型转换与区间校验）。",
        },
    },
    emoji="⚙️",
)
def voice_config(action: str = "get", key: str | None = None, value: Any = None) -> str:
    """get 返回配置摘要；set 校验后原地修改运行时可调项。"""
    try:
        rt = _runtime
        if action == "get":
            return _ok(rt.config.summary())
        if action == "set":
            if not key:
                raise ValueError("action=set 时 key 必需")
            if key not in RUNTIME_SETTABLE:
                raise ValueError(
                    f"配置项 {key} 不支持运行时修改（可调: {', '.join(RUNTIME_SETTABLE)}）"
                )
            # 先构造候选配置（复用 from_dict 的强转与校验），再原地拷贝字段：
            # 运行中的管道持有同一 config 对象，可立即感知变更。
            candidate = VoiceConfig.from_dict({**rt.config.summary(), key: value})
            for field in dataclasses.fields(VoiceConfig):
                setattr(rt.config, field.name, getattr(candidate, field.name))
            return _ok({"key": key, "value": getattr(rt.config, key)})
        raise ValueError(f"未知 action: {action}")
    except Exception as exc:  # noqa: BLE001
        logger.debug("voice_config 失败: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 7：打断当前播报（M7.5 控制文件反向通道）
# ---------------------------------------------------------------------------
@tool(
    name="voice_interrupt",
    description=(
        "打断当前语音播报：写控制文件（与 HUD/CLI 等外部进程同一条反向通道），"
        "常驻管道 ≤50ms 内消费——停止当前 TTS 播放、状态迁回 wake_listening、"
        "发布 voice.interrupted 事件。无播报中状态仅消费指令不动作。"
    ),
    parameters={},
    emoji="⏹️",
)
def voice_interrupt() -> str:
    """写一条 interrupt 控制指令，返回已写入的指令序号。

    host 内调用与外部文件通道同语义：管道侧不区分指令来源，
    统一走控制文件消费路径。
    """
    try:
        cf = VoiceControlFile()
        cf.interrupt()
        return _ok({"interrupted": True, "seq": cf.last_seq})
    except Exception as exc:  # noqa: BLE001 - 统一映射为 ok:false
        logger.debug("voice_interrupt 失败: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 8：获取助手身份信息
# ---------------------------------------------------------------------------
@tool(
    name="voice_identity",
    description="获取助手身份信息（名字、唤醒词、人设等）",
    parameters={},
    emoji="🎙️",
)
def voice_identity() -> str:
    """返回助手身份信息（供 Rust IPC 调用）。"""
    try:
        identity = get_identity()
        return _ok(identity.to_dict())
    except Exception as exc:  # noqa: BLE001
        logger.debug("voice_identity 失败: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# 注册（对齐 WeBrain 插件契约：ctx.register_tool + 可选事件总线接入）
# ---------------------------------------------------------------------------
def _make_handler(func: Callable) -> Callable:
    """把工具函数适配为 registry handler：``(args: dict, **kw) -> JSON 字符串``。"""

    def handler(args: dict[str, Any], **_: Any) -> str:
        try:
            return func(**(args or {}))
        except Exception as exc:  # 参数错误等，统一为 ok:false
            logger.debug("voice tool %s 调用失败: %s", getattr(func, "__name__", "?"), exc)
            return _err(str(exc))

    return handler


def register(ctx) -> None:
    """把 6 个 voice_* tools 注册到插件上下文；若 ctx 携带事件总线则接入。"""
    for meta in TOOLS:
        ctx.register_tool(
            name=meta["name"],
            toolset="omni_voice",
            schema=meta["schema"],
            handler=_make_handler(meta["handler_func"]),
            description=meta["description"],
            emoji=meta["emoji"],
        )
    bus = getattr(ctx, "event_bus", None)
    if bus is not None and callable(getattr(bus, "publish", None)):
        _runtime.event_publisher = bus
    logger.info("omni_voice 插件已注册 %d 个 tools", len(TOOLS))
