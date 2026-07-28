"""omni_voice tools 层测试：6 个 voice_* 工具与 register(ctx) 插件契约。

全部通过 fake 后端驱动，不依赖音频硬件、模型或网络；
每个测试用 ``_reset_runtime()`` 隔离进程内运行时单例。
"""

from __future__ import annotations

import dataclasses
import json
import time

import pytest

from omni_voice import tools
from omni_voice.agent_bridge import FakeAgentBridge
from omni_voice.backends.fakes import FakeASR, FakePlayer, FakeTTS, FakeVAD, FakeWakeWord
from omni_voice.config import RUNTIME_SETTABLE, VoiceConfig
from omni_voice.errors import VoiceBackendError
from omni_voice.pipeline import PipelineState
from omni_voice.state_file import VoiceStateFile


def _parse(result: str) -> dict:
    """工具返回的是 JSON 字符串，解析为 dict。"""
    assert isinstance(result, str)
    return json.loads(result)


def _scripted_components(
    cfg: VoiceConfig,
    *,
    wake: FakeWakeWord | None = None,
    vad: FakeVAD | None = None,
    asr: FakeASR | None = None,
    agent: FakeAgentBridge | None = None,
):
    """组装一套可编程 fake 组件（不含音频帧源，帧源由运行时按脚本创建）。"""
    return {
        "wake": wake or FakeWakeWord(),
        "vad": vad or FakeVAD(),
        "asr": asr or FakeASR(),
        "tts": FakeTTS(),
        "player": FakePlayer(),
        "agent": agent or FakeAgentBridge(),
    }


@pytest.fixture(autouse=True)
def fresh_runtime():
    """每个测试前重置运行时单例，结束后回收管道线程。"""
    rt = tools._reset_runtime()
    yield rt
    if rt.pipeline is not None:
        rt.pipeline.stop()
        rt.pipeline = None


class _FakeEventBus:
    """事件总线 fake：满足 publish(event_type, payload) 鸭子类型。"""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def publish(self, event_type, payload):
        self.events.append((event_type, payload))

    def types(self) -> list[str]:
        return [t for t, _ in self.events]


class _FakeCtx:
    """插件上下文 fake：收集 register_tool 调用，可选携带事件总线。"""

    def __init__(self, with_bus: bool = False):
        self.tools: list[dict] = []
        self.event_bus = _FakeEventBus() if with_bus else None

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)


def _wait_until(cond, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.005)
    return False


# ---------------------------------------------------------------------------
# voice_status
# ---------------------------------------------------------------------------
class TestVoiceStatus:
    def test_initial_status(self, fresh_runtime):
        result = _parse(tools.voice_status())
        assert result["ok"] is True
        data = result["data"]
        assert data["state"] == "idle"
        assert data["running"] is False
        assert data["fake_mode"] is False
        assert data["config"]["sample_rate"] == 16000
        assert data["config"]["wake_word"] == "hey_omni"

    def test_status_reflects_running_pipeline(self, fresh_runtime):
        rt = fresh_runtime
        rt.components = _scripted_components(rt.config)
        _parse(tools.voice_pipeline_start(fake=True))
        result = _parse(tools.voice_status())
        assert result["data"]["running"] is True
        assert result["data"]["state"] == "wake_listening"
        assert result["data"]["fake_mode"] is True


class TestVoiceStatusStateFileFallback:
    """voice_status 状态文件回退（M5.4）：进程内无管道时，经共享状态文件观察宿主管道。

    宿主管道存活 → 进程内状态优先；宿主外进程（CLI/HUD 轮询）→ 读状态文件。
    """

    def test_pipeline_none_falls_back_to_state_file(self, fresh_runtime):
        VoiceStateFile().write("speaking", running=True, fake_mode=True)
        result = _parse(tools.voice_status())
        data = result["data"]
        assert result["ok"] is True
        assert data["state"] == "speaking"
        assert data["running"] is True
        assert data["fake_mode"] is True
        assert data["source"] == "state_file"
        assert data["config"]["sample_rate"] == 16000  # 配置摘要仍由本进程给出

    def test_process_pipeline_wins_over_state_file(self, fresh_runtime):
        rt = fresh_runtime
        rt.components = _scripted_components(rt.config)
        # 文件里残留旧状态 speaking，进程内管道活着时必须优先进程内
        VoiceStateFile().write("speaking", running=True, fake_mode=False)
        _parse(tools.voice_pipeline_start(fake=True))
        result = _parse(tools.voice_status())
        assert result["data"]["state"] == "wake_listening"
        assert result["data"]["source"] == "process"

    def test_no_pipeline_no_file_is_default_idle(self, fresh_runtime):
        result = _parse(tools.voice_status())
        data = result["data"]
        assert data["state"] == "idle"
        assert data["running"] is False
        assert data["fake_mode"] is False
        assert data["source"] == "default"

    def test_corrupt_state_file_degrades_to_default(self, fresh_runtime):
        path = VoiceStateFile.DEFAULT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json {{{", encoding="utf-8")
        result = _parse(tools.voice_status())
        assert result["data"]["state"] == "idle"
        assert result["data"]["source"] == "default"

    def test_state_file_reply_is_passed_through(self, fresh_runtime):
        """M6.3：状态文件含 reply（SPEAKING 快照）时，工具输出透传 reply 字段。

        Tauri 事件 listen 失败退化为纯轮询时，前端依赖该字段做 speakText 联动。
        """
        VoiceStateFile().write("speaking", running=True, fake_mode=True, reply="你好，我是 Omni")
        result = _parse(tools.voice_status())
        data = result["data"]
        assert data["source"] == "state_file"
        assert data["state"] == "speaking"
        assert data["reply"] == "你好，我是 Omni"

    def test_state_file_reply_seq_is_passed_through(self, fresh_runtime):
        """M6.3 修复：状态文件含 reply_seq（轮次序号）时透传——CLI 轮询兜底通道
        与 watcher 推送通道共用同一去重键空间，跨通道不会重复播报。"""
        VoiceStateFile().write("speaking", running=True, fake_mode=True, reply="你好")
        result = _parse(tools.voice_status())
        data = result["data"]
        assert data["source"] == "state_file"
        assert data["reply"] == "你好"
        assert data["reply_seq"] == 1

    def test_state_file_without_reply_has_no_reply_key(self, fresh_runtime):
        """状态文件无 reply 键（M5.4 旧格式）时输出兼容：不报错、不带 reply。"""
        VoiceStateFile().write("wake_listening", running=True, fake_mode=False)
        result = _parse(tools.voice_status())
        data = result["data"]
        assert result["ok"] is True
        assert data["source"] == "state_file"
        assert "reply" not in data

    def test_state_file_non_string_reply_is_dropped(self, fresh_runtime):
        """状态文件 reply 为非字符串时容错：不带出 reply，其余字段照常。"""
        path = VoiceStateFile.DEFAULT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "state": "speaking",
                    "running": True,
                    "fake_mode": False,
                    "ts": time.time(),
                    "reply": 12345,
                }
            ),
            encoding="utf-8",
        )
        result = _parse(tools.voice_status())
        data = result["data"]
        assert result["ok"] is True
        assert data["source"] == "state_file"
        assert data["state"] == "speaking"
        assert "reply" not in data

    def test_pipeline_stop_writes_idle_then_fallback_reports_it(self, fresh_runtime):
        """宿主 stop 后文件落 idle/running=False，外部进程 status 如实观察到。"""
        rt = fresh_runtime
        rt.components = _scripted_components(rt.config)
        _parse(tools.voice_pipeline_start(fake=True))
        _parse(tools.voice_pipeline_stop())
        observed = VoiceStateFile.read()
        assert observed is not None
        assert observed["state"] == "idle"
        assert observed["running"] is False
        result = _parse(tools.voice_status())
        assert result["data"]["state"] == "idle"
        assert result["data"]["running"] is False
        assert result["data"]["source"] == "state_file"


# ---------------------------------------------------------------------------
# voice_config
# ---------------------------------------------------------------------------
class TestVoiceConfig:
    def test_get_returns_summary(self, fresh_runtime):
        result = _parse(tools.voice_config(action="get"))
        assert result["ok"] is True
        assert result["data"]["vad_silence_ms"] == 1200

    def test_get_is_default_action(self, fresh_runtime):
        result = _parse(tools.voice_config())
        assert result["ok"] is True
        assert "llm_model" in result["data"]

    def test_set_valid_field_mutates_in_place(self, fresh_runtime):
        rt = fresh_runtime
        original = rt.config
        result = _parse(tools.voice_config(action="set", key="wake_threshold", value="0.9"))
        assert result["ok"] is True
        assert result["data"]["key"] == "wake_threshold"
        assert result["data"]["value"] == pytest.approx(0.9)
        # 原地修改：运行中的管道持有同一 config 对象即可感知
        assert rt.config is original
        assert rt.config.wake_threshold == pytest.approx(0.9)

    def test_set_all_runtime_settable_fields(self, fresh_runtime):
        values = {
            "wake_threshold": "0.7",
            "vad_threshold": "0.6",
            "vad_silence_ms": "800",
            "max_record_s": "15",
            "tts_voice": "zf_xiaoyi",
            "system_prompt": "新提示词",
            "llm_model": "qwen3",
            "llm_endpoint": "http://localhost:4000/v1",
        }
        for key, value in values.items():
            assert key in RUNTIME_SETTABLE
            result = _parse(tools.voice_config(action="set", key=key, value=value))
            assert result["ok"] is True, key
        cfg = fresh_runtime.config
        assert cfg.vad_silence_ms == 800
        assert cfg.max_record_s == pytest.approx(15.0)
        assert cfg.system_prompt == "新提示词"

    def test_set_non_settable_field_rejected(self, fresh_runtime):
        result = _parse(tools.voice_config(action="set", key="sample_rate", value="8000"))
        assert result["ok"] is False
        assert "sample_rate" in result["error"]

    def test_set_tts_muted_via_existing_tool(self, fresh_runtime):
        """M6.3：tts_muted 复用既有 voice_config 工具即可设置（不新增 tool）。"""
        rt = fresh_runtime
        assert rt.config.tts_muted is False
        result = _parse(tools.voice_config(action="set", key="tts_muted", value="true"))
        assert result["ok"] is True
        assert result["data"]["key"] == "tts_muted"
        assert result["data"]["value"] is True
        assert rt.config.tts_muted is True
        # 非法布尔值被拒绝且不污染配置
        bad = _parse(tools.voice_config(action="set", key="tts_muted", value="maybe"))
        assert bad["ok"] is False
        assert rt.config.tts_muted is True

    def test_set_without_key_rejected(self, fresh_runtime):
        result = _parse(tools.voice_config(action="set", value="0.9"))
        assert result["ok"] is False

    def test_set_invalid_value_rejected_and_config_unchanged(self, fresh_runtime):
        rt = fresh_runtime
        result = _parse(tools.voice_config(action="set", key="wake_threshold", value="2.0"))
        assert result["ok"] is False
        assert rt.config.wake_threshold == pytest.approx(0.5)  # 未被污染

    def test_unknown_action_rejected(self, fresh_runtime):
        result = _parse(tools.voice_config(action="delete"))
        assert result["ok"] is False
        assert "delete" in result["error"]


# ---------------------------------------------------------------------------
# voice_speak
# ---------------------------------------------------------------------------
class TestVoiceSpeak:
    def test_speak_fake(self, fresh_runtime):
        rt = fresh_runtime
        comps = _scripted_components(rt.config)
        rt.components = comps
        result = _parse(tools.voice_speak("你好，世界", fake=True))
        assert result["ok"] is True
        assert result["data"]["spoken"] == "你好，世界"
        assert result["data"]["pcm_bytes"] > 0
        assert comps["tts"].texts == ["你好，世界"]
        assert len(comps["player"].played) == 1

    def test_speak_empty_text_rejected(self, fresh_runtime):
        result = _parse(tools.voice_speak("   ", fake=True))
        assert result["ok"] is False
        assert "text" in result["error"]

    def test_speak_backend_error_mapped(self, fresh_runtime, monkeypatch):
        def _boom(config):
            raise VoiceBackendError("TTS 网关不可达（http://localhost:18789/v1）")

        monkeypatch.setattr(tools, "_build_real_components", _boom)
        result = _parse(tools.voice_speak("你好"))
        assert result["ok"] is False
        assert "网关" in result["error"]


# ---------------------------------------------------------------------------
# voice_listen_once
# ---------------------------------------------------------------------------
class TestVoiceListenOnce:
    def _setup(self, rt, *, asr_text="你好 Omni", replies=None):
        silence = rt.config.vad_silence_ms // rt.config.frame_ms  # 20 帧
        comps = _scripted_components(
            rt.config,
            vad=FakeVAD(results=[True, True, True] + [False] * (silence + 5)),
            asr=FakeASR(transcripts=[asr_text]),
            agent=FakeAgentBridge(replies=replies or ["收到，你好！"]),
        )
        rt.components = comps
        return comps

    def test_listen_once_happy_path(self, fresh_runtime):
        rt = fresh_runtime
        comps = self._setup(rt)
        result = _parse(tools.voice_listen_once(fake=True))
        assert result["ok"] is True
        data = result["data"]
        assert data["transcript"] == "你好 Omni"
        assert data["reply"] == "收到，你好！"
        assert data["spoken"] is True
        assert comps["agent"].messages == ["你好 Omni"]
        assert comps["tts"].texts == ["收到，你好！"]
        assert len(comps["player"].played) == 1

    def test_listen_once_no_speak(self, fresh_runtime):
        rt = fresh_runtime
        comps = self._setup(rt)
        result = _parse(tools.voice_listen_once(speak=False, fake=True))
        assert result["data"]["spoken"] is False
        assert comps["tts"].texts == []

    def test_listen_once_empty_transcript_skips_agent_and_tts(self, fresh_runtime):
        rt = fresh_runtime
        comps = self._setup(rt, asr_text="")
        result = _parse(tools.voice_listen_once(fake=True))
        data = result["data"]
        assert data["transcript"] == ""
        assert data["reply"] == ""
        assert data["spoken"] is False
        assert comps["agent"].messages == []
        assert comps["tts"].texts == []

    def test_listen_once_timeout_bounds_recording(self, fresh_runtime):
        rt = fresh_runtime
        comps = _scripted_components(
            rt.config,
            vad=FakeVAD(default=True),  # 全程语音，只能靠超时退出
            asr=FakeASR(transcripts=["超时"]),
        )
        rt.components = comps
        start = time.monotonic()
        result = _parse(tools.voice_listen_once(timeout_s=0.1, fake=True))
        elapsed = time.monotonic() - start
        assert result["ok"] is True
        assert elapsed < 2.0
        assert result["data"]["transcript"] == "超时"

    def test_listen_once_invalid_timeout_rejected(self, fresh_runtime):
        result = _parse(tools.voice_listen_once(timeout_s=0, fake=True))
        assert result["ok"] is False

    def test_listen_once_pauses_and_resumes_pipeline(self, fresh_runtime):
        rt = fresh_runtime
        comps = self._setup(rt)
        _parse(tools.voice_pipeline_start(fake=True))
        assert rt.pipeline.is_running

        result = _parse(tools.voice_listen_once(fake=True))
        assert result["data"]["transcript"] == "你好 Omni"
        # 管道仍然存活，listen_once 结束后恢复帧消费
        assert rt.pipeline.is_running
        assert _wait_until(lambda: rt.pipeline.state == PipelineState.WAKE_LISTENING)


# ---------------------------------------------------------------------------
# voice_pipeline_start / voice_pipeline_stop
# ---------------------------------------------------------------------------
class TestVoicePipelineLifecycle:
    def test_start_and_stop_fake(self, fresh_runtime):
        rt = fresh_runtime
        rt.components = _scripted_components(rt.config)
        started = _parse(tools.voice_pipeline_start(fake=True))
        assert started["ok"] is True
        assert started["data"]["running"] is True
        assert started["data"]["state"] == "wake_listening"
        assert rt.pipeline is not None and rt.pipeline.is_running

        stopped = _parse(tools.voice_pipeline_stop())
        assert stopped["ok"] is True
        assert stopped["data"]["running"] is False
        assert rt.pipeline is None

    def test_double_start_rejected(self, fresh_runtime):
        rt = fresh_runtime
        rt.components = _scripted_components(rt.config)
        _parse(tools.voice_pipeline_start(fake=True))
        again = _parse(tools.voice_pipeline_start(fake=True))
        assert again["ok"] is False
        assert "运行" in again["error"]

    def test_stop_without_start_is_ok(self, fresh_runtime):
        result = _parse(tools.voice_pipeline_stop())
        assert result["ok"] is True
        assert result["data"]["state"] == "idle"

    def test_full_cycle_publishes_events(self, fresh_runtime):
        rt = fresh_runtime
        bus = _FakeEventBus()
        rt.event_publisher = bus
        silence = rt.config.vad_silence_ms // rt.config.frame_ms
        frame = rt.config.frame_bytes
        rt.fake_audio_frames = [b"\x01" * frame] * 3 + [b"\x00" * frame] * (silence + 5)
        comps = _scripted_components(
            rt.config,
            wake=FakeWakeWord(confidences=[0.95]),
            vad=FakeVAD(results=[True, True] + [False] * (silence + 5)),
            asr=FakeASR(transcripts=["端到端"]),
            agent=FakeAgentBridge(replies=["链路通了"]),
        )
        rt.components = comps
        _parse(tools.voice_pipeline_start(fake=True))
        assert _wait_until(lambda: "voice.reply" in bus.types(), timeout=5)

        types = bus.types()
        assert "voice.wake_detected" in types
        assert "voice.transcript" in types
        assert "voice.reply" in types
        assert comps["agent"].messages == ["端到端"]
        assert comps["tts"].texts[-1] == "链路通了"

    def test_start_backend_error_mapped(self, fresh_runtime, monkeypatch):
        def _boom(config):
            raise VoiceBackendError("音频采集需要 sounddevice")

        monkeypatch.setattr(tools, "_build_real_components", _boom)
        result = _parse(tools.voice_pipeline_start())
        assert result["ok"] is False
        assert "sounddevice" in result["error"]
        assert fresh_runtime.pipeline is None


# ---------------------------------------------------------------------------
# voice_interrupt（M7.5：控制文件打断通道，host 内调用与外部进程同语义）
# ---------------------------------------------------------------------------
class TestVoiceInterrupt:
    def test_interrupt_returns_ok_json_with_seq(self, fresh_runtime):
        result = _parse(tools.voice_interrupt())
        assert result["ok"] is True
        assert result["data"]["interrupted"] is True
        assert result["data"]["seq"] == 1  # conftest 隔离的 tmp 默认路径，全新从 1 起

    def test_interrupt_seq_increments_across_calls(self, fresh_runtime):
        first = _parse(tools.voice_interrupt())
        second = _parse(tools.voice_interrupt())
        assert first["data"]["seq"] == 1
        assert second["data"]["seq"] == 2

    def test_interrupt_writes_control_file_readable(self, fresh_runtime):
        """tool 写出的控制文件可被管道侧 read 消费（schema 一致）。"""
        from omni_voice.control_file import VoiceControlFile

        _parse(tools.voice_interrupt())
        data = VoiceControlFile.read()
        assert data is not None
        assert data["action"] == "interrupt"
        assert data["seq"] == 1

    def test_registered_handler_no_args(self, fresh_runtime):
        """经 ctx 注册的 handler 无参数调用同样返回 ok:true JSON。"""
        ctx = _FakeCtx()
        tools.register(ctx)
        handler = {t["name"]: t["handler"] for t in ctx.tools}["voice_interrupt"]
        parsed = json.loads(handler({}))
        assert parsed["ok"] is True
        assert parsed["data"]["interrupted"] is True


# ---------------------------------------------------------------------------
# register(ctx) 插件契约
# ---------------------------------------------------------------------------
class TestRegister:
    EXPECTED_TOOLS = [
        "voice_status",
        "voice_speak",
        "voice_listen_once",
        "voice_pipeline_start",
        "voice_pipeline_stop",
        "voice_config",
        "voice_interrupt",
        "voice_identity",
    ]

    def test_registers_all_tools(self, fresh_runtime):
        ctx = _FakeCtx()
        tools.register(ctx)
        names = [t["name"] for t in ctx.tools]
        assert names == self.EXPECTED_TOOLS
        for t in ctx.tools:
            assert t["toolset"] == "omni_voice"
            assert t["schema"]["name"] == t["name"]
            assert callable(t["handler"])

    def test_handler_returns_json_string(self, fresh_runtime):
        ctx = _FakeCtx()
        tools.register(ctx)
        handler = {t["name"]: t["handler"] for t in ctx.tools}["voice_status"]
        result = handler({})
        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert parsed["data"]["state"] == "idle"

    def test_handler_bad_args_become_error_json(self, fresh_runtime):
        ctx = _FakeCtx()
        tools.register(ctx)
        handler = {t["name"]: t["handler"] for t in ctx.tools}["voice_speak"]
        # 缺少必需参数 text → TypeError → {"ok": false}
        parsed = json.loads(handler({}))
        assert parsed["ok"] is False

    def test_register_wires_event_bus(self, fresh_runtime):
        rt = fresh_runtime
        ctx = _FakeCtx(with_bus=True)
        tools.register(ctx)
        assert rt.event_publisher is ctx.event_bus

    def test_register_without_event_bus_keeps_none(self, fresh_runtime):
        rt = fresh_runtime
        tools.register(_FakeCtx())
        assert rt.event_publisher is None

    def test_registered_tools_drive_full_cycle(self, fresh_runtime):
        """通过 ctx 注册的 handler 完整走一遍：start → 事件 → stop。"""
        rt = fresh_runtime
        ctx = _FakeCtx(with_bus=True)
        tools.register(ctx)
        handlers = {t["name"]: t["handler"] for t in ctx.tools}

        silence = rt.config.vad_silence_ms // rt.config.frame_ms
        comps = _scripted_components(
            rt.config,
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=[True] + [False] * (silence + 5)),
            asr=FakeASR(transcripts=["契约测试"]),
            agent=FakeAgentBridge(replies=["契约通过"]),
        )
        rt.components = comps
        started = json.loads(handlers["voice_pipeline_start"]({"fake": True}))
        assert started["ok"] is True
        assert _wait_until(lambda: "voice.reply" in ctx.event_bus.types(), timeout=5)

        stopped = json.loads(handlers["voice_pipeline_stop"]({}))
        assert stopped["ok"] is True


# ---------------------------------------------------------------------------
# Runtime 组件构建
# ---------------------------------------------------------------------------
class TestComponentBuilding:
    def test_fake_components_cached_and_shared(self, fresh_runtime):
        rt = fresh_runtime
        first = tools._components(rt, fake=True)
        second = tools._components(rt, fake=True)
        assert first is second  # 缓存复用，脚本化状态可跨工具延续
        assert rt.fake_mode is True

    def test_preset_components_take_precedence(self, fresh_runtime):
        rt = fresh_runtime
        preset = _scripted_components(rt.config)
        rt.components = preset
        assert tools._components(rt, fake=True) is preset

    def test_real_components_built_without_hardware_until_use(
        self, fresh_runtime, monkeypatch
    ):
        """真实组件构建走 _build_real_components；此处替换为哨兵避免触硬件。"""
        sentinel = {"vad": object()}

        def _spy(config):
            _spy.config = config
            return sentinel

        monkeypatch.setattr(tools, "_build_real_components", _spy)
        rt = fresh_runtime
        assert tools._components(rt, fake=False) is sentinel
        assert _spy.config is rt.config
        assert rt.fake_mode is False


# ---------------------------------------------------------------------------
# voice_identity 工具测试
# ---------------------------------------------------------------------------
class TestVoiceIdentity:
    def test_identity_returns_ok_with_data(self, fresh_runtime):
        """voice_identity 返回 ok: true 和完整身份信息。"""
        result = _parse(tools.voice_identity())
        assert result["ok"] is True
        data = result["data"]
        assert data["display_name"] == "雪莉"
        assert data["english_name"] == "Sherry"
        assert "雪莉" in data["wake_aliases"]
        assert "sherry" in data["wake_aliases"]
        assert data["wake_response"] == "我在"
        assert "雪莉" in data["system_prompt"]
        assert data["idle_label"] == "雪莉 · 待命"

    def test_identity_data_matches_get_identity(self, fresh_runtime):
        """voice_identity 返回的数据与 get_identity().to_dict() 一致。"""
        from omni_sdk.identity import get_identity
        expected = get_identity().to_dict()
        result = _parse(tools.voice_identity())
        assert result["ok"] is True
        assert result["data"] == expected
