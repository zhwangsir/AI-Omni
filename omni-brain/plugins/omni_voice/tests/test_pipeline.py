"""VoicePipeline 状态机测试：全路径、截断、回退、异常恢复、线程控制、打断消费。"""

from __future__ import annotations

import threading
import time

import pytest

from omni_voice.agent_bridge import FakeAgentBridge
from omni_voice.audio import FakeAudioSource
from omni_voice.backends.fakes import FakeASR, FakePlayer, FakeTTS, FakeVAD, FakeWakeWord
from omni_voice.config import VoiceConfig
from omni_voice.control_file import VoiceControlFile
from omni_voice.errors import PipelineStateError, VoiceError
from omni_voice.pipeline import PipelineState, VoicePipeline


def _wait_until(cond, timeout: float = 5.0) -> bool:
    """轮询等待条件成立，超时返回 False。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.005)
    return False


class _EventRecorder:
    """事件发布钩子 fake：满足 publish(event_type, payload) 鸭子类型。"""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def publish(self, event_type, payload):
        self.events.append((event_type, payload))

    def types(self) -> list[str]:
        return [t for t, _ in self.events]


def _build(
    *,
    config: VoiceConfig | None = None,
    frames: list[bytes],
    wake: FakeWakeWord,
    vad: FakeVAD,
    asr: FakeASR,
    agent: FakeAgentBridge | None = None,
    publisher: _EventRecorder | None = None,
    states: list | None = None,
    state_writer=None,
    player=None,
    control_file=None,
):
    """组装全 fake 管道，返回 (pipeline, tts, player, agent)。"""
    cfg = config or VoiceConfig()
    frame = cfg.frame_bytes
    tts = FakeTTS()
    player = player if player is not None else FakePlayer()
    agent = agent or FakeAgentBridge(replies=["预设回复"])
    pipeline = VoicePipeline(
        config=cfg,
        audio_source=FakeAudioSource(frames=frames, frame_bytes=frame),
        wake_word=wake,
        vad=vad,
        asr=asr,
        tts=tts,
        agent=agent,
        player=player,
        event_publisher=publisher,
        on_state_change=(lambda old, new: states.append(new)) if states is not None else None,
        state_writer=state_writer,
        control_file=control_file,
    )
    return pipeline, tts, player, agent


def _speech_silence_frames(cfg: VoiceConfig, speech: int = 2, silence: int = 25) -> list[bytes]:
    """构造 [唤醒帧] + 语音帧 + 静音帧 的脚本化输入。"""
    frame = cfg.frame_bytes
    return [b"\x01" * frame] * (1 + speech) + [b"\x00" * frame] * silence


class TestFullPath:
    """唤醒 → 录音 → 静音截断 → ASR → Agent → TTS → 回到等待唤醒。"""

    def test_happy_path(self):
        cfg = VoiceConfig()
        states: list[PipelineState] = []
        publisher = _EventRecorder()
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms  # 37 帧 (1184ms @ 32ms)
        pipeline, tts, player, agent = _build(
            config=cfg,
            frames=_speech_silence_frames(cfg, speech=2, silence=silence_needed + 5),
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=[True, True] + [False] * (silence_needed + 5)),
            asr=FakeASR(transcripts=["你好 Omni"]),
            publisher=publisher,
            states=states,
        )
        pipeline.start()
        try:
            assert _wait_until(lambda: len(tts.texts) >= 2, timeout=5), "TTS 未合成完整两轮（唤醒应答+正式回复）"
            assert player.played_event.wait(timeout=5), "Player 未播放"
            assert _wait_until(lambda: pipeline.state == PipelineState.WAKE_LISTENING)
            observed = list(states)
        finally:
            pipeline.stop()

        assert observed[0] == PipelineState.WAKE_LISTENING
        assert observed[1:] == [
            PipelineState.RECORDING,
            PipelineState.TRANSCRIBING,
            PipelineState.THINKING,
            PipelineState.SPEAKING,
            PipelineState.FOLLOW_UP_LISTENING,
            PipelineState.WAKE_LISTENING,
        ]
        actual_frames = pipeline._asr.calls[0][0] // cfg.frame_bytes
        assert actual_frames >= 1 + 2 + (cfg.vad_silence_ms + cfg.frame_ms - 1) // cfg.frame_ms
        assert pipeline._asr.calls[0][0] == actual_frames * cfg.frame_bytes
        assert agent.messages == ["你好 Omni"]
        assert tts.texts == ["我在", "预设回复"]
        assert len(player.played) == 2
        types = publisher.types()
        assert "voice.wake_detected" in types
        assert "voice.transcript" in types
        assert "voice.reply" in types
        transcript_events = [p for t, p in publisher.events if t == "voice.transcript"]
        assert transcript_events[-1]["text"] == "你好 Omni"


class TestEmptyTranscriptFallback:
    def test_empty_transcript_back_to_wake_listening(self):
        cfg = VoiceConfig(wake_response="")
        states: list[PipelineState] = []
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms
        pipeline, tts, player, agent = _build(
            config=cfg,
            frames=_speech_silence_frames(cfg, speech=1, silence=silence_needed + 2),
            wake=FakeWakeWord(confidences=[0.8]),
            vad=FakeVAD(results=[True] + [False] * (silence_needed + 2)),
            asr=FakeASR(transcripts=["   "]),  # 空白文本
            states=states,
        )
        pipeline.start()
        try:
            assert _wait_until(
                lambda: len(pipeline._asr.calls) == 1
                and pipeline.state == PipelineState.WAKE_LISTENING
            )
            observed = list(states)  # stop() 会追加 IDLE，先快照
        finally:
            pipeline.stop()

        assert PipelineState.THINKING not in observed
        assert PipelineState.SPEAKING not in observed
        assert tts.texts == []
        assert agent.messages == []
        assert observed[-1] == PipelineState.WAKE_LISTENING


class TestMaxRecordTruncation:
    def test_max_record_s_truncates(self):
        cfg = VoiceConfig(max_record_s=0.096, vad_silence_ms=60_000, wake_response="")
        pipeline, tts, _, _ = _build(
            config=cfg,
            frames=[b"\x01" * cfg.frame_bytes] * 10,
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(default=True),
            asr=FakeASR(transcripts=["截断测试"]),
        )
        pipeline.start()
        try:
            assert tts.synthesized.wait(timeout=5)
            assert _wait_until(lambda: pipeline.state == PipelineState.WAKE_LISTENING)
        finally:
            pipeline.stop()
        assert pipeline._asr.calls[0][0] == 3 * cfg.frame_bytes


class TestExceptionRecovery:
    def test_asr_error_recovers_to_wake_listening(self):
        cfg = VoiceConfig(wake_response="")
        publisher = _EventRecorder()
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms
        pipeline, tts, _, _ = _build(
            config=cfg,
            frames=_speech_silence_frames(cfg, speech=1, silence=silence_needed + 2),
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=[True] + [False] * (silence_needed + 2)),
            asr=FakeASR(error=VoiceError("asr 炸了")),
            publisher=publisher,
        )
        pipeline.start()
        try:
            assert _wait_until(lambda: "voice.error" in publisher.types())
            assert _wait_until(lambda: pipeline.state == PipelineState.WAKE_LISTENING)
        finally:
            pipeline.stop()

        assert pipeline.is_running is False  # stop 后
        error_payload = dict(publisher.events)["voice.error"]
        assert "asr 炸了" in error_payload["error"]
        assert tts.texts == []


class TestThreadControl:
    def test_double_start_raises(self):
        cfg = VoiceConfig()
        pipeline, _, _, _ = _build(
            config=cfg,
            frames=[],
            wake=FakeWakeWord(),
            vad=FakeVAD(),
            asr=FakeASR(),
        )
        pipeline.start()
        try:
            with pytest.raises(PipelineStateError):
                pipeline.start()
        finally:
            pipeline.stop()

    def test_stop_idempotent_and_restartable(self):
        cfg = VoiceConfig()
        pipeline, _, _, _ = _build(
            config=cfg,
            frames=[],
            wake=FakeWakeWord(),
            vad=FakeVAD(),
            asr=FakeASR(),
        )
        pipeline.stop()  # 未启动时 stop 不报错
        assert pipeline.state == PipelineState.IDLE

        pipeline.start()
        assert pipeline.is_running
        pipeline.stop()
        pipeline.stop()  # 重复 stop 幂等
        assert pipeline.state == PipelineState.IDLE
        assert pipeline.is_running is False

        # 停止后可再次启动
        pipeline.start()
        assert pipeline.is_running
        pipeline.stop()

    def test_pause_resume(self):
        cfg = VoiceConfig()
        pipeline, _, _, _ = _build(
            config=cfg,
            frames=[],
            wake=FakeWakeWord(),
            vad=FakeVAD(),
            asr=FakeASR(),
        )
        pipeline.start()
        try:
            pipeline.pause()
            time.sleep(0.02)
            paused_reads = pipeline._audio.frames_read
            time.sleep(0.05)
            assert pipeline._audio.frames_read <= paused_reads + 1  # 暂停后不再消费帧
            pipeline.resume()
            assert _wait_until(lambda: pipeline._audio.frames_read > paused_reads)
        finally:
            pipeline.stop()


class TestPublisherDuckTyping:
    def test_no_publish_method_is_ignored(self):
        cfg = VoiceConfig(wake_response="")
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms

        class _NotAPublisher:
            pass

        pipeline, tts, _, _ = _build(
            config=cfg,
            frames=_speech_silence_frames(cfg, speech=1, silence=silence_needed + 2),
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=[True] + [False] * (silence_needed + 2)),
            asr=FakeASR(transcripts=["你好"]),
            publisher=_NotAPublisher(),  # type: ignore[arg-type]
        )
        pipeline.start()
        try:
            assert tts.synthesized.wait(timeout=5)  # 不崩溃走完全程
        finally:
            pipeline.stop()


class _StateWriterRecorder:
    """state_writer fake：记录 (state, running) 写入序列。"""

    def __init__(self):
        self.writes: list[tuple[str, bool]] = []

    def write(self, state: str, running: bool) -> None:
        self.writes.append((state, running))


class TestStateWriter:
    """状态迁移 → 共享状态文件写入（M5.4 外部观察通道）。"""

    def test_every_transition_is_written_with_running_flag(self):
        cfg = VoiceConfig(wake_response="")
        writer = _StateWriterRecorder()
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms
        pipeline, tts, _, _ = _build(
            config=cfg,
            frames=_speech_silence_frames(cfg, speech=2, silence=silence_needed + 5),
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=[True, True] + [False] * (silence_needed + 5)),
            asr=FakeASR(transcripts=["写文件"]),
            state_writer=writer,
        )
        pipeline.start()
        try:
            assert tts.synthesized.wait(timeout=5)
            assert _wait_until(lambda: pipeline.state == PipelineState.WAKE_LISTENING)
        finally:
            pipeline.stop()

        writes = list(writer.writes)
        states = [s for s, _ in writes]
        # 启动即写 wake_listening；完整一轮各迁移都有写入；stop 收尾写 idle
        assert writes[0] == ("wake_listening", True)
        for expected in ("recording", "transcribing", "thinking", "speaking"):
            assert expected in states, f"缺少状态写入: {expected}"
        assert writes[-1] == ("idle", False)
        # 非 IDLE 写入一律 running=True（含 start 中线程尚未启动的第一次写入）
        assert all(running for s, running in writes if s != "idle")

    def test_noop_transition_is_not_written(self):
        cfg = VoiceConfig()
        writer = _StateWriterRecorder()
        pipeline, _, _, _ = _build(
            config=cfg,
            frames=[],
            wake=FakeWakeWord(),
            vad=FakeVAD(),
            asr=FakeASR(),
            state_writer=writer,
        )
        pipeline._set_state(PipelineState.IDLE)  # 已是 IDLE，未发生迁移
        assert writer.writes == []

    def test_writer_exception_does_not_break_pipeline(self):
        cfg = VoiceConfig(wake_response="")
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms

        class _BoomWriter:
            def write(self, state: str, running: bool) -> None:
                raise RuntimeError("磁盘炸了")

        pipeline, tts, _, _ = _build(
            config=cfg,
            frames=_speech_silence_frames(cfg, speech=1, silence=silence_needed + 2),
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=[True] + [False] * (silence_needed + 2)),
            asr=FakeASR(transcripts=["写入器炸了"]),
            state_writer=_BoomWriter(),
        )
        pipeline.start()
        try:
            assert tts.synthesized.wait(timeout=5)  # 写入器抛错不拖垮管道
            assert _wait_until(lambda: pipeline.state == PipelineState.WAKE_LISTENING)
        finally:
            pipeline.stop()


class _ReplyStateWriter:
    """state_writer fake：两参 ``write`` + M6.3 可选 ``write_with_reply`` 双通道记录。"""

    def __init__(self):
        self.writes: list[tuple[str, bool]] = []
        self.reply_writes: list[tuple[str, bool, str]] = []

    def write(self, state: str, running: bool) -> None:
        self.writes.append((state, running))

    def write_with_reply(self, state: str, running: bool, reply: str) -> None:
        self.reply_writes.append((state, running, reply))


class TestReplyPropagation:
    """M6.3：仅进入 SPEAKING 的写入携带本轮回复，其余迁移一律不带。"""

    def test_speaking_write_carries_reply_exclusively(self):
        cfg = VoiceConfig(wake_response="")
        writer = _ReplyStateWriter()
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms
        pipeline, tts, _, _ = _build(
            config=cfg,
            frames=_speech_silence_frames(cfg, speech=1, silence=silence_needed + 2),
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=[True] + [False] * (silence_needed + 2)),
            asr=FakeASR(transcripts=["讲个笑话"]),
            agent=FakeAgentBridge(replies=["本轮回复文本"]),
            state_writer=writer,
        )
        pipeline.start()
        try:
            assert tts.synthesized.wait(timeout=5)
            assert _wait_until(lambda: pipeline.state == PipelineState.WAKE_LISTENING)
        finally:
            pipeline.stop()

        # SPEAKING 迁移走 write_with_reply，恰好一次且携带 Agent 原文
        assert writer.reply_writes == [("speaking", True, "本轮回复文本")]
        # 其余迁移走两参 write，且绝不包含 speaking
        plain_states = [s for s, _ in writer.writes]
        assert "speaking" not in plain_states
        assert writer.writes[0] == ("wake_listening", True)
        for expected in ("recording", "transcribing", "thinking"):
            assert expected in plain_states, f"缺少状态写入: {expected}"
        assert writer.writes[-1] == ("idle", False)

    def test_reply_exception_in_writer_does_not_break_pipeline(self):
        cfg = VoiceConfig(wake_response="")
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms

        class _BoomReplyWriter:
            def write_with_reply(self, state: str, running: bool, reply: str) -> None:
                raise RuntimeError("reply 写入炸了")

        pipeline, tts, _, _ = _build(
            config=cfg,
            frames=_speech_silence_frames(cfg, speech=1, silence=silence_needed + 2),
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=[True] + [False] * (silence_needed + 2)),
            asr=FakeASR(transcripts=["你好"]),
            state_writer=_BoomReplyWriter(),
        )
        pipeline.start()
        try:
            assert tts.synthesized.wait(timeout=5)  # reply 写入抛错不拖垮管道
            assert _wait_until(lambda: pipeline.state == PipelineState.WAKE_LISTENING)
        finally:
            pipeline.stop()


class TestTtsMuted:
    """M6.3：tts_muted=True 时跳过 TTS 播放，状态机 / reply 写入 / 事件发布照走。"""

    def test_muted_skips_tts_but_state_reply_events_intact(self):
        cfg = VoiceConfig(tts_muted=True)
        states: list[PipelineState] = []
        publisher = _EventRecorder()
        writer = _ReplyStateWriter()
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms
        pipeline, tts, player, agent = _build(
            config=cfg,
            frames=_speech_silence_frames(cfg, speech=1, silence=silence_needed + 2),
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=[True] + [False] * (silence_needed + 2)),
            asr=FakeASR(transcripts=["你好 Omni"]),
            agent=FakeAgentBridge(replies=["静音模式回复"]),
            publisher=publisher,
            states=states,
            state_writer=writer,
        )
        pipeline.start()
        try:
            # muted 下 TTS 不会被调用，以 reply 写入 + 回到等待唤醒作为一轮完成信号
            assert _wait_until(
                lambda: len(writer.reply_writes) == 1
                and pipeline.state == PipelineState.WAKE_LISTENING
            )
            observed = list(states)  # stop() 会追加 IDLE，先快照
        finally:
            pipeline.stop()

        # TTS 合成与播放都被跳过
        assert tts.texts == []
        assert player.played == []
        # 状态机照走 SPEAKING，随后回到 WAKE_LISTENING
        assert PipelineState.SPEAKING in observed
        assert observed[-1] == PipelineState.WAKE_LISTENING
        # reply 照写状态文件、voice.reply 事件照发
        assert writer.reply_writes == [("speaking", True, "静音模式回复")]
        reply_payloads = [p for t, p in publisher.events if t == "voice.reply"]
        assert reply_payloads == [{"text": "静音模式回复"}]
        # Agent 仍被调用（muted 只静播报，不静思考）
        assert agent.messages == ["你好 Omni"]


class _BlockingPlayer:
    """阻塞式播放器 fake：play 阻塞直到 stop() 被调用（模拟真实阻塞播放）。

    供 M7.5 打断测试：验证 watcher 线程在 play 阻塞期间调 stop() 解除播放。
    """

    def __init__(self):
        self.stop_calls = 0
        self.play_started = threading.Event()
        self._lock = threading.Lock()

    def play(self, pcm: bytes, sample_rate: int) -> None:
        self.play_started.set()
        while True:
            with self._lock:
                if self.stop_calls > 0:
                    return
            time.sleep(0.005)

    def stop(self) -> None:
        with self._lock:
            self.stop_calls += 1


class _ToolCallsWriterRecorder:
    """state_writer fake：记录 write / write_with_reply / set_tool_calls 调用。

    M13.2：用于验证管道 _on_tool_start / _on_tool_end 是否正确同步 tool_calls
    到状态文件通道。set_tool_calls 入参被快照保存（list 是可变对象）。
    """

    def __init__(self):
        self.writes: list[tuple[str, bool]] = []
        self.reply_writes: list[tuple[str, bool, str]] = []
        self.tool_calls_snapshots: list[list[dict] | None] = []

    def write(self, state: str, running: bool) -> None:
        self.writes.append((state, running))

    def write_with_reply(self, state: str, running: bool, reply: str) -> None:
        self.reply_writes.append((state, running, reply))

    def set_tool_calls(self, calls: list[dict] | None) -> None:
        # 深拷贝避免后续 mutation 影响快照
        self.tool_calls_snapshots.append(list(calls) if calls is not None else None)


class TestPipelineToolCallsPropagation:
    """M13.2：管道工具调用回调 → 状态文件 tool_calls 字段同步。

    验证 ``_on_tool_start`` / ``_on_tool_end`` 在调 writer.set_tool_calls
    （若 writer 支持）后，状态迁移写入能透传当前 tool_calls 到状态文件。
    旧式 writer（无 set_tool_calls 方法）零感知、不报错（鸭子类型兼容）。
    """

    def test_on_tool_start_appends_pending_call_and_sets_tool_calls(self):
        """_on_tool_start(name, args) → set_tool_calls([pending]) + 状态切到 TOOL_USING。"""
        writer = _ToolCallsWriterRecorder()
        pipeline, _, _, _ = _build(
            config=VoiceConfig(wake_response=""),
            frames=[],
            wake=FakeWakeWord(),
            vad=FakeVAD(),
            asr=FakeASR(),
            state_writer=writer,
        )
        pipeline._on_tool_start("home_control_light", {"room": "客厅"})
        assert pipeline.state == PipelineState.TOOL_USING
        # set_tool_calls 被调用过
        assert len(writer.tool_calls_snapshots) >= 1
        latest = writer.tool_calls_snapshots[-1]
        assert latest is not None
        assert len(latest) == 1
        assert latest[0]["name"] == "home_control_light"
        assert latest[0]["args"] == {"room": "客厅"}
        assert latest[0]["status"] == "pending"
        assert latest[0]["result"] is None

    def test_on_tool_end_updates_call_to_success(self):
        """_on_tool_end(name, result) → 更新对应工具为 success + 状态回到 THINKING。"""
        writer = _ToolCallsWriterRecorder()
        pipeline, _, _, _ = _build(
            config=VoiceConfig(wake_response=""),
            frames=[],
            wake=FakeWakeWord(),
            vad=FakeVAD(),
            asr=FakeASR(),
            state_writer=writer,
        )
        pipeline._on_tool_start("home_control_light", {"room": "客厅"})
        pipeline._on_tool_end("home_control_light", '{"ok":true}')
        assert pipeline.state == PipelineState.THINKING
        latest = writer.tool_calls_snapshots[-1]
        assert latest is not None
        assert len(latest) == 1
        assert latest[0]["status"] == "success"
        assert latest[0]["result"] == '{"ok":true}'

    def test_on_tool_end_with_error_result_marks_error(self):
        """工具返回以「错误」开头的字符串 → status='error'（便于前端红色高亮）。"""
        writer = _ToolCallsWriterRecorder()
        pipeline, _, _, _ = _build(
            config=VoiceConfig(wake_response=""),
            frames=[],
            wake=FakeWakeWord(),
            vad=FakeVAD(),
            asr=FakeASR(),
            state_writer=writer,
        )
        pipeline._on_tool_start("failing_tool", {})
        pipeline._on_tool_end("failing_tool", "错误：HA 不可达")
        latest = writer.tool_calls_snapshots[-1]
        assert latest is not None
        assert latest[0]["status"] == "error"
        assert latest[0]["result"] == "错误：HA 不可达"

    def test_multiple_tool_calls_in_sequence(self):
        """多轮工具调用按顺序追加（LLM 连续调多个工具）。"""
        writer = _ToolCallsWriterRecorder()
        pipeline, _, _, _ = _build(
            config=VoiceConfig(wake_response=""),
            frames=[],
            wake=FakeWakeWord(),
            vad=FakeVAD(),
            asr=FakeASR(),
            state_writer=writer,
        )
        pipeline._on_tool_start("tool_a", {"x": 1})
        pipeline._on_tool_end("tool_a", "a-ok")
        pipeline._on_tool_start("tool_b", {"y": 2})
        pipeline._on_tool_end("tool_b", "b-ok")
        latest = writer.tool_calls_snapshots[-1]
        assert latest is not None
        assert len(latest) == 2
        assert [c["name"] for c in latest] == ["tool_a", "tool_b"]
        assert all(c["status"] == "success" for c in latest)

    def test_set_state_speaking_clears_tool_calls(self):
        """进入 SPEAKING 时清空 tool_calls（本轮工具链已结束，准备播报）。"""
        writer = _ToolCallsWriterRecorder()
        pipeline, _, _, _ = _build(
            config=VoiceConfig(wake_response=""),
            frames=[],
            wake=FakeWakeWord(),
            vad=FakeVAD(),
            asr=FakeASR(),
            state_writer=writer,
        )
        pipeline._on_tool_start("tool_a", {})
        pipeline._on_tool_end("tool_a", "ok")
        # 模拟 _set_state(SPEAKING, reply=...) 触发清空
        pipeline._set_state(PipelineState.SPEAKING, reply="已开灯")
        latest = writer.tool_calls_snapshots[-1]
        assert latest == [], "进入 SPEAKING 应清空 tool_calls"

    def test_legacy_writer_without_set_tool_calls_does_not_break(self):
        """旧式 state_writer（无 set_tool_calls 方法）零感知、不报错。"""

        class _LegacyWriter:
            def __init__(self):
                self.writes: list[tuple[str, bool]] = []

            def write(self, state: str, running: bool) -> None:
                self.writes.append((state, running))

        writer = _LegacyWriter()
        pipeline, _, _, _ = _build(
            config=VoiceConfig(wake_response=""),
            frames=[],
            wake=FakeWakeWord(),
            vad=FakeVAD(),
            asr=FakeASR(),
            state_writer=writer,
        )
        # 不抛错即通过
        pipeline._on_tool_start("tool_a", {})
        pipeline._on_tool_end("tool_a", "ok")
        assert pipeline.state == PipelineState.THINKING
        # 状态写入照走（tool_calls 字段无法透传，但状态机不受影响）
        states_written = [s for s, _ in writer.writes]
        assert "tool_using" in states_written
        assert "thinking" in states_written


class TestInterruptConsumption:
    """M7.5：管道消费控制文件 interrupt（与状态文件对称的反向通道）。

    常驻管道跑在宿主进程内，外部进程（HUD Rust 侧）无法直达（W1 教训），
    故打断走控制文件：外部写入 → 管道 ≤50ms 轮询消费 → 停播放、回等待唤醒。
    """

    def _drive_to_speaking(self, tmp_path, *, player, publisher, writer):
        """组装管道并驱动到 SPEAKING（player.play 阻塞中），返回 (pipeline, writer_cf)。"""
        cfg = VoiceConfig(wake_response="")
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms
        control_path = tmp_path / "state" / "voice-control.json"
        pipeline, tts, _, _ = _build(
            config=cfg,
            frames=_speech_silence_frames(cfg, speech=1, silence=silence_needed + 2),
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=[True] + [False] * (silence_needed + 2)),
            asr=FakeASR(transcripts=["讲个长故事"]),
            agent=FakeAgentBridge(replies=["很长很长的回复"]),
            publisher=publisher,
            state_writer=writer,
            player=player,
            control_file=VoiceControlFile(control_path),
        )
        pipeline.start()
        assert player.play_started.wait(timeout=5), "未进入 SPEAKING 播放"
        assert pipeline.state == PipelineState.SPEAKING
        return pipeline, VoiceControlFile(control_path)

    def test_interrupt_stops_playback_and_returns_to_wake_listening(self, tmp_path):
        player = _BlockingPlayer()
        publisher = _EventRecorder()
        writer = _StateWriterRecorder()
        pipeline, writer_cf = self._drive_to_speaking(
            tmp_path, player=player, publisher=publisher, writer=writer
        )
        try:
            writer_cf.interrupt()  # 外部进程写入控制文件
            assert _wait_until(lambda: pipeline.state == PipelineState.WAKE_LISTENING)
            assert _wait_until(lambda: player.stop_calls >= 1)
        finally:
            pipeline.stop()

        # voice.interrupted 事件已发布，携带被消费的 seq
        interrupted = [p for t, p in publisher.events if t == "voice.interrupted"]
        assert interrupted == [{"seq": 1}]
        # 状态文件照常写入：speaking → wake_listening 迁移都有记录
        states_written = [s for s, _ in writer.writes]
        assert "speaking" in states_written
        assert states_written[-1] == "idle"  # stop 收尾
        assert "wake_listening" in states_written

    def test_same_seq_is_not_consumed_twice(self, tmp_path):
        """同一 seq 不重复触发：消费过的序号再次被读到（如文件未变）不重复打断。"""
        player = _BlockingPlayer()
        publisher = _EventRecorder()
        writer = _StateWriterRecorder()
        pipeline, writer_cf = self._drive_to_speaking(
            tmp_path, player=player, publisher=publisher, writer=writer
        )
        try:
            writer_cf.interrupt()
            assert _wait_until(lambda: pipeline.state == PipelineState.WAKE_LISTENING)
            assert _wait_until(lambda: player.stop_calls >= 1)
            time.sleep(0.2)  # 轮询继续读同一文件（同 seq）
        finally:
            pipeline.stop()

        interrupted = [p for t, p in publisher.events if t == "voice.interrupted"]
        assert interrupted == [{"seq": 1}]  # 恰好一次
        assert player.stop_calls == 1

    def test_interrupt_when_not_speaking_is_consumed_silently(self, tmp_path):
        """非 speaking 状态收到 interrupt：仅消费序号，不崩、不迁状态、不发事件。"""
        cfg = VoiceConfig()
        publisher = _EventRecorder()
        control_path = tmp_path / "state" / "voice-control.json"
        pipeline, _, _, _ = _build(
            config=cfg,
            frames=[],
            wake=FakeWakeWord(),
            vad=FakeVAD(),
            asr=FakeASR(),
            publisher=publisher,
            control_file=VoiceControlFile(control_path),
        )
        pipeline.start()
        try:
            assert pipeline.state == PipelineState.WAKE_LISTENING
            VoiceControlFile(control_path).interrupt()
            time.sleep(0.3)  # 数个轮询周期
            assert pipeline.is_running
            assert pipeline.state == PipelineState.WAKE_LISTENING
        finally:
            pipeline.stop()
        assert "voice.interrupted" not in publisher.types()

    def test_player_without_stop_capability_still_transitions(self, tmp_path):
        """player 无 stop 能力：跳过播放停止，状态照走回 wake_listening、事件照发。"""

        class _NoStopPlayer:
            def __init__(self):
                self.play_started = threading.Event()
                self.release = threading.Event()

            def play(self, pcm: bytes, sample_rate: int) -> None:
                self.play_started.set()
                self.release.wait(timeout=5)

        player = _NoStopPlayer()
        publisher = _EventRecorder()
        writer = _StateWriterRecorder()
        pipeline, writer_cf = self._drive_to_speaking(
            tmp_path, player=player, publisher=publisher, writer=writer
        )
        try:
            writer_cf.interrupt()
            # 播放仍阻塞中，但状态已迁移、事件已发布
            assert _wait_until(lambda: pipeline.state == PipelineState.WAKE_LISTENING)
            assert "voice.interrupted" in publisher.types()
        finally:
            player.release.set()
            pipeline.stop()

    def test_default_control_file_uses_default_path(self):
        """缺省构造内部走 VoiceControlFile.DEFAULT_PATH（conftest 已隔离到 tmp）。"""
        cfg = VoiceConfig()
        pipeline, _, _, _ = _build(
            config=cfg,
            frames=[],
            wake=FakeWakeWord(),
            vad=FakeVAD(),
            asr=FakeASR(),
        )
        try:
            VoiceControlFile().interrupt()  # 写默认路径（tmp 隔离）
            pipeline.start()
            # 非 speaking：仅消费不崩，证明 watcher 确实在读默认路径
            time.sleep(0.3)
            assert pipeline.is_running
            assert pipeline.state == PipelineState.WAKE_LISTENING
        finally:
            pipeline.stop()


class _ResettableAgent(FakeAgentBridge):
    """支持 reset() 的 fake agent（模拟 ConversationAgent）。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.reset_calls = 0

    def reset(self) -> None:
        self.reset_calls += 1


class TestFollowUpListening:
    """M8：SPEAKING 后进入 FOLLOW_UP_LISTENING 续听窗口。"""

    def test_speaking_transitions_to_follow_up_listening(self):
        """播报完毕进入 FOLLOW_UP_LISTENING（而非直接回 WAKE_LISTENING）。"""
        cfg = VoiceConfig(follow_up_timeout_s=0.2, wake_response="")
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms
        frames = _speech_silence_frames(cfg, speech=2, silence=silence_needed + 2)
        states: list[PipelineState] = []
        pipeline, tts, _, _ = _build(
            config=cfg,
            frames=frames,
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=[True, True] + [False] * (silence_needed + 2)),
            asr=FakeASR(transcripts=["你好"]),
            states=states,
        )
        pipeline.start()
        try:
            assert tts.synthesized.wait(timeout=5)
            assert _wait_until(
                lambda: pipeline.state == PipelineState.FOLLOW_UP_LISTENING
            )
            observed = list(states)
        finally:
            pipeline.stop()

        assert PipelineState.FOLLOW_UP_LISTENING in observed
        idx = observed.index(PipelineState.FOLLOW_UP_LISTENING)
        assert observed[idx - 1] == PipelineState.SPEAKING

    def test_follow_up_speech_triggers_recording_without_wake_word(self):
        """续听窗口内 VAD 检测到语音 → 直接 RECORDING（无需唤醒词）。"""
        cfg = VoiceConfig(follow_up_timeout_s=5.0, wake_response="")
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms
        first_round_frames = _speech_silence_frames(
            cfg, speech=2, silence=silence_needed + 2
        )
        follow_speech = [b"\x01" * cfg.frame_bytes] * 3
        follow_silence = [b"\x00" * cfg.frame_bytes] * (silence_needed + 2)
        all_frames = first_round_frames + follow_speech + follow_silence
        vad_seq = (
            [True, True]
            + [False] * (silence_needed + 2)
            + [True] * 3
            + [False] * (silence_needed + 2)
        )
        states: list[PipelineState] = []
        agent = _ResettableAgent(replies=["第一轮回复", "续问回复"])
        pipeline, tts, _, _ = _build(
            config=cfg,
            frames=all_frames,
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=vad_seq),
            asr=FakeASR(transcripts=["第一轮", "续问"]),
            agent=agent,
            states=states,
        )
        pipeline.start()
        try:
            assert _wait_until(lambda: len(agent.messages) >= 2, timeout=5), (
                "续问未被处理"
            )
            assert _wait_until(
                lambda: pipeline.state == PipelineState.FOLLOW_UP_LISTENING
            )
            observed = list(states)
        finally:
            pipeline.stop()

        assert agent.messages == ["第一轮", "续问"]
        first_fu = observed.index(PipelineState.FOLLOW_UP_LISTENING)
        assert PipelineState.RECORDING in observed[first_fu + 1 :]

    def test_follow_up_timeout_resets_agent_and_returns_to_wake_listening(self):
        """续听窗口超时无语音 → agent.reset() + WAKE_LISTENING。"""
        cfg = VoiceConfig(follow_up_timeout_s=0.3, wake_response="")
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms
        first_round = _speech_silence_frames(
            cfg, speech=1, silence=silence_needed + 2
        )
        long_silence = [b"\x00" * cfg.frame_bytes] * 80
        all_frames = first_round + long_silence
        vad_seq = [True] + [False] * (silence_needed + 2 + 80)

        agent = _ResettableAgent(replies=["好的"])
        pipeline, tts, _, _ = _build(
            config=cfg,
            frames=all_frames,
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=vad_seq),
            asr=FakeASR(transcripts=["你好"]),
            agent=agent,
        )
        pipeline.start()
        try:
            assert tts.synthesized.wait(timeout=5)
            assert _wait_until(
                lambda: pipeline.state == PipelineState.WAKE_LISTENING, timeout=5
            )
        finally:
            pipeline.stop()

        assert agent.reset_calls >= 1, "超时后应调用 agent.reset()"

    def test_follow_up_timeout_agent_without_reset_is_safe(self):
        """agent 无 reset() 方法时超时不崩溃（鸭子类型容错）。"""
        cfg = VoiceConfig(follow_up_timeout_s=0.1, wake_response="")
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms
        first_round = _speech_silence_frames(
            cfg, speech=1, silence=silence_needed + 2
        )
        long_silence = [b"\x00" * cfg.frame_bytes] * 40
        all_frames = first_round + long_silence
        vad_seq = [True] + [False] * (silence_needed + 2 + 40)

        pipeline, tts, _, _ = _build(
            config=cfg,
            frames=all_frames,
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=vad_seq),
            asr=FakeASR(transcripts=["你好"]),
            agent=FakeAgentBridge(replies=["好"]),
        )
        pipeline.start()
        try:
            assert tts.synthesized.wait(timeout=5)
            assert _wait_until(
                lambda: pipeline.state == PipelineState.WAKE_LISTENING, timeout=5
            )
        finally:
            pipeline.stop()


class TestWakeResponse:
    """M8：唤醒词命中后播短应答（"我在"）再进入录音。"""

    def test_wake_response_synthesized_before_recording(self):
        """配置了 wake_response 时，唤醒后先 TTS 应答再录音。"""
        cfg = VoiceConfig(wake_response="我在", follow_up_timeout_s=0.2)
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms
        pipeline, tts, player, _ = _build(
            config=cfg,
            frames=_speech_silence_frames(cfg, speech=2, silence=silence_needed + 2),
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=[True, True] + [False] * (silence_needed + 2)),
            asr=FakeASR(transcripts=["你好"]),
            agent=FakeAgentBridge(replies=["你好呀"]),
        )
        pipeline.start()
        try:
            assert tts.synthesized.wait(timeout=5)
            assert _wait_until(
                lambda: pipeline.state == PipelineState.FOLLOW_UP_LISTENING
            )
        finally:
            pipeline.stop()

        assert "我在" in tts.texts, "唤醒应答文本应被 TTS 合成"
        assert len(player.played) >= 2, "应播放唤醒应答 + 正式回复两段音频"

    def test_empty_wake_response_skips_ack(self):
        """wake_response 为空字符串时不应答，直接录音。"""
        cfg = VoiceConfig(wake_response="", follow_up_timeout_s=0.2)
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms
        pipeline, tts, _, _ = _build(
            config=cfg,
            frames=_speech_silence_frames(cfg, speech=1, silence=silence_needed + 2),
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=[True] + [False] * (silence_needed + 2)),
            asr=FakeASR(transcripts=["你好"]),
            agent=FakeAgentBridge(replies=["好"]),
        )
        pipeline.start()
        try:
            assert tts.synthesized.wait(timeout=5)
            assert _wait_until(
                lambda: pipeline.state == PipelineState.FOLLOW_UP_LISTENING
            )
        finally:
            pipeline.stop()

        assert "" not in tts.texts
        assert len(tts.texts) == 1
        assert tts.texts[0] == "好"

    def test_tts_muted_skips_wake_response(self):
        """tts_muted=True 时唤醒应答也跳过（OpenTalking 模式）。"""
        cfg = VoiceConfig(tts_muted=True, wake_response="我在", follow_up_timeout_s=0.2)
        silence_needed = cfg.vad_silence_ms // cfg.frame_ms
        pipeline, tts, player, _ = _build(
            config=cfg,
            frames=_speech_silence_frames(cfg, speech=1, silence=silence_needed + 2),
            wake=FakeWakeWord(confidences=[0.9]),
            vad=FakeVAD(results=[True] + [False] * (silence_needed + 2)),
            asr=FakeASR(transcripts=["你好"]),
            agent=FakeAgentBridge(replies=["好"]),
        )
        pipeline.start()
        try:
            assert _wait_until(
                lambda: pipeline.state == PipelineState.FOLLOW_UP_LISTENING, timeout=5
            )
        finally:
            pipeline.stop()

        assert tts.texts == []
        assert player.played == []
