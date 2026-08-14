"""omni_wechat CLI 入口（__main__.py）测试。

全部 fake 后端：``ILinkClient`` / ``MonitorLoop`` 以进程内 fake 替换，
状态目录用 ``tmp_path`` 隔离，环境变量经 ``monkeypatch`` 注入，不访问真实网络。
覆盖：参数解析、send/status/set-target/listen/config/migrate 子命令与
``python -m omni_wechat`` 入口语义。
"""

from __future__ import annotations

import asyncio
import json
import runpy
import sys
from pathlib import Path
from typing import Any

import pytest

from omni_wechat import __main__ as cli_main
from omni_wechat.accounts import AccountStore
from omni_wechat.config import WechatConfig


# ---------------------------------------------------------------------------
# Fake ILinkClient / MonitorLoop
# ---------------------------------------------------------------------------
class FakeILinkClient:
    """记录 send_text 调用并返回预置响应的 fake iLink 客户端。"""

    instances: list[FakeILinkClient] = []

    def __init__(self, config: WechatConfig) -> None:
        self.config = config
        self.send_text_result: dict[str, Any] = {"ok": True, "data": {"message_id": "m-1"}}
        self.send_text_calls: list[dict[str, Any]] = []
        self.closed = False
        FakeILinkClient.instances.append(self)

    async def send_text(
        self,
        target: str,
        text: str,
        context_token: str | None = None,
    ) -> dict[str, Any]:
        self.send_text_calls.append(
            {"target": target, "text": text, "context_token": context_token}
        )
        return self.send_text_result

    async def close(self) -> None:
        self.closed = True


class FakeMonitorLoop:
    """捕获 on_message 回调、记录 start/stop 的 fake 监听器。"""

    instances: list[FakeMonitorLoop] = []

    def __init__(
        self,
        client: Any,
        store: AccountStore,
        account: str,
        on_message: Any = None,
    ) -> None:
        self.client = client
        self.store = store
        self.account = account
        self.on_message = on_message
        self.started = False
        self.stopped = False
        FakeMonitorLoop.instances.append(self)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """每个测试：隔离状态目录、清掉关键环境变量、替换 fake 依赖。"""
    FakeILinkClient.instances.clear()
    FakeMonitorLoop.instances.clear()
    monkeypatch.setenv("OMNI_WECHAT_STATE_DIR", str(tmp_path))
    for var in ("OMNI_WECHAT_ACCOUNT", "OMNI_WECHAT_TOKEN", "OMNI_WECHAT_DEFAULT_TARGET"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(cli_main, "ILinkClient", FakeILinkClient)
    monkeypatch.setattr(cli_main, "MonitorLoop", FakeMonitorLoop)
    return tmp_path


def _run_json(capsys: pytest.CaptureFixture, argv: list[str]) -> tuple[int, dict[str, Any]]:
    """执行 CLI main 并把打印的 JSON 解析为 dict。"""
    code = cli_main.main(argv)
    return code, json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------
class TestBuildParser:
    def test_send(self) -> None:
        args = cli_main._build_parser().parse_args(["send", "你好", "--target", "u1"])
        assert args.cmd == "send"
        assert args.text == "你好"
        assert args.target == "u1"

    def test_send_target_optional(self) -> None:
        args = cli_main._build_parser().parse_args(["send", "hi"])
        assert args.target is None

    def test_status_listen_config(self) -> None:
        parser = cli_main._build_parser()
        assert parser.parse_args(["status"]).cmd == "status"
        assert parser.parse_args(["listen"]).cmd == "listen"
        assert parser.parse_args(["config"]).cmd == "config"

    def test_set_target(self) -> None:
        args = cli_main._build_parser().parse_args(["set-target", "user@im.wechat"])
        assert args.cmd == "set-target"
        assert args.target == "user@im.wechat"

    def test_migrate(self) -> None:
        args = cli_main._build_parser().parse_args(
            ["migrate", "--from-openclaw", "/tmp/oc", "--account", "acc1"]
        )
        assert args.cmd == "migrate"
        assert args.from_openclaw == "/tmp/oc"
        assert args.account == "acc1"

    def test_migrate_requires_from_openclaw(self) -> None:
        with pytest.raises(SystemExit):
            cli_main._build_parser().parse_args(["migrate"])

    def test_no_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit):
            cli_main.main([])


# ---------------------------------------------------------------------------
# _load_config_and_client
# ---------------------------------------------------------------------------
class TestLoadConfigAndClient:
    def test_token_loaded_from_store(self, _isolate: Path) -> None:
        store = AccountStore(str(_isolate))
        store.save_token("acc1", token="tok-store", base_url="https://x", user_id="user@x")
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("OMNI_WECHAT_ACCOUNT", "acc1")
            cfg, client, store2 = cli_main._load_config_and_client()
        assert cfg.token == "tok-store"
        assert cfg.default_target == "user@x"
        assert store2.root == _isolate
        asyncio.run(client.close())

    def test_env_token_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OMNI_WECHAT_ACCOUNT", "acc1")
        monkeypatch.setenv("OMNI_WECHAT_TOKEN", "tok-env")
        monkeypatch.setenv("OMNI_WECHAT_DEFAULT_TARGET", "env-user@x")
        cfg, client, _store = cli_main._load_config_and_client()
        assert cfg.token == "tok-env"
        assert cfg.default_target == "env-user@x"
        asyncio.run(client.close())


# ---------------------------------------------------------------------------
# send 子命令
# ---------------------------------------------------------------------------
class TestCmdSend:
    def test_send_success(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("OMNI_WECHAT_ACCOUNT", "acc1")
        monkeypatch.setenv("OMNI_WECHAT_DEFAULT_TARGET", "user@im.wechat")
        code, out = _run_json(capsys, ["send", "你好"])
        assert code == 0
        assert out["ok"] is True
        client = FakeILinkClient.instances[-1]
        assert client.send_text_calls[0]["target"] == "user@im.wechat"
        assert client.send_text_calls[0]["text"] == "你好"
        assert client.closed

    def test_send_explicit_target(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("OMNI_WECHAT_ACCOUNT", "acc1")
        code, out = _run_json(capsys, ["send", "hi", "--target", "other@im.wechat"])
        assert code == 0
        assert out["ok"] is True
        assert FakeILinkClient.instances[-1].send_text_calls[0]["target"] == "other@im.wechat"

    def test_send_passes_context_token(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, _isolate: Path
    ) -> None:
        monkeypatch.setenv("OMNI_WECHAT_ACCOUNT", "acc1")
        monkeypatch.setenv("OMNI_WECHAT_DEFAULT_TARGET", "user@im.wechat")
        AccountStore(str(_isolate)).save_context_token("acc1", "user@im.wechat", "ctx-1")
        code, _out = _run_json(capsys, ["send", "hi"])
        assert code == 0
        assert FakeILinkClient.instances[-1].send_text_calls[0]["context_token"] == "ctx-1"

    def test_send_no_target(self, capsys: pytest.CaptureFixture) -> None:
        code, out = _run_json(capsys, ["send", "hi"])
        assert code == 1
        assert out["ok"] is False
        assert "target" in out["error"]

    def test_send_failure_result(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("OMNI_WECHAT_DEFAULT_TARGET", "user@im.wechat")

        class _FailClient(FakeILinkClient):
            def __init__(self, config: WechatConfig) -> None:
                super().__init__(config)
                self.send_text_result = {"ok": False, "error": {"message": "boom"}}

        monkeypatch.setattr(cli_main, "ILinkClient", _FailClient)
        code, out = _run_json(capsys, ["send", "hi"])
        assert code == 1
        assert out["ok"] is False


# ---------------------------------------------------------------------------
# status 子命令
# ---------------------------------------------------------------------------
class TestCmdStatus:
    def test_status_with_account(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("OMNI_WECHAT_ACCOUNT", "acc1")
        monkeypatch.setenv("OMNI_WECHAT_TOKEN", "tok")
        code, out = _run_json(capsys, ["status"])
        assert code == 0
        data = out["data"]
        assert data["account"] == "acc1"
        assert data["has_token"] is True
        assert data["registered_accounts"] == []
        assert data["sync_buf_len"] == 0

    def test_status_without_account(self, capsys: pytest.CaptureFixture) -> None:
        code, out = _run_json(capsys, ["status"])
        assert code == 0
        assert out["data"]["account"] is None
        assert out["data"]["has_token"] is False


# ---------------------------------------------------------------------------
# set-target 子命令
# ---------------------------------------------------------------------------
class TestCmdSetTarget:
    def test_set_target_success(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, _isolate: Path
    ) -> None:
        monkeypatch.setenv("OMNI_WECHAT_ACCOUNT", "acc1")
        code, out = _run_json(capsys, ["set-target", "new@im.wechat"])
        assert code == 0
        assert out["ok"] is True
        assert out["data"]["default_target"] == "new@im.wechat"
        # 落盘验证：token.json 的 userId 已更新
        token_data = AccountStore(str(_isolate)).load_token("acc1")
        assert token_data["userId"] == "new@im.wechat"

    def test_set_target_no_account(self, capsys: pytest.CaptureFixture) -> None:
        code, out = _run_json(capsys, ["set-target", "u@x"])
        assert code == 1
        assert out["ok"] is False
        assert "account" in out["error"]


# ---------------------------------------------------------------------------
# listen 子命令
# ---------------------------------------------------------------------------
async def _interrupt(_delay: float) -> None:
    """替代 asyncio.sleep：首次 await 即抛 KeyboardInterrupt，驱动 listen 优雅退出。"""
    raise KeyboardInterrupt


class TestCmdListen:
    def test_listen_no_token(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("OMNI_WECHAT_ACCOUNT", "acc1")
        code, out = _run_json(capsys, ["listen"])
        assert code == 1
        assert out["ok"] is False
        assert "token" in out["error"]

    def test_listen_no_account(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("OMNI_WECHAT_TOKEN", "tok")
        code, out = _run_json(capsys, ["listen"])
        assert code == 1
        assert out["ok"] is False
        assert "account" in out["error"]

    def test_listen_lifecycle(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """长轮询主循环：KeyboardInterrupt 时优雅 stop 并关闭客户端。"""
        monkeypatch.setenv("OMNI_WECHAT_ACCOUNT", "acc1")
        monkeypatch.setenv("OMNI_WECHAT_TOKEN", "tok")
        monkeypatch.setattr(asyncio, "sleep", _interrupt)
        code = cli_main.main(["listen"])
        assert code == 0
        monitor = FakeMonitorLoop.instances[-1]
        assert monitor.started
        assert monitor.stopped
        assert FakeILinkClient.instances[-1].closed
        err = capsys.readouterr().err
        assert "监听已启动" in err
        assert "停止监听" in err

    def test_listen_on_message_saves_context_token(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, _isolate: Path
    ) -> None:
        monkeypatch.setenv("OMNI_WECHAT_ACCOUNT", "acc1")
        monkeypatch.setenv("OMNI_WECHAT_TOKEN", "tok")
        monkeypatch.setattr(asyncio, "sleep", _interrupt)
        cli_main.main(["listen"])
        capsys.readouterr()
        monitor = FakeMonitorLoop.instances[-1]

        monitor.on_message({"from_user_id": "u1", "context_token": "ctx-9"})
        assert AccountStore(str(_isolate)).load_context_token("acc1", "u1") == "ctx-9"

        # 缺字段时不落盘、不抛错
        monitor.on_message({"from_user_id": "u2"})
        assert AccountStore(str(_isolate)).load_context_token("acc1", "u2") is None

    def test_listen_on_message_store_failure_ignored(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("OMNI_WECHAT_ACCOUNT", "acc1")
        monkeypatch.setenv("OMNI_WECHAT_TOKEN", "tok")
        monkeypatch.setattr(asyncio, "sleep", _interrupt)
        cli_main.main(["listen"])
        capsys.readouterr()
        monitor = FakeMonitorLoop.instances[-1]

        def _boom(*_args: Any, **_kwargs: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(monitor.store, "save_context_token", _boom)
        # 存储失败被吞掉，不影响消息打印
        monitor.on_message({"from_user_id": "u1", "context_token": "ctx"})
        out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert out["event"] == "wechat.message_received"


# ---------------------------------------------------------------------------
# config 子命令
# ---------------------------------------------------------------------------
class TestCmdConfig:
    def test_config_summary(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("OMNI_WECHAT_ACCOUNT", "acc1")
        code, out = _run_json(capsys, ["config"])
        assert code == 0
        assert out["ok"] is True
        assert out["data"]["account"] == "acc1"
        assert "base_url" in out["data"]


# ---------------------------------------------------------------------------
# migrate 子命令
# ---------------------------------------------------------------------------
class TestCmdMigrate:
    @staticmethod
    def _write_openclaw_account(src: Path, account: str, token: str) -> None:
        (src / f"{account}.json").write_text(
            json.dumps({"token": token, "baseUrl": "https://x", "userId": "u@x"}),
            encoding="utf-8",
        )

    def test_migrate_success(
        self, capsys: pytest.CaptureFixture, tmp_path: Path, _isolate: Path
    ) -> None:
        src = tmp_path / "openclaw"
        src.mkdir()
        self._write_openclaw_account(src, "acc-m", "tok-m")
        code, out = _run_json(capsys, ["migrate", "--from-openclaw", str(src)])
        assert code == 0
        assert out["ok"] is True
        assert out["data"]["migrated"] == ["acc-m"]
        assert AccountStore(str(_isolate)).load_token("acc-m")["token"] == "tok-m"

    def test_migrate_empty_dir(
        self, capsys: pytest.CaptureFixture, tmp_path: Path
    ) -> None:
        src = tmp_path / "empty"
        src.mkdir()
        code, out = _run_json(capsys, ["migrate", "--from-openclaw", str(src)])
        assert code == 1
        assert out["ok"] is True
        assert out["data"]["migrated"] == []

    def test_migrate_missing_dir(self, capsys: pytest.CaptureFixture) -> None:
        code, out = _run_json(capsys, ["migrate", "--from-openclaw", "/nonexistent/oc"])
        assert code == 1
        assert out["ok"] is False
        assert "不存在" in out["error"]


# ---------------------------------------------------------------------------
# python -m omni_wechat 入口语义
# ---------------------------------------------------------------------------
class TestDunderMain:
    def test_module_execution(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """以 ``python -m omni_wechat config`` 语义执行 __main__.py，SystemExit 透出返回码。"""
        monkeypatch.setattr(sys, "argv", ["omni_wechat", "config"])
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("omni_wechat", run_name="__main__", alter_sys=True)
        assert exc_info.value.code == 0
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True
