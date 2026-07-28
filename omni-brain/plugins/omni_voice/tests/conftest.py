"""omni_voice 测试公共夹具：状态/控制文件默认路径隔离。

VoiceStateFile.DEFAULT_PATH 指向真实家目录 ~/.ai-omni/state/voice-status.json；
VoiceControlFile.DEFAULT_PATH 指向 ~/.ai-omni/state/voice-control.json（M7.5）；
测试绝不读写这两个路径——统一重定向到每个测试独立的 tmp 目录，
避免宿主机真实运行的残留文件污染测试，也避免测试误写真实状态。
"""

from __future__ import annotations

import pytest

from omni_voice.control_file import VoiceControlFile
from omni_voice.state_file import VoiceStateFile


@pytest.fixture(autouse=True)
def _isolate_state_file_path(tmp_path, monkeypatch):
    """重定向状态/控制文件默认路径到 tmp（真实家目录零接触）。"""
    monkeypatch.setattr(
        VoiceStateFile,
        "DEFAULT_PATH",
        tmp_path / ".ai-omni" / "state" / "voice-status.json",
    )
    monkeypatch.setattr(
        VoiceControlFile,
        "DEFAULT_PATH",
        tmp_path / ".ai-omni" / "state" / "voice-control.json",
    )
