"""omni_sdk.identity 单元测试。"""
from __future__ import annotations

from omni_sdk.identity import AssistantIdentity, DEFAULT_IDENTITY, get_identity


def test_default_identity_fields():
    """测试 DEFAULT_IDENTITY 字段正确。"""
    identity = DEFAULT_IDENTITY
    assert identity.display_name == "雪莉"
    assert identity.english_name == "Sherry"
    assert identity.wake_aliases == (
        "雪莉",
        "sherry",
        "雪梨",
        "雪利",
        "雪丽",
        "shelly",
    )
    assert identity.wake_response == "我在"
    assert "雪莉" in identity.system_prompt
    assert "Sherry" in identity.system_prompt
    assert identity.idle_label == "雪莉 · 待命"


def test_wake_aliases_cover_common_asr_misrecognitions():
    """M32.29：别名覆盖 ASR 常见同音误识别，保证喊「雪莉」能通过热词校验。

    覆盖同音字：雪梨（水果名同音）/ 雪利（酒名同音）/ 雪丽（人名用字）/ shelly（近音英文名）。
    注意「siri」不加入别名——发音差别明显且会与 macOS Siri 冲突（见 test_siri_not_in_aliases）。
    """
    aliases = DEFAULT_IDENTITY.wake_aliases
    for expected in ("雪梨", "雪利", "雪丽", "shelly"):
        assert expected in aliases, f"缺少同音误识别别名: {expected}"


def test_siri_not_in_aliases():
    """M32.30a 回归：「siri」不得作为别名——会与 macOS 系统 Siri 冲突。

    用户反馈：喊「雪莉」会意外唤起本机 Siri。/ˈsɪri/ 与 ɕɥɛli 发音差别明显，
    faster-whisper 若转写为 siri 属于严重误识别，ASR prompt 偏置足以纠正，
    不应通过别名放宽来妥协（否则用户喊 Siri 时会误唤醒雪莉）。
    """
    assert "siri" not in DEFAULT_IDENTITY.wake_aliases
    assert "Siri" not in DEFAULT_IDENTITY.wake_aliases
    assert "SIRI" not in DEFAULT_IDENTITY.wake_aliases


def test_get_identity_returns_default():
    """测试 get_identity() 返回默认值。"""
    identity = get_identity()
    assert identity is DEFAULT_IDENTITY
    assert identity.display_name == "雪莉"


def test_to_dict_serialization():
    """测试 to_dict() 序列化正确。"""
    identity = AssistantIdentity()
    d = identity.to_dict()
    assert d["display_name"] == "雪莉"
    assert d["english_name"] == "Sherry"
    assert d["wake_aliases"] == ["雪莉", "sherry", "雪梨", "雪利", "雪丽", "shelly"]
    assert d["wake_response"] == "我在"
    assert "雪莉" in d["system_prompt"]
    assert d["idle_label"] == "雪莉 · 待命"


def test_identity_is_immutable():
    """测试 AssistantIdentity 是不可变的（frozen=True）。"""
    identity = DEFAULT_IDENTITY
    try:
        identity.display_name = "测试"
        assert False, "应该抛出 FrozenInstanceError"
    except Exception:
        pass


def test_custom_identity():
    """测试自定义身份。"""
    custom = AssistantIdentity(
        display_name="测试助手",
        english_name="Test",
        wake_aliases=("测试", "test"),
        wake_response="在呢",
        system_prompt="你是测试助手",
        idle_label="测试 · 待命",
    )
    assert custom.display_name == "测试助手"
    assert custom.wake_aliases == ("测试", "test")
    d = custom.to_dict()
    assert d["display_name"] == "测试助手"
    assert d["wake_aliases"] == ["测试", "test"]
