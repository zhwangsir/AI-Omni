#!/usr/bin/env python3
"""端到端冒烟驱动 + 自动截图：完整状态流验证"""
from __future__ import annotations
import json, os, time, subprocess
from pathlib import Path

STATE_PATH = Path.home() / ".ai-omni" / "state" / "voice-status.json"
SHOTS_DIR = Path("/tmp/hud_smoke_shots")
SHOTS_DIR.mkdir(parents=True, exist_ok=True)

def atomic_write(payload: dict) -> None:
    tmp = STATE_PATH.with_name(f".{STATE_PATH.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_PATH)

def write_state(state: str, running: bool, *, reply: str | None = None, reply_seq: int | None = None) -> None:
    payload: dict = {"state": state, "running": running, "fake_mode": True, "ts": time.time()}
    if reply is not None:
        payload["reply"] = reply
        payload["reply_seq"] = reply_seq if reply_seq is not None else 1
    atomic_write(payload)
    print(f"[{state}] running={running} reply={'有' if reply else '无'}")

def take_screenshot(name: str) -> None:
    path = SHOTS_DIR / f"{name}.png"
    subprocess.run(["screencapture", "-x", str(path)], check=True)
    print(f"  📸 截图: {path.name}")

def main() -> int:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    seq = 1000

    print("=" * 60)
    print("  AI-Omni M7 全息 HUD 端到端冒烟测试")
    print("=" * 60)

    # 1. idle
    print("\n[1/6] idle 初始态（2s）")
    write_state("idle", False)
    time.sleep(2)
    take_screenshot("01_idle")

    # 2. wake_listening
    print("\n[2/6] wake_listening 唤醒态（1.5s）")
    write_state("wake_listening", True)
    time.sleep(1.5)
    take_screenshot("02_wake")

    # 3. recording
    print("\n[3/6] recording 录音态（3s）")
    write_state("recording", True)
    time.sleep(2)
    take_screenshot("03_recording_mid")
    time.sleep(1)

    # 4. transcribing
    print("\n[4/6] transcribing 转写态（1.5s）")
    write_state("transcribing", True)
    time.sleep(1.5)
    take_screenshot("04_transcribing")

    # 5. thinking
    print("\n[5/6] thinking 思考态（2s）")
    write_state("thinking", True)
    time.sleep(2)
    take_screenshot("05_thinking")

    # 6. speaking with subtitle
    seq += 1
    reply = "系统全部在线，反应堆核心输出稳定。正在扫描周边环境，所有传感器数据正常。随时听候您的指令，先生。"
    print(f"\n[6/6] speaking 回复态（6s，字幕: {reply[:25]}...）")
    write_state("speaking", True, reply=reply, reply_seq=seq)
    time.sleep(1)
    take_screenshot("06_speaking_early")
    time.sleep(2)
    take_screenshot("07_speaking_mid")
    time.sleep(3)

    # back to idle
    print("\n[回到 idle]")
    write_state("idle", False)
    time.sleep(1.5)
    take_screenshot("08_back_to_idle")

    print("\n" + "=" * 60)
    print(f"  冒烟完成！截图保存在: {SHOTS_DIR}")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
