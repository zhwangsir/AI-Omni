"""omni_home 实体模型与解析。

把 Home Assistant ``GET /api/states`` 的原始 JSON 解析为 :class:`Entity`，
并提供按 domain/room 分组与按名称/别名/entity_id 的模糊匹配。

房间推断优先级：``attributes.room`` > ``attributes.area`` > 名称中的常见房间词；
不做拼音/英文猜测，避免误判。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: 常见受控 domain（scene/automation 也可被"执行"类指令触发）
SUPPORTED_DOMAINS: tuple[str, ...] = (
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
    "lock",
    "script",
)

#: 常见中文房间词，用于从实体名称推断房间归属
COMMON_ROOMS: tuple[str, ...] = (
    "客厅",
    "主卧",
    "次卧",
    "卧室",
    "儿童房",
    "书房",
    "厨房",
    "餐厅",
    "卫生间",
    "浴室",
    "阳台",
    "走廊",
    "玄关",
    "车库",
    "办公室",
    "茶室",
    "影音室",
)


@dataclass
class Entity:
    """一个 Home Assistant 实体的本地视图。"""

    entity_id: str
    name: str
    state: str
    attributes: dict[str, Any] = field(default_factory=dict)
    room: str = ""

    @property
    def domain(self) -> str:
        """entity_id 的前缀（``light.living_room`` → ``light``）。"""
        return self.entity_id.split(".", 1)[0]

    def to_dict(self) -> dict[str, Any]:
        """返回可 JSON 序列化的实体视图。"""
        return {
            "entity_id": self.entity_id,
            "domain": self.domain,
            "name": self.name,
            "state": self.state,
            "room": self.room,
            "attributes": self.attributes,
        }


def infer_room(name: str, entity_id: str, attributes: dict[str, Any]) -> str:
    """推断实体房间归属：attributes 显式标注优先，其次名称中的常见房间词。"""
    for key in ("room", "area"):
        value = str(attributes.get(key) or "").strip()
        if value:
            return value
    for room in COMMON_ROOMS:
        if room in name:
            return room
    return ""


def parse_states(states: list[dict[str, Any]]) -> list[Entity]:
    """把 ``GET /api/states`` 的返回解析为实体列表；跳过畸形条目。"""
    entities: list[Entity] = []
    for item in states or []:
        if not isinstance(item, dict):
            continue
        entity_id = str(item.get("entity_id") or "")
        if "." not in entity_id:
            continue
        attributes = item.get("attributes") or {}
        if not isinstance(attributes, dict):
            attributes = {}
        name = str(attributes.get("friendly_name") or entity_id)
        entities.append(
            Entity(
                entity_id=entity_id,
                name=name,
                state=str(item.get("state") or ""),
                attributes=attributes,
                room=infer_room(name, entity_id, attributes),
            )
        )
    return entities


def group_by_domain(entities: list[Entity]) -> dict[str, list[Entity]]:
    """按 domain 分组。"""
    grouped: dict[str, list[Entity]] = {}
    for entity in entities:
        grouped.setdefault(entity.domain, []).append(entity)
    return grouped


def group_by_room(entities: list[Entity]) -> dict[str, list[Entity]]:
    """按房间分组；无房间的实体不计入任何房间。"""
    grouped: dict[str, list[Entity]] = {}
    for entity in entities:
        if entity.room:
            grouped.setdefault(entity.room, []).append(entity)
    return grouped


def _score(entity: Entity, query: str) -> int:
    """匹配打分：精确名称 > 精确别名 > 名称子串 > 别名子串 > entity_id 子串。"""
    if not query:
        return 0
    aliases = [str(a) for a in (entity.attributes.get("aliases") or [])]
    if query == entity.name:
        return 100
    if query in aliases:
        return 90
    if query in entity.name or (entity.name and entity.name in query):
        return 60
    for alias in aliases:
        if query in alias or (alias and alias in query):
            return 55
    if query in entity.entity_id:
        return 40
    return 0


def find_entities(
    entities: list[Entity],
    query: str = "",
    room: str | None = None,
    domain: str | None = None,
) -> list[Entity]:
    """按 room/domain 过滤后按 query 模糊匹配，按匹配分降序返回。

    ``query`` 为空时返回过滤后的全量（按 entity_id 排序，保证输出稳定）。
    """
    candidates = entities
    if room:
        candidates = [e for e in candidates if e.room == room]
    if domain:
        candidates = [e for e in candidates if e.domain == domain]
    if not query:
        return sorted(candidates, key=lambda e: e.entity_id)
    scored = [(e, _score(e, query)) for e in candidates]
    scored = [(e, s) for e, s in scored if s > 0]
    # 同分时名称短者在前（更具体的匹配优先），保证结果确定
    scored.sort(key=lambda item: (-item[1], len(item[0].name), item[0].entity_id))
    return [e for e, _ in scored]
