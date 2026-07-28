"""omni_voice 端到端集成测试（全 fake，无硬件/模型/网络依赖）。

链路：register(ctx) → handler 启动常驻管道 → 唤醒走完整一轮
（录音→ASR→Agent→TTS，事件上总线）→ 管道运行中穿插 listen_once →
config 运行时调参 → speak → status → stop，验证各工具协同一致。
"""

from __future__ import annotations

import json
import time

import pytest

from omni_voice import register, tools
from omni_voice.agent_bridge import FakeAgentBridge
from omni_voice.backends.fakes import FakeASR, FakePlayer, FakeTTS, FakeVAD, FakeWakeWord


class _EventBus:
    """进程内事件总线 fake。"""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def publish(self, event_type, payload):
        self.events.append((event_type, payload))

    def types(self) -> list[str]:
        return [t for t, _ in self.events]

    def payloads(self, event_type: str) -> list[dict]:
        return [p for t, p in self.events if t == event_type]


class _Ctx:
    """插件上下文 fake：register_tool 收集 + 事件总线。"""

    def __init__(self):
        self.tools: dict[str, dict] = {}
        self.event_bus = _EventBus()

    def register_tool(self, **kwargs):
        self.tools[kwargs["name"]] = kwargs

    def call(self, name: str, args: dict | None = None) -> dict:
        """模拟宿主调用工具 handler，返回解析后的 JSON。"""
        return json.loads(self.tools[name]["handler"](args or {}))


def _wait_until(cond, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture()
def ctx():
    """重置运行时并注册插件，返回上下文；结束后回收管道。"""
    rt = tools._reset_runtime()
    context = _Ctx()
    register(context)
    yield context
    if rt.pipeline is not None:
        rt.pipeline.stop()
        rt.pipeline = None


class TestVoiceEndToEnd:
    def test_full_voice_interaction_lifecycle(self, ctx):
        rt = tools._runtime
        silence = rt.config.vad_silence_ms // rt.config.frame_ms
        rt.config.follow_up_timeout_s = 0  # 续听窗口立即超时回 WAKE_LISTENING，避免消耗 listen_once 的 VAD 脚本

        # -- 预置脚本化 fake 组件：两轮交互（常驻管道一轮 + listen_once 一轮）
        comps = {
            "wake": FakeWakeWord(confidences=[0.92]),
            "vad": FakeVAD(
                results=(
                    [True, True] + [False] * (silence + 5)  # 管道一轮
                    + [True] * 3 + [False] * (silence + 5)  # listen_once 一轮
                )
            ),
            "asr": FakeASR(transcripts=["Omni 你好", "现在几点了？"]),
            "tts": FakeTTS(),
            "player": FakePlayer(),
            "agent": FakeAgentBridge(replies=["你好！我在。", "我无法看表，但一直在你身边。"]),
        }
        rt.components = comps

        # -- 1. status：未启动
        status = ctx.call("voice_status")
        assert status["ok"] and status["data"]["state"] == "idle"

        # -- 2. 启动常驻管道（fake）
        started = ctx.call("voice_pipeline_start", {"fake": True})
        assert started["ok"] and started["data"]["state"] == "wake_listening"

        # -- 3. 唤醒触发完整一轮：事件按序上总线
        assert comps["tts"].synthesized.wait(timeout=5), "第一轮 TTS 未完成"
        assert _wait_until(lambda: "voice.reply" in ctx.event_bus.types())
        transcript_texts = [p["text"] for p in ctx.event_bus.payloads("voice.transcript")]
        assert "Omni 你好" in transcript_texts
        assert comps["agent"].messages[0] == "Omni 你好"
        assert comps["tts"].texts[0] == "我在", "首条 TTS 是唤醒应答"
        assert comps["tts"].texts[1] == "你好！我在。", "第二条 TTS 是 Agent 回复"

        # -- 4. 管道运行中穿插 listen_once（自动暂停/恢复管道）
        listened = ctx.call("voice_listen_once", {"fake": True, "timeout_s": 5})
        assert listened["ok"]
        assert listened["data"]["transcript"] == "现在几点了？"
        assert listened["data"]["reply"] == "我无法看表，但一直在你身边。"
        assert listened["data"]["spoken"] is True
        assert rt.pipeline.is_running  # 管道未被 listen_once 破坏

        # -- 5. 运行时调参并确认原地生效
        adjusted = ctx.call(
            "voice_config", {"action": "set", "key": "wake_threshold", "value": "0.8"}
        )
        assert adjusted["ok"]
        assert rt.config.wake_threshold == pytest.approx(0.8)
        assert rt.pipeline._config is rt.config  # 管道立即感知

        # -- 6. 一次性播报
        spoken = ctx.call("voice_speak", {"text": "集成测试播报", "fake": True})
        assert spoken["ok"] and spoken["data"]["spoken"] == "集成测试播报"
        assert comps["tts"].texts[-1] == "集成测试播报"

        # -- 7. status：运行中
        status = ctx.call("voice_status")
        assert status["data"]["running"] is True
        assert status["data"]["fake_mode"] is True

        # -- 8. 停止管道，状态归零
        stopped = ctx.call("voice_pipeline_stop")
        assert stopped["ok"] and stopped["data"]["running"] is False
        final = ctx.call("voice_status")
        assert final["data"]["state"] == "idle"
        assert final["data"]["running"] is False

        # -- 9. 事件序列完整性：唤醒/两轮转写/回复，无错误事件
        types = ctx.event_bus.types()
        assert "voice.wake_detected" in types
        assert "voice.error" not in types
        assert len(comps["player"].played) >= 2  # 管道一轮 + listen_once 一轮

    def test_error_event_when_asr_fails(self, ctx):
        """ASR 抛错：管道发布 voice.error 并恢复等待唤醒，不崩溃。"""
        from omni_voice.errors import VoiceError

        rt = tools._runtime
        silence = rt.config.vad_silence_ms // rt.config.frame_ms
        rt.components = {
            "wake": FakeWakeWord(confidences=[0.9]),
            "vad": FakeVAD(results=[True] + [False] * (silence + 5)),
            "asr": FakeASR(error=VoiceError("模拟 ASR 故障")),
            "tts": FakeTTS(),
            "player": FakePlayer(),
            "agent": FakeAgentBridge(),
        }
        started = ctx.call("voice_pipeline_start", {"fake": True})
        assert started["ok"]

        assert _wait_until(lambda: "voice.error" in ctx.event_bus.types())
        errors = ctx.event_bus.payloads("voice.error")
        assert "模拟 ASR 故障" in errors[0]["error"]
        # 管道从错误中恢复，仍在运行
        assert rt.pipeline.is_running
        stopped = ctx.call("voice_pipeline_stop")
        assert stopped["ok"]
