"""omni_home 自然语言理解：把中文家居指令解析为结构化的 :class:`ControlIntent`。

纯规则 + 模板匹配，不依赖任何模型/网络，保证本地可解释、可测试：

- ``parse_command``   ：文本 → 控制意图（动作 / 房间 / domain / 数值 / 目标名）
- ``resolve_targets`` ：意图 + 实体列表 → 目标实体（只保留匹配分最高者）
- ``resolve_service`` ：意图 (+ 目标实体) → Home Assistant (domain, service, data)

支持的动作：turn_on / turn_off / toggle / set / increase / decrease / query / activate；
数值支持阿拉伯数字与常见中文数字（一/两/三…十组合/半）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .entities import COMMON_ROOMS, Entity, find_entities
from .entities import _score as _match_score
from .errors import HomeError

# ---------------------------------------------------------------------------
# 词表与正则
# ---------------------------------------------------------------------------

#: domain 关键词（按优先级排列，先命中先生效；空调须先于温度，避免"空调温度"误判 sensor）
_DOMAIN_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("空调", "climate"),
    ("电视", "media_player"),
    ("风扇", "fan"),
    ("窗帘", "cover"),
    ("门锁", "lock"),
    ("灯", "light"),
    ("场景", "scene"),
    ("自动化", "automation"),
    ("温度", "sensor"),
    ("湿度", "sensor"),
    ("模式", "scene"),
)

#: 中文数字 → 数值（支持 十 组合与 半）
_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

_NUMBER = r"(?:\d+(?:\.\d+)?|[零一二两三四五六七八九十]+|半)"
_UNIT = r"(?:°C|℃|度|%|％|级|格|档)"

_ACTIVATE_VERBS = ("执行", "运行")
_ACTIVATE_HINTS = ("场景", "模式", "自动化")
_QUERY_PREFIX = ("查询", "查一下", "问一问", "看看")
_QUERY_SUFFIX = ("怎么样", "怎样", "如何", "多少", "吗", "呢", "没有")
_QUERY_STATE_WORDS = ("开着", "关着", "开了", "关了")
_LOCK_VERBS = ("锁上", "反锁")
_TOGGLE_VERBS = ("切换",)
_TURN_OFF_VERBS = ("关闭", "关掉", "关上", "关")
_TURN_ON_VERBS = ("打开", "开启", "开")
_ALL_WORDS = ("所有", "全部")
_FILLER_WORDS = ("请", "帮我", "帮忙", "麻烦", "现在")
_PARTICLE_WORDS = ("把", "的", "了", "吧", "啊", "呀", "一下")
#: 非查询指令中的"参数词"（属于被调参数而非设备名本身）
_PARAM_WORDS = ("温度", "音量", "亮度", "声音", "湿度")

#: 设置类：动词 + 数值（单位可缺省，兼容"调到50"这类裸数字）
_SET_RE = re.compile(
    r"(调到|调至|调成|调整为|调整成|设置为|设定为|设置成|设为|设置)\s*(" + _NUMBER + r")\s*(" + _UNIT + r")?"
)
#: 调高/调低类：动词 + （数值+单位 | 一点），数值必须带单位以避免把"一点"误当 1
_INCREASE_RE = re.compile(
    r"(调高|调大|调亮|调响|升高|加大|增大|增强)\s*(?:(" + _NUMBER + r")\s*(" + _UNIT + r")|一点[儿]?|一些)?"
)
_DECREASE_RE = re.compile(
    r"(调低|调小|调暗|降低|减小|减弱)\s*(?:(" + _NUMBER + r")\s*(" + _UNIT + r")|一点[儿]?|一些)?"
)
_INCREASE_HINT_RE = re.compile(r"[大亮高响强]一点[儿]?")
_DECREASE_HINT_RE = re.compile(r"[小暗低弱]一点[儿]?")


# ---------------------------------------------------------------------------
# 意图模型
# ---------------------------------------------------------------------------

@dataclass
class ControlIntent:
    """一条家居控制意图。

    ``action`` ∈ turn_on / turn_off / toggle / set / increase / decrease / query / activate；
    ``name_query`` 为剥离动作词/数值/助词后的目标名称（保留房间与品类词，供模糊匹配）。
    """

    raw: str
    action: str
    room: str | None = None
    domain: str | None = None
    value: float | None = None
    name_query: str = ""
    all_matching: bool = False

    def to_dict(self) -> dict:
        """返回可 JSON 序列化的意图视图。"""
        return {
            "raw": self.raw,
            "action": self.action,
            "room": self.room,
            "domain": self.domain,
            "value": self.value,
            "name_query": self.name_query,
            "all_matching": self.all_matching,
        }


# ---------------------------------------------------------------------------
# 文本解析
# ---------------------------------------------------------------------------

def _parse_cn_number(text: str) -> float | None:
    """解析简单中文数字（0-99 及 半），无法解析返回 None。"""
    text = text.strip()
    if not text:
        return None
    if text == "半":
        return 0.5
    if "十" in text:
        left, _, right = text.partition("十")
        if (left and left not in _CN_DIGITS) or (right and right not in _CN_DIGITS):
            return None
        tens = _CN_DIGITS.get(left, 1) if left else 1
        units = _CN_DIGITS.get(right, 0) if right else 0
        return float(tens * 10 + units)
    if len(text) == 1 and text in _CN_DIGITS:
        return float(_CN_DIGITS[text])
    return None


def _to_value(num_text: str | None) -> float | None:
    """把正则捕获的数值文本统一转为 float。"""
    if num_text is None:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", num_text):
        return float(num_text)
    return _parse_cn_number(num_text)


def _strip_fillers(body: str) -> str:
    """去掉开场客套与时间副词（请/帮我/现在…）。"""
    for word in _FILLER_WORDS:
        body = body.replace(word, "")
    return body


def _detect_room(body: str) -> str | None:
    """从文本中识别房间词（取词表中首个命中）。"""
    for room in COMMON_ROOMS:
        if room in body:
            return room
    return None


def _detect_domain(body: str) -> str | None:
    """按优先级识别 domain 关键词。"""
    for keyword, domain in _DOMAIN_KEYWORDS:
        if keyword in body:
            return domain
    return None


def _clean_name_query(body: str, action: str, matched: str) -> str:
    """剥离已匹配片段、助词与参数词，得到目标名称查询串。"""
    q = body.replace(matched, "", 1) if matched else body
    for word in _ALL_WORDS + _PARTICLE_WORDS:
        q = q.replace(word, "")
    if action == "query":
        for word in _QUERY_STATE_WORDS:
            q = q.replace(word, "")
    else:
        for word in _PARAM_WORDS:
            q = q.replace(word, "")
    return q.strip()


def parse_command(text: str, entities: list[Entity] | None = None) -> ControlIntent | None:
    """把一句中文家居指令解析为 :class:`ControlIntent`，无法识别时返回 None。

    解析为纯文本规则，``entities`` 保留给未来的实体感知消歧（当前不使用）。
    """
    del entities  # 当前解析不依赖实体列表，保留参数以兼容调用方签名
    raw = (text or "").strip()
    if not raw:
        return None
    body = _strip_fillers(raw)

    action: str | None = None
    value: float | None = None
    matched = ""

    # 1. 场景/自动化激活（动词 + 场景类名词同时出现，避免"启动空调"误判）
    if any(v in body for v in _ACTIVATE_VERBS) and any(k in body for k in _ACTIVATE_HINTS):
        action = "activate"
        matched = next(v for v in _ACTIVATE_VERBS if v in body)
    # 2. 锁门（"锁上/反锁"语义为 turn_off，由 resolve_service 映射为 lock.lock）
    elif any(v in body for v in _LOCK_VERBS):
        action = "turn_off"
        matched = next(v for v in _LOCK_VERBS if v in body)
    # 3. 查询（前缀"查询…"或后缀"…怎么样/多少/吗"）须先于开/关判断，避免"开着吗"误判 turn_on
    elif body.startswith(_QUERY_PREFIX) or body.endswith(_QUERY_SUFFIX):
        action = "query"
        matched = ""
    # 4. 设置数值（调到/设为…+ 数字）
    elif (m := _SET_RE.search(body)) is not None:
        action = "set"
        value = _to_value(m.group(2))
        matched = m.group(0)
    # 5. 调高 / 调低
    elif (m := _INCREASE_RE.search(body)) is not None and m.group(1) in body:
        action = "increase"
        value = _to_value(m.group(2)) if m.group(3) else None
        matched = m.group(0)
    elif (m := _DECREASE_RE.search(body)) is not None and m.group(1) in body:
        action = "decrease"
        value = _to_value(m.group(2)) if m.group(3) else None
        matched = m.group(0)
    elif (m := _INCREASE_HINT_RE.search(body)) is not None:
        action = "increase"
        matched = m.group(0)
    elif (m := _DECREASE_HINT_RE.search(body)) is not None:
        action = "decrease"
        matched = m.group(0)
    # 6. 切换 / 关 / 开
    elif any(v in body for v in _TOGGLE_VERBS):
        action = "toggle"
        matched = next(v for v in _TOGGLE_VERBS if v in body)
    elif any(v in body for v in _TURN_OFF_VERBS):
        action = "turn_off"
        matched = next(v for v in _TURN_OFF_VERBS if v in body)
    elif any(v in body for v in _TURN_ON_VERBS):
        action = "turn_on"
        matched = next(v for v in _TURN_ON_VERBS if v in body)

    if action is None:
        return None

    all_matching = any(w in body for w in _ALL_WORDS)

    # 查询类：剥离"查询"前缀与"…多少/吗"后缀后再提取目标名
    q_body = body
    if action == "query":
        for prefix in _QUERY_PREFIX:
            if q_body.startswith(prefix):
                q_body = q_body[len(prefix):]
                break
        for suffix in _QUERY_SUFFIX:
            if q_body.endswith(suffix):
                q_body = q_body[: -len(suffix)]
                break

    return ControlIntent(
        raw=raw,
        action=action,
        room=_detect_room(body),
        domain=_detect_domain(body),
        value=value,
        name_query=_clean_name_query(q_body, action, matched),
        all_matching=all_matching,
    )


# ---------------------------------------------------------------------------
# 目标解析与服务映射
# ---------------------------------------------------------------------------

def resolve_targets(intent: ControlIntent, entities: list[Entity]) -> list[Entity]:
    """把意图解析为目标实体列表。

    - ``all_matching`` 时返回 room/domain 过滤后的全量；
    - 否则按名称模糊匹配，**只保留匹配分最高**的一批（同分并列保留），
      避免"客厅台灯"误伤"客厅灯"这类次优命中。
    """
    entities = entities or []
    if intent.all_matching:
        return find_entities(entities, "", room=intent.room, domain=intent.domain)
    matches = find_entities(entities, intent.name_query, room=intent.room, domain=intent.domain)
    if not intent.name_query or len(matches) <= 1:
        return matches
    top = _match_score(matches[0], intent.name_query)
    return [e for e in matches if _match_score(e, intent.name_query) == top]


def _climate_step(intent: ControlIntent, target: Entity | None, sign: int) -> tuple[str, str, dict]:
    """空调调高/调低：基于目标当前设定温度计算新温度。"""
    if target is None:
        raise HomeError("调温需要已知目标空调的当前设定温度")
    base = float(target.attributes.get("temperature") or 0.0)
    step = float(intent.value) if intent.value is not None else 1.0
    return ("climate", "set_temperature", {"temperature": base + sign * step})


def resolve_service(
    intent: ControlIntent,
    target: Entity | None = None,
) -> tuple[str, str, dict]:
    """把意图映射为 Home Assistant 服务调用 ``(domain, service, data)``。

    ``target`` 用于 domain 兜底（意图未含品类词时取目标实体的 domain）
    与空调调温的当前值读取；查询意图无服务可调，抛 :class:`HomeError`。
    """
    if intent.action == "query":
        raise HomeError("查询指令无需调用服务，请读取实体状态")
    domain = intent.domain or (target.domain if target is not None else None)
    if not domain:
        raise HomeError("无法确定目标设备类型（domain）")
    action = intent.action
    value = intent.value

    if action == "turn_on":
        if domain == "light" and value is not None:
            return ("light", "turn_on", {"brightness_pct": int(value)})
        if domain == "cover":
            return ("cover", "open_cover", {})
        if domain == "lock":
            return ("lock", "unlock", {})
        return (domain, "turn_on", {})
    if action == "turn_off":
        if domain == "cover":
            return ("cover", "close_cover", {})
        if domain == "lock":
            return ("lock", "lock", {})
        return (domain, "turn_off", {})
    if action == "toggle":
        return (domain, "toggle", {})
    if action == "set":
        if value is None:
            raise HomeError("设置指令缺少数值")
        if domain == "climate":
            return ("climate", "set_temperature", {"temperature": float(value)})
        if domain == "light":
            return ("light", "turn_on", {"brightness_pct": int(value)})
        if domain == "media_player":
            level = float(value) if float(value) <= 1 else float(value) / 100.0
            return ("media_player", "volume_set", {"volume_level": round(level, 2)})
        if domain == "fan":
            return ("fan", "set_percentage", {"percentage": int(value)})
        if domain == "cover":
            return ("cover", "set_cover_position", {"position": int(value)})
        raise HomeError(f"不支持对 {domain} 设置数值")
    if action == "increase":
        if domain == "climate":
            return _climate_step(intent, target, +1)
        if domain == "light":
            step = int(value) if value is not None else 20
            return ("light", "turn_on", {"brightness_step_pct": step})
        if domain == "media_player":
            return ("media_player", "volume_up", {})
        if domain == "fan":
            return ("fan", "increase_speed", {})
        raise HomeError(f"不支持对 {domain} 执行调高")
    if action == "decrease":
        if domain == "climate":
            return _climate_step(intent, target, -1)
        if domain == "light":
            step = int(value) if value is not None else 20
            return ("light", "turn_on", {"brightness_step_pct": -step})
        if domain == "media_player":
            return ("media_player", "volume_down", {})
        if domain == "fan":
            return ("fan", "decrease_speed", {})
        raise HomeError(f"不支持对 {domain} 执行调低")
    if action == "activate":
        if domain == "automation":
            return ("automation", "trigger", {})
        return (domain, "turn_on", {})  # scene / script 均以 turn_on 触发
    raise HomeError(f"不支持的指令动作: {action}")
