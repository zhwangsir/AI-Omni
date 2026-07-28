"""omni_home 知识图谱测试。

HomeGraph 从实体列表构建"房间 → 设备 / 场景 / 自动化"的本地知识视图，
供 tools 层组织设备清单、生成中文家庭摘要（LLM 上下文 / 回复用户）。
全部基于演示家庭 fake 数据，无网络依赖。
"""

from __future__ import annotations

import json

import pytest

from omni_home.entities import parse_states
from omni_home.knowledge import HomeGraph, describe_state


@pytest.fixture
def graph(demo_states):
    return HomeGraph.from_entities(parse_states(demo_states))


# ---------------------------------------------------------------------------
# 构建与分组
# ---------------------------------------------------------------------------
class TestBuildAndGrouping:
    def test_rooms_sorted_by_device_count(self, graph):
        # 按房间设备数降序：客厅(5) > 卧室(3) > 书房(1)
        assert graph.rooms() == ["客厅", "卧室", "书房"]

    def test_devices_in_living_room(self, graph):
        names = {e.name for e in graph.devices_in_room("客厅")}
        assert names == {"客厅灯", "客厅台灯", "客厅空调", "客厅电视", "客厅温度传感器"}

    def test_devices_in_unknown_room_empty(self, graph):
        assert graph.devices_in_room("阁楼") == []

    def test_domains(self, graph):
        domains = graph.domains()
        assert "light" in domains
        assert "climate" in domains
        assert "scene" in domains

    def test_roomless_devices_excluded_from_rooms(self, graph):
        # 大门门磁 / 门锁 / 场景 / 自动化无房间归属
        for room in graph.rooms():
            names = {e.name for e in graph.devices_in_room(room)}
            assert "大门门磁" not in names
            assert "大门门锁" not in names

    def test_scenes(self, graph):
        assert {e.name for e in graph.scenes()} == {"回家场景", "睡眠场景"}

    def test_automations(self, graph):
        assert [e.name for e in graph.automations()] == ["早安自动化"]

    def test_controllable_excludes_sensors(self, graph):
        names = {e.name for e in graph.controllable()}
        assert "客厅温度传感器" not in names
        assert "大门门磁" not in names
        assert "客厅灯" in names
        assert len(names) == 12

    def test_find_delegates_fuzzy_match(self, graph):
        assert [e.name for e in graph.find("客厅灯")] == ["客厅灯"]


# ---------------------------------------------------------------------------
# 状态中文描述
# ---------------------------------------------------------------------------
class TestDescribeState:
    def test_light_on_off(self, graph):
        light = graph.find("卧室灯")[0]
        assert describe_state(light) == "开启"
        lamp = graph.find("客厅台灯")[0]
        assert describe_state(lamp) == "关闭"

    def test_climate_with_temperature(self, graph):
        ac = graph.find("客厅空调")[0]
        assert describe_state(ac) == "制冷中（设定 26°C）"

    def test_cover_open(self, graph):
        curtain = graph.find("卧室窗帘")[0]
        assert describe_state(curtain) == "打开"

    def test_lock_locked(self, graph):
        door = graph.find("大门门锁")[0]
        assert describe_state(door) == "已上锁"

    def test_sensor_with_unit(self, graph):
        sensor = graph.find("客厅温度传感器")[0]
        assert describe_state(sensor) == "27.5°C"

    def test_binary_sensor_normal(self, graph):
        door = graph.find("大门门磁")[0]
        assert describe_state(door) == "未触发"

    def test_scene_state(self, graph):
        scene = graph.scenes()[0]
        assert describe_state(scene) == "可触发"

    def test_automation_enabled(self, graph):
        auto = graph.automations()[0]
        assert describe_state(auto) == "已启用"


# ---------------------------------------------------------------------------
# 摘要与统计
# ---------------------------------------------------------------------------
class TestSummary:
    def test_describe_mentions_rooms_and_devices(self, graph):
        text = graph.describe()
        assert "客厅" in text
        assert "卧室" in text
        assert "客厅灯" in text
        assert "回家场景" in text

    def test_describe_room(self, graph):
        text = graph.describe_room("客厅")
        assert "客厅" in text
        assert "客厅空调" in text
        assert "26°C" in text

    def test_describe_room_unknown(self, graph):
        assert graph.describe_room("阁楼") == ""

    def test_stats(self, graph):
        stats = graph.stats()
        assert stats["devices"] == 14
        assert stats["rooms"] == 3
        assert stats["scenes"] == 2
        assert stats["by_domain"]["light"] == 3
        assert stats["by_domain"]["lock"] == 1

    def test_room_of(self, graph):
        assert graph.room_of("light.living_room_main") == "客厅"
        assert graph.room_of("lock.front_door") == ""
        assert graph.room_of("nonexistent.x") == ""

    def test_to_dict_jsonable(self, graph):
        data = graph.to_dict()
        json.dumps(data, ensure_ascii=False)
        assert data["stats"]["devices"] == 14
        assert any(r["name"] == "客厅" for r in data["rooms"])


# ---------------------------------------------------------------------------
# 空图边界
# ---------------------------------------------------------------------------
class TestEmptyGraph:
    def test_empty(self):
        graph = HomeGraph.from_entities([])
        assert graph.rooms() == []
        assert graph.devices_in_room("客厅") == []
        assert graph.scenes() == []
        assert graph.controllable() == []
        assert graph.stats()["devices"] == 0
        assert graph.describe_room("客厅") == ""
        assert "无" in graph.describe()
