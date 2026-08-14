"""omni_office CLI（cli.py）测试。

契约（对齐 omni_weather/cli.py）：
- ``python -m omni_office <子命令>`` 打印 JSON 信封，ok:true → 退出码 0，否则 1
- ``call <tool> --args '<json>'`` 为 Rust 桥接通用入口
- 参数解析错误经 JsonErrorArgumentParser 返回 E_INVALID_PARAMS JSON
- ``--db PATH`` 全局参数或 env ``AI_OMNI_OFFICE_DB`` 指向临时库（测试不触用户目录）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omni_office import cli


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """每个测试独立文件库 + 重置 tools 运行时。"""
    monkeypatch.setenv("AI_OMNI_OFFICE_DB", str(tmp_path / "office.db"))
    from omni_office import tools

    tools._reset_runtime()
    yield
    if tools._runtime.db is not None:
        tools._runtime.db.close()
    tools._reset_runtime()


def _run(argv: list[str]) -> tuple[int, dict]:
    """执行 CLI main，捕获打印的 JSON（经 capsys 外层处理）。"""
    code = cli.main(argv)
    return code


class TestCallSubcommand:
    def test_call_status(self, capsys: pytest.CaptureFixture) -> None:
        code = cli.main(["call", "office_status"])
        out = json.loads(capsys.readouterr().out)
        assert code == 0
        assert out["ok"] is True
        assert "documents" in out["data"]

    def test_call_unknown_tool(self, capsys: pytest.CaptureFixture) -> None:
        code = cli.main(["call", "office_hack"])
        out = json.loads(capsys.readouterr().out)
        assert code == 1
        assert out["ok"] is False
        assert out["error"]["code"] == "E_INVALID_ARGS"

    def test_call_bad_args_json(self, capsys: pytest.CaptureFixture) -> None:
        code = cli.main(["call", "office_status", "--args", "{not json"])
        out = json.loads(capsys.readouterr().out)
        assert code == 1
        assert out["error"]["code"] == "E_INVALID_ARGS"

    def test_call_doc_create_with_args(self, capsys: pytest.CaptureFixture) -> None:
        code = cli.main([
            "call", "office_doc_create",
            "--args", json.dumps({"title": "CLI 文档", "content": "内容"}),
        ])
        out = json.loads(capsys.readouterr().out)
        assert code == 0
        assert out["data"]["doc_id"].startswith("doc_")


class TestNamedSubcommands:
    def test_doc_create_then_list(self, capsys: pytest.CaptureFixture) -> None:
        code = cli.main(["doc-create", "周报", "--content", "第一周", "--tags", "工作"])
        out = json.loads(capsys.readouterr().out)
        assert code == 0
        doc_id = out["data"]["doc_id"]

        code = cli.main(["doc-list"])
        out = json.loads(capsys.readouterr().out)
        assert code == 0
        assert [d["id"] for d in out["data"]["documents"]] == [doc_id]

    def test_event_create_and_conflicts(self, capsys: pytest.CaptureFixture) -> None:
        code = cli.main([
            "event-create", "评审",
            "--start", "2026-08-07T14:00", "--end", "2026-08-07T15:00",
        ])
        assert json.loads(capsys.readouterr().out)["ok"] is True

        code = cli.main([
            "event-conflicts",
            "--start", "2026-08-07T14:30", "--end", "2026-08-07T16:00",
        ])
        out = json.loads(capsys.readouterr().out)
        assert len(out["data"]["conflicts"]) == 1

    def test_email_send_fake(self, capsys: pytest.CaptureFixture) -> None:
        code = cli.main([
            "email-send", "--to", "a@x.com", "--subject", "hi",
            "--body", "hello", "--fake",
        ])
        out = json.loads(capsys.readouterr().out)
        assert code == 0
        assert out["data"]["email_id"].startswith("mail_")

    def test_meeting_prep_fake(self, capsys: pytest.CaptureFixture) -> None:
        code = cli.main([
            "meeting-prep", "评审",
            "--start", "2026-08-07T14:00", "--end", "2026-08-07T15:00",
            "--attendees", "a@x.com,b@x.com", "--agenda", "议题", "--fake",
        ])
        out = json.loads(capsys.readouterr().out)
        assert code == 0
        assert out["data"]["emails_sent"] == 2

    def test_status_subcommand(self, capsys: pytest.CaptureFixture) -> None:
        code = cli.main(["status"])
        out = json.loads(capsys.readouterr().out)
        assert code == 0
        assert out["ok"] is True

    def test_reminders_subcommand(self, capsys: pytest.CaptureFixture) -> None:
        cli.main([
            "event-create", "评审",
            "--start", "2026-08-07T14:00", "--end", "2026-08-07T15:00",
            "--reminder-minutes", "15",
        ])
        capsys.readouterr()
        code = cli.main(["reminders", "--now", "2026-08-07T13:50"])
        out = json.loads(capsys.readouterr().out)
        assert code == 0
        assert len(out["data"]["reminders"]) == 1

    def test_parse_error_returns_json(self, capsys: pytest.CaptureFixture) -> None:
        """缺必需参数 → E_INVALID_PARAMS JSON + 退出码 1。"""
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["doc-create"])  # 缺 title
        assert exc_info.value.code == 1
        out = json.loads(capsys.readouterr().out)
        assert out["error"]["code"] == "E_INVALID_PARAMS"
