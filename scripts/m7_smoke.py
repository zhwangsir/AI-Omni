"""M7 全息 HUD 冒烟驱动：模拟真实语音交互全状态流。

直接原子写入 ~/.ai-omni/state/voice-status.json，
驱动 Tauri notify watcher → 前端 mood/字幕/HUD 状态变化。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

STATE_PATH = Path.home() / ".ai-omni" / "state" / "voice-status.json"


def atomic_write(payload: dict) -> None:
    tmp = STATE_PATH.with_name(f".{STATE_PATH.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_PATH)
    print(f"  → state={payload['state']} running={payload['running']} ts={payload['ts']:.1f}")


def write_state(state: str, running: bool, *, reply: str | None = None, reply_seq: int | None = None) -> None:
    payload: dict = {
        "state": state,
        "running": running,
        "fake_mode": True,
        "ts": time.time(),
    }
    if reply is not None:
        payload["reply"] = reply
        payload["reply_seq"] = reply_seq if reply_seq is not None else 1
    atomic_write(payload)


def main() -> int:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    seq = 0

    print("=== M7 全息 HUD 冒烟驱动 ===\n")

    # 1. idle（初始态，持续 2s）
    print("[1/6] idle（初始态，粒子平静漂移）")
    write_state("idle", False)
    time.sleep(2)

    # 2. wake_listening（唤醒词检测到，持续 1s）
    print("[2/6] wake_listening（唤醒态，粒子微活跃）")
    write_state("wake_listening", True)
    time.sleep(1)

    # 3. recording（录音中，持续 3s）
    print("[3/6] recording（录音态，粒子活跃流动）")
    write_state("recording", True)
    time.sleep(3)

    # 4. transcribing（转写中，持续 1.5s）
    print("[4/6] transcribing（转写态）")
    write_state("transcribing", True)
    time.sleep(1.5)

    # 5. thinking（思考中，持续 2s）
    print("[5/6] thinking（思考态）")
    write_state("thinking", True)
    time.sleep(2)

    # 6. speaking（回复中，带字幕，持续 5s）
    seq += 1
    reply_text = "系统已就绪，全息显示场域正在运行。所有传感器数据正常，随时待命。"
    print(f"[6/6] speaking（回复态，字幕显示：{reply_text[:20]}...）")
    write_state("speaking", True, reply=reply_text, reply_seq=seq)
    time.sleep(5)

    # 回到 idle
    print("\n=== 回到 idle ===")
    write_state("idle", False)
    time.sleep(1)

    print("\n=== 冒烟驱动完成 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
