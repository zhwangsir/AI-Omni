"""omni_home 配置模型测试：默认值、env 覆盖、非法值、ws_url 推导、token 脱敏。"""

from __future__ import annotations

import pytest

from omni_home.config import ENV_PREFIX, HomeConfig


class TestDefaults:
    def test_default_values(self):
        cfg = HomeConfig()
        assert cfg.ha_url == "http://homeassistant.local:8123"
        assert cfg.ha_token == ""
        assert cfg.connect_timeout == 10.0
        assert cfg.read_timeout == 30.0
        assert cfg.default_room == ""

    def test_ws_url_derived_from_http(self):
        cfg = HomeConfig(ha_url="http://homeassistant.local:8123")
        assert cfg.ws_url == "ws://homeassistant.local:8123/api/websocket"

    def test_ws_url_derived_from_https(self):
        cfg = HomeConfig(ha_url="https://ha.example.com:8123/")
        assert cfg.ws_url == "wss://ha.example.com:8123/api/websocket"

    def test_api_url_strips_trailing_slash(self):
        cfg = HomeConfig(ha_url="http://ha.local:8123/")
        assert cfg.api_url == "http://ha.local:8123/api"


class TestValidation:
    def test_empty_url_rejected(self):
        with pytest.raises(ValueError, match="ha_url"):
            HomeConfig(ha_url="")

    def test_bad_scheme_rejected(self):
        with pytest.raises(ValueError, match="http"):
            HomeConfig(ha_url="ftp://ha.local")

    def test_connect_timeout_must_be_positive(self):
        with pytest.raises(ValueError, match="connect_timeout"):
            HomeConfig(connect_timeout=0)

    def test_read_timeout_must_be_positive(self):
        with pytest.raises(ValueError, match="read_timeout"):
            HomeConfig(read_timeout=-1)

    def test_token_may_be_empty(self):
        # 空 token 合法（由 tools 层在使用前提示），但必须是字符串
        cfg = HomeConfig(ha_token="")
        assert cfg.ha_token == ""


class TestFromDict:
    def test_from_dict_full(self):
        cfg = HomeConfig.from_dict(
            {
                "ha_url": "http://192.168.1.10:8123",
                "ha_token": "secret-token",
                "connect_timeout": "5",
                "read_timeout": 15,
                "default_room": "客厅",
            }
        )
        assert cfg.ha_url == "http://192.168.1.10:8123"
        assert cfg.ha_token == "secret-token"
        assert cfg.connect_timeout == 5.0
        assert cfg.read_timeout == 15.0
        assert cfg.default_room == "客厅"

    def test_from_dict_unknown_key(self):
        with pytest.raises(ValueError, match="未知配置项"):
            HomeConfig.from_dict({"no_such_key": 1})

    def test_from_dict_bad_value(self):
        with pytest.raises(ValueError, match="非法"):
            HomeConfig.from_dict({"connect_timeout": "not-a-number"})

    def test_from_dict_none_gives_defaults(self):
        cfg = HomeConfig.from_dict(None)
        assert cfg.ha_url == "http://homeassistant.local:8123"


class TestFromEnv:
    def test_env_prefix(self):
        assert ENV_PREFIX == "OMNI_HOME_"

    def test_from_env_overrides(self):
        env = {
            "OMNI_HOME_HA_URL": "http://ha.internal:8123",
            "OMNI_HOME_HA_TOKEN": "env-token",
            "OMNI_HOME_READ_TIMEOUT": "60",
            "OMNI_HOME_DEFAULT_ROOM": "卧室",
        }
        cfg = HomeConfig.from_env(env)
        assert cfg.ha_url == "http://ha.internal:8123"
        assert cfg.ha_token == "env-token"
        assert cfg.read_timeout == 60.0
        assert cfg.default_room == "卧室"

    def test_from_env_ignores_unrelated(self):
        cfg = HomeConfig.from_env({"OTHER_VAR": "x", "OMNI_HOME_HA_URL": "http://a:8123"})
        assert cfg.ha_url == "http://a:8123"
        assert cfg.ha_token == ""

    def test_from_env_bad_value_raises(self):
        with pytest.raises(ValueError):
            HomeConfig.from_env({"OMNI_HOME_CONNECT_TIMEOUT": "-5"})

    def test_from_env_on_top_of_base(self):
        base = HomeConfig(ha_token="base-token", read_timeout=45.0)
        cfg = HomeConfig.from_env({"OMNI_HOME_HA_URL": "http://b:8123"}, base=base)
        assert cfg.ha_url == "http://b:8123"
        assert cfg.ha_token == "base-token"
        assert cfg.read_timeout == 45.0


class TestSummary:
    def test_summary_masks_token(self):
        cfg = HomeConfig(ha_token="abcdefgh12345678")
        summary = cfg.summary()
        assert summary["ha_token"] != "abcdefgh12345678"
        assert "abcd" in summary["ha_token"]
        assert "5678" in summary["ha_token"]

    def test_summary_short_token_fully_masked(self):
        cfg = HomeConfig(ha_token="short")
        assert cfg.summary()["ha_token"] == "***"

    def test_summary_empty_token_stays_empty(self):
        assert HomeConfig().summary()["ha_token"] == ""

    def test_summary_unmasked_roundtrip(self):
        cfg = HomeConfig(ha_token="tok")
        assert cfg.summary(mask_token=False)["ha_token"] == "tok"
