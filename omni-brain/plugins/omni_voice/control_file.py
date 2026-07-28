"""语音管道控制文件（M7.5 打断反向通道）。

与状态文件（state_file.py，管道 → 外部）对称的**反向**通道（外部 → 管道）：
外部进程（HUD Rust 侧、CLI）把 ``{"action": "interrupt", "seq": N, "ts": ...}``
原子写入 ``~/.ai-omni/state/voice-control.json``；宿主常驻管道轮询消费，
停止当前 TTS 播报并回到等待唤醒。常驻管道跑在宿主进程内，外部进程无法
直达（W1 教训），控制文件是跨进程可见的唯一反向通道。

双向容错约定（同 state_file）：

- 写失败静默降级——控制文件只是指令通道，绝不能拖垮调用方；
- 读遇缺失/损坏/schema 不符返回 ``None``——管道按「无待消费指令」处理。

``seq`` 跨进程续号（同 state_file 的 reply_seq 续号模式）：CLI/HUD 每次
是新进程，新实例初始化时沿用文件既有序号，保证序号单调递增——管道侧以
``> 已消费序号`` 判新指令，归零会撞已消费序号导致打断丢失。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class VoiceControlFile:
    """控制文件的写入器（外部进程/CLI 侧）与读取器（管道侧）。

    写入采用 临时文件 + ``os.replace`` 原子替换，读者不会读到半截 JSON。
    """

    #: 默认控制文件路径（测试经 monkeypatch 重定向到 tmp，真实家目录零接触）
    DEFAULT_PATH: Path = Path.home() / ".ai-omni" / "state" / "voice-control.json"

    #: 当前支持的控制动作
    ACTION_INTERRUPT = "interrupt"

    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path is not None else Path(self.DEFAULT_PATH)
        # 跨进程续号：初始化沿用文件既有 seq；文件缺失/损坏/schema 不符从 0 起
        self._seq = 0
        snapshot = self.read(self._path)
        if snapshot is not None:
            self._seq = snapshot["seq"]

    @property
    def path(self) -> Path:
        """当前绑定的控制文件路径。"""
        return self._path

    @property
    def last_seq(self) -> int:
        """最近一次 ``interrupt()`` 写入的序号（初始化续号时为文件既有序号）。"""
        return self._seq

    def interrupt(self) -> None:
        """原子写入一条 interrupt 指令；任何失败静默吞掉并尽量清理临时文件。"""
        self._seq += 1
        tmp: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "action": self.ACTION_INTERRUPT,
                "seq": self._seq,
                "ts": time.time(),
            }
            tmp = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:  # noqa: BLE001 - 指令通道静默降级，不拖垮调用方
            logger.debug("控制文件写入失败（已忽略）: %s", self._path, exc_info=True)
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

    @classmethod
    def read(cls, path: Path | None = None) -> dict[str, Any] | None:
        """读取并校验控制指令；缺失/损坏/schema 不符一律返回 None。

        schema 约定：``action`` 必须为 ``"interrupt"``、``seq`` 必须为 int
        （bool 是 int 子类，显式排除）；``ts`` 缺失/非数值时容错归 0.0。
        """
        target = Path(path) if path is not None else Path(cls.DEFAULT_PATH)
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # 文件不存在/不可读/JSON 损坏
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("action") != cls.ACTION_INTERRUPT:
            return None
        seq = payload.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int):
            return None
        ts = payload.get("ts")
        return {
            "action": cls.ACTION_INTERRUPT,
            "seq": seq,
            "ts": float(ts)
            if isinstance(ts, (int, float)) and not isinstance(ts, bool)
            else 0.0,
        }
