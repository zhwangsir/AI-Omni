"""omni_wechat 配置模型测试。

验证 WechatConfig 的字段校验、client_version_int 编码、
from_dict / from_env 构建路径。
"""

from __future__ import annotations

import os

import pytest

from omni_wechat.config import (
    DEFAULT_BASE_URL,
    DEFAULT_BOT_AGENT,
    DEFAULT_CHANNEL_VERSION,
    DEFAULT_ILINK_APP_ID,
    ENV_PREFIX,
    WechatConfig,
)


class TestDefaults:
    """默认值测试。"""

    def test_default_base_url(self) -> None:
        cfg = WechatConfig()
        assert cfg.base_url == DEFAULT_BASE_URL
        assert cfg.base_url == "https://ilinkai.weixin.qq.com"

    def test_default_channel_version(self) -> None:
        cfg = WechatConfig()
        assert cfg.channel_version == DEFAULT_CHANNEL_VERSION
        assert cfg.channel_version == "2.4.6"

    def test_default_ilink_app_id(self) -> None:
        cfg = WechatConfig()
        assert cfg.ilink_app_id == DEFAULT_ILINK_APP_ID

    def test_default_bot_agent(self) -> None:
        cfg = WechatConfig()
        assert cfg.bot_agent == DEFAULT_BOT_AGENT

    def test_default_timeouts(self) -> None:
        cfg = WechatConfig()
        assert cfg.timeout_s == 15.0
        assert cfg.long_poll_timeout_s == 35.0

    def test_default_empty_credentials(self) -> None:
        cfg = WechatConfig()
        assert cfg.account == ""
        assert cfg.token == ""
        assert cfg.default_target == ""

    def test_default_state_dir(self) -> None:
        cfg = WechatConfig()
        assert cfg.state_dir == "~/.omni_wechat"


class TestValidation:
    """字段校验测试。"""

    def test_timeout_s_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="timeout_s"):
            WechatConfig(timeout_s=0)

    def test_timeout_s_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="timeout_s"):
            WechatConfig(timeout_s=-1)

    def test_long_poll_timeout_s_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="long_poll_timeout_s"):
            WechatConfig(long_poll_timeout_s=0)

    def test_base_url_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="base_url"):
            WechatConfig(base_url="")

    def test_base_url_whitespace_raises(self) -> None:
        with pytest.raises(ValueError, match="base_url"):
            WechatConfig(base_url="   ")

    def test_channel_version_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="channel_version"):
            WechatConfig(channel_version="")

    def test_ilink_app_id_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="ilink_app_id"):
            WechatConfig(ilink_app_id="")


class TestClientVersionInt:
    """client_version_int uint32 编码测试。"""

    def test_version_2_4_6(self) -> None:
        cfg = WechatConfig(channel_version="2.4.6")
        # (2<<16)|(4<<8)|6 = 131072 + 1024 + 6 = 132102
        assert cfg.client_version_int == 132102
        assert cfg.client_version_int == 0x00020406

    def test_version_1_0_0(self) -> None:
        cfg = WechatConfig(channel_version="1.0.0")
        assert cfg.client_version_int == (1 << 16)

    def test_version_0_0_1(self) -> None:
        cfg = WechatConfig(channel_version="0.0.1")
        assert cfg.client_version_int == 1

    def test_version_255_255_255(self) -> None:
        cfg = WechatConfig(channel_version="255.255.255")
        assert cfg.client_version_int == 0x00FFFFFF

    def test_version_overflow_clamped(self) -> None:
        cfg = WechatConfig(channel_version="256.0.0")
        # 256 & 0xFF = 0
        assert cfg.client_version_int == 0

    def test_version_non_digit_parts(self) -> None:
        cfg = WechatConfig(channel_version="abc.def.ghi")
        assert cfg.client_version_int == 0

    def test_version_partial(self) -> None:
        cfg = WechatConfig(channel_version="3")
        assert cfg.client_version_int == (3 << 16)

    def test_version_two_parts(self) -> None:
        cfg = WechatConfig(channel_version="2.4")
        assert cfg.client_version_int == (2 << 16) | (4 << 8)


class TestSummary:
    """summary() 输出测试。"""

    def test_summary_excludes_token(self) -> None:
        cfg = WechatConfig(token="secret-token-123")
        s = cfg.summary()
        assert "token" not in s
        assert "secret" not in str(s)

    def test_summary_contains_all_fields(self) -> None:
        cfg = WechatConfig(account="test-acc", default_target="user@im.wechat")
        s = cfg.summary()
        assert s["account"] == "test-acc"
        assert s["default_target"] == "user@im.wechat"
        assert s["base_url"] == DEFAULT_BASE_URL
        assert s["channel_version"] == "2.4.6"
        assert "client_version_int" in s
        assert isinstance(s["client_version_int"], int)


class TestFromDict:
    """from_dict 构建测试。"""

    def test_from_empty_dict(self) -> None:
        cfg = WechatConfig.from_dict({})
        assert cfg.base_url == DEFAULT_BASE_URL

    def test_from_none(self) -> None:
        cfg = WechatConfig.from_dict(None)
        assert cfg.base_url == DEFAULT_BASE_URL

    def test_from_dict_override(self) -> None:
        cfg = WechatConfig.from_dict({"account": "my-account", "timeout_s": 30.0})
        assert cfg.account == "my-account"
        assert cfg.timeout_s == 30.0

    def test_from_dict_unknown_key_raises(self) -> None:
        with pytest.raises(ValueError, match="未知配置项"):
            WechatConfig.from_dict({"nonexistent_field": "value"})

    def test_from_dict_int_coercion(self) -> None:
        cfg = WechatConfig.from_dict({"timeout_s": "20.5"})
        assert cfg.timeout_s == 20.5

    def test_from_dict_str_coercion(self) -> None:
        cfg = WechatConfig.from_dict({"account": 12345})
        assert cfg.account == "12345"


class TestFromEnv:
    """from_env 环境变量覆盖测试。"""

    def test_from_env_empty(self) -> None:
        cfg = WechatConfig.from_env(environ={})
        assert cfg.base_url == DEFAULT_BASE_URL

    def test_from_env_override(self) -> None:
        env = {
            f"{ENV_PREFIX}ACCOUNT": "env-account",
            f"{ENV_PREFIX}TOKEN": "env-token",
            f"{ENV_PREFIX}BASE_URL": "https://custom.example.com",
            f"{ENV_PREFIX}TIMEOUT_S": "20",
        }
        cfg = WechatConfig.from_env(environ=env)
        assert cfg.account == "env-account"
        assert cfg.token == "env-token"
        assert cfg.base_url == "https://custom.example.com"
        assert cfg.timeout_s == 20.0

    def test_from_env_preserves_base(self) -> None:
        base = WechatConfig(account="base-acc", token="base-token")
        cfg = WechatConfig.from_env(environ={}, base=base)
        assert cfg.account == "base-acc"
        assert cfg.token == "base-token"

    def test_from_env_overrides_base(self) -> None:
        base = WechatConfig(account="base-acc")
        env = {f"{ENV_PREFIX}ACCOUNT": "env-acc"}
        cfg = WechatConfig.from_env(environ=env, base=base)
        assert cfg.account == "env-acc"

    def test_from_env_does_not_leak_token_into_summary(self) -> None:
        env = {f"{ENV_PREFIX}TOKEN": "secret"}
        cfg = WechatConfig.from_env(environ=env)
        assert "token" not in cfg.summary()
        assert cfg.token == "secret"
