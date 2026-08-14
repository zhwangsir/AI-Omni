"""omni_wechat 配置模型。

默认值对齐 ``@tencent-weixin/openclaw-weixin@2.4.6`` 插件协议；
凭据从 ``~/.omni_wechat/accounts/<account>.json`` 读取，环境变量 ``OMNI_WECHAT_*`` 可覆盖。
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from typing import Any


#: 环境变量前缀
ENV_PREFIX = "OMNI_WECHAT_"

#: 默认 iLink 端点（腾讯官方微信 Bot API）
DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"

#: 默认 channel_version（对齐 openclaw-weixin 2.4.6 协议）
DEFAULT_CHANNEL_VERSION = "2.4.6"

#: 默认 iLink App ID
DEFAULT_ILINK_APP_ID = "bot"

#: 默认 bot_agent（UA 风格，用于服务端日志聚合）
DEFAULT_BOT_AGENT = "OpenClaw/omni_wechat"


@dataclass
class WechatConfig:
    """微信通道配置。

    凭据（token）与目标用户（default_target）必须通过状态文件或环境变量注入，
    代码内不硬编码真实凭据。
    """

    # iLink 服务端点
    base_url: str = DEFAULT_BASE_URL
    timeout_s: float = 15.0
    long_poll_timeout_s: float = 35.0

    # 账户与凭据
    account: str = ""           # 例 "5c5c75d92a90-im-bot"
    token: str = ""             # 例 "5c5c75d92a90@im.bot:0600007401..."
    default_target: str = ""    # 例 "o9cq804L_KWMLwn6nzTphaGmXn1c@im.wechat"

    # 协议必需字段（"幽灵字段"，与 openclaw-weixin 对齐）
    channel_version: str = DEFAULT_CHANNEL_VERSION
    ilink_app_id: str = DEFAULT_ILINK_APP_ID
    bot_agent: str = DEFAULT_BOT_AGENT

    # 状态目录（账户凭据/sync_buf 持久化）
    state_dir: str = "~/.omni_wechat"

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """校验配置字段，非法值抛 ``ValueError``。"""
        if self.timeout_s <= 0:
            raise ValueError("timeout_s 必须 > 0")
        if self.long_poll_timeout_s <= 0:
            raise ValueError("long_poll_timeout_s 必须 > 0")
        if not str(self.base_url).strip():
            raise ValueError("base_url 不能为空")
        if not str(self.channel_version).strip():
            raise ValueError("channel_version 不能为空")
        if not str(self.ilink_app_id).strip():
            raise ValueError("ilink_app_id 不能为空")

    @property
    def client_version_int(self) -> int:
        """iLink-App-ClientVersion：uint32 编码为 0x00MMNNPP。

        例如 "2.4.6" → (2<<16)|(4<<8)|6 = 0x00020406 = 132102。
        """
        parts = self.channel_version.split(".")
        major = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
        minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        patch = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        return ((major & 0xFF) << 16) | ((minor & 0xFF) << 8) | (patch & 0xFF)

    def summary(self) -> dict[str, Any]:
        """返回可 JSON 序列化的配置摘要（不含 token）。"""
        return {
            "base_url": self.base_url,
            "timeout_s": self.timeout_s,
            "long_poll_timeout_s": self.long_poll_timeout_s,
            "account": self.account,
            "default_target": self.default_target,
            "channel_version": self.channel_version,
            "ilink_app_id": self.ilink_app_id,
            "bot_agent": self.bot_agent,
            "state_dir": self.state_dir,
            "client_version_int": self.client_version_int,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "WechatConfig":
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
        base: "WechatConfig | None" = None,
    ) -> "WechatConfig":
        """以 ``OMNI_WECHAT_`` 前缀环境变量覆盖 base 构建配置。"""
        env = os.environ if environ is None else environ
        base_cfg = base or cls()
        merged = base_cfg.summary()
        # token 不在 summary() 中，单独补充
        merged["token"] = base_cfg.token
        # client_version_int 是派生属性，from_dict 时不接受
        merged.pop("client_version_int", None)
        for field in dataclasses.fields(cls):
            key = ENV_PREFIX + field.name.upper()
            if key in env:
                merged[field.name] = env[key]
        return cls.from_dict(merged)
