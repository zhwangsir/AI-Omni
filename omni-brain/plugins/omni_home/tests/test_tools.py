"""omni_home tools 层测试：6 个 home_* 工具。

全部通过 fake 客户端驱动（FakeHomeAssistantClient 演示家庭），
不依赖真实 Home Assistant / 网络；
每个测试用 ``_reset_runtime()`` 隔离进程内运行时单例。
"""

from __future__ import annotations

import json

import pytest

from omni_home import tools
from omni_home.client import FakeHomeAssistantClient
from omni_home.config import HomeConfig


def _parse(result: str) -> dict:
    """工具返回的是 JSON 字符串，解析为 dict。"""
    assert isinstance(result, str)
    return json.loads(result)


@pytest.fixture(autouse=True)
def fresh_runtime():
    """每个测试前重置运行时单例。"""
    rt = tools._reset_runtime()
    yield rt


@pytest.fixture
def demo_client():
    """返回预置演示家庭的 fake 客户端。"""
    return FakeHomeAssistantClient.with_demo_home()


# ---------------------------------------------------------------------------
# home_status
# ---------------------------------------------------------------------------
class TestHomeStatus:
    def test_status_ok_shape(self):
        data = _parse(tools.home_status(fake=True))
        assert data["ok"] is True
        payload = data["data"]
        assert payload["fake_mode"] is True
        assert "config" in payload
        assert payload["config"]["ha_url"].startswith("http")

    def test_status_masks_token(self):
        rt = tools._runtime
        rt.config = HomeConfig(ha_token="abcdefgh12345678")
        data = _parse(tools.home_status(fake=True))
        token_text = data["data"]["config"]["ha_token"]
        assert "abcdefgh12345678" not in token_text

    def test_status_not_fake_by_default(self):
        data = _parse(tools.home_status())
        assert data["data"]["fake_mode"] is False


# ---------------------------------------------------------------------------
# home_refresh
# ---------------------------------------------------------------------------
class TestHomeRefresh:
    def test_refresh_fake_demo_home(self):
        data = _parse(tools.home_refresh(fake=True))
        assert data["ok"] is True
        stats = data["data"]
        assert stats["devices"] == 14
        assert stats["rooms"] == 3
        assert stats["scenes"] == 2

    def test_refresh_caches_entities(self):
        tools.home_refresh(fake=True)
        rt = tools._runtime
        assert rt.entities is not None
        assert len(rt.entities) == 14

    def test_refresh_real_mode_without_token_fails(self):
        rt = tools._runtime
        rt.config = HomeConfig(ha_token="")
        data = _parse(tools.home_refresh(fake=False))
        assert data["ok"] is False
        assert "token" in data["error"]["message"].lower()

    def test_refresh_failure_maps_error(self):
        from omni_home.errors import HomeConnectionError

        rt = tools._runtime
        rt.client = FakeHomeAssistantClient(fail_with=HomeConnectionError("连不上"))
        data = _parse(tools.home_refresh())
        assert data["ok"] is False
        assert "连不上" in data["error"]["message"]


# ---------------------------------------------------------------------------
# home_control
# ---------------------------------------------------------------------------
class TestHomeControl:
    def test_turn_on_light(self):
        data = _parse(tools.home_control("打开客厅灯", fake=True))
        assert data["ok"] is True
        results = data["data"]["results"]
        assert len(results) == 1
        result = results[0]
        assert result["entity_id"] == "light.living_room_main"
        assert result["service"] == "light.turn_on"
        assert result["state"] == "on"
        assert result["state_text"] == "开启"

    def test_turn_off_climate(self):
        data = _parse(tools.home_control("关闭客厅空调", fake=True))
        assert data["ok"] is True
        result = data["data"]["results"][0]
        assert result["service"] == "climate.turn_off"
        assert result["state"] == "off"

    def test_set_ac_temperature(self):
        data = _parse(tools.home_control("把客厅空调温度调到26度", fake=True))
        assert data["ok"] is True
        result = data["data"]["results"][0]
        assert result["service"] == "climate.set_temperature"
        assert result["attributes"]["temperature"] == 26.0

    def test_increase_light_brightness(self):
        data = _parse(tools.home_control("把卧室灯调亮一点", fake=True))
        assert data["ok"] is True
        result = data["data"]["results"][0]
        assert result["service"] == "light.turn_on"

    def test_control_all_lights(self):
        data = _parse(tools.home_control("打开所有灯", fake=True))
        assert data["ok"] is True
        results = data["data"]["results"]
        entity_ids = {r["entity_id"] for r in results}
        assert entity_ids == {
            "light.living_room_main",
            "light.living_room_lamp",
            "light.bedroom_main",
        }
        assert all(r["state"] == "on" for r in results)

    def test_activate_scene(self):
        data = _parse(tools.home_control("执行回家场景", fake=True))
        assert data["ok"] is True
        result = data["data"]["results"][0]
        assert result["entity_id"] == "scene.home_mode"
        assert result["service"] == "scene.turn_on"

    def test_lock_door(self):
        data = _parse(tools.home_control("锁上大门门锁", fake=True))
        assert data["ok"] is True
        result = data["data"]["results"][0]
        assert result["service"] == "lock.lock"
        assert result["state"] == "locked"

    def test_unrecognized_command(self):
        data = _parse(tools.home_control(" blah blah", fake=True))
        assert data["ok"] is False
        assert "无法识别" in data["error"]["message"]

    def test_query_action_redirects(self):
        data = _parse(tools.home_control("客厅灯开着吗", fake=True))
        assert data["ok"] is False
        assert "home_query" in data["error"]["message"]

    def test_target_not_found(self):
        data = _parse(tools.home_control("打开阁楼灯", fake=True))
        assert data["ok"] is False
        assert "找不到" in data["error"]["message"]

    def test_ambiguous_targets(self):
        data = _parse(tools.home_control("打开灯", fake=True))
        assert data["ok"] is False
        assert "歧义" in data["error"]["message"] or "多个" in data["error"]["message"]
        assert "candidates" in data["error"]["message"] or "客厅" in data["error"]["message"]

    def test_default_room_fallback(self):
        rt = tools._runtime
        rt.config = HomeConfig(default_room="卧室")
        data = _parse(tools.home_control("打开灯", fake=True))
        assert data["ok"] is True
        result = data["data"]["results"][0]
        assert result["entity_id"] == "light.bedroom_main"

    def test_control_publishes_event(self):
        published: list[tuple[str, dict]] = []
        rt = tools._runtime

        class _Bus:
            def publish(self, event_type, payload):
                published.append((event_type, payload))

        rt.event_publisher = _Bus()
        tools.home_control("打开客厅灯", fake=True)
        assert any(t == "home.control_executed" for t, _ in published)

    def test_service_failure_maps_error(self):
        from omni_home.errors import HomeConnectionError

        rt = tools._runtime
        rt.client = FakeHomeAssistantClient(fail_with=HomeConnectionError("断网"))
        data = _parse(tools.home_control("打开客厅灯"))
        assert data["ok"] is False
        assert "断网" in data["error"]["message"]


# ---------------------------------------------------------------------------
# home_query
# ---------------------------------------------------------------------------
class TestHomeQuery:
    def test_query_light_state(self):
        data = _parse(tools.home_query("卧室灯开着吗", fake=True))
        assert data["ok"] is True
        answers = data["data"]["answers"]
        assert len(answers) == 1
        assert answers[0]["entity_id"] == "light.bedroom_main"
        assert answers[0]["state_text"] == "开启"

    def test_query_temperature(self):
        data = _parse(tools.home_query("客厅温度多少", fake=True))
        assert data["ok"] is True
        answers = data["data"]["answers"]
        assert any("27.5" in a["state_text"] for a in answers)

    def test_query_room_summary(self):
        data = _parse(tools.home_query("看看客厅", fake=True))
        assert data["ok"] is True
        answers = data["data"]["answers"]
        entity_ids = {a["entity_id"] for a in answers}
        assert "light.living_room_main" in entity_ids
        assert "climate.living_room_ac" in entity_ids

    def test_control_action_redirects(self):
        data = _parse(tools.home_query("打开客厅灯", fake=True))
        assert data["ok"] is False
        assert "home_control" in data["error"]["message"]

    def test_unrecognized_query(self):
        data = _parse(tools.home_query(" blah blah", fake=True))
        assert data["ok"] is False

    def test_query_lock_state(self):
        data = _parse(tools.home_query("大门门锁怎么样", fake=True))
        assert data["ok"] is True
        assert data["data"]["answers"][0]["state_text"] == "已上锁"


# ---------------------------------------------------------------------------
# home_list
# ---------------------------------------------------------------------------
class TestHomeList:
    def test_list_all_returns_graph(self):
        data = _parse(tools.home_list(fake=True))
        assert data["ok"] is True
        payload = data["data"]
        assert "rooms" in payload
        assert "stats" in payload
        room_names = [r["name"] for r in payload["rooms"]]
        assert "客厅" in room_names and "卧室" in room_names

    def test_list_filter_room(self):
        data = _parse(tools.home_list(room="书房", fake=True))
        assert data["ok"] is True
        devices = data["data"]["devices"]
        assert len(devices) == 1
        assert devices[0]["entity_id"] == "fan.study_fan"
        assert devices[0]["state_text"] == "关闭"

    def test_list_filter_domain(self):
        data = _parse(tools.home_list(domain="light", fake=True))
        assert data["ok"] is True
        devices = data["data"]["devices"]
        assert len(devices) == 3
        assert all(d["domain"] == "light" for d in devices)

    def test_list_empty_room(self):
        data = _parse(tools.home_list(room="阁楼", fake=True))
        assert data["ok"] is True
        assert data["data"]["devices"] == []


# ---------------------------------------------------------------------------
# home_config
# ---------------------------------------------------------------------------
class TestHomeConfig:
    def test_get_returns_summary(self):
        data = _parse(tools.home_config(action="get"))
        assert data["ok"] is True
        assert data["data"]["ha_url"].startswith("http")

    def test_get_masks_token(self):
        rt = tools._runtime
        rt.config = HomeConfig(ha_token="abcdefgh12345678")
        data = _parse(tools.home_config(action="get"))
        assert "abcdefgh12345678" not in data["data"]["ha_token"]

    def test_set_url(self):
        data = _parse(tools.home_config(action="set", key="ha_url", value="http://ha.local:8123"))
        assert data["ok"] is True
        assert data["data"]["value"] == "http://ha.local:8123"
        assert tools._runtime.config.ha_url == "http://ha.local:8123"

    def test_set_unknown_key(self):
        data = _parse(tools.home_config(action="set", key="no_such_key", value="x"))
        assert data["ok"] is False
        assert "不支持" in data["error"]["message"]

    def test_set_invalid_value(self):
        data = _parse(tools.home_config(action="set", key="connect_timeout", value="-5"))
        assert data["ok"] is False

    def test_set_missing_key(self):
        data = _parse(tools.home_config(action="set"))
        assert data["ok"] is False

    def test_unknown_action(self):
        data = _parse(tools.home_config(action="delete"))
        assert data["ok"] is False
