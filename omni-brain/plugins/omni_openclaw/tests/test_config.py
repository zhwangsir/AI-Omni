"""omni_openclaw 配置模型测试。"""

from __future__ import annotations

import pytest

from omni_openclaw.config import OpenClawConfig


class TestOpenClawConfig:
    """OpenClawConfig 默认值与校验测试。"""

    def test_default_gateway_is_openclaw01(self) -> None:
        """默认网关应指向 openclaw01 的 LAN IP 与 18789 端口。"""
        cfg = OpenClawConfig()
        assert cfg.gateway == "http://192.168.71.86:18789"

    def test_default_model_endpoints(self) -> None:
        """默认模型端点应符合 openclaw01 规格。"""
        cfg = OpenClawConfig()
        assert cfg.llm_l1_endpoint == "http://192.168.71.127:8000/v1"
        assert cfg.llm_l4_endpoint == "http://192.168.71.82:8000/v1"
        assert cfg.llm_l2_l3_endpoint == "http://192.168.71.109:52415/v1"
        assert cfg.comfyui_endpoint == "http://192.168.71.127:8188"
        assert cfg.tts_endpoint == "http://192.168.71.127:9200"
        assert cfg.embedding_endpoint == "http://192.168.71.127:9302/v1"

    def test_default_models(self) -> None:
        """默认模型 ID 应符合 openclaw01 规格。"""
        cfg = OpenClawConfig()
        assert cfg.llm_l1_model == "Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16"
        assert cfg.llm_l4_model == "euryale-70b"
        assert cfg.embedding_model == "Qwen3-Embedding-4B"

    def test_wechat_defaults(self) -> None:
        """微信默认账号与目标用户应符合规格。"""
        cfg = OpenClawConfig()
        assert cfg.wechat_account == "5c5c75d92a90-im-bot"
        assert cfg.wechat_default_target == "o9cq804L_KWMLwn6nzTphaGmXn1c@im.wechat"

    def test_timeout_positive(self) -> None:
        """timeout 必须为正数。"""
        with pytest.raises(ValueError, match="timeout"):
            OpenClawConfig(timeout_s=0)

    def test_empty_gateway_rejected(self) -> None:
        """网关地址不能为空。"""
        with pytest.raises(ValueError, match="gateway"):
            OpenClawConfig(gateway="  ")

    def test_from_env_overrides(self) -> None:
        """环境变量应能覆盖默认值。"""
        cfg = OpenClawConfig.from_env(
            {
                "OMNI_OPENCLAW_GATEWAY": "http://100.69.0.4:18789",
                "OMNI_OPENCLAW_TIMEOUT_S": "5",
                "OMNI_OPENCLAW_HA_TOKEN": "fake-token",
            }
        )
        assert cfg.gateway == "http://100.69.0.4:18789"
        assert cfg.timeout_s == 5
        assert cfg.ha_token == "fake-token"

    def test_summary_serializable(self) -> None:
        """summary() 返回应可 JSON 序列化。"""
        cfg = OpenClawConfig()
        summary = cfg.summary()
        assert isinstance(summary, dict)
        assert summary["gateway"] == cfg.gateway
        assert "ha_token" not in summary
