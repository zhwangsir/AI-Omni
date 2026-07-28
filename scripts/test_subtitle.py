#!/usr/bin/env python3
"""完整状态流驱动：idle → speaking，验证字幕显示"""
import json, time, os
from pathlib import Path

STATE_PATH = Path.home() / ".ai-omni" / "state" / "voice-status.json"

def write_state(state, running, reply=None, reply_seq=None):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    data = {"state": state, "running": running, "fake_mode": True, "ts": time.time()}
    if reply is not None:
        data["reply"] = reply
    if reply_seq is not None:
        data["reply_seq"] = reply_seq
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_PATH)
    print(f"  → state={state} reply={'有' if reply else '无'} reply_seq={reply_seq}")

print("=== 1. 先回到 idle（2秒）===")
write_state("idle", False)
time.sleep(2)

print("\n=== 2. 触发 speaking（带字幕，reply_seq=101）===")
write_state("speaking", True,
    reply="贾维斯系统已全面上线。所有传感器数据正常，全息交互界面已激活。随时等候您的指令，先生。",
    reply_seq=101)
print("\n等待 2.5 秒让 UI 更新和过渡完成...")
time.sleep(2.5)
print("可以截图了。")
