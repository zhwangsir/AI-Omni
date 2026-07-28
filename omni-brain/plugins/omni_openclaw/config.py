"""omni_openclaw 配置模型。

所有端点、凭据、默认值集中管理；凭据通过环境变量或配置文件传入，代码内不硬编码。
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


#: 环境变量前缀
ENV_PREFIX = "OMNI_OPENCLAW_"


@dataclass
class OpenClawConfig:
    """OpenClaw 网关配置。

    默认值对应 openclaw01（192.168.71.86）的当前部署规格。
    """

    # OpenClaw 网关
    gateway: str = "http://192.168.71.86:18789"
    timeout_s: float = 15.0

    # LLM 端点（四层 AICG）
    llm_l1_endpoint: str = "http://192.168.71.127:8000/v1"
    llm_l1_model: str = "qwen3.6-uncensored"

    llm_l2_l3_endpoint: str = "http://192.168.71.109:52415/v1"

    llm_l4_endpoint: str = "http://192.168.71.82:8000/v1"
    llm_l4_model: str = "euryale-70b"

    # 多模态/图像/TTS/Embedding
    comfyui_endpoint: str = "http://192.168.71.127:8188"
    tts_endpoint: str = "http://192.168.71.127:9200"
    # 2026-07-28 设备文档: Infinity Embedding :9301 已停，替换为真机 Qwen3-Embedding-4B :9302
    embedding_endpoint: str = "http://192.168.71.127:9302/v1"
    embedding_model: str = "Qwen3-Embedding-4B"

    # 微信通道
    wechat_bridge_endpoint: str = "http://192.168.71.86:9095"
    wechat_account: str = "5c5c75d92a90-im-bot"
    wechat_default_target: str = "o9cq804L_KWMLwn6nzTphaGmXn1c@im.wechat"

    # Home Assistant
    ha_endpoint: str = "http://192.168.71.127:8211"
    ha_token: str = ""

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """校验配置字段，非法值抛 ``ValueError``。"""
        if self.timeout_s <= 0:
            raise ValueError("timeout_s 必须 > 0")
        if not str(self.gateway).strip():
            raise ValueError("gateway 不能为空")
        if not str(self.llm_l1_endpoint).strip():
            raise ValueError("llm_l1_endpoint 不能为空")
        if not str(self.llm_l4_endpoint).strip():
            raise ValueError("llm_l4_endpoint 不能为空")

    def summary(self) -> dict[str, Any]:
        """返回可 JSON 序列化的配置摘要（不含凭据）。"""
        return {
            "gateway": self.gateway,
            "timeout_s": self.timeout_s,
            "llm_l1_endpoint": self.llm_l1_endpoint,
            "llm_l1_model": self.llm_l1_model,
            "llm_l2_l3_endpoint": self.llm_l2_l3_endpoint,
            "llm_l4_endpoint": self.llm_l4_endpoint,
            "llm_l4_model": self.llm_l4_model,
            "comfyui_endpoint": self.comfyui_endpoint,
            "tts_endpoint": self.tts_endpoint,
            "embedding_endpoint": self.embedding_endpoint,
            "embedding_model": self.embedding_model,
            "wechat_bridge_endpoint": self.wechat_bridge_endpoint,
            "wechat_account": self.wechat_account,
            "wechat_default_target": self.wechat_default_target,
            "ha_endpoint": self.ha_endpoint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "OpenClawConfig":
        """从字典构建；未知键抛 ``ValueError``。"""
        fields = {f.name: f for f in dataclasses.fields(cls)}
        kwargs: dict[str, Any] = {}
        for key, value in (data or {}).items():
            field = fields.get(key)
            if field is None:
                raise ValueError(f"未知配置项: {key}")
            target = type(field.default)
            if target is bool:
                lowered = str(value).strip().lower()
                kwargs[key] = lowered in ("true", "1", "yes", "on")
            elif target is int:
                kwargs[key] = int(float(value))
            elif target is float:
                kwargs[key] = float(value)
            else:
                kwargs[key] = str(value)
        return cls(**kwargs)

    @classmethod
    def from_env(
        cls,
        environ: dict[str, str] | None = None,
        base: "OpenClawConfig | None" = None,
    ) -> "OpenClawConfig":
        """以 ``OMNI_OPENCLAW_`` 前缀环境变量覆盖 base 构建配置。"""
        env = os.environ if environ is None else environ
        merged = (base or cls()).summary()
        # 凭据字段不在 summary() 中，需要单独补充
        merged["ha_token"] = (base or cls()).ha_token
        for field in dataclasses.fields(cls):
            key = ENV_PREFIX + field.name.upper()
            if key in env:
                merged[field.name] = env[key]
        return cls.from_dict(merged)
