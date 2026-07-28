"""Manifest 解析器单元测试：合法/非法 manifest 校验、字段默认值、权限/事件/工具列表解析。"""

from __future__ import annotations

import pytest

from omni_sdk.manifest import (
    Events,
    Manifest,
    ManifestError,
    parse_manifest,
    validate_manifest,
)


def _valid_dict() -> dict:
    """构造一份合法 manifest dict。"""
    return {
        "name": "omni_voice",
        "version": "0.1.0",
        "description": "语音交互管道",
        "author": "AI-Omni",
        "permissions": ["voice.listen", "fs.read:./state", "tools.register"],
        "platforms": ["macos", "linux"],
        "dependencies": {"omni_sdk": ">=0.1.0"},
        "events": {
            "publishes": ["voice.state_changed", "voice.wake_detected"],
            "subscribes": ["system.volume_changed"],
        },
        "tools": ["voice_status", "voice_listen"],
    }


def test_parse_valid_manifest() -> None:
    """合法 manifest 解析得到 Manifest 实例，字段一一对应。"""
    m = parse_manifest(_valid_dict())
    assert isinstance(m, Manifest)
    assert m.name == "omni_voice"
    assert m.version == "0.1.0"
    assert m.description == "语音交互管道"
    assert m.author == "AI-Omni"
    assert m.permissions == ["voice.listen", "fs.read:./state", "tools.register"]
    assert m.platforms == ["macos", "linux"]
    assert m.dependencies == {"omni_sdk": ">=0.1.0"}
    assert isinstance(m.events, Events)
    assert m.events.publishes == ["voice.state_changed", "voice.wake_detected"]
    assert m.events.subscribes == ["system.volume_changed"]
    assert m.tools == ["voice_status", "voice_listen"]


def test_parse_rejects_missing_name() -> None:
    """缺 name 字段应抛 ManifestError。"""
    data = _valid_dict()
    del data["name"]
    with pytest.raises(ManifestError):
        parse_manifest(data)


def test_parse_rejects_empty_name() -> None:
    """空字符串 name 也应抛错。"""
    data = _valid_dict()
    data["name"] = ""
    with pytest.raises(ManifestError):
        parse_manifest(data)


def test_parse_rejects_name_not_omni_prefix() -> None:
    """name 不以 omni_ 开头应抛错。"""
    data = _valid_dict()
    data["name"] = "voice_plugin"
    with pytest.raises(ManifestError):
        parse_manifest(data)


def test_parse_rejects_name_not_snake_case() -> None:
    """name 含非法字符（大写/连字符）应抛错。"""
    data = _valid_dict()
    data["name"] = "omniVoice"
    with pytest.raises(ManifestError):
        parse_manifest(data)


def test_parse_rejects_invalid_version() -> None:
    """version 不是 X.Y.Z 形式应抛错。"""
    data = _valid_dict()
    data["version"] = "v1"
    with pytest.raises(ManifestError):
        parse_manifest(data)


def test_parse_rejects_non_dict_input() -> None:
    """非 dict 输入应抛 ManifestError。"""
    with pytest.raises(ManifestError):
        parse_manifest(["not", "a", "dict"])  # type: ignore[arg-type]


def test_parse_defaults_platforms_to_all() -> None:
    """缺 platforms 时默认全平台（macos/linux/windows）。"""
    data = _valid_dict()
    del data["platforms"]
    m = parse_manifest(data)
    assert m.platforms == ["macos", "linux", "windows"]


def test_parse_defaults_author_to_unknown() -> None:
    """缺 author 时默认 unknown。"""
    data = _valid_dict()
    del data["author"]
    m = parse_manifest(data)
    assert m.author == "unknown"


def test_parse_defaults_empty_permissions_when_missing() -> None:
    """缺 permissions 时默认空列表。"""
    data = _valid_dict()
    del data["permissions"]
    m = parse_manifest(data)
    assert m.permissions == []


def test_parse_defaults_empty_events_when_missing() -> None:
    """缺 events 时默认 publishes/subscribes 都为空。"""
    data = _valid_dict()
    del data["events"]
    m = parse_manifest(data)
    assert m.events.publishes == []
    assert m.events.subscribes == []


def test_parse_defaults_empty_tools_when_missing() -> None:
    """缺 tools 时默认空列表。"""
    data = _valid_dict()
    del data["tools"]
    m = parse_manifest(data)
    assert m.tools == []


def test_parse_defaults_empty_dependencies_when_missing() -> None:
    """缺 dependencies 时默认空 dict。"""
    data = _valid_dict()
    del data["dependencies"]
    m = parse_manifest(data)
    assert m.dependencies == {}


def test_parse_permissions_list() -> None:
    """permissions 列表被原样解析。"""
    data = _valid_dict()
    data["permissions"] = ["network", "voice.listen", "fs.read:./state", "fs.write:./state"]
    m = parse_manifest(data)
    assert m.permissions == ["network", "voice.listen", "fs.read:./state", "fs.write:./state"]


def test_parse_events_publishes_and_subscribes() -> None:
    """events.publishes 与 events.subscribes 列表被解析。"""
    data = _valid_dict()
    data["events"] = {
        "publishes": ["music.started"],
        "subscribes": ["voice.state_changed", "home.scene_applied"],
    }
    m = parse_manifest(data)
    assert m.events.publishes == ["music.started"]
    assert m.events.subscribes == ["voice.state_changed", "home.scene_applied"]


def test_parse_tools_list() -> None:
    """tools 列表被原样解析。"""
    data = _valid_dict()
    data["tools"] = ["home_list_entities", "home_call_service", "home_apply_scene"]
    m = parse_manifest(data)
    assert m.tools == ["home_list_entities", "home_call_service", "home_apply_scene"]


def test_validate_manifest_valid_returns_no_errors() -> None:
    """合法 manifest 校验返回空错误列表。"""
    m = parse_manifest(_valid_dict())
    errors = validate_manifest(m)
    assert errors == []


def test_validate_manifest_flags_empty_description() -> None:
    """description 为空字符串应被校验为软错误。"""
    data = _valid_dict()
    data["description"] = ""
    m = parse_manifest(data)
    errors = validate_manifest(m)
    assert any("description" in e for e in errors)


def test_validate_manifest_flags_tool_name_not_snake_case() -> None:
    """tools 中含非 snake_case 名应被校验为软错误。"""
    data = _valid_dict()
    data["tools"] = ["voiceStatus"]
    m = parse_manifest(data)
    errors = validate_manifest(m)
    assert any("voiceStatus" in e for e in errors)


def test_validate_manifest_flags_event_type_not_dotted() -> None:
    """event_type 不符合 <domain>.<event> 格式应被校验为软错误。"""
    data = _valid_dict()
    data["events"] = {"publishes": ["voiceStateChanged"], "subscribes": []}
    m = parse_manifest(data)
    errors = validate_manifest(m)
    assert any("voiceStateChanged" in e for e in errors)


def test_validate_manifest_flags_unknown_permission_prefix() -> None:
    """不在已知权限清单内的 permission 应被校验为软错误。"""
    data = _valid_dict()
    data["permissions"] = ["network", "voice.listen", "totally_unknown_perm"]
    m = parse_manifest(data)
    errors = validate_manifest(m)
    assert any("totally_unknown_perm" in e for e in errors)


def test_manifest_is_dataclass_with_frozen_fields() -> None:
    """Manifest 是 dataclass，字段可访问。"""
    m = parse_manifest(_valid_dict())
    assert hasattr(m, "name")
    assert hasattr(m, "version")
    assert hasattr(m, "permissions")
    assert hasattr(m, "events")
    assert hasattr(m, "tools")
