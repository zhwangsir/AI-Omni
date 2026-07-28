"""omni_home 插件契约测试：plugin.yaml 与 register(ctx) 对齐 WeBrain 插件机制。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omni_home import register, tools
from omni_voice.config import parse_simple_yaml

PLUGIN_DIR = Path(__file__).resolve().parent.parent


class _FakeCtx:
    """插件上下文 fake：收集 register_tool 调用，可选携带事件总线。"""

    def __init__(self, with_bus: bool = False):
        self.tools: list[dict] = []
        self.event_bus = _FakeEventBus() if with_bus else None

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)


class _FakeEventBus:
    """事件总线 fake：满足 publish(event_type, payload) 鸭子类型。"""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def publish(self, event_type, payload):
        self.events.append((event_type, payload))


@pytest.fixture(autouse=True)
def fresh_runtime():
    """每个测试前重置运行时单例。"""
    yield tools._reset_runtime()


class TestPluginYaml:
    def test_plugin_yaml_exists(self):
        assert (PLUGIN_DIR / "plugin.yaml").is_file()

    def test_plugin_yaml_fields(self):
        meta = parse_simple_yaml((PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8"))
        assert meta["name"] == "omni_home"
        assert meta["version"]
        assert meta["description"]
        assert isinstance(meta.get("provides_tools"), list)

    def test_provides_tools_matches_registry(self):
        meta = parse_simple_yaml((PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8"))
        declared = set(meta["provides_tools"])
        registered = {meta_["name"] for meta_ in tools.TOOLS}
        assert declared == registered


class TestRegister:
    def test_register_six_tools(self):
        ctx = _FakeCtx()
        register(ctx)
        assert len(ctx.tools) == 6
        names = [t["name"] for t in ctx.tools]
        assert names == [
            "home_status",
            "home_refresh",
            "home_control",
            "home_query",
            "home_list",
            "home_config",
        ]

    def test_register_tool_fields(self):
        ctx = _FakeCtx()
        register(ctx)
        for tool in ctx.tools:
            assert tool["toolset"] == "omni_home"
            assert tool["description"]
            assert tool["emoji"]
            schema = tool["schema"]
            assert schema["name"] == tool["name"]
            assert schema["parameters"]["type"] == "object"
            assert isinstance(schema["parameters"]["properties"], dict)
            assert isinstance(schema["parameters"]["required"], list)
            assert callable(tool["handler"])

    def test_handler_returns_json_string(self):
        ctx = _FakeCtx()
        register(ctx)
        handler = next(t["handler"] for t in ctx.tools if t["name"] == "home_status")
        result = handler({"fake": True})
        assert isinstance(result, str)
        payload = json.loads(result)
        assert payload["ok"] is True

    def test_handler_bad_args_returns_error_json(self):
        ctx = _FakeCtx()
        register(ctx)
        handler = next(t["handler"] for t in ctx.tools if t["name"] == "home_control")
        result = handler({})  # 缺 command 参数
        payload = json.loads(result)
        assert payload["ok"] is False

    def test_register_connects_event_bus(self):
        ctx = _FakeCtx(with_bus=True)
        register(ctx)
        rt = tools._runtime
        assert rt.event_publisher is ctx.event_bus
        # 控制成功后事件发布到总线
        handler = next(t["handler"] for t in ctx.tools if t["name"] == "home_control")
        handler({"command": "打开客厅灯", "fake": True})
        assert any(t == "home.control_executed" for t, _ in ctx.event_bus.events)

    def test_register_without_event_bus(self):
        ctx = _FakeCtx(with_bus=False)
        register(ctx)
        assert tools._runtime.event_publisher is None
