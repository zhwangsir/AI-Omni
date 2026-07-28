"""omni_home 客户端测试。

- :class:`HomeAssistantClient`：注入 fake opener 断言 URL/headers/payload/错误映射，
  不发起真实网络请求；
- :class:`FakeHomeAssistantClient`：可编程行为（预设实体、服务调用记录、状态变更模拟）。
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from omni_home.client import FakeHomeAssistantClient, HomeAssistantClient
from omni_home.config import HomeConfig
from omni_home.errors import HomeAuthError, HomeConnectionError, HomeError


# ---------------------------------------------------------------------------
# 真实客户端（fake opener 注入）
# ---------------------------------------------------------------------------
class _FakeResponse:
    """模拟 urllib 响应：支持 read() 与上下文管理。"""

    def __init__(self, body):
        self._body = body if isinstance(body, (bytes, str)) else json.dumps(body)

    def read(self):
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _make_client(record: list, *, response=None, raise_exc: Exception | None = None):
    """构建注入了 fake opener 的客户端；opener 调用记录进 record。"""
    cfg = HomeConfig(ha_url="http://ha.test:8123", ha_token="test-token")

    def opener(req, timeout):
        record.append({"req": req, "timeout": timeout})
        if raise_exc is not None:
            raise raise_exc
        return _FakeResponse(response if response is not None else [])

    return HomeAssistantClient(cfg, opener=opener)


class TestRealClientRequests:
    def test_get_states_url_headers(self):
        record = []
        client = _make_client(record, response=[{"entity_id": "light.x", "state": "on"}])
        states = client.get_states()
        assert states == [{"entity_id": "light.x", "state": "on"}]
        req = record[0]["req"]
        assert req.full_url == "http://ha.test:8123/api/states"
        assert req.get_header("Authorization") == "Bearer test-token"
        assert req.get_method() == "GET"
        assert record[0]["timeout"] == 30.0

    def test_get_state_path(self):
        record = []
        client = _make_client(record, response={"entity_id": "light.x", "state": "on"})
        state = client.get_state("light.x")
        assert state["state"] == "on"
        assert record[0]["req"].full_url == "http://ha.test:8123/api/states/light.x"

    def test_call_service_payload(self):
        record = []
        client = _make_client(record)
        client.call_service("light", "turn_on", entity_id="light.x", data={"brightness_pct": 50})
        req = record[0]["req"]
        assert req.full_url == "http://ha.test:8123/api/services/light/turn_on"
        assert req.get_method() == "POST"
        body = json.loads(req.data.decode("utf-8"))
        assert body == {"brightness_pct": 50, "entity_id": "light.x"}
        assert req.get_header("Content-type") == "application/json"

    def test_call_service_without_entity(self):
        record = []
        client = _make_client(record)
        client.call_service("scene", "turn_on")
        body = json.loads(record[0]["req"].data.decode("utf-8"))
        assert body == {}

    def test_get_config_path(self):
        record = []
        client = _make_client(record, response={"location_name": "Home"})
        assert client.get_config()["location_name"] == "Home"
        assert record[0]["req"].full_url == "http://ha.test:8123/api/config"

    def test_trailing_slash_url_normalized(self):
        record = []
        cfg = HomeConfig(ha_url="http://ha.test:8123/", ha_token="t")
        client = HomeAssistantClient(
            cfg, opener=lambda req, timeout: (record.append(req), _FakeResponse({}))[1]
        )
        client.get_config()
        assert record[0].full_url == "http://ha.test:8123/api/config"


class TestRealClientErrorMapping:
    def test_401_maps_to_auth_error(self):
        exc = urllib.error.HTTPError("u", 401, "Unauthorized", None, None)
        client = _make_client([], raise_exc=exc)
        with pytest.raises(HomeAuthError):
            client.get_states()

    def test_403_maps_to_auth_error(self):
        exc = urllib.error.HTTPError("u", 403, "Forbidden", None, None)
        client = _make_client([], raise_exc=exc)
        with pytest.raises(HomeAuthError):
            client.get_states()

    def test_404_maps_to_home_error(self):
        exc = urllib.error.HTTPError("u", 404, "Not Found", None, None)
        client = _make_client([], raise_exc=exc)
        with pytest.raises(HomeError, match="404"):
            client.get_state("light.missing")

    def test_500_maps_to_home_error(self):
        exc = urllib.error.HTTPError("u", 500, "Server Error", None, None)
        client = _make_client([], raise_exc=exc)
        with pytest.raises(HomeError):
            client.get_states()

    def test_url_error_maps_to_connection_error(self):
        exc = urllib.error.URLError("connection refused")
        client = _make_client([], raise_exc=exc)
        with pytest.raises(HomeConnectionError):
            client.get_states()

    def test_timeout_maps_to_connection_error(self):
        client = _make_client([], raise_exc=TimeoutError("timed out"))
        with pytest.raises(HomeConnectionError):
            client.get_states()

    def test_os_error_maps_to_connection_error(self):
        client = _make_client([], raise_exc=OSError("network unreachable"))
        with pytest.raises(HomeConnectionError):
            client.get_states()

    def test_bad_json_maps_to_home_error(self):
        cfg = HomeConfig(ha_url="http://ha.test:8123", ha_token="t")
        client = HomeAssistantClient(
            cfg, opener=lambda req, timeout: _FakeResponse("not-json{{{")
        )
        with pytest.raises(HomeError, match="JSON"):
            client.get_states()


# ---------------------------------------------------------------------------
# Fake 客户端
# ---------------------------------------------------------------------------
class TestFakeClientBasics:
    def test_with_demo_home_seeded(self):
        client = FakeHomeAssistantClient.with_demo_home()
        states = client.get_states()
        assert len(states) >= 10
        ids = {s["entity_id"] for s in states}
        assert "light.living_room_main" in ids
        assert "climate.living_room_ac" in ids

    def test_empty_by_default(self):
        assert FakeHomeAssistantClient().get_states() == []

    def test_get_state_found(self):
        client = FakeHomeAssistantClient.with_demo_home()
        state = client.get_state("light.living_room_main")
        assert state["attributes"]["friendly_name"] == "客厅灯"

    def test_get_state_missing_raises(self):
        client = FakeHomeAssistantClient.with_demo_home()
        with pytest.raises(HomeError, match="不存在"):
            client.get_state("light.ghost")

    def test_get_config(self):
        client = FakeHomeAssistantClient.with_demo_home()
        assert client.get_config()["location_name"] == "Omni 演示家庭"

    def test_fail_with_injection(self):
        client = FakeHomeAssistantClient(fail_with=HomeConnectionError("模拟断网"))
        with pytest.raises(HomeConnectionError):
            client.get_states()
        with pytest.raises(HomeConnectionError):
            client.get_config()


class TestFakeClientServiceCalls:
    def test_call_records_and_turns_on_light(self):
        client = FakeHomeAssistantClient.with_demo_home()
        client.call_service("light", "turn_on", entity_id="light.living_room_main")
        assert client.get_state("light.living_room_main")["state"] == "on"
        assert client.service_calls[-1] == {
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.living_room_main",
            "data": {},
        }

    def test_toggle_flips_state(self):
        client = FakeHomeAssistantClient.with_demo_home()
        assert client.get_state("light.bedroom_main")["state"] == "on"
        client.call_service("light", "toggle", entity_id="light.bedroom_main")
        assert client.get_state("light.bedroom_main")["state"] == "off"

    def test_brightness_pct_updates_attributes(self):
        client = FakeHomeAssistantClient.with_demo_home()
        client.call_service(
            "light", "turn_on",
            entity_id="light.living_room_main", data={"brightness_pct": 100},
        )
        state = client.get_state("light.living_room_main")
        assert state["state"] == "on"
        assert state["attributes"]["brightness"] == 255

    def test_climate_set_temperature(self):
        client = FakeHomeAssistantClient.with_demo_home()
        client.call_service(
            "climate", "set_temperature",
            entity_id="climate.living_room_ac", data={"temperature": 22},
        )
        assert client.get_state("climate.living_room_ac")["attributes"]["temperature"] == 22

    def test_climate_turn_off(self):
        client = FakeHomeAssistantClient.with_demo_home()
        client.call_service("climate", "turn_off", entity_id="climate.living_room_ac")
        assert client.get_state("climate.living_room_ac")["state"] == "off"

    def test_cover_open_close(self):
        client = FakeHomeAssistantClient.with_demo_home()
        client.call_service("cover", "close_cover", entity_id="cover.bedroom_curtain")
        assert client.get_state("cover.bedroom_curtain")["state"] == "closed"

    def test_lock_unlock(self):
        client = FakeHomeAssistantClient.with_demo_home()
        client.call_service("lock", "unlock", entity_id="lock.front_door")
        assert client.get_state("lock.front_door")["state"] == "unlocked"

    def test_media_volume_set(self):
        client = FakeHomeAssistantClient.with_demo_home()
        client.call_service(
            "media_player", "volume_set",
            entity_id="media_player.living_room_tv", data={"volume_level": 0.8},
        )
        assert client.get_state("media_player.living_room_tv")["attributes"]["volume_level"] == 0.8

    def test_scene_records_without_state_mutation(self):
        client = FakeHomeAssistantClient.with_demo_home()
        before = client.get_state("scene.home_mode")["state"]
        client.call_service("scene", "turn_on", entity_id="scene.home_mode")
        assert client.get_state("scene.home_mode")["state"] == before
        assert client.service_calls[-1]["service"] == "turn_on"

    def test_call_missing_entity_raises(self):
        client = FakeHomeAssistantClient.with_demo_home()
        with pytest.raises(HomeError, match="不存在"):
            client.call_service("light", "turn_on", entity_id="light.ghost")

    def test_call_returns_affected_states(self):
        client = FakeHomeAssistantClient.with_demo_home()
        result = client.call_service("light", "turn_on", entity_id="light.living_room_main")
        assert result[0]["entity_id"] == "light.living_room_main"
        assert result[0]["state"] == "on"

    def test_apply_external_change(self):
        client = FakeHomeAssistantClient.with_demo_home()
        client.apply_external_change(
            "light.living_room_main",
            {"entity_id": "light.living_room_main", "state": "on", "attributes": {"friendly_name": "客厅灯"}},
        )
        assert client.get_state("light.living_room_main")["state"] == "on"
