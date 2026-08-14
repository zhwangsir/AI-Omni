"""语音管道状态机。

状态流转：

    IDLE → (start) → WAKE_LISTENING
    WAKE_LISTENING --唤醒置信度≥wake_threshold--> RECORDING
    RECORDING --连续静音≥vad_silence_ms 或 时长≥max_record_s--> TRANSCRIBING
    TRANSCRIBING --空文本--> WAKE_LISTENING
    TRANSCRIBING --有文本--> THINKING
    THINKING --Agent 回复--> SPEAKING
    SPEAKING --TTS 播放完毕--> FOLLOW_UP_LISTENING
    FOLLOW_UP_LISTENING --VAD 检测到语音--> RECORDING（续听无需唤醒词）
    FOLLOW_UP_LISTENING --超时 follow_up_timeout_s 无语音--> WAKE_LISTENING（重置会话）

任一环节抛错：发布 ``voice.error`` 事件并回到 WAKE_LISTENING。
管道在后台 ``threading.Thread`` 中运行，``threading.Event`` 控制停止与暂停。

M7.5 打断：另一条后台 watcher 线程以 ≤50ms 节奏轮询控制文件
（``control_file.py``，与状态文件对称的反向通道），发现未消费的
interrupt 且当前为 SPEAKING 时：停当前播放（player 有 stop 能力则调用）、
迁移回 WAKE_LISTENING、发布 ``voice.interrupted`` 事件、状态文件照写。

M8 常驻助手：SPEAKING 完毕进入 FOLLOW_UP_LISTENING 续听窗口（默认4秒），
窗口内用户再次说话直接进 RECORDING（无需唤醒词），实现小爱同学式连续对话。
超时无语音则重置对话历史（agent.reset() 鸭子调用）并回 WAKE_LISTENING。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol

from .agent_bridge import AgentBridge
from .audio import AudioSource
from .backends.base import ASRBackend, TTSBackend, VADBackend, WakeWordBackend
from .config import VoiceConfig
from .control_file import VoiceControlFile
from .errors import PipelineStateError

logger = logging.getLogger(__name__)


class PipelineState(Enum):
    """管道状态机枚举。"""

    IDLE = "idle"
    WAKE_LISTENING = "wake_listening"
    FOLLOW_UP_LISTENING = "follow_up_listening"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    TOOL_USING = "tool_using"
    SPEAKING = "speaking"


class PlayerProtocol(Protocol):
    """播放器协议（鸭子类型）：播放一段 PCM16 音频；stop 为可选打断能力。"""

    def play(self, pcm: bytes, sample_rate: int) -> None: ...

    def stop(self) -> None: ...


#: 事件类型常量
EVENT_WAKE = "voice.wake_detected"
EVENT_TRANSCRIPT = "voice.transcript"
EVENT_REPLY = "voice.reply"
EVENT_ERROR = "voice.error"
EVENT_INTERRUPTED = "voice.interrupted"
EVENT_TOOL_START = "voice.tool_start"
EVENT_TOOL_END = "voice.tool_end"

#: 控制文件轮询间隔（M7.5 打断延迟上限）
CONTROL_POLL_INTERVAL_S = 0.05


class VoicePipeline:
    """语音交互管道：唤醒 → 录音 → 识别 → 思考 → 播报，循环往复。

    所有组件依赖注入（真实后端或 fake 均可）；
    ``event_publisher`` 为可选鸭子类型——有 ``publish(event_type, payload)``
    方法则调用，没有则忽略；
    ``state_writer`` 为可选鸭子类型（M5.4 共享状态文件通道）——有
    ``write(state: str, running: bool)`` 方法则在每次状态迁移时调用，
    写入失败不得拖垮管道；
    ``control_file`` 为可选控制文件实例（M7.5 打断反向通道）——缺省走
    ``VoiceControlFile.DEFAULT_PATH``，测试注入 tmp 路径实例。
    """

    def __init__(
        self,
        *,
        config: VoiceConfig,
        audio_source: AudioSource,
        wake_word: WakeWordBackend,
        vad: VADBackend,
        asr: ASRBackend,
        tts: TTSBackend,
        agent: AgentBridge,
        player: PlayerProtocol,
        on_state_change: Callable[[PipelineState, PipelineState], None] | None = None,
        event_publisher: Any = None,
        state_writer: Any = None,
        control_file: Any = None,
    ):
        self._config = config
        self._audio = audio_source
        self._wake = wake_word
        self._vad = vad
        self._asr = asr
        self._tts = tts
        self._agent = agent
        self._player = player
        self._on_state_change = on_state_change
        self._event_publisher = event_publisher
        self._state_writer = state_writer
        self._control_file = control_file if control_file is not None else VoiceControlFile()

        self._state = PipelineState.IDLE
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._thread: threading.Thread | None = None
        self._control_thread: threading.Thread | None = None
        #: 已消费的控制指令序号（仅 watcher 线程读写）
        self._consumed_control_seq = 0
        #: M34.3 控制文件签名缓存（mtime_ns, size；仅 watcher 线程读写）：
        #: 50ms 轮询下签名未变跳过 read+JSON 解析（9.47µs → 1.42µs/次，-85%）。
        self._control_sig: tuple[int, int] | None = None

        # 录音缓冲（仅 RECORDING 状态使用）
        self._rec_buffer: list[bytes] = []
        self._rec_silence_ms = 0
        # pre-roll 环形缓冲：等待唤醒时持续保存最近 N 帧语音，触发时前置进录音缓冲，
        # 避免唤醒词（如"雪莉"）在 VAD 累积判定期间被漏掉。
        # M34.3：list+pop(0)（每帧 O(n) 搬移）改为有界 deque（append 自动逐出 O(1)）。
        self._preroll_frames = max(1, int(1500 / config.frame_ms))  # 默认 1.5 秒
        self._preroll_buf: deque[bytes] = deque(maxlen=self._preroll_frames)
        # 续听窗口超时截止时间（monotonic）
        self._follow_up_deadline: float = 0.0
        # 首轮标志：唤醒后第一次说话需要校验唤醒词
        self._is_first_turn = True
        # M32.29：最近一次实际播报的回复文本——续听窗口回声过滤依据。
        # TTS 播报被自家麦克风拾取会形成自激循环（转写≈reply → 免热词直达 LLM），
        # 仅在 player.play 后记录（tts_muted 无扬声器输出，不存在声学回声）。
        self._last_spoken_reply: str | None = None
        # 热词校验失败后的额外冷却截止时间（避免环境音连续触发循环）
        self._reject_cooldown_until: float = 0.0

        # M13.2：当前轮次进行中的工具调用列表（_on_tool_start 追加、
        # _on_tool_end 更新；进入 SPEAKING 时清空）。每次变更都同步到
        # state_writer.set_tool_calls（鸭子类型，旧式 writer 无此方法则跳过）。
        self._current_tool_calls: list[dict[str, Any]] = []
        self._tool_call_seq: int = 0

        # M9：自动连接 ConversationAgent 的工具回调（鸭子类型）
        self._connect_agent_callbacks()

    # ------------------------------------------------------------------
    # 状态与生命周期
    # ------------------------------------------------------------------
    @property
    def state(self) -> PipelineState:
        with self._state_lock:
            return self._state

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> PipelineState:
        """启动后台线程进入 WAKE_LISTENING；重复启动抛 PipelineStateError。

        返回启动时进入的初始状态（确定值 WAKE_LISTENING）。调用方上报
        "启动结果"应使用该返回值——线程启动后实时状态机可能已迁移
        （如首帧即唤醒），事后读 ``state`` 属性是竞态的。
        """
        if self.is_running:
            raise PipelineStateError("语音管道已在运行")
        self._stop_event.clear()
        self._resume_event.set()
        self._audio.start()
        self._set_state(PipelineState.WAKE_LISTENING)
        entered = self.state
        self._thread = threading.Thread(
            target=self._run, name="omni-voice-pipeline", daemon=True
        )
        self._thread.start()
        # M7.5：控制文件 watcher 线程（≤50ms 轮询消费 interrupt 指令）
        self._control_thread = threading.Thread(
            target=self._control_watch, name="omni-voice-control", daemon=True
        )
        self._control_thread.start()
        return entered

    def stop(self, timeout_s: float = 2.0) -> None:
        """停止后台线程（幂等）：置位停止事件，join 超时清理。"""
        self._stop_event.set()
        self._resume_event.set()  # 解除可能的暂停，让线程尽快看到停止事件
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout_s)
        self._thread = None
        control_thread = self._control_thread
        if control_thread is not None and control_thread.is_alive():
            control_thread.join(timeout=timeout_s)
        self._control_thread = None
        try:
            self._audio.stop()
        finally:
            if self.state != PipelineState.IDLE:
                self._set_state(PipelineState.IDLE)

    def pause(self) -> None:
        """暂停帧消费（listen_once 等独占操作使用）。"""
        self._resume_event.clear()

    def resume(self) -> None:
        """恢复帧消费。"""
        self._resume_event.set()

    # ------------------------------------------------------------------
    # 内部：状态迁移与事件发布
    # ------------------------------------------------------------------
    def _set_state(self, new_state: PipelineState, reply: str | None = None) -> None:
        with self._state_lock:
            old_state = self._state
            if old_state is new_state:
                return
            self._state = new_state
        # M13.2：进入 SPEAKING 表示本轮工具链已结束，先清空 tool_calls
        # 并同步到 writer（set_tool_calls([])），随后 write_with_reply 透传
        # 空数组到状态文件，覆盖上一轮残留的工具列表。
        if new_state is PipelineState.SPEAKING:
            self._current_tool_calls = []
            self._sync_tool_calls_to_writer()
        self._write_state(new_state, reply)
        if self._on_state_change is not None:
            try:
                self._on_state_change(old_state, new_state)
            except Exception:  # 回调异常不能拖垮管道线程
                logger.exception("on_state_change 回调抛错，已忽略")

    def _write_state(self, new_state: PipelineState, reply: str | None = None) -> None:
        """把状态迁移写入共享状态文件（M5.4）；非 IDLE 即视为 running。

        M6.3：仅进入 SPEAKING 时携带本轮回复文本——writer 具备可选方法
        ``write_with_reply`` 则走它（PipelineStateWriter），否则回退两参
        ``write`` 鸭子契约（旧式 writer 零感知）。
        """
        running = new_state is not PipelineState.IDLE
        if reply is not None:
            write_with_reply = getattr(self._state_writer, "write_with_reply", None)
            if callable(write_with_reply):
                try:
                    write_with_reply(new_state.value, running, reply)
                except Exception:  # 写入失败不能拖垮管道线程
                    logger.exception("state_writer 写入抛错，已忽略")
                return
        write = getattr(self._state_writer, "write", None)
        if not callable(write):
            return
        try:
            write(new_state.value, running)
        except Exception:  # 写入失败不能拖垮管道线程
            logger.exception("state_writer 写入抛错，已忽略")

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        publish = getattr(self._event_publisher, "publish", None)
        if callable(publish):
            try:
                publish(event_type, payload)
            except Exception:  # 发布失败不影响管道
                logger.exception("事件 %s 发布失败，已忽略", event_type)

    # ------------------------------------------------------------------
    # 内部：工具调用回调（M9 Function Calling）
    # ------------------------------------------------------------------
    def _connect_agent_callbacks(self) -> None:
        """鸭子类型：若 agent 是 ConversationAgent（有 _on_tool_start/_on_tool_end），挂载回调。"""
        if hasattr(self._agent, "_on_tool_start"):
            self._agent._on_tool_start = self._on_tool_start
        if hasattr(self._agent, "_on_tool_end"):
            self._agent._on_tool_end = self._on_tool_end

    def _on_tool_start(self, tool_name: str, tool_args: dict[str, Any]) -> None:
        """工具开始执行：追加 pending 记录、同步到 writer、切到 TOOL_USING 并发布事件。

        M13.2：维护 ``_current_tool_calls`` 列表（追加 pending 记录），
        通过 ``_sync_tool_calls_to_writer`` 把列表透传到 state_writer，
        后续 ``_set_state(TOOL_USING)`` 写入的快照即携带本轮工具列表。
        旧式 writer（无 ``set_tool_calls`` 方法）零感知、不报错。
        """
        self._tool_call_seq += 1
        call_id = f"seq{self._tool_call_seq}"
        self._current_tool_calls.append({
            "id": call_id,
            "name": tool_name,
            "args": tool_args,
            "status": "pending",
            "result": None,
            "ts": time.time(),
        })
        self._sync_tool_calls_to_writer()
        self._set_state(PipelineState.TOOL_USING)
        self._publish(EVENT_TOOL_START, {"name": tool_name, "args": tool_args})

    def _on_tool_end(self, tool_name: str, result: str) -> None:
        """工具执行完毕：更新对应记录为 success/error、同步、回到 THINKING、发布事件。

        M13.2：在 ``_current_tool_calls`` 中找到首个同名且 pending 的记录，
        按 result 是否以「错误」开头标记 success/error 并写入 result；
        随后同步到 writer、回到 THINKING（LLM 还需继续处理本轮工具结果）。
        未找到匹配记录时不报错（容错：旧版 agent 直接调 _on_tool_end）。
        """
        for call in self._current_tool_calls:
            if call["name"] == tool_name and call["status"] == "pending":
                call["status"] = "error" if result.startswith("错误") else "success"
                call["result"] = result
                call["ts"] = time.time()
                break
        self._sync_tool_calls_to_writer()
        self._set_state(PipelineState.THINKING)
        self._publish(EVENT_TOOL_END, {"name": tool_name, "result_preview": result[:200]})

    def _sync_tool_calls_to_writer(self) -> None:
        """同步当前工具调用列表到 state_writer（鸭子类型，无 set_tool_calls 则跳过）。

        传入 list 的浅拷贝，避免 writer 持有可变引用导致后续 mutation 影响快照。
        写入失败不得拖垮管道线程（与 _write_state 同样的容错约定）。
        """
        set_tool_calls = getattr(self._state_writer, "set_tool_calls", None)
        if not callable(set_tool_calls):
            return
        try:
            set_tool_calls(list(self._current_tool_calls))
        except Exception:  # 写入失败不能拖垮管道线程
            logger.exception("state_writer.set_tool_calls 抛错，已忽略")

    # ------------------------------------------------------------------
    # 内部：控制文件消费（M7.5 打断反向通道）
    # ------------------------------------------------------------------
    def _control_watch(self) -> None:
        """以 ≤50ms 节奏轮询控制文件；任何消费异常都不得拖垮 watcher。"""
        while not self._stop_event.wait(CONTROL_POLL_INTERVAL_S):
            try:
                self._consume_control_once()
            except Exception:  # noqa: BLE001 - 控制通道故障不影响管道主循环
                logger.exception("控制文件消费出错，已忽略")

    def _consume_control_once(self) -> None:
        """消费一条 interrupt 指令：停播放、回 WAKE_LISTENING、发事件。

        同一 seq 只消费一次（``> 已消费序号`` 判新）；非 SPEAKING 状态
        仅消费序号不打断——不打断录音/思考，也避免陈旧指令误伤后续播报。
        """
        cf = self._control_file
        read = getattr(cf, "read", None)
        if not callable(read):
            return
        # M34.3 签名缓存：文件元数据（mtime_ns, size）未变则跳过 read+JSON 解析。
        # 非 Path path（fake 注入）直接放行读路径，保持鸭子类型兼容。
        path = getattr(cf, "path", None)
        if isinstance(path, Path):
            try:
                st = path.stat()
            except OSError:
                return  # 文件不存在/不可读：本轮无指令
            sig = (st.st_mtime_ns, st.st_size)
            if sig == self._control_sig:
                return
            self._control_sig = sig
        payload = read(getattr(cf, "path", None))
        if payload is None:
            return
        seq = payload["seq"]
        if seq <= self._consumed_control_seq:
            return
        self._consumed_control_seq = seq
        if self.state is not PipelineState.SPEAKING:
            return
        # player 无 stop 能力则跳过播放停止，状态照走
        stop = getattr(self._player, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:  # 播放停止失败不拖垮 watcher
                logger.exception("player.stop 抛错，已忽略")
        self._reset_conversation()
        self._reset_wake_state()
        self._set_state(PipelineState.WAKE_LISTENING)
        self._publish(EVENT_INTERRUPTED, {"seq": seq})

    # ------------------------------------------------------------------
    # 内部：主循环与状态机
    # ------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop_event.is_set():
            if not self._resume_event.wait(timeout=0.1):
                continue  # 暂停中
            try:
                frame = self._audio.read_frame()
                if not frame:
                    time.sleep(0.005)
                    continue
                self._dispatch(frame)
            except Exception as exc:  # noqa: BLE001 - 任何后端错误都恢复等待
                logger.exception("管道帧处理出错")
                self._publish(EVENT_ERROR, {"error": str(exc), "stage": self.state.value})
                self._reset_wake_state()
                self._set_state(PipelineState.WAKE_LISTENING)

    def _dispatch(self, frame: bytes) -> None:
        state = self.state
        if state == PipelineState.WAKE_LISTENING:
            # 维护 pre-roll 环形缓冲：有界 deque 满员自动逐出最旧帧（O(1)）
            self._preroll_buf.append(frame)
            # 热词校验失败后的额外冷却期内，跳过唤醒检测
            if time.monotonic() < self._reject_cooldown_until:
                return
            confidence = self._wake.detect(frame)
            if confidence >= self._config.wake_threshold:
                self._publish(EVENT_WAKE, {"confidence": confidence})
                self._on_wake_detected()
        elif state == PipelineState.FOLLOW_UP_LISTENING:
            self._handle_follow_up(frame)
        elif state == PipelineState.RECORDING:
            self._record_frame(frame)

    def _on_wake_detected(self) -> None:
        """唤醒触发：进入录音。专用模型模式立即播应答，VAD 模式延后到热词校验后。"""
        if not getattr(self._wake, "requires_hotword_check", False):
            self._play_wake_ack()
            self._is_first_turn = False
        self._begin_recording()

    def _play_wake_ack(self) -> None:
        """热词校验通过后播短应答。"""
        cfg = self._config
        if cfg.wake_response and not cfg.tts_muted:
            try:
                ack = self._tts.synthesize(cfg.wake_response)
                tts_sr = getattr(self._tts, "sample_rate", cfg.sample_rate)
                self._player.play(ack, tts_sr)
                time.sleep(0.2)
            except Exception:
                logger.exception("唤醒应答 TTS 失败，跳过应答")

    def _begin_recording(self, initial_frame: bytes | None = None) -> None:
        # 把 pre-roll 缓冲的前置帧全部加入录音（包含唤醒词）
        self._rec_buffer = list(self._preroll_buf)
        self._preroll_buf = []
        self._rec_silence_ms = 0
        if initial_frame is not None:
            self._rec_buffer.append(initial_frame)
            if self._vad.is_speech(initial_frame, self._config.sample_rate):
                self._rec_silence_ms = 0
            else:
                self._rec_silence_ms = self._config.frame_ms
        # 重置静音计时：pre-roll 末尾是语音（触发点），从 0 开始
        self._rec_silence_ms = 0
        self._set_state(PipelineState.RECORDING)

    def _record_frame(self, frame: bytes) -> None:
        cfg = self._config
        self._rec_buffer.append(frame)
        if self._vad.is_speech(frame, cfg.sample_rate):
            self._rec_silence_ms = 0
        else:
            self._rec_silence_ms += cfg.frame_ms
        # M32.29：首轮（热词校验前）录音是投机性的——嘈杂环境可能录到媒体音——
        # 用更短的 wake_max_record_s 上限；热词校验通过后的续听仍用 max_record_s。
        speculative = self._is_first_turn and getattr(self._wake, "requires_hotword_check", False)
        limit_s = cfg.wake_max_record_s if speculative else cfg.max_record_s
        max_frames = max(1, int(limit_s * 1000) // cfg.frame_ms)
        min_frames = max(1, int(800) // cfg.frame_ms)  # 最小录音 800ms，避免短噪音截断
        silence_hit = self._rec_silence_ms >= cfg.vad_silence_ms and len(self._rec_buffer) >= min_frames
        length_hit = len(self._rec_buffer) >= max_frames
        if silence_hit or length_hit:
            pcm = b"".join(self._rec_buffer)
            self._rec_buffer = []
            self._finish_utterance(pcm)

    def _finish_utterance(self, pcm: bytes) -> None:
        cfg = self._config
        self._set_state(PipelineState.TRANSCRIBING)
        text = self._asr.transcribe(pcm, cfg.sample_rate, language=None)
        self._publish(EVENT_TRANSCRIPT, {"text": text})
        if not text or not text.strip():
            self._reset_wake_state()
            # 空识别结果：设置 2 秒拒绝冷却，避免环境音循环触发
            self._reject_cooldown_until = time.monotonic() + 2.0
            self._set_state(PipelineState.WAKE_LISTENING)
            return
        if not self._is_first_turn and self._is_echo_transcript(text, self._last_spoken_reply):
            # M32.29：续听窗口拾到自家播报的回声——丢弃并留在续听窗口
            #（deadline 不变，用户仍可在剩余窗口内说话；无真实语音则超时退出）。
            logger.debug("续听回声丢弃: %r", text)
            self._set_state(PipelineState.FOLLOW_UP_LISTENING)
            return
        if self._is_first_turn and getattr(self._wake, "requires_hotword_check", False):
            processed = self._check_hotword(text, cfg)
            if processed is None:
                self._reset_wake_state()
                # 热词校验失败：设置 2.5 秒拒绝冷却，避免背景音持续触发
                self._reject_cooldown_until = time.monotonic() + 2.5
                logger.debug("热词校验失败，文本中未找到唤醒词，进入 2.5s 冷却")
                self._set_state(PipelineState.WAKE_LISTENING)
                return
            text = processed
            self._is_first_turn = False
            self._play_wake_ack()
        elif self._is_first_turn:
            self._is_first_turn = False
        self._reject_cooldown_until = 0.0  # 唤醒成功，清除拒绝冷却
        self._set_state(PipelineState.THINKING)
        reply = self._agent.chat(text)
        self._publish(EVENT_REPLY, {"text": reply})
        self._set_state(PipelineState.SPEAKING, reply=reply)
        if not cfg.tts_muted:
            speech = self._tts.synthesize(reply)
            tts_sr = getattr(self._tts, "sample_rate", cfg.sample_rate)
            self._player.play(speech, tts_sr)
            self._last_spoken_reply = reply
        self._enter_follow_up_listening()

    _ECHO_STRIP_RE = re.compile(r"[\s，。！？,.!?、；;：:\"'\"'（）()…—~·-]+")

    @staticmethod
    def _is_echo_transcript(text: str, last_reply: str | None) -> bool:
        """续听回声判定：归一化（去标点/空白、小写）后互为子串或相似度 ≥0.6。

        只拾到播报开头（子串）、混响拖尾多出尾巴（反向子串）、ASR 个别字
        转写差异（相似度）都视为回声；`last_reply` 为 None 或任一侧归一化
        后为空时不判回声（无从比较）。
        """
        if not last_reply:
            return False
        a = VoicePipeline._ECHO_STRIP_RE.sub("", text).lower()
        b = VoicePipeline._ECHO_STRIP_RE.sub("", last_reply).lower()
        if not a or not b:
            return False
        if a in b or b in a:
            return True
        return SequenceMatcher(None, a, b).ratio() >= 0.6

    @staticmethod
    def _check_hotword(text: str, cfg: VoiceConfig) -> str | None:
        """首轮热词校验：文本中包含任一唤醒词别名则通过，返回去除唤醒词后的文本；否则返回 None。"""
        lowered = text.lower().strip()
        aliases = [cfg.wake_word.lower()] + [a.lower() for a in cfg.wake_aliases]
        for alias in aliases:
            idx = lowered.find(alias)
            if idx >= 0:
                cleaned = (text[:idx] + text[idx + len(alias) :]).strip(" ，。！？,.!?")
                return cleaned if cleaned.strip() else "我在"
        return None

    def _reset_wake_state(self) -> None:
        """回到 WAKE_LISTENING 前重置唤醒后端状态（冷却+重新检测）。"""
        reset = getattr(self._wake, "reset", None)
        if callable(reset):
            try:
                reset()
            except Exception:
                logger.exception("wake.reset() 调用失败，已忽略")
        self._is_first_turn = True

    def _enter_follow_up_listening(self) -> None:
        """播报完毕进入续听窗口：设置超时截止时间。"""
        self._follow_up_deadline = time.monotonic() + self._config.follow_up_timeout_s
        self._set_state(PipelineState.FOLLOW_UP_LISTENING)

    def _handle_follow_up(self, frame: bytes) -> None:
        """FOLLOW_UP_LISTENING 帧处理：VAD 检测语音直接进录音，超时回等待唤醒。"""
        if time.monotonic() >= self._follow_up_deadline:
            self._reset_conversation()
            self._reset_wake_state()
            self._set_state(PipelineState.WAKE_LISTENING)
            return
        if self._vad.is_speech(frame, self._config.sample_rate):
            self._begin_recording(initial_frame=frame)

    def _reset_conversation(self) -> None:
        """续听超时后重置对话历史（鸭子调用 agent.reset）。"""
        reset = getattr(self._agent, "reset", None)
        if callable(reset):
            try:
                reset()
            except Exception:
                logger.exception("agent.reset() 调用失败，已忽略")
