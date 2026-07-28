"""Fake Open-Meteo 后端（演示/测试用）。

返回预设的晴朗天气数据，不访问真实网络，用于：
- CLI --fake 演示
- 单元测试
- 无网络环境
"""

from __future__ import annotations

import time
from typing import Any

__all__ = ["FakeOpenMeteoBackend", "FakeGeocodingBackend", "FakeIpLocationBackend"]


def _generate_hourly() -> list[dict[str, Any]]:
    """生成24小时预报的假数据。"""
    hourly: list[dict[str, Any]] = []
    now = time.time()
    for i in range(24):
        t = time.localtime(now + i * 3600)
        hourly.append(
            {
                "time": time.strftime("%Y-%m-%dT%H:00", t),
                "temperature": 22 + (i % 6 - 3) * 2,
                "weather_code": 0 if i % 4 != 3 else 3,
                "precipitation_probability": 10 if i % 4 != 3 else 60,
            }
        )
    return hourly


class FakeOpenMeteoBackend:
    """Fake 天气后端：返回预设晴朗天气数据。"""

    def get_weather(
        self,
        lat: float,
        lon: float,
        city: str | None = None,
    ) -> dict[str, Any]:
        """返回预设天气数据。"""
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "error": {"code": "E_INVALID_ARG", "message": f"lat/lon 必须为数字: lat={lat!r}, lon={lon!r}"},
            }

        temp = 22.0
        current = {
            "temperature": temp,
            "humidity": 60,
            "wind_speed": 2.0,
            "weather_code": 0,
            "apparent_temperature": temp + 0.5,
        }

        result: dict[str, Any] = {
            "ok": True,
            "current": current,
            "hourly": _generate_hourly(),
            "fake": True,
            "lat": lat_f,
            "lon": lon_f,
        }
        if city is not None:
            result["city"] = city
        return result


class FakeGeocodingBackend:
    """Fake 地理编码后端：返回预设城市数据，未知城市返回失败。"""

    _FAKE_CITIES: dict[str, list[dict[str, Any]]] = {
        "beijing": [{"name": "Beijing", "lat": 39.9042, "lon": 116.4074, "country": "China", "admin1": "Beijing"}],
        "shanghai": [{"name": "Shanghai", "lat": 31.2304, "lon": 121.4737, "country": "China", "admin1": "Shanghai"}],
        "shenzhen": [{"name": "Shenzhen", "lat": 22.5431, "lon": 114.0579, "country": "China", "admin1": "Guangdong"}],
        "北京": [{"name": "北京", "lat": 39.9042, "lon": 116.4074, "country": "China", "admin1": "Beijing"}],
        "上海": [{"name": "上海", "lat": 31.2304, "lon": 121.4737, "country": "China", "admin1": "Shanghai"}],
        "深圳": [{"name": "深圳", "lat": 22.5431, "lon": 114.0579, "country": "China", "admin1": "Guangdong"}],
    }

    def search(self, keyword: str, limit: int = 5) -> dict[str, Any]:
        """搜索城市（fake）。"""
        if not isinstance(keyword, str) or not keyword.strip():
            return {"ok": False, "error": {"code": "E_INVALID_ARG", "message": "keyword 不能为空"}}
        keyword_lower = keyword.strip().lower()
        results: list[dict[str, Any]] = []
        for name, cities in self._FAKE_CITIES.items():
            if keyword_lower in name.lower():
                results.extend(cities)
        if not results:
            return {
                "ok": False,
                "error": {"code": "E_CITY_NOT_FOUND", "message": f"未找到城市: {keyword}"},
            }
        return {"ok": True, "results": results[:limit], "count": len(results[:limit])}


class FakeIpLocationBackend:
    """Fake IP 定位后端：可配置成功/失败（默认返回 Beijing）。"""

    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail

    def locate(self) -> dict[str, Any]:
        """返回预设位置或失败。"""
        if self.should_fail:
            return {
                "ok": False,
                "error": {"code": "E_IP_LOCATION_FAILED", "message": "IP 定位失败（fake 后端）"},
            }
        return {
            "ok": True,
            "lat": 39.9042,
            "lon": 116.4074,
            "city": "Beijing",
            "fake": True,
        }
