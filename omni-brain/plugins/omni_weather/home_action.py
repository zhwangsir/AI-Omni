"""智能家居联动建议（纯函数）。

根据天气数据生成家居动作建议。**不直接调用 omni_home**；
通过事件总线 ``publish("weather.home_hint", {hint, reason, ...})`` 或在工具返回结果中
包含 ``home_hint`` 字段，由大脑决策执行。

规则：
- 下雨（WMO 51-67, 80-82）→ 关窗帘
- 温度 > 28°C → 开空调
- 温度 < 18°C → 开暖气
- 雾天（WMO 45, 48）→ 开灯
- mood=sunny → 开窗帘（让阳光进来）
- mood=dreamy（雪天）→ 调暗灯光（梦幻氛围）
"""

from __future__ import annotations

from typing import Any

from omni_weather.weather_mood import get_mood

__all__ = ["build_home_hint"]


# 各 WMO code 类别（与 weather_mood.WMO_TO_MOOD 对齐）
_RAIN_CODES: frozenset[int] = frozenset({51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82})
_FOG_CODES: frozenset[int] = frozenset({45, 48})

# 温度阈值
_HOT_THRESHOLD = 28.0
_COLD_THRESHOLD = 18.0


def build_home_hint(weather_data: dict[str, Any], mood: str | None) -> dict[str, Any]:
    """根据天气数据生成家居动作建议。

    :param weather_data: 标准化天气 dict（含 ``current`` 字段）
    :param mood: 可选 mood 名（如 ``sunny``）；为 None 时按 weather_code 推断
    :return: ``{"ok": True, "actions": [...], "summary": str}``
    """
    actions: list[dict[str, str]] = []
    current = weather_data.get("current") or {}
    weather_code = current.get("weather_code")
    temperature = current.get("temperature")

    # 推断 mood（如未传）
    if mood is None:
        mood_obj = get_mood(weather_code if isinstance(weather_code, int) else None)
        mood_name = mood_obj.mood
    else:
        mood_name = mood

    # 1. 雨天 → 关窗帘
    if isinstance(weather_code, int) and weather_code in _RAIN_CODES:
        actions.append(
            {
                "action": "close_curtains",
                "reason": f"下雨（WMO {weather_code}），关窗帘防雨防潮",
            }
        )

    # 2. 高温 → 开空调
    if isinstance(temperature, (int, float)) and temperature > _HOT_THRESHOLD:
        actions.append(
            {
                "action": "turn_on_ac",
                "reason": f"高温 {temperature}°C，建议开启空调降温",
            }
        )

    # 3. 低温 → 开暖气
    if isinstance(temperature, (int, float)) and temperature < _COLD_THRESHOLD:
        actions.append(
            {
                "action": "turn_on_heater",
                "reason": f"低温 {temperature}°C，建议开启暖气",
            }
        )

    # 4. 雾天 → 开灯
    if isinstance(weather_code, int) and weather_code in _FOG_CODES:
        actions.append(
            {
                "action": "turn_on_lights",
                "reason": f"雾天（WMO {weather_code}），能见度低，建议开灯",
            }
        )

    # 5. 晴天 → 开窗帘
    if mood_name == "sunny":
        actions.append(
            {
                "action": "open_curtains",
                "reason": "晴天，可拉开窗帘让阳光进入",
            }
        )

    # 6. 雪天 → 调暗灯光（梦幻氛围）
    if mood_name == "dreamy":
        actions.append(
            {
                "action": "dim_lights",
                "reason": "雪天梦幻氛围，建议调暗灯光",
            }
        )

    summary = _build_summary(actions)
    return {"ok": True, "actions": actions, "summary": summary}


def _build_summary(actions: list[dict[str, str]]) -> str:
    """把 actions 列表汇总为一句中文。"""
    if not actions:
        return "天气舒适，无需特别家居调整"
    names = [a["action"] for a in actions]
    return "建议动作：" + "、".join(names)
