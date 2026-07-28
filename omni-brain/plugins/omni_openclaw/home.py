"""omni_openclaw 智能家居/Home Assistant 桥接。

封装 HA REST API 的常用服务调用，支持注入 fake backend 用于测试。
所有请求携带 ``Authorization: Bearer <ha_token>`` 头，返回统一 ``{ok: ...}`` 结构。
"""

from __future__ import annotations

from typing import Any

from omni_openclaw.client import HttpxBackend, HttpBackend
from omni_openclaw.config import OpenClawConfig
from omni_openclaw.errors import error_response, success_response


#: 语音模式开关实体 ID
VOICE_MODE_ENTITY = "input_boolean.drita_voice_mode"
#: 扬声器播报脚本实体 ID
SPEAKER_SAY_SCRIPT = "script.speaker_say"


class HomeAssistantClient:
    """Home Assistant REST API 桥接客户端。"""

    def __init__(
        self,
        config: OpenClawConfig | None = None,
        backend: HttpBackend | None = None,
    ) -> None:
        self.config = config or OpenClawConfig()
        if backend is None:
            # 复用 HttpxBackend，将 HA endpoint 作为 gateway base_url 传入
            ha_config = OpenClawConfig(
                gateway=self.config.ha_endpoint,
                timeout_s=self.config.timeout_s,
            )
            self._backend: HttpBackend = HttpxBackend(ha_config)
            self._owns_backend = True
        else:
            self._backend = backend
            self._owns_backend = False

    def _headers(self) -> dict[str, str]:
        """构造 HA 认证请求头。"""
        return {
            "Authorization": f"Bearer {self.config.ha_token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> tuple[int, Any]:
        """透传到 backend。"""
        return await self._backend.request(method, path, **kwargs)

    async def _call_service(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any],
    ) -> dict[str, Any]:
        """调用 HA 服务并统一包装响应。"""
        try:
            status, body = await self._request(
                "POST",
                f"/api/services/{domain}/{service}",
                headers=self._headers(),
                json=service_data,
            )
        except (TimeoutError, OSError):
            return error_response(
                "E_HA_UNAVAILABLE",
                f"无法连接到 Home Assistant {self.config.ha_endpoint}",
            )
        except Exception as exc:
            return error_response(
                "E_HA_ERROR",
                f"请求 Home Assistant 时出错: {exc}",
            )

        if status == 200:
            return success_response(
                domain=domain,
                service=service,
                service_data=service_data,
            )
        return error_response(
            "E_HA_SERVICE_ERROR",
            f"Home Assistant 服务调用失败 (HTTP {status})",
            status_code=status,
            body=body,
        )

    async def control_light(
        self,
        entity_id: str,
        on: bool,
        brightness: int | None = None,
        color_temp: int | None = None,
    ) -> dict[str, Any]:
        """控制灯光开关、亮度与色温。"""
        if not entity_id or not str(entity_id).strip():
            return error_response("E_INVALID_PARAMS", "entity_id 不能为空")

        service_data: dict[str, Any] = {"entity_id": entity_id}
        if not on:
            return await self._call_service("light", "turn_off", service_data)

        if brightness is not None:
            service_data["brightness"] = brightness
        if color_temp is not None:
            service_data["color_temp"] = color_temp
        return await self._call_service("light", "turn_on", service_data)

    async def control_fan(
        self,
        entity_id: str,
        on: bool,
        speed: str | None = None,
    ) -> dict[str, Any]:
        """控制风扇开关与风速。"""
        if not entity_id or not str(entity_id).strip():
            return error_response("E_INVALID_PARAMS", "entity_id 不能为空")

        service_data: dict[str, Any] = {"entity_id": entity_id}
        if not on:
            return await self._call_service("fan", "turn_off", service_data)

        if speed is not None:
            service_data["speed"] = speed
        return await self._call_service("fan", "turn_on", service_data)

    async def control_air_purifier(
        self,
        entity_id: str,
        on: bool,
        mode: str | None = None,
    ) -> dict[str, Any]:
        """控制空气净化器开关与模式（HA 中通常为 fan 实体）。"""
        if not entity_id or not str(entity_id).strip():
            return error_response("E_INVALID_PARAMS", "entity_id 不能为空")

        service_data: dict[str, Any] = {"entity_id": entity_id}
        if not on:
            return await self._call_service("fan", "turn_off", service_data)

        if mode is not None:
            service_data["mode"] = mode
        return await self._call_service("fan", "turn_on", service_data)

    async def _set_input_boolean(self, entity_id: str, on: bool) -> dict[str, Any]:
        """切换 input_boolean 实体状态。"""
        return await self._call_service(
            "input_boolean",
            "turn_on" if on else "turn_off",
            {"entity_id": entity_id},
        )

    async def speaker_voice_on(self) -> dict[str, Any]:
        """开启扬声器语音模式。"""
        return await self._set_input_boolean(VOICE_MODE_ENTITY, True)

    async def speaker_voice_off(self) -> dict[str, Any]:
        """关闭扬声器语音模式。"""
        return await self._set_input_boolean(VOICE_MODE_ENTITY, False)

    async def speaker_say(self, text: str) -> dict[str, Any]:
        """通过 TTS 或脚本播报文本。"""
        if not text or not str(text).strip():
            return error_response("E_INVALID_PARAMS", "text 不能为空")

        try:
            status, body = await self._request(
                "POST",
                "/api/services/tts/speak",
                headers=self._headers(),
                json={"message": text},
            )
        except (TimeoutError, OSError):
            return error_response(
                "E_HA_UNAVAILABLE",
                f"无法连接到 Home Assistant {self.config.ha_endpoint}",
            )
        except Exception as exc:
            return error_response(
                "E_HA_ERROR",
                f"请求 Home Assistant 时出错: {exc}",
            )

        if status == 200:
            return success_response(text=text, service="tts/speak")

        # tts/speak 不可用时回退到脚本播报
        if status in (400, 404, 501):
            return await self._call_service(
                "script",
                "turn_on",
                {
                    "entity_id": SPEAKER_SAY_SCRIPT,
                    "variables": {"message": text},
                },
            )

        return error_response(
            "E_HA_TTS_ERROR",
            f"TTS 服务调用失败 (HTTP {status})",
            status_code=status,
            body=body,
        )

    async def close(self) -> None:
        """释放 backend 资源。"""
        if self._owns_backend and hasattr(self._backend, "close"):
            await self._backend.close()
