"""omni_process 工具 handler 测试（M16-P1）。

全部使用 FakeProcessBackend，不执行真实系统命令。
覆盖：
- list_processes：默认 limit / 自定义 limit / 空列表
- kill_process：成功 / 进程不存在 / 异常
- start_process：成功 / 异常
- 工具返回 JSON 字串格式（ok:true / ok:false）
- 事件发布（system.process_killed / system.process_started）
- E_BACKEND_UNAVAILABLE 错误码
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from omni_sdk.context import PluginContext
from omni_sdk.event_bus import EventBus
from omni_sdk.permissions import PermissionChecker
from omni_sdk.registry import ToolRegistry

from omni_process import ProcessPlugin
from omni_process.backends import FakeProcessBackend


def _setup_plugin(backend: Any = None) -> tuple[ProcessPlugin, PluginContext, EventBus]:
    """构造已 on_load 的插件 + ctx + event_bus，注入 fake 后端。"""
    event_bus = EventBus()
    ctx = PluginContext(
        config={"backend": backend} if backend is not None else {},
        event_bus=event_bus,
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        plugin_name="omni_process",
    )
    plugin = ProcessPlugin()
    asyncio.run(plugin.on_load(ctx))
    return plugin, ctx, event_bus


def _call_tool(ctx: PluginContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """调用 tool_registry 中的工具并解析返回 JSON。"""
    tool = ctx.tool_registry.get_tool(name)
    assert tool is not None, f"工具 {name} 未注册"
    result = tool.handler_func(args)
    assert isinstance(result, str), "handler 必须返回 JSON 字符串"
    return json.loads(result)


class TestListProcesses:
    def test_list_processes_default_limit(self) -> None:
        """默认 limit=20，返回 fake 进程列表。"""
        fake = FakeProcessBackend()
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_list_processes", {})
        assert result["ok"] is True
        assert "processes" in result
        assert len(result["processes"]) == 2  # fake 默认 2 个进程
        assert result["count"] == 2
        # 验证进程字段
        proc = result["processes"][0]
        assert "pid" in proc
        assert "name" in proc
        assert "cpu" in proc
        assert "memory" in proc

    def test_list_processes_custom_limit(self) -> None:
        """自定义 limit 透传到后端。"""
        fake = FakeProcessBackend()
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_list_processes", {"limit": 1})
        assert result["ok"] is True
        assert len(result["processes"]) == 1
        assert fake.last_limit == 1

    def test_list_processes_empty(self) -> None:
        """后端返回空列表时 ok:true + processes=[]。"""
        fake = FakeProcessBackend(processes=[])
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_list_processes", {})
        assert result["ok"] is True
        assert result["processes"] == []
        assert result["count"] == 0

    def test_list_processes_invalid_limit_type(self) -> None:
        """limit 类型错误时返回 ok:false。"""
        fake = FakeProcessBackend()
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_list_processes", {"limit": "not-a-number"})
        assert result["ok"] is False
        assert "error" in result

    def test_list_processes_backend_exception(self) -> None:
        """后端抛异常时映射为 ok:false。"""
        fake = FakeProcessBackend(raise_on_list=True)
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_list_processes", {})
        assert result["ok"] is False
        assert "error" in result


class TestKillProcess:
    def test_kill_process_success(self) -> None:
        """杀进程成功，返回 ok:true。"""
        fake = FakeProcessBackend()
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_kill_process", {"pid": 1234})
        assert result["ok"] is True
        assert result["pid"] == 1234
        assert 1234 in fake.killed

    def test_kill_process_not_found(self) -> None:
        """进程不存在时返回 ok:false。"""
        fake = FakeProcessBackend()
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_kill_process", {"pid": 99999})
        assert result["ok"] is False
        assert "error" in result

    def test_kill_process_missing_pid(self) -> None:
        """缺 pid 参数返回 ok:false。"""
        fake = FakeProcessBackend()
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_kill_process", {})
        assert result["ok"] is False
        assert "error" in result

    def test_kill_process_publishes_event(self) -> None:
        """杀进程成功后发布 system.process_killed 事件。"""
        fake = FakeProcessBackend()
        plugin, ctx, event_bus = _setup_plugin(fake)
        received: list[dict[str, Any]] = []
        event_bus.subscribe("system.process_killed", lambda p: received.append(p))
        _call_tool(ctx, "system_kill_process", {"pid": 1234})
        # 触发事件循环处理 create_task 调度
        asyncio.run(asyncio.sleep(0.01))
        assert len(received) == 1
        assert received[0]["pid"] == 1234

    def test_kill_process_no_backend(self) -> None:
        """后端缺失时 kill 返回 E_BACKEND_UNAVAILABLE。"""
        plugin, ctx, _ = _setup_plugin(backend=None)
        result = _call_tool(ctx, "system_kill_process", {"pid": 1234})
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"

    @pytest.mark.parametrize("bad_pid", [-3, 0, "abc", True])
    def test_kill_process_invalid_pid(self, bad_pid: Any) -> None:
        """pid 非正整数（含 bool/字符串/负数/0）时返回 E_INVALID_PARAM。"""
        fake = FakeProcessBackend()
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_kill_process", {"pid": bad_pid})
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_PARAM"

    def test_kill_process_backend_exception(self) -> None:
        """后端抛异常时映射为 E_BACKEND_ERROR。"""
        fake = FakeProcessBackend(raise_on_kill=True)
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_kill_process", {"pid": 1234})
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_ERROR"


class TestStartProcess:
    def test_start_process_success(self) -> None:
        """启动进程成功。"""
        fake = FakeProcessBackend()
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_start_process", {"command": "Safari"})
        assert result["ok"] is True
        assert "command" in result
        assert fake.last_started_command == "Safari"

    def test_start_process_missing_command(self) -> None:
        """缺 command 参数返回 ok:false。"""
        fake = FakeProcessBackend()
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_start_process", {})
        assert result["ok"] is False
        assert "error" in result

    def test_start_process_empty_command(self) -> None:
        """空 command 返回 ok:false。"""
        fake = FakeProcessBackend()
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_start_process", {"command": ""})
        assert result["ok"] is False
        assert "error" in result

    def test_start_process_publishes_event(self) -> None:
        """启动进程成功后发布 system.process_started 事件。"""
        fake = FakeProcessBackend()
        plugin, ctx, event_bus = _setup_plugin(fake)
        received: list[dict[str, Any]] = []
        event_bus.subscribe("system.process_started", lambda p: received.append(p))
        _call_tool(ctx, "system_start_process", {"command": "Terminal"})
        asyncio.run(asyncio.sleep(0.01))
        assert len(received) == 1
        assert received[0]["command"] == "Terminal"

    def test_start_process_backend_exception(self) -> None:
        """后端抛异常时映射为 ok:false。"""
        fake = FakeProcessBackend(raise_on_start=True)
        plugin, ctx, _ = _setup_plugin(fake)
        result = _call_tool(ctx, "system_start_process", {"command": "Safari"})
        assert result["ok"] is False
        assert "error" in result

    def test_start_process_no_backend(self) -> None:
        """后端缺失时 start 返回 E_BACKEND_UNAVAILABLE。"""
        plugin, ctx, _ = _setup_plugin(backend=None)
        result = _call_tool(ctx, "system_start_process", {"command": "Safari"})
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"

    def test_start_process_start_failed(self) -> None:
        """后端返回 started=False 时映射为 E_START_FAILED。"""

        class _FailStartBackend:
            def list_processes(self, limit: int = 20) -> list[dict[str, Any]]:
                return []

            def kill_process(self, pid: int) -> dict[str, Any]:
                return {"pid": pid, "killed": False}

            def start_process(self, command: str) -> dict[str, Any]:
                return {"command": command, "started": False}

        plugin, ctx, _ = _setup_plugin(_FailStartBackend())
        result = _call_tool(ctx, "system_start_process", {"command": "Nope"})
        assert result["ok"] is False
        assert result["error"]["code"] == "E_START_FAILED"


class TestBackendUnavailable:
    def test_no_backend_returns_e_backend_unavailable(self) -> None:
        """未注入后端且真实后端不可用时返回 E_BACKEND_UNAVAILABLE。

        通过 monkeypatch 让真实后端构建抛 ImportError，模拟 psutil/subprocess 不可用。
        """
        plugin, ctx, _ = _setup_plugin(backend=None)
        # 真实后端构建会尝试 import psutil；这里通过把 _backend 置 None 已模拟不可用
        # 实际插件 on_load 不会构建真实后端，调用时检测 _backend is None 返回错误
        result = _call_tool(ctx, "system_list_processes", {})
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"


class TestRealSubprocessBackend:
    """真实 SubprocessProcessBackend 测试（monkeypatch psutil/subprocess）。"""

    def test_subprocess_list_processes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """list_processes 用 psutil.process_iter 返回进程列表。"""
        from omni_process.backends import SubprocessProcessBackend

        class _FakeMem:
            def __init__(self, rss):
                self.rss = rss

        class _FakeProcInfo:
            def __init__(self, info):
                self.info = info

        fake_procs = [
            {
                "pid": 1,
                "name": "init",
                "cpu_percent": 0.1,
                "memory_info": _FakeMem(524288),
            },
            {
                "pid": 100,
                "name": "python",
                "cpu_percent": 50.0,
                "memory_info": _FakeMem(125829120),
            },
        ]

        import sys
        import types

        fake_psutil = types.ModuleType("psutil")
        fake_psutil.process_iter = lambda attrs=None: iter(
            [_FakeProcInfo(p) for p in fake_procs]
        )
        monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

        backend = SubprocessProcessBackend()
        result = backend.list_processes(limit=10)
        assert len(result) == 2
        # 按 cpu 降序
        assert result[0]["pid"] == 100
        assert result[0]["cpu"] == 50.0
        assert result[0]["memory"] == 120.0  # 125829120 / 1024 / 1024
        assert result[1]["pid"] == 1

    def test_subprocess_kill_process_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """kill_process 成功。"""
        import sys
        import types

        class _FakeProcess:
            def __init__(self, pid):
                self.pid = pid
                self.killed = False

            def kill(self):
                self.killed = True

        fake_psutil = types.ModuleType("psutil")
        fake_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        fake_psutil.Process = _FakeProcess
        monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

        from omni_process.backends import SubprocessProcessBackend

        backend = SubprocessProcessBackend()
        result = backend.kill_process(1234)
        assert result == {"pid": 1234, "killed": True}

    def test_subprocess_kill_process_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """kill_process 进程不存在返回 killed=False。"""
        import sys
        import types

        NoSuchProcess = type("NoSuchProcess", (Exception,), {})

        class _FakeProcess:
            def __init__(self, pid):
                raise NoSuchProcess()

        fake_psutil = types.ModuleType("psutil")
        fake_psutil.NoSuchProcess = NoSuchProcess
        fake_psutil.Process = _FakeProcess
        monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

        from omni_process.backends import SubprocessProcessBackend

        backend = SubprocessProcessBackend()
        result = backend.kill_process(99999)
        assert result == {"pid": 99999, "killed": False}

    def test_subprocess_start_process_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """macOS 下 start_process 用 open -a。"""
        import sys
        import types

        fake_platform = types.ModuleType("platform")
        fake_platform.system = lambda: "Darwin"
        monkeypatch.setitem(sys.modules, "platform", fake_platform)

        captured: dict[str, Any] = {}

        class _FakeResult:
            returncode = 0
            stderr = ""

        class _FakeSubprocess:
            @staticmethod
            def run(args, capture_output=False, text=False, check=False):
                captured["args"] = args
                return _FakeResult()

        fake_subprocess = types.ModuleType("subprocess")
        fake_subprocess.run = _FakeSubprocess.run
        monkeypatch.setitem(sys.modules, "subprocess", fake_subprocess)

        from omni_process.backends import SubprocessProcessBackend

        backend = SubprocessProcessBackend()
        result = backend.start_process("Safari")
        assert result["started"] is True
        assert captured["args"] == ["open", "-a", "Safari"]

    def test_subprocess_start_process_non_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非 macOS 下 start_process 用 Popen。"""
        import sys
        import types

        fake_platform = types.ModuleType("platform")
        fake_platform.system = lambda: "Linux"
        monkeypatch.setitem(sys.modules, "platform", fake_platform)

        captured: dict[str, Any] = {}

        class _FakePopen:
            def __init__(self, cmd, shell=False):
                captured["cmd"] = cmd
                captured["shell"] = shell

        fake_subprocess = types.ModuleType("subprocess")
        fake_subprocess.Popen = _FakePopen
        monkeypatch.setitem(sys.modules, "subprocess", fake_subprocess)

        from omni_process.backends import SubprocessProcessBackend

        backend = SubprocessProcessBackend()
        result = backend.start_process("vim")
        assert result["started"] is True
        assert captured["cmd"] == "vim"

    def test_subprocess_start_process_popen_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非 macOS 下 Popen 抛异常返回 started=False。"""
        import sys
        import types

        fake_platform = types.ModuleType("platform")
        fake_platform.system = lambda: "Linux"
        monkeypatch.setitem(sys.modules, "platform", fake_platform)

        class _FakePopen:
            def __init__(self, cmd, shell=False):
                raise FileNotFoundError("not found")

        fake_subprocess = types.ModuleType("subprocess")
        fake_subprocess.Popen = _FakePopen
        monkeypatch.setitem(sys.modules, "subprocess", fake_subprocess)

        from omni_process.backends import SubprocessProcessBackend

        backend = SubprocessProcessBackend()
        result = backend.start_process("nonexistent")
        assert result["started"] is False
        assert "error" in result


class TestProcessEventPublish:
    """omni_process._publish_event 边界分支测试。"""

    def test_publish_event_no_event_bus(self) -> None:
        """event_bus 为 None 时静默返回。"""
        plugin = ProcessPlugin()
        plugin._event_bus = None
        # 不应抛异常
        plugin._publish_event("system.process_killed", {"pid": 1})

    def test_publish_event_bus_exception_swallowed(self) -> None:
        """event_bus.publish 抛异常时被吞掉，不影响调用方。"""
        plugin = ProcessPlugin()

        class _BadBus:
            def publish(self, event_type, payload):
                raise RuntimeError("bus broken")

        plugin._event_bus = _BadBus()
        # 不应抛异常
        plugin._publish_event("system.process_killed", {"pid": 1})
