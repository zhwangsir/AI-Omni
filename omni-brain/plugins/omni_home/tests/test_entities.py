"""omni_home 实体模型测试：解析、分组、房间推断、模糊匹配。"""

from __future__ import annotations

from omni_home.entities import (
    SUPPORTED_DOMAINS,
    Entity,
    find_entities,
    group_by_domain,
    group_by_room,
    infer_room,
    parse_states,
)


class TestParseStates:
    def test_parse_extracts_fields(self, demo_states):
        entities = parse_states(demo_states)
        assert len(entities) == len(demo_states)
        light = next(e for e in entities if e.entity_id == "light.living_room_main")
        assert light.domain == "light"
        assert light.name == "客厅灯"
        assert light.state == "off"
        assert light.room == "客厅"
        assert light.attributes["brightness"] == 128

    def test_parse_skips_malformed_entries(self):
        states = [
            {"entity_id": "light.ok", "state": "on", "attributes": {}},
            {"no_entity_id": True},
            "not-a-dict",
            {"entity_id": "nodot", "state": "on"},
        ]
        entities = parse_states(states)
        assert [e.entity_id for e in entities] == ["light.ok"]

    def test_missing_friendly_name_falls_back_to_entity_id(self):
        entities = parse_states([{"entity_id": "light.x1", "state": "on", "attributes": {}}])
        assert entities[0].name == "light.x1"

    def test_supported_domains_cover_common_home(self):
        for domain in (
            "light",
            "switch",
            "climate",
            "cover",
            "fan",
            "media_player",
            "sensor",
            "binary_sensor",
            "scene",
            "automation",
        ):
            assert domain in SUPPORTED_DOMAINS


class TestInferRoom:
    def test_room_attribute_wins(self):
        assert infer_room("随便什么灯", "light.x", {"room": "书房"}) == "书房"

    def test_area_attribute_fallback(self):
        assert infer_room("随便什么灯", "light.x", {"area": "阳台"}) == "阳台"

    def test_room_inferred_from_name(self):
        assert infer_room("客厅吊灯", "light.x", {}) == "客厅"
        assert infer_room("主卧吸顶灯", "light.y", {}) == "主卧"

    def test_room_inferred_from_entity_id_pinyin(self):
        # entity_id 无中文房间词时返回空串（不做拼音猜测，避免误判）
        assert infer_room("灯", "light.living_room_lamp", {}) == ""

    def test_no_room_gives_empty(self):
        assert infer_room("门磁", "binary_sensor.door", {}) == ""


class TestGrouping:
    def test_group_by_domain(self, demo_states):
        entities = parse_states(demo_states)
        grouped = group_by_domain(entities)
        assert {e.name for e in grouped["light"]} == {"客厅灯", "客厅台灯", "卧室灯"}
        assert len(grouped["scene"]) == 2
        assert grouped["climate"][0].entity_id == "climate.living_room_ac"

    def test_group_by_room(self, demo_states):
        entities = parse_states(demo_states)
        grouped = group_by_room(entities)
        assert {e.name for e in grouped["客厅"]} == {"客厅灯", "客厅台灯", "客厅空调", "客厅电视", "客厅温度传感器"}
        assert "大门门磁" not in {e.name for room in grouped.values() for e in room}


class TestFindEntities:
    def test_exact_name_beats_substring(self, demo_states):
        entities = parse_states(demo_states)
        # "客厅灯" 精确命中 light.living_room_main，"客厅台灯" 不含连续子串 "客厅灯"
        matches = find_entities(entities, "客厅灯")
        assert matches[0].entity_id == "light.living_room_main"
        assert len(matches) == 1

    def test_substring_matches_multiple(self, demo_states):
        entities = parse_states(demo_states)
        matches = find_entities(entities, "灯")
        names = {e.name for e in matches}
        assert {"客厅灯", "客厅台灯", "卧室灯"} <= names

    def test_alias_match(self, demo_states):
        entities = parse_states(demo_states)
        matches = find_entities(entities, "回家模式")
        assert matches[0].entity_id == "scene.home_mode"

    def test_entity_id_match(self, demo_states):
        entities = parse_states(demo_states)
        matches = find_entities(entities, "living_room_ac")
        assert matches[0].entity_id == "climate.living_room_ac"

    def test_room_filter(self, demo_states):
        entities = parse_states(demo_states)
        matches = find_entities(entities, "灯", room="卧室")
        assert [e.name for e in matches] == ["卧室灯"]

    def test_domain_filter(self, demo_states):
        entities = parse_states(demo_states)
        matches = find_entities(entities, "客厅", domain="climate")
        assert [e.entity_id for e in matches] == ["climate.living_room_ac"]

    def test_no_match_returns_empty(self, demo_states):
        entities = parse_states(demo_states)
        assert find_entities(entities, "不存在的设备") == []

    def test_empty_query_returns_filtered_all(self, demo_states):
        entities = parse_states(demo_states)
        matches = find_entities(entities, "", domain="scene")
        assert len(matches) == 2


class TestEntityModel:
    def test_domain_derived_from_entity_id(self):
        e = Entity(entity_id="climate.ac", name="空调", state="cool", attributes={}, room="客厅")
        assert e.domain == "climate"

    def test_to_dict_jsonable(self):
        e = Entity(
            entity_id="light.x",
            name="灯",
            state="on",
            attributes={"brightness": 100},
            room="客厅",
        )
        d = e.to_dict()
        assert d == {
            "entity_id": "light.x",
            "domain": "light",
            "name": "灯",
            "state": "on",
            "room": "客厅",
            "attributes": {"brightness": 100},
        }
