"""语音管道共享状态文件（M5.4 W1 数据通道重构）。

宿主常驻管道把每次状态迁移原子写入 ``~/.ai-omni/state/voice-status.json``；
外部观察者（omni-hud Tauri 侧 notify watcher、CLI ``status`` 回退）读该文件，
替代"每秒 spawn CLI 独立进程"的轮询——独立进程读不到宿主进程内管道，
而状态文件是跨进程可见的共享通道。

双向容错约定：

- 写失败静默降级——状态文件只是观察通道，绝不能拖垮语音管道；
- 读遇缺失/损坏/schema 不符返回 ``None``——调用方按 idle 缺省处理。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# M12 灵动岛双形态：活跃语音状态集合 → Full cover-display；
# 不在此集合内的状态（idle / None / 未知）→ Mini 顶部浮窗。
# 用 frozenset 实现O(1) 查找；新增活跃态在此登记即可被推导为 Full。
_ACTIVE_VOICE_STATES: frozenset[str] = frozenset(
    {
        "wake_listening",
        "recording",
        "transcribing",
        "thinking",
        "speaking",
        "tool_using",
        "follow_up_listening",
    }
)


def derive_window_mode(state: str | None) -> str:
    """根据语音管道状态推导 HUD 窗口形态（M12 灵动岛双形态）。

    推导规则：

    - ``idle`` → ``mini``：顶部浮窗，让出桌面视野，仅显示状态文字
      （如「雪莉 · 待命」）；
    - 活跃态（``wake_listening`` / ``recording`` / ``transcribing`` /
      ``thinking`` / ``speaking`` / ``tool_using`` / ``follow_up_listening``）
      → ``full``：cover-display 全屏覆盖（FieldStage + CaptionLayer + WellZone）。

    ``None`` / 未知状态默认 ``full``——安全态，避免浮窗遮挡可能进行的活跃交互。
    """
    if state in _ACTIVE_VOICE_STATES:
        return "full"
    if state == "idle":
        return "mini"
    # None / 未知状态默认 Full（安全态）
    return "full"


class VoiceStateFile:
    """语音状态文件的写入器（管道侧）与读取器（tools/CLI 侧）。

    写入采用 临时文件 + ``os.replace`` 原子替换，读者不会读到半截 JSON。
    """

    #: 默认状态文件路径（测试经 monkeypatch 重定向到 tmp，真实家目录零接触）
    DEFAULT_PATH: Path = Path.home() / ".ai-omni" / "state" / "voice-status.json"

    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path is not None else Path(self.DEFAULT_PATH)
        # M6.3 修复：reply 粘性状态。tts_muted 下 SPEAKING 帧转瞬即逝，紧随的
        # WAKE_LISTENING 写入若不携带 reply，watcher 事件合并后快照里的回复被
        # 覆盖丢失 → HUD/OpenTalking 永远读不到。故一次携带后，后续 bare write
        # 保留最近回复；reply_seq 每显式携带一次递增，相同文本的新一轮回复
        # 下游（Rust watcher 去抖 / 前端 bridge 去重）也能区分为两个轮次。
        self._last_reply: str | None = None
        self._reply_seq: int = 0
        # M6.3 续修：跨进程续号。omni_voice 重启后新实例 seq 若从 0 归零，
        # 可能撞上 bridge 已见序号（同为 1）→ 重启后首轮回复被 !== 去重吞掉。
        # 故初始化时沿用状态文件已有 reply_seq，保证序号跨进程单调递增。
        # 注意只续号、不继承旧回复粘性（_last_reply 仍从 None 起）：
        # 旧轮次文本不应冒充新进程的状态。
        snapshot = self.read(self._path)
        if snapshot is not None:
            seq = snapshot.get("reply_seq")
            if isinstance(seq, int) and seq > 0:
                self._reply_seq = seq

    @property
    def path(self) -> Path:
        """当前绑定的状态文件路径。"""
        return self._path

    def write(
        self,
        state: str,
        *,
        running: bool,
        fake_mode: bool,
        reply: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """原子写入一份状态快照；任何失败静默吞掉并尽量清理临时文件。

        ``reply`` 为 M6.3 可选字段：为 str 时随快照写入并刷新粘性状态、
        ``reply_seq`` 递增；为 None 时语义为「本次未指定」——若此前携带过
        reply 则快照继续附带最近回复与序号（粘性），从未携带过则两个键
        均不出现，与 M5.4 旧格式完全一致。

        M12 灵动岛双形态：每次写入自动从 ``state`` 推导 ``window_mode`` 字段
        （``mini`` / ``full``）并随快照写入——Rust voice_watch 透传到前端，
        前端据此渲染 MiniBar 或 Full cover-display。

        M13.2 Agent 可视化：``tool_calls`` 为可选字段——为 list 时（含空数组）
        随快照写入（覆盖旧值，便于清空一轮结束后的工具列表）；为 None 时
        快照不含该键（与 M12 旧格式完全兼容，向后兼容）。与 ``reply`` 不同，
        ``tool_calls`` **不粘性**——每次写入都按本次入参决定是否携带，
        避免上一轮的工具列表误显示到下一轮。
        """
        if reply is not None:
            self._last_reply = reply
            self._reply_seq += 1
        tmp: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "state": state,
                "running": bool(running),
                "fake_mode": bool(fake_mode),
                "ts": time.time(),
                "window_mode": derive_window_mode(state),
            }
            if self._last_reply is not None:
                payload["reply"] = self._last_reply
                payload["reply_seq"] = self._reply_seq
            # M13.2：tool_calls 是 list（含空数组）即写入；None 则不带该键。
            if tool_calls is not None:
                payload["tool_calls"] = list(tool_calls)
            tmp = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:  # noqa: BLE001 - 观察通道静默降级，不拖垮管道
            logger.debug("状态文件写入失败（已忽略）: %s", self._path, exc_info=True)
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

    @classmethod
    def read(cls, path: Path | None = None) -> dict[str, Any] | None:
        """读取并校验状态快照；缺失/损坏/schema 不符一律返回 None。

        M6.3：``reply`` 仅当快照中为字符串时才带出到返回 dict；
        缺省或非字符串一律**不含 reply 键**（调用方用 ``data.get("reply")``
        判空），既有 ``{state,running,fake_mode,ts}`` schema 校验不变。
        ``reply_seq``（轮次序号）同理：仅当为 int（非 bool）时带出。

        M12：``window_mode`` 仅当快照中为字符串时才带出；缺省或非字符串
        一律**不含 window_mode 键**（调用方按 Full 缺省处理，安全态）。

        M13.2：``tool_calls`` 仅当快照中为 list 时才带出；list 中每个元素
        必须是 dict（非 dict 元素被过滤掉）。空 list 仍带出（key 存在值为 []，
        表示「本轮已结束」）。非 list 一律不含该键（向后兼容旧格式）。
        """
        target = Path(path) if path is not None else Path(cls.DEFAULT_PATH)
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # 文件不存在/不可读/JSON 损坏
            return None
        if not cls._schema_valid(payload):
            return None
        result: dict[str, Any] = {
            "state": payload["state"],
            "running": payload["running"],
            "fake_mode": payload["fake_mode"],
            "ts": float(payload["ts"]),
        }
        reply = payload.get("reply")
        if isinstance(reply, str):
            result["reply"] = reply
        reply_seq = payload.get("reply_seq")
        if isinstance(reply_seq, int) and not isinstance(reply_seq, bool):
            result["reply_seq"] = reply_seq
        window_mode = payload.get("window_mode")
        if isinstance(window_mode, str):
            result["window_mode"] = window_mode
        # M13.2：tool_calls 容错解析——list 且元素 dict 才保留，其余过滤。
        tool_calls_raw = payload.get("tool_calls")
        if isinstance(tool_calls_raw, list):
            result["tool_calls"] = [c for c in tool_calls_raw if isinstance(c, dict)]
        return result

    @staticmethod
    def _schema_valid(payload: Any) -> bool:
        """schema 校验：state 非空字符串、running/fake_mode 布尔、ts 数值。"""
        if not isinstance(payload, dict):
            return False
        state = payload.get("state")
        running = payload.get("running")
        fake_mode = payload.get("fake_mode")
        ts = payload.get("ts")
        if not isinstance(state, str) or not state:
            return False
        if not isinstance(running, bool) or not isinstance(fake_mode, bool):
            return False
        # bool 是 int 子类，需显式排除；int 时间戳兼容跨语言写入方
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            return False
        return True


class PipelineStateWriter:
    """``VoiceStateFile`` → 管道 ``state_writer`` 契约适配器。

    管道侧鸭子契约为 ``write(state, running)`` 两参调用；
    ``fake_mode`` 在管道启动时绑定（一次启动周期内不变）。

    M13.2 扩展：``set_tool_calls`` 持有当前轮次进行中的工具调用列表，
    后续 ``write`` / ``write_with_reply`` 自动透传到状态文件——管道侧
    只需在工具开始/结束时调一次 ``set_tool_calls``，状态迁移的写入
    自动带上当前 tool_calls。传 None 表示「不写该键」（与旧格式兼容），
    传 [] 表示「显式清空」（一轮结束后覆盖旧值）。
    """

    def __init__(self, state_file: VoiceStateFile | None = None, *, fake_mode: bool = False):
        self._state_file = state_file or VoiceStateFile()
        self._fake_mode = fake_mode
        # M13.2：None 表示「不写 tool_calls 键」（默认行为，向后兼容）；
        # 一旦管道调过 set_tool_calls 即转为 list（含空数组）。
        self._tool_calls: list[dict[str, Any]] | None = None

    def write(self, state: str, running: bool) -> None:
        """按管道契约写入；底层失败由 VoiceStateFile 静默降级。"""
        self._state_file.write(
            state,
            running=running,
            fake_mode=self._fake_mode,
            tool_calls=self._tool_calls,
        )

    def write_with_reply(self, state: str, running: bool, reply: str) -> None:
        """M6.3 可选扩展：携带本轮回复文本写入（仅 SPEAKING 迁移使用）。

        最小侵入方案：管道鸭子契约保持 ``write(state, running)`` 两参不变，
        reply 经本可选方法下发——管道检测到 writer 具备此方法才调用，
        旧式两参 writer 零感知、自动回退。

        M13.2：同时透传当前 ``tool_calls``——SPEAKING 快照可同时包含
        本轮回复与已完成的工具调用列表，前端 AgentPanel 据此渲染完整轮次。
        """
        self._state_file.write(
            state,
            running=running,
            fake_mode=self._fake_mode,
            reply=reply,
            tool_calls=self._tool_calls,
        )

    def set_tool_calls(self, calls: list[dict[str, Any]] | None) -> None:
        """M13.2：设置当前轮次的工具调用列表，后续 write 自动透传。

        - ``calls`` 为 list（含空数组）→ 后续写入携带 tool_calls 字段；
        - ``calls`` 为 None → 后续写入不含该键（与旧格式完全兼容）。

        管道在 ``_on_tool_start`` / ``_on_tool_end`` 时调用本方法更新列表；
        ``_set_state(SPEAKING)`` 前显式传 ``[]`` 清空，避免下一轮残留。
        """
        self._tool_calls = list(calls) if calls is not None else None
