"""Open-Meteo 天气 API 客户端。

文档：``https://api.open-meteo.com/v1/forecast``

获取当前天气 + 24h 预报，标准化字段：
- ``current``：temperature / humidity / wind_speed / weather_code / apparent_temperature
- ``hourly``：24 条小时预报（time / temperature / weather_code / precipitation_probability）

httpx 惰性导入（函数内 import），``ImportError`` 时返回 ``E_BACKEND_UNAVAILABLE``；
HTTP 错误映射为 ``E_HTTP_FAILED``，JSON 解析失败映射为 ``E_PARSE_FAILED``。
"""

from __future__ import annotations

from typing import Any

__all__ = ["OpenMeteoBackend"]


_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


class OpenMeteoBackend:
    """Open-Meteo 天气客户端。

    所有方法返回 dict：成功 ``{"ok": True, ...}``；
    失败 ``{"ok": False, "error": {"code": "E_XXX", "message": "..."}}``。
    """

    def get_weather(
        self,
        lat: float,
        lon: float,
        city: str | None = None,
    ) -> dict[str, Any]:
        """获取当前天气 + 24h 预报。

        :param lat: 纬度 [-90, 90]
        :param lon: 经度 [-180, 180]
        :param city: 可选城市名（写入返回结果，便于日志/UI 展示）
        :return: 标准化天气 dict
        """
        # 参数校验（与 urllib 不同，httpx 不做范围检查）
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "error": {"code": "E_INVALID_ARG", "message": f"lat/lon 必须为数字: lat={lat!r}, lon={lon!r}"},
            }
        if not -90 <= lat_f <= 90:
            return {
                "ok": False,
                "error": {"code": "E_INVALID_ARG", "message": f"lat 超出 [-90, 90]: {lat_f}"},
            }
        if not -180 <= lon_f <= 180:
            return {
                "ok": False,
                "error": {"code": "E_INVALID_ARG", "message": f"lon 超出 [-180, 180]: {lon_f}"},
            }

        params = {
            "latitude": lat_f,
            "longitude": lon_f,
            "current": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "apparent_temperature",
                    "wind_speed_10m",
                    "weather_code",
                ]
            ),
            "hourly": ",".join(
                [
                    "temperature_2m",
                    "weather_code",
                    "precipitation_probability",
                ]
            ),
            "forecast_days": 1,
            "timezone": "auto",
        }
        data = self._http_get(_OPEN_METEO_URL, params)
        if not data.get("ok"):
            return data
        raw = data["data"]
        return self._normalize(raw, city=city)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _http_get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """惰性 import httpx，发起 GET 请求；返回标准化结果。"""
        try:
            import httpx  # 惰性导入（CLAUDE.md §三）
        except ImportError as exc:
            return {
                "ok": False,
                "error": {"code": "E_BACKEND_UNAVAILABLE", "message": f"httpx 不可用: {exc}"},
            }
        try:
            resp = httpx.get(url, params=params, timeout=10)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - 网络异常统一映射
            return {
                "ok": False,
                "error": {"code": "E_HTTP_FAILED", "message": str(exc)},
            }
        try:
            return {"ok": True, "data": resp.json()}
        except Exception as exc:  # noqa: BLE001 - ValueError 等
            return {
                "ok": False,
                "error": {"code": "E_PARSE_FAILED", "message": str(exc)},
            }

    @staticmethod
    def _normalize(raw: dict[str, Any], city: str | None = None) -> dict[str, Any]:
        """把 Open-Meteo 原始响应标准化为内部结构。"""
        current_raw = raw.get("current", {}) or {}
        hourly_raw = raw.get("hourly", {}) or {}

        current = {
            "temperature": current_raw.get("temperature_2m"),
            "humidity": current_raw.get("relative_humidity_2m"),
            "wind_speed": current_raw.get("wind_speed_10m"),
            "weather_code": current_raw.get("weather_code"),
            "apparent_temperature": current_raw.get("apparent_temperature"),
        }

        times = hourly_raw.get("time", []) or []
        temps = hourly_raw.get("temperature_2m", []) or []
        codes = hourly_raw.get("weather_code", []) or []
        precips = hourly_raw.get("precipitation_probability", []) or []
        hourly: list[dict[str, Any]] = []
        for i, t in enumerate(times):
            hourly.append(
                {
                    "time": t,
                    "temperature": temps[i] if i < len(temps) else None,
                    "weather_code": codes[i] if i < len(codes) else None,
                    "precipitation_probability": precips[i] if i < len(precips) else None,
                }
            )

        result: dict[str, Any] = {
            "ok": True,
            "current": current,
            "hourly": hourly,
            "raw": raw,
        }
        if city is not None:
            result["city"] = city
        return result
