"""omni_home 插件 tools：6 个 home_* 工具与 ``register(ctx)`` 注册入口。

工具统一返回 JSON 字符串 ``{"ok": bool, "data": ..., "error": ...}``：

- ``home_status``   ：插件状态 + 配置摘要（token 脱敏）
- ``home_refresh``  ：从 HA 拉取全部实体并重建知识图谱缓存
- ``home_control``  ：自然语言控制指令（"把客厅空调调到26度"）
- ``home_query``    ：自然语言状态查询（"客厅灯开着吗"）
- ``home_list``     ：家庭结构 / 设备清单（可按房间、品类过滤）
- ``home_config``   ：配置读写（get 摘要 / set 运行时可调项）

进程内 :class:`Runtime` 单例持有配置、客户端与实体缓存；
所有工具接受 ``fake=True`` 使用演示家庭 fake 客户端（无需真实 HA）。
"""

from __future__ import annotations

import dataclasses
import json
import logging
from typing import Any, Callable

from .config import HomeConfig
from .entities import Entity, parse_states
from .errors import HomeError
from .knowledge import HomeGraph, describe_state
from .nlu import parse_command, resolve_service, resolve_targets

logger = logging.getLogger(__name__)

#: 运行时可调配置项（action=set 白名单）
RUNTIME_SETTABLE: tuple[str, ...] = (
    "ha_url",
    "ha_token",
    "connect_timeout",
    "read_timeout",
    "default_room",
)


# ---------------------------------------------------------------------------
# 运行时单例
# ---------------------------------------------------------------------------
class Runtime:
    """进程内运行时：持有配置、HA 客户端、实体缓存与事件发布器。

    ``client`` 可由测试/CLI 预置为 :class:`FakeHomeAssistantClient`；
    ``entities`` 为最近一次 refresh 的实体缓存（None 表示尚未刷新）。
    """

    def __init__(self, config: HomeConfig | None = None):
        self.config = config or HomeConfig()
        self.client: Any | None = None
        self.entities: list[Entity] | None = None
        self.fake_mode = False
        self.event_publisher: Any = None


_runtime = Runtime()


def _reset_runtime(runtime: Runtime | None = None) -> Runtime:
    """替换进程内运行时（测试隔离用），返回新实例。"""
    global _runtime
    _runtime = runtime or Runtime()
    return _runtime


# ---------------------------------------------------------------------------
# JSON 响应约定
# ---------------------------------------------------------------------------
def _ok(data: Any) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False)


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 客户端与实体缓存
# ---------------------------------------------------------------------------
def _client(rt: Runtime, fake: bool) -> Any:
    """取 HA 客户端；未预置时按 fake/真实构建并缓存。"""
    if fake:
        rt.fake_mode = True  # 预置客户端场景也如实上报 fake 模式
    if rt.client is not None:
        return rt.client
    if fake:
        from .client import FakeHomeAssistantClient

        rt.client = FakeHomeAssistantClient.with_demo_home()
        return rt.client
    if not rt.config.ha_token:
        raise HomeError("未配置 ha_token，请先通过 home_config set ha_token 配置")
    from .client import HomeAssistantClient

    rt.client = HomeAssistantClient(rt.config)
    return rt.client


def _entities(rt: Runtime, fake: bool) -> list[Entity]:
    """取实体缓存；缓存为空时自动 refresh 一次。"""
    if rt.entities is None:
        states = _client(rt, fake).get_states()
        rt.entities = parse_states(states)
    return rt.entities


def _publish(rt: Runtime, event_type: str, payload: dict[str, Any]) -> None:
    """向事件总线发布事件（未接入总线时静默跳过）。"""
    bus = rt.event_publisher
    if bus is not None and callable(getattr(bus, "publish", None)):
        try:
            bus.publish(event_type, payload)
        except Exception:  # noqa: BLE001 - 总线异常不应拖垮控制结果
            logger.debug("事件发布失败: %s", event_type)


def _entity_view(entity: Entity, **extra: Any) -> dict[str, Any]:
    """实体的工具返回视图：基础字段 + 中文状态描述 + 扩展字段。"""
    view = {**entity.to_dict(), "state_text": describe_state(entity)}
    view.update(extra)
    return view


# ---------------------------------------------------------------------------
# Tool 元数据注册表
# ---------------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = []


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    required: list[str] | None = None,
    emoji: str = "",
) -> Callable:
    """@tool 装饰器：为函数附加 tool schema 元数据并登记到 TOOLS。"""

    def decorator(func: Callable) -> Callable:
        TOOLS.append(
            {
                "name": name,
                "description": description,
                "emoji": emoji,
                "schema": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": parameters,
                        "required": list(required or []),
                    },
                },
                "handler_func": func,
            }
        )
        return func

    return decorator


_FAKE_PARAM = {
    "type": "boolean",
    "description": "为 true 时使用演示家庭 fake 客户端（演示/测试，无需真实 Home Assistant）。",
}


# ---------------------------------------------------------------------------
# Tool 1：状态查询
# ---------------------------------------------------------------------------
@tool(
    name="home_status",
    description=(
        "查询智能家居插件状态：是否 fake 模式、实体缓存规模、"
        "Home Assistant 连接配置摘要（token 脱敏）。"
    ),
    parameters={"fake": _FAKE_PARAM},
    emoji="🏠",
)
def home_status(fake: bool = False) -> str:
    """返回插件状态与配置摘要。"""
    rt = _runtime
    if fake:
        rt.fake_mode = True
    entities = rt.entities or []
    return _ok(
        {
            "fake_mode": rt.fake_mode,
            "cached_entities": len(entities),
            "rooms": len({e.room for e in entities if e.room}),
            "config": rt.config.summary(),
        }
    )


# ---------------------------------------------------------------------------
# Tool 2：刷新实体
# ---------------------------------------------------------------------------
@tool(
    name="home_refresh",
    description=(
        "从 Home Assistant 拉取全部实体状态并重建本地知识图谱缓存，"
        "返回家庭规模统计（设备数/房间数/场景数/各品类计数）。"
    ),
    parameters={"fake": _FAKE_PARAM},
    emoji="🔄",
)
def home_refresh(fake: bool = False) -> str:
    """拉取实体、重建缓存，返回知识图谱统计。"""
    try:
        rt = _runtime
        states = _client(rt, fake).get_states()
        rt.entities = parse_states(states)
        graph = HomeGraph.from_entities(rt.entities)
        return _ok(graph.stats())
    except Exception as exc:  # noqa: BLE001 - 统一映射为 ok:false
        logger.debug("home_refresh 失败: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 3：自然语言控制
# ---------------------------------------------------------------------------
@tool(
    name="home_control",
    description=(
        "执行一句中文家居控制指令，例如：打开客厅灯 / 关闭客厅空调 / "
        "把空调温度调到26度 / 把卧室灯调亮一点 / 打开所有灯 / 执行回家场景 / "
        "锁上大门门锁。支持开/关/切换/调数值/调高/调低/批量/场景激活。"
        "状态查询请改用 home_query。"
    ),
    parameters={
        "command": {"type": "string", "description": "中文控制指令，不能为空。"},
        "fake": _FAKE_PARAM,
    },
    required=["command"],
    emoji="🎛️",
)
def home_control(command: str, fake: bool = False) -> str:
    """解析指令 → 定位目标 → 调用 HA 服务 → 返回执行结果。"""
    try:
        rt = _runtime
        if not command or not command.strip():
            raise ValueError("command 不能为空")
        entities = _entities(rt, fake)
        intent = parse_command(command, entities)
        if intent is None:
            raise HomeError(f"无法识别指令: {command}")
        if intent.action == "query":
            raise HomeError("这是查询指令，请改用 home_query 工具")
        room = intent.room or rt.config.default_room or None
        intent.room = room
        targets = resolve_targets(intent, entities)
        if not targets:
            raise HomeError(f"找不到匹配的设备: {intent.name_query or command}")
        if len(targets) > 1 and not intent.all_matching:
            names = "、".join(f"{e.name}（{e.room or '未分组'}）" for e in targets)
            raise HomeError(f"指令存在歧义，匹配到多个设备: {names}，请说得更具体")
        results: list[dict[str, Any]] = []
        client = _client(rt, fake)
        for target in targets:
            domain, service, data = resolve_service(intent, target)
            changed = client.call_service(domain, service, entity_id=target.entity_id, data=data)
            latest = changed[0] if changed else client.get_state(target.entity_id)
            fresh = parse_states([latest])[0]
            results.append(
                _entity_view(fresh, service=f"{domain}.{service}")
            )
            # 同步缓存，保证后续 query/list 读到最新状态
            if rt.entities is not None:
                rt.entities = [fresh if e.entity_id == fresh.entity_id else e for e in rt.entities]
        payload = {"command": intent.raw, "results": results}
        _publish(rt, "home.control_executed", payload)
        return _ok(payload)
    except Exception as exc:  # noqa: BLE001
        logger.debug("home_control 失败: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 4：自然语言查询
# ---------------------------------------------------------------------------
@tool(
    name="home_query",
    description=(
        "执行一句中文家居状态查询，例如：卧室灯开着吗 / 客厅温度多少 / "
        "大门门锁怎么样 / 看看客厅。返回目标设备的中文状态描述。"
        "控制类指令请改用 home_control。"
    ),
    parameters={
        "command": {"type": "string", "description": "中文查询指令，不能为空。"},
        "fake": _FAKE_PARAM,
    },
    required=["command"],
    emoji="🔍",
)
def home_query(command: str, fake: bool = False) -> str:
    """解析查询指令 → 定位目标 → 返回中文状态描述。"""
    try:
        rt = _runtime
        if not command or not command.strip():
            raise ValueError("command 不能为空")
        entities = _entities(rt, fake)
        intent = parse_command(command, entities)
        if intent is None:
            raise HomeError(f"无法识别查询: {command}")
        if intent.action != "query":
            raise HomeError("这是控制指令，请改用 home_control 工具")
        intent.room = intent.room or rt.config.default_room or None
        targets = resolve_targets(intent, entities)
        if not targets:
            raise HomeError(f"找不到匹配的设备: {intent.name_query or command}")
        answers = [_entity_view(e) for e in targets]
        return _ok({"command": intent.raw, "answers": answers})
    except Exception as exc:  # noqa: BLE001
        logger.debug("home_query 失败: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 5：设备清单
# ---------------------------------------------------------------------------
@tool(
    name="home_list",
    description=(
        "列出家庭结构与设备清单：不带过滤条件时返回完整知识视图"
        "（各房间设备、场景、自动化、统计）；带 room/domain 时返回过滤后的设备列表。"
    ),
    parameters={
        "room": {"type": "string", "description": "按房间过滤（如 客厅），缺省不限。"},
        "domain": {
            "type": "string",
            "description": "按品类过滤（如 light/climate/cover），缺省不限。",
        },
        "fake": _FAKE_PARAM,
    },
    emoji="📋",
)
def home_list(room: str = "", domain: str = "", fake: bool = False) -> str:
    """返回家庭知识视图或过滤后的设备列表。"""
    try:
        rt = _runtime
        entities = _entities(rt, fake)
        graph = HomeGraph.from_entities(entities)
        if not room and not domain:
            return _ok(graph.to_dict())
        filtered = entities
        if room:
            filtered = [e for e in filtered if e.room == room]
        if domain:
            filtered = [e for e in filtered if e.domain == domain]
        devices = [_entity_view(e) for e in sorted(filtered, key=lambda e: e.entity_id)]
        return _ok({"devices": devices, "count": len(devices)})
    except Exception as exc:  # noqa: BLE001
        logger.debug("home_list 失败: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Tool 6：配置读写
# ---------------------------------------------------------------------------
@tool(
    name="home_config",
    description=(
        "智能家居配置读写：action=get 返回完整配置摘要（token 脱敏）；"
        "action=set 修改运行时可调项（ha_url/ha_token/connect_timeout/"
        "read_timeout/default_room），原地生效。"
    ),
    parameters={
        "action": {
            "type": "string",
            "enum": ["get", "set"],
            "description": "操作类型，默认 get。",
        },
        "key": {
            "type": "string",
            "description": "配置项名（action=set 时必需，且必须在可调项名单内）。",
        },
        "value": {
            "type": "string",
            "description": "新值（数值型会自动做类型转换与校验）。",
        },
    },
    emoji="⚙️",
)
def home_config(action: str = "get", key: str | None = None, value: Any = None) -> str:
    """get 返回配置摘要；set 校验后原地修改运行时可调项。"""
    try:
        rt = _runtime
        if action == "get":
            return _ok(rt.config.summary())
        if action == "set":
            if not key:
                raise ValueError("action=set 时 key 必需")
            if key not in RUNTIME_SETTABLE:
                raise ValueError(
                    f"配置项 {key} 不支持运行时修改（可调: {', '.join(RUNTIME_SETTABLE)}）"
                )
            # 先构造候选配置（复用 from_dict 的强转与校验），再原地拷贝字段：
            # 已缓存的客户端持有同一 config 对象，可立即感知变更。
            candidate = HomeConfig.from_dict({**rt.config.summary(mask_token=False), key: value})
            for field in dataclasses.fields(HomeConfig):
                setattr(rt.config, field.name, getattr(candidate, field.name))
            return _ok({"key": key, "value": getattr(rt.config, key)})
        raise ValueError(f"未知 action: {action}")
    except Exception as exc:  # noqa: BLE001
        logger.debug("home_config 失败: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# 注册（对齐 WeBrain 插件契约：ctx.register_tool + 可选事件总线接入）
# ---------------------------------------------------------------------------
def _make_handler(func: Callable) -> Callable:
    """把工具函数适配为 registry handler：``(args: dict, **kw) -> JSON 字符串``。"""

    def handler(args: dict[str, Any], **_: Any) -> str:
        try:
            return func(**(args or {}))
        except Exception as exc:  # 参数错误等，统一为 ok:false
            logger.debug("home tool %s 调用失败: %s", getattr(func, "__name__", "?"), exc)
            return _err(str(exc))

    return handler


def register(ctx) -> None:
    """把 6 个 home_* tools 注册到插件上下文；若 ctx 携带事件总线则接入。"""
    for meta in TOOLS:
        ctx.register_tool(
            name=meta["name"],
            toolset="omni_home",
            schema=meta["schema"],
            handler=_make_handler(meta["handler_func"]),
            description=meta["description"],
            emoji=meta["emoji"],
        )
    bus = getattr(ctx, "event_bus", None)
    if bus is not None and callable(getattr(bus, "publish", None)):
        _runtime.event_publisher = bus
    logger.info("omni_home 插件已注册 %d 个 tools", len(TOOLS))
