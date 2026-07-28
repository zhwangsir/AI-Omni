"""omni_home 知识图谱：房间/设备/场景的本地知识视图。

:class:`HomeGraph` 从实体列表构建只读知识视图，回答三类问题：

1. "家里有什么"——房间清单、各房间设备、场景/自动化列表（``rooms`` / ``scenes`` …）；
2. "某设备现在怎样"——中文状态描述（``describe_state``）；
3. "怎么向用户/LLM 描述这个家"——整体摘要（``describe`` / ``to_dict``）。

纯内存结构，构建后即与数据源解耦；tools 层每次刷新实体后重建即可。
"""

from __future__ import annotations

from typing import Any

from .entities import Entity, find_entities, group_by_domain, group_by_room

#: 不可控（只读感知）domain
_SENSOR_ONLY_DOMAINS = {"sensor", "binary_sensor"}

#: climate 状态 → 中文
_CLIMATE_STATES = {
    "cool": "制冷中",
    "heat": "制热中",
    "auto": "自动",
    "dry": "除湿中",
    "fan_only": "送风中",
    "off": "关闭",
}

#: cover 状态 → 中文
_COVER_STATES = {"open": "打开", "closed": "关闭", "opening": "正在打开", "closing": "正在关闭"}


def _fmt_num(value: Any) -> str:
    """数值格式化：整数去掉 .0 尾巴（26.0 → "26"），其余原样。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(num)) if num == int(num) else str(num)


def describe_state(entity: Entity) -> str:
    """把实体状态翻译为面向用户的中文短语。"""
    state = entity.state
    domain = entity.domain
    if domain == "climate":
        text = _CLIMATE_STATES.get(state, state)
        if state != "off" and "temperature" in entity.attributes:
            text += f"（设定 {_fmt_num(entity.attributes['temperature'])}°C）"
        return text
    if domain == "cover":
        return _COVER_STATES.get(state, state)
    if domain == "lock":
        return {"locked": "已上锁", "unlocked": "已解锁"}.get(state, state)
    if domain == "sensor":
        unit = str(entity.attributes.get("unit_of_measurement") or "")
        return f"{state}{unit}"
    if domain == "binary_sensor":
        return {"on": "触发", "off": "未触发"}.get(state, state)
    if domain in ("scene", "script"):
        return "可触发"
    if domain == "automation":
        return {"on": "已启用", "off": "已停用"}.get(state, state)
    return {"on": "开启", "off": "关闭"}.get(state, state)


class HomeGraph:
    """房间/设备/场景的本地知识视图（只读）。"""

    def __init__(self, entities: list[Entity]):
        self._entities = list(entities)
        self._by_room = group_by_room(self._entities)
        self._by_domain = group_by_domain(self._entities)
        self._by_id = {e.entity_id: e for e in self._entities}

    @classmethod
    def from_entities(cls, entities: list[Entity]) -> "HomeGraph":
        """从实体列表构建知识图谱。"""
        return cls(entities)

    # -- 结构查询 ------------------------------------------------------------
    def rooms(self) -> list[str]:
        """房间清单：按设备数降序（同数按名称），摘要展示更自然。"""
        return sorted(self._by_room, key=lambda r: (-len(self._by_room[r]), r))

    def domains(self) -> list[str]:
        """出现的 domain 清单（字母序）。"""
        return sorted(self._by_domain)

    def devices_in_room(self, room: str) -> list[Entity]:
        """某房间的全部设备（entity_id 排序，输出稳定）。"""
        return sorted(self._by_room.get(room, []), key=lambda e: e.entity_id)

    def scenes(self) -> list[Entity]:
        """全部场景。"""
        return sorted(self._by_domain.get("scene", []), key=lambda e: e.entity_id)

    def automations(self) -> list[Entity]:
        """全部自动化。"""
        return sorted(self._by_domain.get("automation", []), key=lambda e: e.entity_id)

    def controllable(self) -> list[Entity]:
        """可被控制的实体（排除只读传感器）。"""
        return [e for e in self._entities if e.domain not in _SENSOR_ONLY_DOMAINS]

    def find(self, query: str) -> list[Entity]:
        """按名称/别名模糊查找实体（委托 entities.find_entities）。"""
        return find_entities(self._entities, query)

    def room_of(self, entity_id: str) -> str:
        """实体的房间归属；实体不存在或无房间时返回空串。"""
        entity = self._by_id.get(entity_id)
        return entity.room if entity is not None else ""

    # -- 摘要 ----------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        """规模统计：设备/房间/场景数与各 domain 计数。"""
        return {
            "devices": len(self._entities),
            "rooms": len(self._by_room),
            "scenes": len(self._by_domain.get("scene", [])),
            "automations": len(self._by_domain.get("automation", [])),
            "by_domain": {d: len(items) for d, items in sorted(self._by_domain.items())},
        }

    def describe_room(self, room: str) -> str:
        """单房间中文摘要："客厅：客厅灯（关闭）、…"；房间不存在返回空串。"""
        devices = self.devices_in_room(room)
        if not devices:
            return ""
        items = "、".join(f"{e.name}（{describe_state(e)}）" for e in devices)
        return f"{room}：{items}"

    def describe(self) -> str:
        """整个家庭的中文摘要（房间设备 + 场景 + 自动化），供回复用户或 LLM 上下文。"""
        if not self._entities:
            return "家中暂无已发现的设备。"
        lines = [f"家庭共 {len(self._entities)} 个设备/实体："]
        for room in self.rooms():
            lines.append(self.describe_room(room))
        roomless = [e for e in self._entities if not e.room and e.domain not in ("scene", "automation")]
        if roomless:
            items = "、".join(f"{e.name}（{describe_state(e)}）" for e in roomless)
            lines.append(f"其他：{items}")
        scenes = self.scenes()
        if scenes:
            lines.append("场景：" + "、".join(e.name for e in scenes))
        automations = self.automations()
        if automations:
            lines.append("自动化：" + "、".join(e.name for e in automations))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """可 JSON 序列化的知识视图（供 tool 返回）。"""
        return {
            "rooms": [
                {
                    "name": room,
                    "devices": [
                        {**e.to_dict(), "state_text": describe_state(e)}
                        for e in self.devices_in_room(room)
                    ],
                }
                for room in self.rooms()
            ],
            "scenes": [e.to_dict() for e in self.scenes()],
            "automations": [e.to_dict() for e in self.automations()],
            "stats": self.stats(),
        }
