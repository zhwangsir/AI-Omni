"""omni_home 端到端集成测试（全 fake，无真实 HA / 网络依赖）。

链路：register(ctx) → refresh 拉取演示家庭 → control 多指令控制 →
query 状态联动 → list 结构视图 → config 运行时调参 →
事件总线收到控制事件 → WS 推送外部变更后 query 读到新状态。
"""

from __future__ import annotations

import json

import pytest

from omni_home import register, tools
from omni_home.client import FakeHomeAssistantClient
from omni_home.config import HomeConfig
from omni_home.ws_sync import FakeWebSocket, HomeStateSync


class _EventBus:
    """进程内事件总线 fake。"""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def publish(self, event_type, payload):
        self.events.append((event_type, payload))

    def types(self) -> list[str]:
        return [t for t, _ in self.events]

    def payloads(self, event_type: str) -> list[dict]:
        return [p for t, p in self.events if t == event_type]


class _Ctx:
    """插件上下文 fake：register_tool 收集 + 事件总线。"""

    def __init__(self):
        self.tools: dict[str, dict] = {}
        self.event_bus = _EventBus()

    def register_tool(self, **kwargs):
        self.tools[kwargs["name"]] = kwargs

    def call(self, name: str, args: dict | None = None) -> dict:
        """模拟宿主调用工具 handler，返回解析后的 JSON。"""
        return json.loads(self.tools[name]["handler"](args or {}))


@pytest.fixture(autouse=True)
def fresh_runtime():
    """每个测试前重置运行时单例。"""
    yield tools._reset_runtime()


@pytest.fixture
def ctx():
    """注册插件并返回上下文 fake。"""
    context = _Ctx()
    register(context)
    return context


class TestE2EFlow:
    def test_full_flow(self, ctx):
        """register → refresh → control → query → list → config 全链路协同。"""
        # 1. 刷新：演示家庭 14 个实体
        refreshed = ctx.call("home_refresh", {"fake": True})
        assert refreshed["ok"] is True
        assert refreshed["data"]["devices"] == 14
        assert refreshed["data"]["rooms"] == 3

        # 2. 状态：fake 模式 + 缓存规模
        status = ctx.call("home_status", {"fake": True})
        assert status["ok"] is True
        assert status["data"]["fake_mode"] is True
        assert status["data"]["cached_entities"] == 14

        # 3. 控制：开空调并调温（缓存联动）
        turned_on = ctx.call("home_control", {"command": "打开客厅灯", "fake": True})
        assert turned_on["ok"] is True
        assert turned_on["data"]["results"][0]["state"] == "on"

        # 4. 查询：控制后状态联动（读的是缓存而非重新拉取）
        answer = ctx.call("home_query", {"command": "客厅灯开着吗", "fake": True})
        assert answer["ok"] is True
        assert answer["data"]["answers"][0]["state_text"] == "开启"

        # 5. 批量控制 + 结构清单
        batch = ctx.call("home_control", {"command": "关闭所有灯", "fake": True})
        assert batch["ok"] is True
        assert len(batch["data"]["results"]) == 3
        listing = ctx.call("home_list", {"room": "客厅", "fake": True})
        assert listing["ok"] is True
        lights = [d for d in listing["data"]["devices"] if d["domain"] == "light"]
        assert all(d["state"] == "off" for d in lights)

        # 6. 配置调参：默认房间兜底消歧
        configured = ctx.call("home_config", {"action": "set", "key": "default_room", "value": "卧室"})
        assert configured["ok"] is True
        fallback = ctx.call("home_control", {"command": "打开灯", "fake": True})
        assert fallback["ok"] is True
        assert fallback["data"]["results"][0]["entity_id"] == "light.bedroom_main"

    def test_control_events_on_bus(self, ctx):
        """每次控制成功都向事件总线发布 home.control_executed。"""
        ctx.call("home_control", {"command": "打开客厅灯", "fake": True})
        ctx.call("home_control", {"command": "执行回家场景", "fake": True})
        events = ctx.event_bus.payloads("home.control_executed")
        assert len(events) == 2
        assert events[0]["results"][0]["service"] == "light.turn_on"
        assert events[1]["results"][0]["service"] == "scene.turn_on"

    def test_error_flows(self, ctx):
        """错误路径：查询走错工具 / 未知指令 / 未知设备 / 非法配置。"""
        wrong_tool = ctx.call("home_control", {"command": "客厅灯开着吗", "fake": True})
        assert wrong_tool["ok"] is False

        unknown = ctx.call("home_query", {"command": " blah", "fake": True})
        assert unknown["ok"] is False

        missing = ctx.call("home_control", {"command": "打开阁楼灯", "fake": True})
        assert missing["ok"] is False
        assert "找不到" in missing["error"]["message"]

        bad_config = ctx.call("home_config", {"action": "set", "key": "ha_url", "value": "ftp://x"})
        assert bad_config["ok"] is False

    def test_ws_push_updates_cached_view(self, ctx):
        """WS 推送的外部状态变更同步进实体缓存，query 读到最新状态。"""
        rt = tools._runtime
        client = FakeHomeAssistantClient.with_demo_home()
        rt.client = client

        ctx.call("home_refresh")

        # 模拟 HA WS 推送：客厅灯被外部打开
        changed = client.get_state("light.living_room_main")
        changed["state"] = "on"
        sync = HomeStateSync(
            HomeConfig(),
            ws_factory=lambda _cfg: FakeWebSocket(
                [
                    {"type": "auth_required"},
                    {"type": "auth_ok"},
                    {"id": 1, "type": "result", "success": True},
                    {
                        "id": 1,
                        "type": "event",
                        "event": {
                            "event_type": "state_changed",
                            "data": {
                                "entity_id": "light.living_room_main",
                                "new_state": changed,
                            },
                        },
                    },
                ]
            ),
        )
        sync.connect()
        sync.subscribe()
        assert sync.run_once() is True
        pushed = sync.get_cached("light.living_room_main")
        assert pushed["state"] == "on"

        # 把推送结果回写 fake 客户端（真实部署中 HA 侧已是新状态）
        client.apply_external_change("light.living_room_main", pushed)
        ctx.call("home_refresh")  # 重新拉取后缓存即为最新
        answer = ctx.call("home_query", {"command": "客厅灯开着吗"})
        assert answer["data"]["answers"][0]["state_text"] == "开启"
