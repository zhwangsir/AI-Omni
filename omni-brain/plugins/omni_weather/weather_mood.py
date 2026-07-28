"""天气情绪映射表：WMO weather code → Mood。

WMO 标准天气代码（0-99）映射到 6 种基础情绪：

- ``sunny``        晴朗欢快（WMO 0）
- ``calm``         平静（WMO 1, 2, 3，多云/阴）
- ``melancholy``   忧郁（WMO 51-67, 80-82，雨）
- ``dreamy``       梦幻（WMO 71-77, 85-86，雪）
- ``mysterious``   神秘（WMO 45, 48，雾）
- ``dramatic``     戏剧（WMO 95, 96, 99，雷暴）

每个 Mood 含：description / color_palette（≤6 色，遵循 CLAUDE.md §六 Film Atelier 暗房风格）
/ particle_params（speed/density/brightness，供前端 FieldStage 使用）/ music_tags（推荐歌单风格）
/ home_hint（家居建议文本）。

参考：``https://open-meteo.com/en/docs`` 末尾 WMO Weather interpretation code 表。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["Mood", "MOODS", "WMO_TO_MOOD", "get_mood", "list_moods"]


@dataclass(frozen=True)
class Mood:
    """单个情绪描述符。

    :ivar mood: 情绪名（如 ``sunny``）
    :ivar description: 中文描述
    :ivar color_palette: hex 颜色列表（≤6 色）
    :ivar particle_params: 粒子参数 dict（speed/density/brightness）
    :ivar music_tags: 推荐音乐风格标签
    :ivar home_hint: 家居建议文本
    """

    mood: str
    description: str
    color_palette: list[str]
    particle_params: dict[str, float]
    music_tags: list[str]
    home_hint: str

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化 dict。"""
        return {
            "mood": self.mood,
            "description": self.description,
            "color_palette": list(self.color_palette),
            "particle_params": dict(self.particle_params),
            "music_tags": list(self.music_tags),
            "home_hint": self.home_hint,
        }


# ---------------------------------------------------------------------------
# 6 种基础情绪定义（Film Atelier 暗房风格：低饱和、克制）
# ---------------------------------------------------------------------------
MOODS: dict[str, Mood] = {
    "sunny": Mood(
        mood="sunny",
        description="晴朗欢快：阳光充足，色彩明亮，呼吸感轻盈",
        color_palette=["#F4A261", "#E9C46A", "#F1FAEE", "#A8DADC"],
        particle_params={"speed": 0.8, "density": 1500, "brightness": 0.85},
        music_tags=["pop", "upbeat", "sunny", "indie"],
        home_hint="阳光明媚，可拉开窗帘让自然光进入",
    ),
    "calm": Mood(
        mood="calm",
        description="平静：多云到阴，柔和的灰调，节奏舒缓",
        color_palette=["#8D99AE", "#CED4DA", "#DEE2E6", "#6C757D"],
        particle_params={"speed": 0.4, "density": 1000, "brightness": 0.55},
        music_tags=["chill", "calm", "acoustic", "lofi"],
        home_hint="天气平稳，按常规使用即可",
    ),
    "melancholy": Mood(
        mood="melancholy",
        description="忧郁：雨日，冷蓝灰调，雨声白噪",
        color_palette=["#3D5A80", "#5C6B73", "#9DB4C0", "#4A5568"],
        particle_params={"speed": 0.6, "density": 2000, "brightness": 0.45},
        music_tags=["melancholy", "sad", "mellow", "rainy", "piano"],
        home_hint="下雨天，建议关窗帘防潮，可点亮暖光灯",
    ),
    "dreamy": Mood(
        mood="dreamy",
        description="梦幻：雪日，柔白与冰蓝，缓慢飘落",
        color_palette=["#E0FBFC", "#C2DFE3", "#9DB4C0", "#EAF4F4"],
        particle_params={"speed": 0.3, "density": 2500, "brightness": 0.75},
        music_tags=["dreamy", "ambient", "snow", "ethereal"],
        home_hint="雪天路面湿滑，注意保暖，调暗灯光营造氛围",
    ),
    "mysterious": Mood(
        mood="mysterious",
        description="神秘：雾日，朦胧低对比，墨绿与深紫",
        color_palette=["#2B2D42", "#3A506B", "#5D5C61", "#444444"],
        particle_params={"speed": 0.2, "density": 800, "brightness": 0.35},
        music_tags=["ambient", "mysterious", "fog", "dark"],
        home_hint="雾天能见度低，建议开灯并减少外出",
    ),
    "dramatic": Mood(
        mood="dramatic",
        description="戏剧：雷暴，强对比深紫与亮黄，激烈",
        color_palette=["#22223B", "#4A4E69", "#F2E8CF", "#9A8C98"],
        particle_params={"speed": 1.2, "density": 1800, "brightness": 0.7},
        music_tags=["dramatic", "intense", "epic", "storm", "orchestral"],
        home_hint="雷暴天气，建议关好门窗、断开不必要的电器",
    ),
}


# ---------------------------------------------------------------------------
# WMO weather code → mood 名映射
# 完整 WMO 代码表见 Open-Meteo 文档
# ---------------------------------------------------------------------------
WMO_TO_MOOD: dict[int, str] = {
    # 晴朗
    0: "sunny",
    # 多云到阴
    1: "calm",
    2: "calm",
    3: "calm",
    # 雾
    45: "mysterious",
    48: "mysterious",
    # 毛毛雨
    51: "melancholy",
    53: "melancholy",
    55: "melancholy",
    56: "melancholy",
    57: "melancholy",
    # 雨
    61: "melancholy",
    63: "melancholy",
    65: "melancholy",
    66: "melancholy",
    67: "melancholy",
    # 阵雨
    80: "melancholy",
    81: "melancholy",
    82: "melancholy",
    # 雪
    71: "dreamy",
    73: "dreamy",
    75: "dreamy",
    77: "dreamy",
    85: "dreamy",
    86: "dreamy",
    # 雷暴
    95: "dramatic",
    96: "dramatic",
    99: "dramatic",
}


def get_mood(weather_code: int | None) -> Mood:
    """按 WMO weather code 取对应 Mood；未知 code / None 走 calm fallback。

    :param weather_code: WMO weather code（0-99）；None 时返回 calm
    :return: :class:`Mood` 实例
    """
    if weather_code is None:
        return MOODS["calm"]
    name = WMO_TO_MOOD.get(int(weather_code), "calm")
    return MOODS[name]


def list_moods() -> list[str]:
    """返回全部 mood 名清单。"""
    return list(MOODS.keys())
