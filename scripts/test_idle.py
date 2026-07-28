#!/usr/bin/env python3
"""验证 idle 后字幕消失"""
import json, os, time, subprocess
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

print("写入 idle，等待 4 秒让字幕完全消失...")
write_state("idle", False)
time.sleep(4)
subprocess.run(["screencapture", "-x", "/tmp/hud_idle_clean.png"], check=True)
print("截图完成: /tmp/hud_idle_clean.png")
