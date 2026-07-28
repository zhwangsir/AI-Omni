"""VoiceControlFile 测试（M7.5 打断反向通道）：原子写、schema 容错读、跨进程续号。

全部落在 tmp_path，不触碰真实家目录（conftest 同时把默认路径重定向到 tmp）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from omni_voice.control_file import VoiceControlFile


@pytest.fixture()
def control_path(tmp_path) -> Path:
    """每个测试独立的控制文件路径（目录未创建，由写入方负责）。"""
    return tmp_path / "state" / "voice-control.json"


class TestInterruptWrite:
    def test_interrupt_creates_dirs_and_schema(self, control_path):
        cf = VoiceControlFile(control_path)
        cf.interrupt()
        payload = json.loads(control_path.read_text(encoding="utf-8"))
        assert payload["action"] == "interrupt"
        assert payload["seq"] == 1
        assert payload["ts"] == pytest.approx(time.time(), abs=5)

    def test_interrupt_seq_increments_per_call(self, control_path):
        cf = VoiceControlFile(control_path)
        cf.interrupt()
        cf.interrupt()
        cf.interrupt()
        payload = json.loads(control_path.read_text(encoding="utf-8"))
        assert payload["seq"] == 3
        assert cf.last_seq == 3

    def test_interrupt_leaves_no_tmp_files(self, control_path):
        """原子写（tmp + os.replace）完成后目录里只有目标文件本身。"""
        VoiceControlFile(control_path).interrupt()
        names = [p.name for p in control_path.parent.iterdir()]
        assert names == ["voice-control.json"]

    def test_interrupt_failure_degrades_silently(self, tmp_path):
        """父路径被普通文件占用 → mkdir 失败 → 静默吞掉，绝不向上抛。"""
        blocker = tmp_path / "blocked"
        blocker.write_text("x", encoding="utf-8")
        cf = VoiceControlFile(blocker / "sub" / "voice-control.json")
        cf.interrupt()  # 不抛异常即通过
        assert not (blocker / "sub").exists()

    def test_default_path_uses_class_default(self):
        """缺省构造走 DEFAULT_PATH（conftest 已重定向到 tmp，不碰真实家目录）。"""
        cf = VoiceControlFile()
        assert cf.path == VoiceControlFile.DEFAULT_PATH
        assert cf.path.name == "voice-control.json"


class TestRead:
    def test_read_roundtrip(self, control_path):
        VoiceControlFile(control_path).interrupt()
        data = VoiceControlFile.read(control_path)
        assert data is not None
        assert data["action"] == "interrupt"
        assert data["seq"] == 1
        assert isinstance(data["ts"], float)

    def test_read_default_path_roundtrip(self):
        """read() 缺省走 DEFAULT_PATH（conftest 隔离后的 tmp 路径）。"""
        VoiceControlFile().interrupt()
        data = VoiceControlFile.read()
        assert data is not None
        assert data["action"] == "interrupt"
        assert data["seq"] == 1

    def test_read_missing_file_returns_none(self, control_path):
        assert VoiceControlFile.read(control_path) is None

    def test_read_bad_json_returns_none(self, control_path):
        control_path.parent.mkdir(parents=True)
        control_path.write_text("not json {{{", encoding="utf-8")
        assert VoiceControlFile.read(control_path) is None

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            ["not", "a", "dict"],
            {"action": "stop", "seq": 1, "ts": 1.0},  # action 非 interrupt
            {"action": "interrupt"},  # 缺 seq
            {"action": "interrupt", "seq": True},  # seq bool（int 子类，必须排除）
            {"action": "interrupt", "seq": "3"},  # seq 类型错
            {"action": "interrupt", "seq": 1.5},  # seq 非 int
            {"seq": 1},  # 缺 action
        ],
    )
    def test_read_schema_violations_return_none(self, control_path, payload):
        control_path.parent.mkdir(parents=True)
        control_path.write_text(json.dumps(payload), encoding="utf-8")
        assert VoiceControlFile.read(control_path) is None


class TestSeqContinuation:
    """跨进程续号（同 state_file 的 reply_seq 续号模式）。

    CLI/HUD 每次是新进程，新实例若从 0 归零，管道侧以 > 判未消费时会
    把新打断误判为已消费旧序号 → 打断丢失。故初始化沿用文件既有 seq。
    """

    def test_new_instance_continues_seq_from_existing_file(self, control_path):
        """模拟进程重启：同路径新实例的下一次 interrupt seq = 既有序号 + 1。"""
        cf1 = VoiceControlFile(control_path)
        cf1.interrupt()
        cf1.interrupt()
        cf2 = VoiceControlFile(control_path)
        cf2.interrupt()
        payload = json.loads(control_path.read_text(encoding="utf-8"))
        assert payload["seq"] == 3
        assert cf2.last_seq == 3

    def test_continuation_with_missing_file_starts_at_one(self, control_path):
        cf = VoiceControlFile(control_path)
        cf.interrupt()
        payload = json.loads(control_path.read_text(encoding="utf-8"))
        assert payload["seq"] == 1

    def test_continuation_with_corrupt_file_starts_at_one(self, control_path):
        """文件损坏（非 JSON）：从 1 起号，不抛错。"""
        control_path.parent.mkdir(parents=True, exist_ok=True)
        control_path.write_text("not json{", encoding="utf-8")
        cf = VoiceControlFile(control_path)
        cf.interrupt()
        payload = json.loads(control_path.read_text(encoding="utf-8"))
        assert payload["seq"] == 1

    def test_continuation_with_seqless_file_starts_at_one(self, control_path):
        """无 seq 键的旧/脏文件（schema 校验不过）：从 1 起号。"""
        control_path.parent.mkdir(parents=True, exist_ok=True)
        control_path.write_text(
            json.dumps({"action": "interrupt", "ts": 1.0}), encoding="utf-8"
        )
        cf = VoiceControlFile(control_path)
        cf.interrupt()
        payload = json.loads(control_path.read_text(encoding="utf-8"))
        assert payload["seq"] == 1
