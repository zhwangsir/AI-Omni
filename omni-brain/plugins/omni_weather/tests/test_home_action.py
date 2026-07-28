"""omni_weather 家居动作建议测试。

验证纯函数 ``build_home_hint(weather_data, mood)`` 根据天气生成家居建议；
不直接调用 omni_home（通过返回值 / 事件总线由大脑决策执行）。
"""

from __future__ import annotations

from typing import Any

import pytest

from omni_weather.home_action import build_home_hint


def _weather(temp: float, code: int = 0, humidity: int = 50) -> dict[str, Any]:
    """构造一份预制 weather_data。"""
    return {
        "current": {
            "temperature": temp,
            "humidity": humidity,
            "wind_speed": 2.0,
            "weather_code": code,
            "apparent_temperature": temp,
        },
        "city": "测试",
    }


class TestBuildHomeHint:
    def test_rain_suggests_close_curtains(self):
        """下雨 → 关窗帘。"""
        hint = build_home_hint(_weather(20.0, code=61), mood=None)  # type: ignore[arg-type]
        assert hint["ok"] is True
        actions = hint["actions"]
        assert any(a["action"] == "close_curtains" for a in actions), f"下雨应建议关窗帘: {actions}"

    def test_drizzle_suggests_close_curtains(self):
        """毛毛雨 → 关窗帘。"""
        hint = build_home_hint(_weather(15.0, code=51), mood=None)  # type: ignore[arg-type]
        assert any(a["action"] == "close_curtains" for a in hint["actions"])

    def test_hot_suggests_ac_on(self):
        """温度 > 28°C → 开空调。"""
        hint = build_home_hint(_weather(32.0, code=0), mood=None)  # type: ignore[arg-type]
        assert any(a["action"] == "turn_on_ac" for a in hint["actions"])
        # 验证 reason 含温度信息
        ac = next(a for a in hint["actions"] if a["action"] == "turn_on_ac")
        assert "32" in ac["reason"] or "高温" in ac["reason"]

    def test_cold_suggests_heater_on(self):
        """温度 < 18°C → 开暖气。"""
        hint = build_home_hint(_weather(10.0, code=0), mood=None)  # type: ignore[arg-type]
        assert any(a["action"] == "turn_on_heater" for a in hint["actions"])
        heater = next(a for a in hint["actions"] if a["action"] == "turn_on_heater")
        assert "10" in heater["reason"] or "低温" in heater["reason"]

    def test_fog_suggests_turn_on_lights(self):
        """雾天 → 开灯。"""
        hint = build_home_hint(_weather(18.0, code=45), mood=None)  # type: ignore[arg-type]
        assert any(a["action"] == "turn_on_lights" for a in hint["actions"])

    def test_mood_sunny_suggests_open_curtains(self):
        """晴天 → 开窗帘（让阳光进来）。"""
        hint = build_home_hint(_weather(22.0, code=0), mood="sunny")
        assert any(a["action"] == "open_curtains" for a in hint["actions"])

    def test_mood_dreamy_suggests_dim_lights(self):
        """雪天 → 调暗灯光（梦幻氛围）。"""
        hint = build_home_hint(_weather(-2.0, code=75), mood="dreamy")
        assert any(a["action"] == "dim_lights" for a in hint["actions"])

    def test_comfortable_no_action(self):
        """温度舒适（18-28°C）、晴天、无恶劣天气 → 返回空 actions（但 ok=True）。"""
        hint = build_home_hint(_weather(22.0, code=0), mood="sunny")
        # 至少有 open_curtains，但若去掉 mood 则应无温控动作
        hint2 = build_home_hint(_weather(22.0, code=1), mood=None)  # type: ignore[arg-type]
        actions = [a["action"] for a in hint2["actions"]]
        assert "turn_on_ac" not in actions
        assert "turn_on_heater" not in actions

    def test_boundary_28_no_ac(self):
        """温度 = 28°C 时不触发开空调（> 28 才触发）。"""
        hint = build_home_hint(_weather(28.0, code=0), mood=None)  # type: ignore[arg-type]
        assert not any(a["action"] == "turn_on_ac" for a in hint["actions"])

    def test_boundary_18_no_heater(self):
        """温度 = 18°C 时不触发开暖气（< 18 才触发）。"""
        hint = build_home_hint(_weather(18.0, code=0), mood=None)  # type: ignore[arg-type]
        assert not any(a["action"] == "turn_on_heater" for a in hint["actions"])

    def test_missing_temperature_field(self):
        """weather_data 缺 temperature 字段时不抛错（跳过温控建议）。"""
        data = {"current": {"weather_code": 0}}
        hint = build_home_hint(data, mood=None)  # type: ignore[arg-type]
        assert hint["ok"] is True

    def test_missing_current_field(self):
        """weather_data 缺 current 字段时不抛错。"""
        hint = build_home_hint({}, mood=None)  # type: ignore[arg-type]
        assert hint["ok"] is True
        assert hint["actions"] == []

    def test_hint_includes_summary(self):
        """返回结果含 summary 文本。"""
        hint = build_home_hint(_weather(30.0, code=0), mood=None)  # type: ignore[arg-type]
        assert "summary" in hint
        assert isinstance(hint["summary"], str)

    def test_each_action_has_required_fields(self):
        """每个 action 含 action / reason 字段。"""
        hint = build_home_hint(_weather(30.0, code=61), mood=None)  # type: ignore[arg-type]
        for a in hint["actions"]:
            assert "action" in a
            assert "reason" in a
            assert isinstance(a["action"], str)
            assert isinstance(a["reason"], str)
            assert a["action"]
            assert a["reason"]
