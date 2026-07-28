"""omni_home 配置模型。

提供 :class:`HomeConfig` 数据类及两种加载方式：

- ``from_dict`` ：字典加载（未知键 / 非法值抛 ``ValueError``）
- ``from_env``  ：``OMNI_HOME_`` 前缀环境变量覆盖

``ws_url`` / ``api_url`` 由 ``ha_url`` 自动推导；
``summary()`` 默认对 token 脱敏，避免日志/事件泄露凭据。
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from typing import Any

#: 环境变量前缀
ENV_PREFIX = "OMNI_HOME_"


def _coerce(target: type, value: Any) -> Any:
    """把外部输入（常为字符串）强转为目标类型，失败抛 ValueError。"""
    if target is int:
        return int(float(value))  # 容忍 "10.0" 这类输入
    if target is float:
        return float(value)
    return str(value)


def _mask_token(token: str) -> str:
    """token 脱敏：长度 > 8 保留首尾各 4 位，短 token 全掩码。"""
    if not token:
        return ""
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}…{token[-4:]}"


@dataclass
class HomeConfig:
    """Home Assistant 接入配置。

    ``ha_token`` 允许为空（如仅演示 fake 模式），
    由 tools 层在发起真实请求前检查并给出友好错误。
    """

    ha_url: str = "http://homeassistant.local:8123"
    ha_token: str = ""
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    default_room: str = ""

    def __post_init__(self) -> None:
        self.validate()

    @property
    def api_url(self) -> str:
        """REST API 根地址（``<ha_url>/api``）。"""
        return self.ha_url.rstrip("/") + "/api"

    @property
    def ws_url(self) -> str:
        """WebSocket 地址：http→ws、https→wss，路径 ``/api/websocket``。"""
        base = self.ha_url.rstrip("/")
        if base.startswith("https://"):
            base = "wss://" + base[len("https://"):]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://"):]
        return base + "/api/websocket"

    def validate(self) -> None:
        """校验所有字段，非法值抛 ``ValueError``。"""
        url = str(self.ha_url).strip()
        if not url:
            raise ValueError("ha_url 不能为空")
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("ha_url 必须以 http:// 或 https:// 开头")
        if self.connect_timeout <= 0:
            raise ValueError("connect_timeout 必须 > 0")
        if self.read_timeout <= 0:
            raise ValueError("read_timeout 必须 > 0")
        if not isinstance(self.ha_token, str):
            raise ValueError("ha_token 必须是字符串")

    def summary(self, mask_token: bool = True) -> dict[str, Any]:
        """返回可 JSON 序列化的配置摘要；默认对 token 脱敏。"""
        data = dataclasses.asdict(self)
        if mask_token:
            data["ha_token"] = _mask_token(self.ha_token)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "HomeConfig":
        """从字典构建；未知键或非法值抛 ``ValueError``。"""
        fields = {f.name: f for f in dataclasses.fields(cls)}
        kwargs: dict[str, Any] = {}
        for key, value in (data or {}).items():
            field = fields.get(key)
            if field is None:
                raise ValueError(f"未知配置项: {key}")
            target = type(field.default)
            try:
                kwargs[key] = _coerce(target, value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"配置项 {key} 的值非法: {value!r}") from exc
        return cls(**kwargs)

    @classmethod
    def from_env(
        cls,
        environ: dict[str, str] | None = None,
        base: "HomeConfig | None" = None,
    ) -> "HomeConfig":
        """以 ``OMNI_HOME_`` 前缀环境变量覆盖 base（默认默认值）构建配置。"""
        env = os.environ if environ is None else environ
        merged = (base or cls()).summary(mask_token=False)
        for field in dataclasses.fields(cls):
            key = ENV_PREFIX + field.name.upper()
            if key in env:
                merged[field.name] = env[key]
        return cls.from_dict(merged)
