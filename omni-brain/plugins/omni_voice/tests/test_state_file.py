"""VoiceStateFile 测试：原子写、schema 校验读、容错降级。

全部落在 tmp_path，不触碰真实家目录（conftest 同时把默认路径重定向到 tmp）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from omni_voice.state_file import PipelineStateWriter, VoiceStateFile


@pytest.fixture()
def state_path(tmp_path) -> Path:
    """每个测试独立的状态文件路径（目录未创建，由写入方负责）。"""
    return tmp_path / "state" / "voice-status.json"


class TestWrite:
    def test_write_creates_dirs_and_schema(self, state_path):
        f = VoiceStateFile(state_path)
        f.write("speaking", running=True, fake_mode=True)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["state"] == "speaking"
        assert payload["running"] is True
        assert payload["fake_mode"] is True
        assert payload["ts"] == pytest.approx(time.time(), abs=5)

    def test_write_leaves_no_tmp_files(self, state_path):
        """原子写（tmp + os.replace）完成后目录里只有目标文件本身。"""
        f = VoiceStateFile(state_path)
        f.write("idle", running=False, fake_mode=False)
        names = [p.name for p in state_path.parent.iterdir()]
        assert names == ["voice-status.json"]

    def test_write_overwrites_previous_state(self, state_path):
        f = VoiceStateFile(state_path)
        f.write("recording", running=True, fake_mode=False)
        f.write("thinking", running=True, fake_mode=False)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["state"] == "thinking"

    def test_write_failure_degrades_silently(self, tmp_path):
        """父路径被普通文件占用 → mkdir 失败 → 静默吞掉，绝不向上抛。"""
        blocker = tmp_path / "blocked"
        blocker.write_text("x", encoding="utf-8")
        f = VoiceStateFile(blocker / "sub" / "voice-status.json")
        f.write("idle", running=False, fake_mode=False)  # 不抛异常即通过
        assert not (blocker / "sub").exists()

    def test_default_path_uses_class_default(self):
        """缺省构造走 DEFAULT_PATH（conftest 已重定向到 tmp，不碰真实家目录）。"""
        f = VoiceStateFile()
        assert f.path == VoiceStateFile.DEFAULT_PATH
        assert f.path.name == "voice-status.json"


class TestRead:
    def test_read_roundtrip(self, state_path):
        VoiceStateFile(state_path).write("wake_listening", running=True, fake_mode=False)
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["state"] == "wake_listening"
        assert data["running"] is True
        assert data["fake_mode"] is False
        assert isinstance(data["ts"], float)

    def test_read_default_path_roundtrip(self):
        """read() 缺省走 DEFAULT_PATH（conftest 隔离后的 tmp 路径）。"""
        VoiceStateFile().write("speaking", running=True, fake_mode=True)
        data = VoiceStateFile.read()
        assert data is not None
        assert data["state"] == "speaking"
        assert data["fake_mode"] is True

    def test_read_missing_file_returns_none(self, state_path):
        assert VoiceStateFile.read(state_path) is None

    def test_read_bad_json_returns_none(self, state_path):
        state_path.parent.mkdir(parents=True)
        state_path.write_text("not json {{{", encoding="utf-8")
        assert VoiceStateFile.read(state_path) is None

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"state": "idle"},  # 缺 running/fake_mode/ts
            {"state": "", "running": True, "fake_mode": False, "ts": 1.0},  # 空 state
            {"state": 42, "running": True, "fake_mode": False, "ts": 1.0},  # state 类型错
            {"state": "idle", "running": "yes", "fake_mode": False, "ts": 1.0},
            {"state": "idle", "running": True, "fake_mode": 1, "ts": 1.0},
            {"state": "idle", "running": True, "fake_mode": False, "ts": "now"},
            ["not", "a", "dict"],
        ],
    )
    def test_read_schema_violations_return_none(self, state_path, payload):
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        assert VoiceStateFile.read(state_path) is None


class TestWriteReply:
    """M6.3：reply 为可选字段——为 str 时写入；全新实例未写过 reply 时 payload 不带该键。

    注意：一旦某次写入携带过 reply，后续写入走粘性语义（见 TestStickyReply）。
    """

    def test_write_with_reply_includes_key(self, state_path):
        f = VoiceStateFile(state_path)
        f.write("speaking", running=True, fake_mode=False, reply="本轮回复文本")
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["state"] == "speaking"
        assert payload["reply"] == "本轮回复文本"

    def test_write_without_reply_omits_key(self, state_path):
        f = VoiceStateFile(state_path)
        f.write("idle", running=False, fake_mode=False)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert "reply" not in payload

    def test_write_reply_none_explicitly_omits_key(self, state_path):
        f = VoiceStateFile(state_path)
        f.write("thinking", running=True, fake_mode=False, reply=None)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert "reply" not in payload


class TestReadReply:
    """M6.3：read 对 reply 宽容——是字符串则带出，缺省/非字符串则不含 reply 键。"""

    def test_read_roundtrip_with_reply(self, state_path):
        VoiceStateFile(state_path).write(
            "speaking", running=True, fake_mode=False, reply="你好呀"
        )
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["reply"] == "你好呀"

    def test_read_legacy_file_without_reply_omits_key(self, state_path):
        """M5.4 旧格式（无 reply 键）必须可读，返回 dict 不含 reply 键。"""
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps({"state": "idle", "running": False, "fake_mode": False, "ts": 1.0}),
            encoding="utf-8",
        )
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["state"] == "idle"
        assert "reply" not in data

    @pytest.mark.parametrize("bad_reply", [42, True, 1.5, ["列表"], {"嵌套": 1}])
    def test_read_non_string_reply_tolerated(self, state_path, bad_reply):
        """reply 非字符串 → 容错忽略（不拖垮既有 schema 校验），返回不含 reply 键。"""
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps(
                {
                    "state": "speaking",
                    "running": True,
                    "fake_mode": False,
                    "ts": 1.0,
                    "reply": bad_reply,
                }
            ),
            encoding="utf-8",
        )
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["state"] == "speaking"
        assert "reply" not in data


class TestStickyReply:
    """M6.3 修复（tts_muted 字幕丢失）：reply 粘性 + reply_seq 轮次序号。

    根因：tts_muted 下 SPEAKING 帧转瞬即逝，紧随的 WAKE_LISTENING 写入（不带 reply）
    在 watcher 事件合并后覆盖快照 → HUD 永远读不到回复。
    约定：一次 write 携带 reply 后，后续未显式给 reply 的写入仍保留最近一次回复；
    每次显式携带 reply 时 reply_seq 递增——相同文本的新一轮回复下游也能区分轮次。
    """

    def test_reply_sticks_across_subsequent_bare_writes(self, state_path):
        """speaking 携带回复后，紧随的 bare write（wake_listening）快照仍带该回复。"""
        f = VoiceStateFile(state_path)
        f.write("speaking", running=True, fake_mode=False, reply="本轮回复")
        f.write("wake_listening", running=True, fake_mode=False)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["state"] == "wake_listening"
        assert payload["reply"] == "本轮回复"

    def test_explicit_none_reply_does_not_clear_sticky(self, state_path):
        """reply=None 语义为「本次未指定」而非「清除」：粘性依旧。"""
        f = VoiceStateFile(state_path)
        f.write("speaking", running=True, fake_mode=False, reply="保留我")
        f.write("thinking", running=True, fake_mode=False, reply=None)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["reply"] == "保留我"

    def test_new_reply_overwrites_sticky(self, state_path):
        f = VoiceStateFile(state_path)
        f.write("speaking", running=True, fake_mode=False, reply="旧回复")
        f.write("speaking", running=True, fake_mode=False, reply="新回复")
        f.write("wake_listening", running=True, fake_mode=False)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["reply"] == "新回复"

    def test_reply_seq_increments_per_explicit_reply(self, state_path):
        """相同文本的连续两轮回复：seq 递增，下游可区分为两个轮次；粘性携带时序号不变。"""
        f = VoiceStateFile(state_path)
        f.write("speaking", running=True, fake_mode=False, reply="同一句话")
        first = json.loads(state_path.read_text(encoding="utf-8"))
        f.write("wake_listening", running=True, fake_mode=False)
        between = json.loads(state_path.read_text(encoding="utf-8"))
        f.write("speaking", running=True, fake_mode=False, reply="同一句话")
        second = json.loads(state_path.read_text(encoding="utf-8"))
        assert first["reply_seq"] == 1
        assert between["reply_seq"] == 1  # 粘性携带，序号不变
        assert second["reply_seq"] == 2

    def test_no_reply_ever_written_omits_seq_key(self, state_path):
        """全新实例从未写过 reply：reply 与 reply_seq 键均不存在（旧格式完全兼容）。"""
        f = VoiceStateFile(state_path)
        f.write("idle", running=False, fake_mode=False)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert "reply" not in payload
        assert "reply_seq" not in payload


class TestReplySeqContinuation:
    """M6.3 续修：reply_seq 跨进程续号。

    根因：omni_voice 重启后新实例 seq 从 0 归零，而 HUD bridge 以 !== 判新轮次——
    若 bridge 已见序号恰好也是 1，重启后首轮回复 seq=1 被去重吞掉。
    约定：新实例初始化时沿用状态文件已有的 reply_seq（只续号、不继承旧回复
    粘性——旧轮次文本不应冒充新进程的状态）。
    """

    def test_new_instance_continues_seq_from_existing_file(self, state_path):
        """模拟进程重启：同路径新实例的首轮回复 seq = 文件既有序号 + 1，不归零。"""
        f1 = VoiceStateFile(state_path)
        f1.write("speaking", running=True, fake_mode=False, reply="第一轮")
        f2 = VoiceStateFile(state_path)
        f2.write("speaking", running=True, fake_mode=False, reply="第二轮")
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["reply"] == "第二轮"
        assert payload["reply_seq"] == 2

    def test_continuation_with_missing_file_starts_at_one(self, state_path):
        """文件缺失：从 1 起号（现行为不变）。"""
        f = VoiceStateFile(state_path)
        f.write("speaking", running=True, fake_mode=False, reply="x")
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["reply_seq"] == 1

    def test_continuation_with_corrupt_file_starts_at_one(self, state_path):
        """文件损坏（非 JSON）：从 1 起号，不抛错。"""
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("not json{", encoding="utf-8")
        f = VoiceStateFile(state_path)
        f.write("speaking", running=True, fake_mode=False, reply="x")
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["reply_seq"] == 1

    def test_continuation_with_legacy_seqless_file_starts_at_one(self, state_path):
        """旧格式文件（无 reply_seq 键）：从 1 起号。"""
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"state": "idle", "running": False, "fake_mode": True, "ts": 1.0}),
            encoding="utf-8",
        )
        f = VoiceStateFile(state_path)
        f.write("speaking", running=True, fake_mode=False, reply="x")
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["reply_seq"] == 1

    def test_new_instance_does_not_inherit_sticky_reply(self, state_path):
        """只续号、不继承旧回复粘性：新实例 bare write 不携带 reply/reply_seq 键。"""
        f1 = VoiceStateFile(state_path)
        f1.write("speaking", running=True, fake_mode=False, reply="旧回复")
        f2 = VoiceStateFile(state_path)
        f2.write("wake_listening", running=True, fake_mode=False)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert "reply" not in payload
        assert "reply_seq" not in payload


class TestReadReplySeq:
    """read 对 reply_seq 宽容：是 int（非 bool）才带出；缺省/非 int 一律不含该键。"""

    def test_read_roundtrip_with_reply_seq(self, state_path):
        VoiceStateFile(state_path).write(
            "speaking", running=True, fake_mode=False, reply="你好"
        )
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["reply"] == "你好"
        assert data["reply_seq"] == 1

    def test_read_legacy_file_without_seq_omits_key(self, state_path):
        """M6.3 初版格式（有 reply 无 seq）必须可读，返回不含 reply_seq 键。"""
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps(
                {
                    "state": "speaking",
                    "running": True,
                    "fake_mode": False,
                    "ts": 1.0,
                    "reply": "旧格式回复",
                }
            ),
            encoding="utf-8",
        )
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["reply"] == "旧格式回复"
        assert "reply_seq" not in data

    @pytest.mark.parametrize("bad_seq", [True, 1.5, "3", [1], {"n": 1}])
    def test_read_non_int_seq_tolerated(self, state_path, bad_seq):
        """reply_seq 非 int → 容错忽略（bool 是 int 子类，必须显式排除）。"""
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps(
                {
                    "state": "speaking",
                    "running": True,
                    "fake_mode": False,
                    "ts": 1.0,
                    "reply": "回复",
                    "reply_seq": bad_seq,
                }
            ),
            encoding="utf-8",
        )
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["reply"] == "回复"
        assert "reply_seq" not in data


class TestPipelineStateWriter:
    """管道 state_writer 契约适配器：write(state, running) 两参调用，fake_mode 构造时绑定。"""

    def test_adapter_forwards_with_bound_fake_mode(self, state_path):
        writer = PipelineStateWriter(VoiceStateFile(state_path), fake_mode=True)
        writer.write("speaking", True)
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["state"] == "speaking"
        assert data["running"] is True
        assert data["fake_mode"] is True

    def test_adapter_default_file_uses_default_path(self):
        """缺省构造内部用 VoiceStateFile()（DEFAULT_PATH 已被 conftest 隔离）。"""
        writer = PipelineStateWriter(fake_mode=False)
        writer.write("wake_listening", True)
        data = VoiceStateFile.read()
        assert data is not None
        assert data["state"] == "wake_listening"
        assert data["fake_mode"] is False

    def test_adapter_write_failure_degrades_silently(self, tmp_path):
        """底层文件写入失败同样静默（适配器不新增异常路径）。"""
        blocker = tmp_path / "blocked"
        blocker.write_text("x", encoding="utf-8")
        writer = PipelineStateWriter(
            VoiceStateFile(blocker / "sub" / "voice-status.json"), fake_mode=False
        )
        writer.write("idle", False)  # 不抛异常即通过

    def test_write_with_reply_forwards_reply(self, state_path):
        """M6.3 可选扩展方法：携带本轮回复写入，fake_mode 仍为构造期绑定值。"""
        writer = PipelineStateWriter(VoiceStateFile(state_path), fake_mode=True)
        writer.write_with_reply("speaking", True, "回复文本")
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["state"] == "speaking"
        assert data["running"] is True
        assert data["fake_mode"] is True
        assert data["reply"] == "回复文本"

    def test_two_arg_write_still_omits_reply(self, state_path):
        """两参鸭子契约不破坏：普通 write 写出的文件不带 reply 键。"""
        writer = PipelineStateWriter(VoiceStateFile(state_path), fake_mode=False)
        writer.write("thinking", True)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert "reply" not in payload

    def test_write_with_reply_then_bare_write_keeps_sticky(self, state_path):
        """管道契约复现 tts_muted 场景：SPEAKING 经 write_with_reply 写入后，
        紧随的 bare write（WAKE_LISTENING）快照仍携带该回复与轮次序号。"""
        writer = PipelineStateWriter(VoiceStateFile(state_path), fake_mode=True)
        writer.write_with_reply("speaking", True, "本轮回复")
        writer.write("wake_listening", True)
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["state"] == "wake_listening"
        assert data["reply"] == "本轮回复"
        assert data["reply_seq"] == 1


class TestPipelineWindowModeDerivation:
    """M12 灵动岛双形态：管道适配器自动从 state 推导 window_mode。

    验证管道 ``write(state, running)`` 两参鸭子契约写出的快照包含正确的
    ``window_mode`` 字段——管道侧无需感知 window_mode，由 VoiceStateFile
    从 state 自动推导。这是 Rust voice_watch → 前端联动的事实来源。
    """

    def test_adapter_write_idle_derives_window_mode_mini(self, state_path):
        writer = PipelineStateWriter(VoiceStateFile(state_path), fake_mode=False)
        writer.write("idle", False)
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["window_mode"] == "mini"

    def test_adapter_write_speaking_derives_window_mode_full(self, state_path):
        writer = PipelineStateWriter(VoiceStateFile(state_path), fake_mode=False)
        writer.write("speaking", True)
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["window_mode"] == "full"

    def test_adapter_write_with_reply_also_derives_window_mode(self, state_path):
        """write_with_reply 路径同样推导 window_mode（speaking → full）。"""
        writer = PipelineStateWriter(VoiceStateFile(state_path), fake_mode=True)
        writer.write_with_reply("speaking", True, "回复")
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["window_mode"] == "full"

    def test_adapter_state_transitions_flip_window_mode(self, state_path):
        """管道状态机流转时 window_mode 自动跟随：idle(mini) → speaking(full) → idle(mini)。"""
        writer = PipelineStateWriter(VoiceStateFile(state_path), fake_mode=False)
        writer.write("idle", False)
        assert VoiceStateFile.read(state_path)["window_mode"] == "mini"
        writer.write("wake_listening", True)
        assert VoiceStateFile.read(state_path)["window_mode"] == "full"
        writer.write("recording", True)
        assert VoiceStateFile.read(state_path)["window_mode"] == "full"
        writer.write("speaking", True)
        assert VoiceStateFile.read(state_path)["window_mode"] == "full"
        writer.write("idle", False)
        assert VoiceStateFile.read(state_path)["window_mode"] == "mini"


class TestDeriveWindowMode:
    """M12 灵动岛双形态：语音状态 → 窗口形态推导。

    推导规则：
    - ``idle`` → ``mini``（待命态退化为顶部浮窗，让出桌面视野）；
    - 活跃态（``wake_listening`` / ``recording`` / ``transcribing`` /
      ``thinking`` / ``speaking`` / ``tool_using`` / ``follow_up_listening``）
      → ``full``（cover-display 全屏覆盖，FieldStage + CaptionLayer + WellZone）。
    """

    def test_idle_derives_mini(self):
        from omni_voice.state_file import derive_window_mode

        assert derive_window_mode("idle") == "mini"

    @pytest.mark.parametrize(
        "state",
        [
            "wake_listening",
            "recording",
            "transcribing",
            "thinking",
            "speaking",
            "tool_using",
            "follow_up_listening",
        ],
    )
    def test_active_states_derive_full(self, state):
        from omni_voice.state_file import derive_window_mode

        assert derive_window_mode(state) == "full"

    def test_unknown_state_defaults_to_full(self):
        """未知状态默认 Full（安全态：保持全屏，避免浮窗遮挡活跃交互）。"""
        from omni_voice.state_file import derive_window_mode

        assert derive_window_mode("unknown_state") == "full"

    def test_none_state_defaults_to_full(self):
        """None 状态（管道未启动）默认 Full。"""
        from omni_voice.state_file import derive_window_mode

        assert derive_window_mode(None) == "full"


class TestWriteWindowMode:
    """M12：write 自动推导 window_mode 并写入快照。"""

    def test_write_idle_includes_window_mode_mini(self, state_path):
        f = VoiceStateFile(state_path)
        f.write("idle", running=False, fake_mode=False)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["window_mode"] == "mini"

    def test_write_speaking_includes_window_mode_full(self, state_path):
        f = VoiceStateFile(state_path)
        f.write("speaking", running=True, fake_mode=False)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["window_mode"] == "full"

    def test_write_wake_listening_includes_window_mode_full(self, state_path):
        f = VoiceStateFile(state_path)
        f.write("wake_listening", running=True, fake_mode=False)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["window_mode"] == "full"


class TestReadWindowMode:
    """M12：read 容忍 window_mode 缺省/非字符串，仅当为字符串时带出。"""

    def test_read_roundtrip_with_window_mode(self, state_path):
        VoiceStateFile(state_path).write("idle", running=False, fake_mode=False)
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["window_mode"] == "mini"

    def test_read_legacy_file_without_window_mode_omits_key(self, state_path):
        """M12 之前的旧格式（无 window_mode 键）必须可读，返回 dict 不含该键。"""
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps({"state": "idle", "running": False, "fake_mode": False, "ts": 1.0}),
            encoding="utf-8",
        )
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["state"] == "idle"
        assert "window_mode" not in data

    @pytest.mark.parametrize("bad_mode", [42, True, 1.5, ["mini"], {"k": 1}])
    def test_read_non_string_window_mode_tolerated(self, state_path, bad_mode):
        """window_mode 非字符串 → 容错忽略，返回不含该键（不拖垮 schema 校验）。"""
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps(
                {
                    "state": "idle",
                    "running": False,
                    "fake_mode": False,
                    "ts": 1.0,
                    "window_mode": bad_mode,
                }
            ),
            encoding="utf-8",
        )
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["state"] == "idle"
        assert "window_mode" not in data


# =========================================================================
# M13.2：tool_calls 字段（Agent 可视化工作台数据通道）
# =========================================================================


def _sample_tool_call(
    *,
    id: str = "seq1-0",
    name: str = "home_control_light",
    args: dict | None = None,
    result: str | None = None,
    status: str = "pending",
    ts: float = 1.0,
) -> dict:
    """构造合法的 tool_calls 数组单元素（与 Python/前端契约对齐）。"""
    return {
        "id": id,
        "name": name,
        "args": args if args is not None else {"room": "客厅"},
        "result": result,
        "status": status,
        "ts": ts,
    }


class TestWriteToolCalls:
    """M13.2：write 携带 tool_calls 时随快照写入；缺省/None 不带该键。"""

    def test_write_with_tool_calls_includes_key(self, state_path):
        f = VoiceStateFile(state_path)
        calls = [_sample_tool_call()]
        f.write("tool_using", running=True, fake_mode=False, tool_calls=calls)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["state"] == "tool_using"
        assert payload["tool_calls"] == calls

    def test_write_without_tool_calls_omits_key(self, state_path):
        """未传 tool_calls 参数：快照不含 tool_calls 键（与 M12 旧格式完全兼容）。"""
        f = VoiceStateFile(state_path)
        f.write("idle", running=False, fake_mode=False)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert "tool_calls" not in payload

    def test_write_with_empty_tool_calls_list_clears_field(self, state_path):
        """传 tool_calls=[] 显式清空（一轮结束后写入空数组覆盖旧值）。"""
        f = VoiceStateFile(state_path)
        f.write("tool_using", running=True, fake_mode=False, tool_calls=[_sample_tool_call()])
        f.write("speaking", running=True, fake_mode=False, tool_calls=[])
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["tool_calls"] == []

    def test_write_tool_calls_with_reply_simultaneously(self, state_path):
        """tool_calls 与 reply 可在同一快照共存（如 speaking 携带 reply + 已完成工具列表）。"""
        f = VoiceStateFile(state_path)
        calls = [_sample_tool_call(status="success", result='{"ok":true}')]
        f.write(
            "speaking",
            running=True,
            fake_mode=False,
            reply="已为你开灯",
            tool_calls=calls,
        )
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["reply"] == "已为你开灯"
        assert payload["tool_calls"] == calls


class TestReadToolCalls:
    """M13.2：read 对 tool_calls 宽容——是 list 且元素为 dict 才带出。"""

    def test_read_roundtrip_with_tool_calls(self, state_path):
        calls = [_sample_tool_call()]
        VoiceStateFile(state_path).write(
            "tool_using", running=True, fake_mode=False, tool_calls=calls
        )
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["tool_calls"] == calls

    def test_read_legacy_file_without_tool_calls_omits_key(self, state_path):
        """M13.2 之前的旧格式（无 tool_calls 键）必须可读，返回不含该键。"""
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps(
                {"state": "idle", "running": False, "fake_mode": False, "ts": 1.0}
            ),
            encoding="utf-8",
        )
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["state"] == "idle"
        assert "tool_calls" not in data

    def test_read_empty_tool_calls_list(self, state_path):
        """显式空数组（一轮结束清空）必须可读，返回 tool_calls=[]。"""
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps(
                {
                    "state": "speaking",
                    "running": True,
                    "fake_mode": False,
                    "ts": 1.0,
                    "tool_calls": [],
                }
            ),
            encoding="utf-8",
        )
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["tool_calls"] == []

    def test_read_non_list_tool_calls_tolerated(self, state_path):
        """tool_calls 非数组 → 容错忽略，返回不含该键（不拖垮 schema 校验）。"""
        state_path.parent.mkdir(parents=True)
        for bad in [42, True, "string", {"k": 1}]:
            state_path.write_text(
                json.dumps(
                    {
                        "state": "tool_using",
                        "running": True,
                        "fake_mode": False,
                        "ts": 1.0,
                        "tool_calls": bad,
                    }
                ),
                encoding="utf-8",
            )
            data = VoiceStateFile.read(state_path)
            assert data is not None, f"非数组 tool_calls 不应拖垮解析: {bad}"
            assert data["state"] == "tool_using"
            assert "tool_calls" not in data

    def test_read_tool_calls_with_non_dict_element_filters_them(self, state_path):
        """tool_calls 数组中含非 dict 元素 → 过滤掉非法元素，仅保留合法 dict。"""
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps(
                {
                    "state": "tool_using",
                    "running": True,
                    "fake_mode": False,
                    "ts": 1.0,
                    "tool_calls": [
                        _sample_tool_call(),
                        "not-a-dict",
                        42,
                        None,
                        _sample_tool_call(id="seq1-1", name="other_tool"),
                    ],
                }
            ),
            encoding="utf-8",
        )
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert len(data["tool_calls"]) == 2, "仅保留 2 个合法 dict 元素"
        assert data["tool_calls"][0]["id"] == "seq1-0"
        assert data["tool_calls"][1]["id"] == "seq1-1"

    def test_read_tool_calls_all_non_dict_returns_empty_list(self, state_path):
        """tool_calls 数组所有元素都非法 → 容错为空数组（key 仍存在）。"""
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps(
                {
                    "state": "tool_using",
                    "running": True,
                    "fake_mode": False,
                    "ts": 1.0,
                    "tool_calls": ["a", 42, None],
                }
            ),
            encoding="utf-8",
        )
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["tool_calls"] == []


class TestPipelineStateWriterToolCalls:
    """M13.2：PipelineStateWriter 持有当前工具调用列表，每次写入时透传。"""

    def test_set_tool_calls_then_write_includes_them(self, state_path):
        writer = PipelineStateWriter(VoiceStateFile(state_path), fake_mode=False)
        calls = [_sample_tool_call()]
        writer.set_tool_calls(calls)
        writer.write("tool_using", True)
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["tool_calls"] == calls

    def test_clear_tool_calls_by_setting_empty(self, state_path):
        writer = PipelineStateWriter(VoiceStateFile(state_path), fake_mode=False)
        writer.set_tool_calls([_sample_tool_call()])
        writer.write("tool_using", True)
        writer.set_tool_calls([])
        writer.write("thinking", True)
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["tool_calls"] == []

    def test_clear_tool_calls_by_setting_none_omits_key(self, state_path):
        """set_tool_calls(None) → 后续写入不含 tool_calls 键（与旧格式兼容）。"""
        writer = PipelineStateWriter(VoiceStateFile(state_path), fake_mode=False)
        writer.set_tool_calls([_sample_tool_call()])
        writer.write("tool_using", True)
        writer.set_tool_calls(None)
        writer.write("thinking", True)
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert "tool_calls" not in data

    def test_initial_state_no_tool_calls(self, state_path):
        """新构造的 writer 默认不写 tool_calls 键。"""
        writer = PipelineStateWriter(VoiceStateFile(state_path), fake_mode=False)
        writer.write("idle", False)
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert "tool_calls" not in data

    def test_write_with_reply_forwards_tool_calls(self, state_path):
        """write_with_reply 路径同样透传当前 tool_calls（speaking 携带 reply + 已完成工具）。"""
        writer = PipelineStateWriter(VoiceStateFile(state_path), fake_mode=True)
        calls = [_sample_tool_call(status="success", result='{"ok":true}')]
        writer.set_tool_calls(calls)
        writer.write_with_reply("speaking", True, "已开灯")
        data = VoiceStateFile.read(state_path)
        assert data is not None
        assert data["reply"] == "已开灯"
        assert data["tool_calls"] == calls
