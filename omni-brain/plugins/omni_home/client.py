"""omni_home 的 Home Assistant 客户端。

- :class:`HomeAssistantClient`：REST API 封装，仅用标准库 urllib，
  opener 可注入（测试不发起真实网络请求）；错误统一映射为
  :class:`HomeAuthError` / :class:`HomeConnectionError` / :class:`HomeError`。
- :class:`FakeHomeAssistantClient`：可编程 fake——预设实体、服务调用记录、
  状态变更模拟；``with_demo_home()`` 提供开箱即用的演示家庭（CLI --fake 用）。
"""

from __future__ import annotations

import copy
import json
import urllib.error
import urllib.request
from typing import Any, Callable

from .config import HomeConfig
from .errors import HomeAuthError, HomeConnectionError, HomeError

#: opener 协议：``(request, timeout) -> 响应上下文管理器``
Opener = Callable[..., Any]


def _default_opener(req: urllib.request.Request, timeout: float):
    """默认 opener：真实发起 HTTP 请求（仅此函数触碰网络）。"""
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - URL 由用户配置


class HomeAssistantClient:
    """Home Assistant REST API 客户端（Bearer token 认证）。"""

    def __init__(self, config: HomeConfig, *, opener: Opener | None = None):
        self._config = config
        self._opener = opener or _default_opener

    def get_states(self) -> list[dict[str, Any]]:
        """GET /api/states：返回全部实体状态。"""
        return self._request("GET", "/states")

    def get_state(self, entity_id: str) -> dict[str, Any]:
        """GET /api/states/<entity_id>：返回单个实体状态。"""
        return self._request("GET", f"/states/{entity_id}")

    def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """POST /api/services/<domain>/<service>：调用服务，返回受影响实体状态。"""
        payload = dict(data or {})
        if entity_id:
            payload["entity_id"] = entity_id
        return self._request("POST", f"/services/{domain}/{service}", payload)

    def get_config(self) -> dict[str, Any]:
        """GET /api/config：返回 HA 实例配置。"""
        return self._request("GET", "/config")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        """发起一次 API 请求并完成错误映射与 JSON 解析。"""
        url = self._config.api_url + path
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self._config.ha_token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with self._opener(req, self._config.read_timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            code = exc.code
            # M32.23：关闭异常持有的底层响应资源（Python 3.14 起未关闭触发
            # ResourceWarning；真实运行时对应未释放的 socket 连接）。
            exc.close()
            if code in (401, 403):
                raise HomeAuthError(
                    f"Home Assistant 认证失败（HTTP {code}），请检查 ha_token"
                ) from exc
            raise HomeError(f"Home Assistant 请求失败（HTTP {code}）: {path}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HomeConnectionError(
                f"无法连接 Home Assistant（{self._config.ha_url}）: {exc}"
            ) from exc
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HomeError(f"Home Assistant 返回了非法 JSON: {path}") from exc


# ---------------------------------------------------------------------------
# Fake 客户端
# ---------------------------------------------------------------------------

#: 演示家庭 states（对齐 GET /api/states 返回格式），供 fake 客户端与 CLI 演示使用
DEMO_HOME_STATES: list[dict[str, Any]] = [
    {
        "entity_id": "light.living_room_main",
        "state": "off",
        "attributes": {"friendly_name": "客厅灯", "room": "客厅", "brightness": 128},
    },
    {
        "entity_id": "light.living_room_lamp",
        "state": "off",
        "attributes": {"friendly_name": "客厅台灯", "room": "客厅"},
    },
    {
        "entity_id": "light.bedroom_main",
        "state": "on",
        "attributes": {"friendly_name": "卧室灯", "room": "卧室"},
    },
    {
        "entity_id": "climate.living_room_ac",
        "state": "cool",
        "attributes": {
            "friendly_name": "客厅空调",
            "room": "客厅",
            "temperature": 26.0,
            "current_temperature": 27.5,
        },
    },
    {
        "entity_id": "cover.bedroom_curtain",
        "state": "open",
        "attributes": {"friendly_name": "卧室窗帘", "room": "卧室"},
    },
    {
        "entity_id": "fan.study_fan",
        "state": "off",
        "attributes": {"friendly_name": "书房风扇", "room": "书房"},
    },
    {
        "entity_id": "media_player.living_room_tv",
        "state": "off",
        "attributes": {"friendly_name": "客厅电视", "room": "客厅", "volume_level": 0.3},
    },
    {
        "entity_id": "sensor.living_room_temperature",
        "state": "27.5",
        "attributes": {
            "friendly_name": "客厅温度传感器",
            "room": "客厅",
            "unit_of_measurement": "°C",
        },
    },
    {
        "entity_id": "binary_sensor.front_door",
        "state": "off",
        "attributes": {"friendly_name": "大门门磁"},
    },
    {
        "entity_id": "scene.home_mode",
        "state": "2026-07-20T00:00:00+00:00",
        "attributes": {"friendly_name": "回家场景", "aliases": ["回家模式"]},
    },
    {
        "entity_id": "scene.sleep_mode",
        "state": "2026-07-20T00:00:00+00:00",
        "attributes": {"friendly_name": "睡眠场景"},
    },
    {
        "entity_id": "switch.humidifier",
        "state": "off",
        "attributes": {"friendly_name": "加湿器开关", "room": "卧室"},
    },
    {
        "entity_id": "automation.morning_routine",
        "state": "on",
        "attributes": {"friendly_name": "早安自动化"},
    },
    {
        "entity_id": "lock.front_door",
        "state": "locked",
        "attributes": {"friendly_name": "大门门锁"},
    },
]

#: 仅做 on/off/toggle 状态切换的 domain
_ON_OFF_DOMAINS = {"light", "switch", "fan", "media_player", "humidifier", "input_boolean"}


class FakeHomeAssistantClient:
    """可编程 Home Assistant fake：与真实客户端同构的接口。

    - ``states``      ：预设实体列表（深拷贝持有，互不影响）
    - ``fail_with``   ：注入后所有读操作抛出该异常（模拟断网/认证失败）
    - ``service_calls``：服务调用记录（``{domain, service, entity_id, data}``）
    """

    def __init__(
        self,
        states: list[dict[str, Any]] | None = None,
        *,
        fail_with: Exception | None = None,
    ):
        self._states: dict[str, dict[str, Any]] = {
            s["entity_id"]: copy.deepcopy(s) for s in (states or [])
        }
        self._fail_with = fail_with
        self.service_calls: list[dict[str, Any]] = []

    @classmethod
    def with_demo_home(cls) -> "FakeHomeAssistantClient":
        """返回预置演示家庭的 fake 客户端（CLI --fake / 测试用）。"""
        return cls(states=DEMO_HOME_STATES)

    # -- 读操作 ------------------------------------------------------------
    def get_states(self) -> list[dict[str, Any]]:
        self._maybe_fail()
        return [copy.deepcopy(s) for s in self._states.values()]

    def get_state(self, entity_id: str) -> dict[str, Any]:
        self._maybe_fail()
        state = self._states.get(entity_id)
        if state is None:
            raise HomeError(f"实体不存在: {entity_id}")
        return copy.deepcopy(state)

    def get_config(self) -> dict[str, Any]:
        self._maybe_fail()
        return {
            "location_name": "Omni 演示家庭",
            "version": "2026.7.0",
            "unit_system": {"temperature": "°C"},
        }

    # -- 写操作 ------------------------------------------------------------
    def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """记录调用并模拟状态变更，返回受影响实体状态。"""
        self._maybe_fail()
        data = dict(data or {})
        self.service_calls.append(
            {"domain": domain, "service": service, "entity_id": entity_id, "data": data}
        )
        if entity_id is None:
            return []
        state = self._states.get(entity_id)
        if state is None:
            raise HomeError(f"实体不存在: {entity_id}")
        self._simulate(state, domain, service, data)
        return [copy.deepcopy(state)]

    def apply_external_change(self, entity_id: str, new_state: dict[str, Any]) -> None:
        """模拟外部因素（如 WebSocket 推送）导致的实体状态变更。"""
        self._states[entity_id] = copy.deepcopy(new_state)

    # -- 内部 ----------------------------------------------------------------
    def _maybe_fail(self) -> None:
        if self._fail_with is not None:
            raise self._fail_with

    def _simulate(self, state: dict, domain: str, service: str, data: dict) -> None:
        """按 domain/service 语义模拟状态迁移（覆盖常见受控场景）。"""
        attrs = state.setdefault("attributes", {})
        if domain in _ON_OFF_DOMAINS and service in ("turn_on", "turn_off", "toggle"):
            if service == "toggle":
                state["state"] = "off" if state.get("state") == "on" else "on"
            else:
                state["state"] = "on" if service == "turn_on" else "off"
            if domain == "light" and "brightness_pct" in data:
                attrs["brightness"] = round(255 * float(data["brightness_pct"]) / 100)
            if domain == "light" and "brightness_step_pct" in data:
                step = round(255 * float(data["brightness_step_pct"]) / 100)
                attrs["brightness"] = max(0, min(255, int(attrs.get("brightness", 0)) + step))
        elif domain == "media_player" and service == "volume_set":
            attrs["volume_level"] = float(data.get("volume_level", attrs.get("volume_level", 0)))
        elif domain == "media_player" and service in ("volume_up", "volume_down"):
            delta = 0.1 if service == "volume_up" else -0.1
            attrs["volume_level"] = round(
                max(0.0, min(1.0, float(attrs.get("volume_level", 0)) + delta)), 2
            )
        elif domain == "climate":
            if service == "set_temperature" and "temperature" in data:
                attrs["temperature"] = float(data["temperature"])
            elif service == "turn_off":
                state["state"] = "off"
            elif service == "turn_on" and state.get("state") == "off":
                state["state"] = "cool"
        elif domain == "cover":
            if service == "open_cover":
                state["state"] = "open"
            elif service == "close_cover":
                state["state"] = "closed"
            elif service == "set_cover_position" and "position" in data:
                attrs["position"] = int(data["position"])
                state["state"] = "open" if int(data["position"]) > 0 else "closed"
        elif domain == "lock":
            if service == "lock":
                state["state"] = "locked"
            elif service == "unlock":
                state["state"] = "unlocked"
        # scene/script/automation：只记录调用，不迁移状态（对齐 HA 语义）
