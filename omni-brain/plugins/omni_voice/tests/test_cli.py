"""omni_voice CLI 测试：argparse 子命令、退出码、--fake 演示路径。

CLI 是 tools 层的薄壳：解析参数 → 调用 tools → 打印 JSON → 映射退出码。
fake 演示组件的脚本化（让演示无需硬件也有完整输出）由 CLI 负责。
"""

from __future__ import annotations

import json

import pytest

from omni_voice import cli, tools
from omni_voice.errors import VoiceBackendError


@pytest.fixture(autouse=True)
def fresh_runtime():
    """每个测试前重置 tools 运行时单例，结束后回收管道线程。"""
    rt = tools._reset_runtime()
    yield rt
    if rt.pipeline is not None:
        rt.pipeline.stop()
        rt.pipeline = None


def _out_json(capsys) -> dict:
    """从标准输出解析最后一行 JSON。"""
    out = capsys.readouterr().out.strip().splitlines()
    assert out, "CLI 无输出"
    return json.loads(out[-1])


# ---------------------------------------------------------------------------
# 解析与帮助
# ---------------------------------------------------------------------------
class TestParsing:
    def test_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--help"])
        assert exc.value.code == 0
        assert "listen-once" in capsys.readouterr().out

    def test_no_command_shows_help_and_fails(self):
        with pytest.raises(SystemExit) as exc:
            cli.main([])
        assert exc.value.code == 2

    def test_unknown_command_fails(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["bogus"])
        assert exc.value.code == 2


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------
class TestStatusCommand:
    def test_status_prints_json(self, capsys):
        assert cli.main(["status"]) == 0
        result = _out_json(capsys)
        assert result["ok"] is True
        assert result["data"]["state"] == "idle"
        assert result["data"]["config"]["sample_rate"] == 16000


# ---------------------------------------------------------------------------
# speak
# ---------------------------------------------------------------------------
class TestSpeakCommand:
    def test_speak_fake(self, capsys, fresh_runtime):
        assert cli.main(["speak", "你好 CLI", "--fake"]) == 0
        result = _out_json(capsys)
        assert result["ok"] is True
        assert result["data"]["spoken"] == "你好 CLI"
        assert fresh_runtime.components["tts"].texts == ["你好 CLI"]

    def test_speak_missing_text_arg_fails(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["speak"])
        assert exc.value.code == 2

    def test_speak_backend_error_exits_one(self, capsys, monkeypatch):
        def _boom(config):
            raise VoiceBackendError("TTS 网关不可达")

        monkeypatch.setattr(tools, "_build_real_components", _boom)
        assert cli.main(["speak", "你好"]) == 1
        assert _out_json(capsys)["ok"] is False


# ---------------------------------------------------------------------------
# listen-once
# ---------------------------------------------------------------------------
class TestListenOnceCommand:
    def test_listen_once_fake(self, capsys):
        assert cli.main(["listen-once", "--fake"]) == 0
        result = _out_json(capsys)
        assert result["ok"] is True
        data = result["data"]
        # CLI 预置的演示脚本应给出非空转写与回复
        assert data["transcript"]
        assert data["reply"]
        assert data["spoken"] is True

    def test_listen_once_no_speak_fake(self, capsys):
        assert cli.main(["listen-once", "--fake", "--no-speak"]) == 0
        assert _out_json(capsys)["data"]["spoken"] is False

    def test_listen_once_timeout_arg(self, capsys):
        assert cli.main(["listen-once", "--fake", "--timeout", "5"]) == 0
        assert _out_json(capsys)["ok"] is True


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------
class TestRunCommand:
    def test_run_fake_duration(self, capsys):
        assert cli.main(["run", "--fake", "--duration", "2"]) == 0
        out = capsys.readouterr().out
        # 演示脚本走完一轮：唤醒 → 转写 → 回复，事件逐行打印
        assert "voice.wake_detected" in out
        assert "voice.transcript" in out
        assert "voice.reply" in out
        # 结束打印最终状态 JSON
        final = json.loads(out.strip().splitlines()[-1])
        assert final["ok"] is True
        assert final["data"]["running"] is False

    def test_run_backend_error_exits_one(self, capsys, monkeypatch):
        def _boom(config):
            raise VoiceBackendError("音频采集需要 sounddevice")

        monkeypatch.setattr(tools, "_build_real_components", _boom)
        assert cli.main(["run", "--duration", "0.1"]) == 1
        assert _out_json(capsys)["ok"] is False


# ---------------------------------------------------------------------------
# python -m omni_voice 入口
# ---------------------------------------------------------------------------
class TestMainModuleEntry:
    def test_dunder_main_executes_cli(self, capsys, monkeypatch):
        import runpy
        import sys

        monkeypatch.setattr(sys, "argv", ["omni_voice", "status"])
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("omni_voice", run_name="__main__")
        assert exc.value.code == 0
        assert _out_json(capsys)["ok"] is True


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
class TestConfigCommand:
    def test_config_get(self, capsys):
        assert cli.main(["config", "get"]) == 0
        result = _out_json(capsys)
        assert result["ok"] is True
        assert result["data"]["wake_word"] == "hey_omni"

    def test_config_set_then_get(self, capsys, fresh_runtime):
        assert cli.main(["config", "set", "wake_threshold", "0.8"]) == 0
        result = _out_json(capsys)
        assert result["ok"] is True
        assert result["data"]["value"] == pytest.approx(0.8)
        assert fresh_runtime.config.wake_threshold == pytest.approx(0.8)

    def test_config_set_invalid_exits_one(self, capsys):
        assert cli.main(["config", "set", "wake_threshold", "9.9"]) == 1
        assert _out_json(capsys)["ok"] is False


# ---------------------------------------------------------------------------
# interrupt（M7.5：写控制文件，供外部进程打断宿主管道播报）
# ---------------------------------------------------------------------------
class TestInterruptCommand:
    def test_interrupt_prints_ok_json(self, capsys):
        assert cli.main(["interrupt"]) == 0
        result = _out_json(capsys)
        assert result["ok"] is True
        assert result["data"]["interrupted"] is True
        assert result["data"]["seq"] == 1

    def test_interrupt_writes_consumable_control_file(self, capsys):
        """CLI 写出的控制文件可被管道侧 read 消费（schema 一致）。"""
        from omni_voice.control_file import VoiceControlFile

        assert cli.main(["interrupt"]) == 0
        _out_json(capsys)
        data = VoiceControlFile.read()
        assert data is not None
        assert data["action"] == "interrupt"
        assert data["seq"] == 1

    def test_help_mentions_interrupt(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--help"])
        assert exc.value.code == 0
        assert "interrupt" in capsys.readouterr().out
