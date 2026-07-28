"""Manifest 解析器：插件元数据 + 权限 + 事件 + 工具声明。

每个插件根目录的 ``manifest.json`` 经 :func:`parse_manifest` 解析为 :class:`Manifest`；
硬错误（缺 name / name 不以 omni_ 开头 / version 不是 X.Y.Z）抛 :class:`ManifestError`。
软错误（空 description / 工具名非 snake_case / 事件类型非点分格式 / 未知权限前缀）
经 :func:`validate_manifest` 返回错误列表，由调用方决定处理方式。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# name 必须以 omni_ 开头，全小写蛇形
_NAME_RE = re.compile(r"^omni_[a-z][a-z0-9_]*$")
# version 必须形如 X.Y.Z
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
# 工具名 snake_case
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# 事件类型 <domain>.<event> 点分小写
_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
# 全平台默认值
_ALL_PLATFORMS: list[str] = ["macos", "linux", "windows"]
# 已知权限前缀（D15.3 宽松起步：未知前缀告警而非拒绝）
_KNOWN_PERMISSION_PREFIXES: frozenset[str] = frozenset(
    {"network", "voice.listen", "home.control", "fs.read", "fs.write", "tools.register"}
)


class ManifestError(Exception):
    """manifest 硬错误：解析失败。"""


@dataclass
class Events:
    """事件声明：插件发布与订阅的事件类型清单。"""

    publishes: list[str] = field(default_factory=list)
    subscribes: list[str] = field(default_factory=list)


@dataclass
class Manifest:
    """插件 manifest 数据类。

    字段对应 AGENTS.md §7.2 manifest.json 格式。
    """

    name: str
    version: str
    description: str = ""
    author: str = "unknown"
    permissions: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=lambda: list(_ALL_PLATFORMS))
    dependencies: dict[str, str] = field(default_factory=dict)
    events: Events = field(default_factory=Events)
    tools: list[str] = field(default_factory=list)


def _require_str(data: dict[str, Any], key: str) -> str:
    """从 dict 取必填 str 字段；缺失或类型不符抛 ManifestError。"""
    if key not in data:
        raise ManifestError(f"manifest 缺少必填字段: {key}")
    value = data[key]
    if not isinstance(value, str):
        raise ManifestError(f"manifest.{key} 必须是字符串，got {type(value).__name__}")
    return value


def _validate_name(name: str) -> None:
    """校验 name：必填、omni_ 前缀、snake_case。"""
    if not name:
        raise ManifestError("manifest.name 不能为空")
    if not _NAME_RE.match(name):
        raise ManifestError(
            f"manifest.name 必须以 omni_ 开头且为全小写 snake_case，got: {name!r}"
        )


def _validate_version(version: str) -> None:
    """校验 version：X.Y.Z 形式。"""
    if not _VERSION_RE.match(version):
        raise ManifestError(f"manifest.version 必须形如 X.Y.Z，got: {version!r}")


def parse_manifest(data: dict[str, Any]) -> Manifest:
    """解析 manifest dict 为 :class:`Manifest` 实例。

    硬错误抛 :class:`ManifestError`；软错误（如空 description）由 :func:`validate_manifest` 报告。

    :param data: manifest.json 反序列化后的 dict
    :return: :class:`Manifest` 实例
    :raises ManifestError: name/version 不合规时
    """
    if not isinstance(data, dict):
        raise ManifestError(f"manifest 必须是 dict，got {type(data).__name__}")

    name = _require_str(data, "name")
    _validate_name(name)
    version = _require_str(data, "version")
    _validate_version(version)

    description = data.get("description", "")
    if not isinstance(description, str):
        raise ManifestError("manifest.description 必须是字符串")

    author = data.get("author", "unknown")
    if not isinstance(author, str):
        raise ManifestError("manifest.author 必须是字符串")

    permissions = data.get("permissions", [])
    if not isinstance(permissions, list):
        raise ManifestError("manifest.permissions 必须是列表")
    permissions = [str(p) for p in permissions]

    platforms = data.get("platforms")
    if platforms is None:
        platforms = list(_ALL_PLATFORMS)
    else:
        if not isinstance(platforms, list):
            raise ManifestError("manifest.platforms 必须是列表")
        platforms = [str(p) for p in platforms]

    dependencies = data.get("dependencies", {})
    if not isinstance(dependencies, dict):
        raise ManifestError("manifest.dependencies 必须是 dict")
    dependencies = {str(k): str(v) for k, v in dependencies.items()}

    events_data = data.get("events", {})
    if not isinstance(events_data, dict):
        raise ManifestError("manifest.events 必须是 dict")
    publishes = events_data.get("publishes", [])
    subscribes = events_data.get("subscribes", [])
    if not isinstance(publishes, list) or not isinstance(subscribes, list):
        raise ManifestError("manifest.events.publishes/subscribes 必须是列表")
    events = Events(
        publishes=[str(e) for e in publishes],
        subscribes=[str(e) for e in subscribes],
    )

    tools = data.get("tools", [])
    if not isinstance(tools, list):
        raise ManifestError("manifest.tools 必须是列表")
    tools = [str(t) for t in tools]

    return Manifest(
        name=name,
        version=version,
        description=description,
        author=author,
        permissions=permissions,
        platforms=platforms,
        dependencies=dependencies,
        events=events,
        tools=tools,
    )


def validate_manifest(manifest: Manifest) -> list[str]:
    """校验 manifest 软约束；返回错误消息列表（空列表 = 全部通过）。

    软约束包括：空 description / 工具名非 snake_case / 事件类型非点分格式 / 未知权限前缀。

    :param manifest: :class:`Manifest` 实例
    :return: 错误消息列表
    """
    errors: list[str] = []
    if not manifest.description:
        errors.append("manifest.description 为空，建议补充插件用途说明")

    for tool in manifest.tools:
        if not _TOOL_NAME_RE.match(tool):
            errors.append(f"工具名 {tool!r} 不符合 snake_case 命名规范")

    for evt in manifest.events.publishes + manifest.events.subscribes:
        if not _EVENT_TYPE_RE.match(evt):
            errors.append(f"事件类型 {evt!r} 不符合 <domain>.<event> 点分小写格式")

    for perm in manifest.permissions:
        prefix = perm.split(":", 1)[0]
        if prefix not in _KNOWN_PERMISSION_PREFIXES:
            errors.append(f"权限 {perm!r} 前缀不在已知清单内")

    return errors
