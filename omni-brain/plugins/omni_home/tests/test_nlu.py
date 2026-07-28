"""omni_home 自然语言理解测试。

规则 + 模板匹配解析中文家居指令；覆盖：开/关/切换/调高/调低/设置温度/
查询状态/执行场景/全量控制/门锁，以及房间限定、模糊名称、中文数字。
"""

from __future__ import annotations

import pytest

from omni_home.entities import parse_states
from omni_home.errors import HomeError
from omni_home.nlu import ControlIntent, parse_command, resolve_service, resolve_targets


@pytest.fixture
def entities(demo_states):
    return parse_states(demo_states)


def _resolve_names(intent, entities):
    return [e.name for e in resolve_targets(intent, entities)]


# ---------------------------------------------------------------------------
# 开 / 关 / 切换
# ---------------------------------------------------------------------------
class TestOnOffToggle:
    def test_open_living_room_light(self, entities):
        intent = parse_command("打开客厅灯", entities)
        assert intent.action == "turn_on"
        assert intent.room == "客厅"
        assert intent.domain == "light"
        assert _resolve_names(intent, entities) == ["客厅灯"]

    def test_open_with_de_particle(self, entities):
        intent = parse_command("打开客厅的灯", entities)
        assert intent.action == "turn_on"
        assert _resolve_names(intent, entities) == ["客厅灯"]

    def test_close_with_ba_construction(self, entities):
        intent = parse_command("把卧室灯关掉", entities)
        assert intent.action == "turn_off"
        assert intent.room == "卧室"
        assert _resolve_names(intent, entities) == ["卧室灯"]

    def test_close_curtain_maps_to_cover(self, entities):
        intent = parse_command("关闭卧室窗帘", entities)
        assert intent.action == "turn_off"
        assert intent.domain == "cover"
        domain, service, _ = resolve_service(intent, resolve_targets(intent, entities)[0])
        assert (domain, service) == ("cover", "close_cover")

    def test_open_fan(self, entities):
        intent = parse_command("打开书房风扇", entities)
        assert intent.action == "turn_on"
        assert intent.domain == "fan"
        assert _resolve_names(intent, entities) == ["书房风扇"]

    def test_toggle(self, entities):
        intent = parse_command("切换客厅台灯", entities)
        assert intent.action == "toggle"
        assert _resolve_names(intent, entities) == ["客厅台灯"]

    def test_device_without_domain_keyword(self, entities):
        intent = parse_command("打开加湿器", entities)
        assert intent.action == "turn_on"
        assert intent.domain is None
        assert _resolve_names(intent, entities) == ["加湿器开关"]

    def test_open_tv(self, entities):
        intent = parse_command("打开客厅电视", entities)
        assert intent.domain == "media_player"
        assert _resolve_names(intent, entities) == ["客厅电视"]


# ---------------------------------------------------------------------------
# 设置（温度 / 亮度 / 音量）
# ---------------------------------------------------------------------------
class TestSet:
    def test_set_ac_temperature(self, entities):
        intent = parse_command("把客厅空调温度调到26度", entities)
        assert intent.action == "set"
        assert intent.domain == "climate"
        assert intent.value == 26.0
        target = resolve_targets(intent, entities)[0]
        domain, service, data = resolve_service(intent, target)
        assert (domain, service) == ("climate", "set_temperature")
        assert data["temperature"] == 26.0

    def test_set_temperature_without_room(self, entities):
        intent = parse_command("空调调到24度", entities)
        assert intent.action == "set"
        assert intent.value == 24.0
        assert _resolve_names(intent, entities) == ["客厅空调"]

    def test_set_light_brightness_bare_number(self, entities):
        intent = parse_command("把客厅灯亮度调到50", entities)
        assert intent.action == "set"
        assert intent.domain == "light"
        assert intent.value == 50.0
        _, service, data = resolve_service(intent, resolve_targets(intent, entities)[0])
        assert service == "turn_on"
        assert data["brightness_pct"] == 50

    def test_set_tv_volume_percent(self, entities):
        intent = parse_command("电视音量调到30%", entities)
        assert intent.action == "set"
        assert intent.value == 30.0
        domain, service, data = resolve_service(intent, resolve_targets(intent, entities)[0])
        assert (domain, service) == ("media_player", "volume_set")
        assert data["volume_level"] == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# 调高 / 调低
# ---------------------------------------------------------------------------
class TestIncreaseDecrease:
    def test_ac_up_one_degree_cn_numeral(self, entities):
        intent = parse_command("把客厅空调调高一度", entities)
        assert intent.action == "increase"
        assert intent.domain == "climate"
        assert intent.value == 1.0
        target = resolve_targets(intent, entities)[0]
        _, service, data = resolve_service(intent, target)
        assert service == "set_temperature"
        # 演示家庭空调当前设定 26 → +1
        assert data["temperature"] == 27.0

    def test_ac_down_two_degrees(self, entities):
        intent = parse_command("空调调低两度", entities)
        assert intent.action == "decrease"
        assert intent.value == 2.0
        target = resolve_targets(intent, entities)[0]
        _, _, data = resolve_service(intent, target)
        assert data["temperature"] == 24.0

    def test_light_brighter_default_step(self, entities):
        intent = parse_command("客厅灯调亮一点", entities)
        assert intent.action == "increase"
        _, service, data = resolve_service(intent, resolve_targets(intent, entities)[0])
        assert service == "turn_on"
        assert data["brightness_step_pct"] == 20

    def test_tv_louder(self, entities):
        intent = parse_command("电视声音大一点", entities)
        assert intent.action == "increase"
        _, service, _ = resolve_service(intent, resolve_targets(intent, entities)[0])
        assert service == "volume_up"

    def test_light_dimmer(self, entities):
        intent = parse_command("把卧室灯调暗一点", entities)
        assert intent.action == "decrease"
        _, _, data = resolve_service(intent, resolve_targets(intent, entities)[0])
        assert data["brightness_step_pct"] == -20


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
class TestQuery:
    def test_query_temperature(self, entities):
        intent = parse_command("查询客厅温度", entities)
        assert intent.action == "query"
        assert intent.room == "客厅"
        assert _resolve_names(intent, entities) == ["客厅温度传感器"]

    def test_query_temperature_how(self, entities):
        intent = parse_command("客厅温度怎么样", entities)
        assert intent.action == "query"
        assert _resolve_names(intent, entities) == ["客厅温度传感器"]

    def test_query_light_on(self, entities):
        intent = parse_command("客厅灯开着吗", entities)
        assert intent.action == "query"
        assert _resolve_names(intent, entities) == ["客厅灯"]

    def test_query_with_now_filler(self, entities):
        intent = parse_command("现在客厅温度多少", entities)
        assert intent.action == "query"
        assert intent.domain == "sensor"

    def test_query_has_no_service(self, entities):
        intent = parse_command("查询客厅温度", entities)
        with pytest.raises(HomeError):
            resolve_service(intent)


# ---------------------------------------------------------------------------
# 场景 / 自动化
# ---------------------------------------------------------------------------
class TestSceneActivation:
    def test_execute_scene(self, entities):
        intent = parse_command("执行回家场景", entities)
        assert intent.action == "activate"
        assert intent.domain == "scene"
        assert _resolve_names(intent, entities) == ["回家场景"]
        _, service, _ = resolve_service(intent)
        assert service == "turn_on"

    def test_run_sleep_scene(self, entities):
        intent = parse_command("运行睡眠场景", entities)
        assert intent.action == "activate"
        assert _resolve_names(intent, entities) == ["睡眠场景"]

    def test_open_scene_by_alias(self, entities):
        intent = parse_command("打开回家模式", entities)
        # 别名命中 scene.home_mode；turn_on + scene 语义等价于激活
        assert _resolve_names(intent, entities) == ["回家场景"]


# ---------------------------------------------------------------------------
# 全量 / 门锁
# ---------------------------------------------------------------------------
class TestAllAndLock:
    def test_turn_on_all_lights(self, entities):
        intent = parse_command("打开所有灯", entities)
        assert intent.action == "turn_on"
        assert intent.all_matching is True
        names = _resolve_names(intent, entities)
        assert set(names) == {"客厅灯", "客厅台灯", "卧室灯"}

    def test_turn_off_all_lights_in_room(self, entities):
        intent = parse_command("关闭客厅所有的灯", entities)
        assert intent.all_matching is True
        assert intent.room == "客厅"
        names = _resolve_names(intent, entities)
        assert set(names) == {"客厅灯", "客厅台灯"}

    def test_lock_door(self, entities):
        intent = parse_command("锁上大门门锁", entities)
        assert intent.action == "turn_off"
        target = resolve_targets(intent, entities)[0]
        assert target.entity_id == "lock.front_door"
        domain, service, _ = resolve_service(intent, target)
        assert (domain, service) == ("lock", "lock")

    def test_unlock_door(self, entities):
        intent = parse_command("打开门锁", entities)
        target = resolve_targets(intent, entities)[0]
        domain, service, _ = resolve_service(intent, target)
        assert (domain, service) == ("lock", "unlock")


# ---------------------------------------------------------------------------
# 解析失败与目标解析边界
# ---------------------------------------------------------------------------
class TestParseFailureAndResolution:
    def test_gibberish_returns_none(self, entities):
        assert parse_command("嗯嗯啊啊", entities) is None

    def test_empty_returns_none(self, entities):
        assert parse_command("", entities) is None
        assert parse_command("   ", entities) is None

    def test_unknown_device_resolves_empty(self, entities):
        intent = parse_command("打开洗衣机", entities)
        assert intent is not None
        assert resolve_targets(intent, entities) == []

    def test_ambiguous_resolves_multiple(self, entities):
        intent = parse_command("打开灯", entities)
        assert intent.all_matching is False
        assert len(resolve_targets(intent, entities)) == 3

    def test_room_mismatch_resolves_empty(self, entities):
        # 卧室没有空调：不应错误命中客厅空调
        intent = parse_command("关闭卧室空调", entities)
        assert resolve_targets(intent, entities) == []

    def test_intent_keeps_raw_text(self, entities):
        intent = parse_command("打开客厅灯", entities)
        assert intent.raw == "打开客厅灯"

    def test_parse_without_entities(self):
        # entities 缺省时仅做文本解析，不进解析不了实体列表也不报错
        intent = parse_command("打开客厅灯")
        assert intent.action == "turn_on"
        assert intent.room == "客厅"


# ---------------------------------------------------------------------------
# resolve_service 覆盖矩阵
# ---------------------------------------------------------------------------
class TestResolveServiceMatrix:
    def _intent(self, action, domain=None, value=None):
        return ControlIntent(raw="", action=action, domain=domain, value=value)

    def test_turn_on_light_with_value(self):
        intent = self._intent("turn_on", "light", 80)
        assert resolve_service(intent) == ("light", "turn_on", {"brightness_pct": 80})

    def test_turn_on_plain(self):
        assert resolve_service(self._intent("turn_on", "switch")) == ("switch", "turn_on", {})

    def test_turn_off_plain(self):
        assert resolve_service(self._intent("turn_off", "switch")) == ("switch", "turn_off", {})

    def test_toggle(self):
        assert resolve_service(self._intent("toggle", "light")) == ("light", "toggle", {})

    def test_open_cover_on_turn_on(self):
        assert resolve_service(self._intent("turn_on", "cover")) == ("cover", "open_cover", {})

    def test_set_fan_percentage(self):
        domain, service, data = resolve_service(self._intent("set", "fan", 60))
        assert (domain, service) == ("fan", "set_percentage")
        assert data["percentage"] == 60

    def test_set_cover_position(self):
        domain, service, data = resolve_service(self._intent("set", "cover", 30))
        assert (domain, service) == ("cover", "set_cover_position")
        assert data["position"] == 30

    def test_set_volume_fraction_passthrough(self):
        # ≤1 的值视为 0-1 区间音量直接使用
        _, _, data = resolve_service(self._intent("set", "media_player", 0.5))
        assert data["volume_level"] == pytest.approx(0.5)

    def test_increase_fan(self):
        assert resolve_service(self._intent("increase", "fan")) == ("fan", "increase_speed", {})

    def test_decrease_media(self):
        assert resolve_service(self._intent("decrease", "media_player")) == (
            "media_player",
            "volume_down",
            {},
        )

    def test_activate_automation(self):
        assert resolve_service(self._intent("activate", "automation")) == (
            "automation",
            "trigger",
            {},
        )

    def test_query_raises(self):
        with pytest.raises(HomeError):
            resolve_service(self._intent("query", "light"))
