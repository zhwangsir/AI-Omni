"""omni_weather 情绪映射测试：WMO weather code → Mood。

覆盖：
- 主要 WMO 代码（0-99）均能映射到合法 mood
- 各 mood 含完整字段（description / color_palette ≤6 / particle_params / music_tags / home_hint）
- 未知 code 走 fallback（calm）
- get_mood 接受 int 与 None
"""

from __future__ import annotations

import pytest

from omni_weather.weather_mood import (
    MOODS,
    WMO_TO_MOOD,
    Mood,
    get_mood,
    list_moods,
)


class TestMoodMapping:
    def test_clear_sky_maps_to_sunny(self):
        """WMO 0 → sunny。"""
        mood = get_mood(0)
        assert mood.mood == "sunny"

    def test_mainly_clear_maps_to_calm(self):
        """WMO 1 → calm。"""
        mood = get_mood(1)
        assert mood.mood == "calm"

    def test_overcast_maps_to_calm(self):
        """WMO 3 → calm（阴天仍归平静）。"""
        mood = get_mood(3)
        assert mood.mood == "calm"

    def test_fog_maps_to_mysterious(self):
        """WMO 45/48 → mysterious。"""
        assert get_mood(45).mood == "mysterious"
        assert get_mood(48).mood == "mysterious"

    def test_drizzle_maps_to_melancholy(self):
        """WMO 51/53/55/56/57 → melancholy。"""
        for code in (51, 53, 55, 56, 57):
            assert get_mood(code).mood == "melancholy", f"code {code}"

    def test_rain_maps_to_melancholy(self):
        """WMO 61/63/65/66/67 → melancholy。"""
        for code in (61, 63, 65, 66, 67):
            assert get_mood(code).mood == "melancholy", f"code {code}"

    def test_rain_showers_maps_to_melancholy(self):
        """WMO 80/81/82 → melancholy。"""
        for code in (80, 81, 82):
            assert get_mood(code).mood == "melancholy", f"code {code}"

    def test_snow_maps_to_dreamy(self):
        """WMO 71/73/75/77/85/86 → dreamy。"""
        for code in (71, 73, 75, 77, 85, 86):
            assert get_mood(code).mood == "dreamy", f"code {code}"

    def test_thunderstorm_maps_to_dramatic(self):
        """WMO 95/96/99 → dramatic。"""
        for code in (95, 96, 99):
            assert get_mood(code).mood == "dramatic", f"code {code}"

    def test_unknown_code_falls_back_to_calm(self):
        """未知 code（如 200）→ calm（fallback）。"""
        mood = get_mood(200)
        assert mood.mood == "calm"

    def test_none_code_falls_back_to_calm(self):
        """None code（缺 weather_code）→ calm。"""
        mood = get_mood(None)
        assert mood.mood == "calm"


class TestMoodStructure:
    def test_all_moods_have_required_fields(self):
        """每个 mood 含 description / color_palette / particle_params / music_tags / home_hint。"""
        for name, mood in MOODS.items():
            assert isinstance(mood, Mood)
            assert mood.mood == name
            assert mood.description
            assert isinstance(mood.color_palette, list)
            assert 1 <= len(mood.color_palette) <= 6, f"{name} 颜色数超限"
            for hex_color in mood.color_palette:
                assert hex_color.startswith("#"), f"{name} 颜色非 hex"
                assert len(hex_color) == 7, f"{name} 颜色 {hex_color} 非 #RRGGBB"
            assert "speed" in mood.particle_params
            assert "density" in mood.particle_params
            assert "brightness" in mood.particle_params
            assert isinstance(mood.music_tags, list)
            assert len(mood.music_tags) >= 1
            assert isinstance(mood.home_hint, str)
            assert mood.home_hint

    def test_sunny_mood_has_warm_palette(self):
        """sunny 调色板含暖色（#F 为橙黄系粗校验：包含 #F / #E / #D 起始）。"""
        mood = get_mood(0)
        # 至少有一个颜色属于暖色范围（#E/#F/#D 开头）
        assert any(c[1].upper() in "DEF" for c in mood.color_palette)

    def test_melancholy_mood_has_cool_palette(self):
        """melancholy 调色板含冷色（蓝灰系 #4-#8 粗校验）。"""
        mood = get_mood(61)
        # 至少有一个颜色属于冷色范围（#4/#5/#6/#7/#8 起头）
        assert any(c[1].upper() in "45678" for c in mood.color_palette)

    def test_particle_params_within_bounds(self):
        """粒子参数有界：speed 0-2 / density 0-4000 / brightness 0-1（CLAUDE.md §六 粒子上限）。"""
        for name, mood in MOODS.items():
            assert 0 <= mood.particle_params["speed"] <= 2, f"{name} speed"
            assert 0 <= mood.particle_params["density"] <= 4000, f"{name} density"
            assert 0 <= mood.particle_params["brightness"] <= 1, f"{name} brightness"

    def test_mood_to_dict_serializable(self):
        """Mood.to_dict 返回可 JSON 序列化 dict。"""
        import json

        mood = get_mood(0)
        d = mood.to_dict()
        # 应可序列化
        json.dumps(d, ensure_ascii=False)
        assert d["mood"] == "sunny"
        assert "color_palette" in d
        assert "particle_params" in d
        assert "music_tags" in d
        assert "home_hint" in d
        assert "description" in d

    def test_list_moods_returns_all(self):
        """list_moods 返回全部 mood 名（≥6 种）。"""
        names = list_moods()
        assert len(names) >= 6
        for n in ("sunny", "calm", "melancholy", "dreamy", "mysterious", "dramatic"):
            assert n in names


class TestWmoTable:
    def test_wmo_table_covers_main_codes(self):
        """WMO_TO_MOOD 覆盖 0-99 主要 code（≥ 20 个）。"""
        assert len(WMO_TO_MOOD) >= 20

    def test_wmo_table_values_are_valid_mood_names(self):
        """WMO_TO_MOOD 的 value 必须是 MOODS 的 key。"""
        for code, mood_name in WMO_TO_MOOD.items():
            assert mood_name in MOODS, f"code {code} → 未知 mood {mood_name}"
            assert isinstance(code, int)
            assert 0 <= code <= 99
