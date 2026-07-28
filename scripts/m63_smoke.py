"""M6.3 真机冒烟驱动 v2（一次性，跑完即删）。

改进：monkeypatch PipelineStateWriter 全量记录每次写（不错过快速迁移）；
收集事件总线全部事件；同进程设 tts_muted。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "omni-brain/plugins")

from omni_voice import tools  # noqa: E402
from omni_voice.cli import _script_fake_demo  # noqa: E402
from omni_voice.state_file import PipelineStateWriter as _RealPSW  # noqa: E402

writes: list[dict] = []
events: list[dict] = []


class _SpyPSW(_RealPSW):
    def write_with_reply(self, state: str, running: bool, reply: str | None = None) -> None:  # noqa: ANN001
        writes.append({"state": state, "running": running, "reply": reply, "ts": time.time()})
        return super().write_with_reply(state, running, reply)

    def write(self, state: str, running: bool) -> None:  # noqa: ANN001
        writes.append({"state": state, "running": running, "reply": None, "ts": time.time()})
        return super().write(state, running)


class _EventCollector:
    def publish(self, event_type: str, payload: dict) -> None:
        events.append({"type": event_type, "payload": payload, "ts": time.time()})


tools.PipelineStateWriter = _SpyPSW  # type: ignore[attr-defined]


def main() -> int:
    print("[smoke] set tts_muted:", tools.voice_config(action="set", key="tts_muted", value=True))
    _script_fake_demo(tools._runtime, scenario="run")
    tools._runtime.event_publisher = _EventCollector()

    started = json.loads(tools.voice_pipeline_start(fake=True))
    print("[smoke] pipeline_start:", json.dumps(started, ensure_ascii=False))
    if not started["ok"]:
        return 1

    time.sleep(6)
    print("[smoke] pipeline_stop:", tools.voice_pipeline_stop())

    print("[smoke] writes:")
    for w in writes:
        print("   ", json.dumps(w, ensure_ascii=False))
    print("[smoke] events:")
    for e in events:
        print("   ", json.dumps(e, ensure_ascii=False))

    reply_writes = [w for w in writes if w["reply"]]
    ok = bool(reply_writes) and reply_writes[0]["state"] == "speaking"
    muted_no_crash = True
    print("[smoke] RESULT:", "PASS" if ok and muted_no_crash else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
