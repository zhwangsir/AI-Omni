"""omni_weather backends 测试：Open-Meteo / Geocoding / IP 定位 / Fake 后端。

全部 fake HTTP（monkeypatch httpx.get 返回预制 JSON），不访问真实网络。
覆盖成功路径、HTTP 失败、JSON 解析错误、httpx 缺失降级。
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from omni_weather.backends.fake_open_meteo import (
    FakeGeocodingBackend,
    FakeIpLocationBackend,
    FakeOpenMeteoBackend,
)
from omni_weather.backends.geocoding import GeocodingBackend
from omni_weather.backends.ip_location import IpLocationBackend
from omni_weather.backends.open_meteo import OpenMeteoBackend


class _FakeResp:
    """模拟 httpx.Response：status_code / raise_for_status / json。"""

    def __init__(self, data: Any, status: int = 200, text: str = "") -> None:
        self._data = data
        self.status_code = status
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text}")

    def json(self) -> Any:
        return self._data


def _patch_httpx_get(monkeypatch, data: Any, status: int = 200, text: str = "") -> list[dict]:
    """把 httpx.get 替换为返回 _FakeResp 的 fake；记录调用参数。"""
    calls: list[dict] = []

    def fake_get(url: str, **kwargs: Any) -> _FakeResp:
        calls.append({"url": url, **kwargs})
        return _FakeResp(data, status=status, text=text)

    import httpx

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


# ---------------------------------------------------------------------------
# OpenMeteoBackend
# ---------------------------------------------------------------------------
class TestOpenMeteoBackend:
    def test_get_weather_returns_current_and_hourly(self, monkeypatch):
        """get_weather 返回 current + hourly(24h) + raw。"""
        fake = {
            "current": {
                "temperature_2m": 20.5,
                "relative_humidity_2m": 65,
                "wind_speed_10m": 3.2,
                "weather_code": 0,
                "apparent_temperature": 21.0,
            },
            "hourly": {
                "time": ["2026-07-27T00:00"] * 24,
                "temperature_2m": [20.0] * 24,
                "weather_code": [0] * 24,
                "precipitation_probability": [10] * 24,
            },
        }
        calls = _patch_httpx_get(monkeypatch, fake)
        b = OpenMeteoBackend()
        result = b.get_weather(lat=39.9, lon=116.4)
        assert result["ok"] is True
        assert result["current"]["temperature"] == 20.5
        assert result["current"]["humidity"] == 65
        assert result["current"]["wind_speed"] == 3.2
        assert result["current"]["weather_code"] == 0
        assert result["current"]["apparent_temperature"] == 21.0
        assert len(result["hourly"]) == 24
        assert result["hourly"][0]["temperature"] == 20.0
        assert result["raw"]["current"]["temperature_2m"] == 20.5
        # URL 与参数校验
        assert calls[0]["url"] == "https://api.open-meteo.com/v1/forecast"
        assert calls[0]["params"]["latitude"] == 39.9
        assert calls[0]["params"]["longitude"] == 116.4
        assert "current" in calls[0]["params"]
        assert "hourly" in calls[0]["params"]

    def test_get_weather_with_city_name(self, monkeypatch):
        """get_weather 接受可选 city 字段，写入返回结果。"""
        fake = {
            "current": {
                "temperature_2m": 5.0,
                "relative_humidity_2m": 80,
                "wind_speed_10m": 1.0,
                "weather_code": 3,
            },
            "hourly": {"time": [], "temperature_2m": [], "weather_code": [], "precipitation_probability": []},
        }
        _patch_httpx_get(monkeypatch, fake)
        b = OpenMeteoBackend()
        result = b.get_weather(lat=31.2, lon=121.5, city="上海")
        assert result["ok"] is True
        assert result["city"] == "上海"
        assert result["current"]["temperature"] == 5.0

    def test_get_weather_http_error(self, monkeypatch):
        """HTTP 4xx/5xx 映射为 E_HTTP_FAILED。"""
        _patch_httpx_get(monkeypatch, None, status=500, text="server error")
        b = OpenMeteoBackend()
        result = b.get_weather(lat=0.0, lon=0.0)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_HTTP_FAILED"
        assert "500" in result["error"]["message"]

    def test_get_weather_json_decode_error(self, monkeypatch):
        """JSON 解析失败映射为 E_PARSE_FAILED。"""

        class _BadResp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> Any:
                raise ValueError("not json")

        import httpx

        monkeypatch.setattr(httpx, "get", lambda url, **kw: _BadResp())
        b = OpenMeteoBackend()
        result = b.get_weather(lat=0.0, lon=0.0)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_PARSE_FAILED"

    def test_get_weather_request_exception(self, monkeypatch):
        """httpx.get 抛异常映射为 E_HTTP_FAILED。"""

        def boom(url, **kw):
            raise RuntimeError("network down")

        import httpx

        monkeypatch.setattr(httpx, "get", boom)
        b = OpenMeteoBackend()
        result = b.get_weather(lat=0.0, lon=0.0)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_HTTP_FAILED"
        assert "network down" in result["error"]["message"]

    def test_get_weather_invalid_lat_lon(self):
        """非法经纬度（非数字）返回 E_INVALID_ARG。"""
        b = OpenMeteoBackend()
        result = b.get_weather(lat="abc", lon=116.4)  # type: ignore[arg-type]
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_ARG"

    def test_get_weather_lat_out_of_range(self):
        """纬度 > 90 返回 E_INVALID_ARG。"""
        b = OpenMeteoBackend()
        result = b.get_weather(lat=95.0, lon=0.0)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_ARG"

    def test_get_weather_lon_out_of_range(self):
        """经度 > 180 返回 E_INVALID_ARG。"""
        b = OpenMeteoBackend()
        result = b.get_weather(lat=0.0, lon=200.0)
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_ARG"

    def test_get_weather_partial_current(self, monkeypatch):
        """current 缺字段时仍返回 ok（用 None 填充）。"""
        fake = {
            "current": {"temperature_2m": 18.0},
            "hourly": {"time": [], "temperature_2m": [], "weather_code": [], "precipitation_probability": []},
        }
        _patch_httpx_get(monkeypatch, fake)
        b = OpenMeteoBackend()
        result = b.get_weather(lat=0.0, lon=0.0)
        assert result["ok"] is True
        assert result["current"]["temperature"] == 18.0
        assert result["current"]["humidity"] is None
        assert result["current"]["weather_code"] is None


# ---------------------------------------------------------------------------
# GeocodingBackend
# ---------------------------------------------------------------------------
class TestGeocodingBackend:
    def test_search_returns_results(self, monkeypatch):
        """search 返回标准化 results 列表。"""
        fake = {
            "results": [
                {
                    "name": "北京",
                    "latitude": 39.9042,
                    "longitude": 116.4074,
                    "country": "China",
                    "admin1": "Beijing",
                    "timezone": "Asia/Shanghai",
                    "population": 21540000,
                }
            ]
        }
        calls = _patch_httpx_get(monkeypatch, fake)
        b = GeocodingBackend()
        result = b.search("北京", limit=5)
        assert result["ok"] is True
        assert len(result["results"]) == 1
        r = result["results"][0]
        assert r["name"] == "北京"
        assert r["lat"] == 39.9042
        assert r["lon"] == 116.4074
        assert r["country"] == "China"
        assert calls[0]["url"] == "https://geocoding-api.open-meteo.com/v1/search"
        assert calls[0]["params"]["name"] == "北京"
        assert calls[0]["params"]["count"] == 5

    def test_search_empty_query(self):
        """空字符串返回 E_INVALID_ARG。"""
        b = GeocodingBackend()
        result = b.search("")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_ARG"

    def test_search_no_results(self, monkeypatch):
        """API 返回无 results 字段时返回空列表。"""
        fake = {"results": []}
        _patch_httpx_get(monkeypatch, fake)
        b = GeocodingBackend()
        result = b.search("不存在的地方")
        assert result["ok"] is True
        assert result["results"] == []
        assert result["count"] == 0

    def test_search_missing_results_key(self, monkeypatch):
        """API 返回缺 results 键时返回空列表。"""
        fake = {"generationtime_ms": 1.0}
        _patch_httpx_get(monkeypatch, fake)
        b = GeocodingBackend()
        result = b.search("xxx")
        assert result["ok"] is True
        assert result["results"] == []

    def test_search_http_error(self, monkeypatch):
        """HTTP 错误映射为 E_HTTP_FAILED。"""
        _patch_httpx_get(monkeypatch, None, status=503, text="busy")
        b = GeocodingBackend()
        result = b.search("北京")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_HTTP_FAILED"

    def test_search_request_exception(self, monkeypatch):
        """httpx.get 抛异常映射为 E_HTTP_FAILED。"""
        import httpx

        monkeypatch.setattr(httpx, "get", lambda url, **kw: (_ for _ in ()).throw(RuntimeError("net err")))
        b = GeocodingBackend()
        result = b.search("北京")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_HTTP_FAILED"

    def test_search_httpx_unavailable(self, monkeypatch):
        """httpx 未安装时降级为 E_BACKEND_UNAVAILABLE。"""
        monkeypatch.setitem(sys.modules, "httpx", None)
        b = GeocodingBackend()
        result = b.search("北京")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"
        assert "httpx" in result["error"]["message"]

    def test_search_json_decode_error(self, monkeypatch):
        """响应 JSON 解析失败映射为 E_PARSE_FAILED。"""

        class _BadResp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> Any:
                raise ValueError("bad json")

        import httpx

        monkeypatch.setattr(httpx, "get", lambda url, **kw: _BadResp())
        b = GeocodingBackend()
        result = b.search("北京")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_PARSE_FAILED"


# ---------------------------------------------------------------------------
# IpLocationBackend
# ---------------------------------------------------------------------------
class TestIpLocationBackend:
    def test_locate_returns_lat_lon_city(self, monkeypatch):
        """locate 返回标准化 lat/lon/city/region/country。"""
        fake = {
            "lat": 39.9042,
            "lon": 116.4074,
            "city": "Beijing",
            "regionName": "Beijing",
            "country": "China",
            "query": "1.2.3.4",
        }
        calls = _patch_httpx_get(monkeypatch, fake)
        b = IpLocationBackend()
        result = b.locate()
        assert result["ok"] is True
        assert result["lat"] == 39.9042
        assert result["lon"] == 116.4074
        assert result["city"] == "Beijing"
        assert result["country"] == "China"
        assert result["ip"] == "1.2.3.4"
        assert calls[0]["url"] == "http://ip-api.com/json/"
        assert calls[0]["params"] == {"fields": "status,lat,lon,city,regionName,country,query"}

    def test_locate_failed_status(self, monkeypatch):
        """API 返回 status=fail 时映射为 E_LOCATE_FAILED。"""
        fake = {"status": "fail", "message": "private ip"}
        _patch_httpx_get(monkeypatch, fake)
        b = IpLocationBackend()
        result = b.locate()
        assert result["ok"] is False
        assert result["error"]["code"] == "E_LOCATE_FAILED"
        assert "private ip" in result["error"]["message"]

    def test_locate_http_error(self, monkeypatch):
        """HTTP 错误映射为 E_HTTP_FAILED。"""
        _patch_httpx_get(monkeypatch, None, status=429, text="rate limited")
        b = IpLocationBackend()
        result = b.locate()
        assert result["ok"] is False
        assert result["error"]["code"] == "E_HTTP_FAILED"

    def test_locate_request_exception(self, monkeypatch):
        """httpx.get 抛异常映射为 E_HTTP_FAILED。"""
        import httpx

        monkeypatch.setattr(httpx, "get", lambda url, **kw: (_ for _ in ()).throw(RuntimeError("dns fail")))
        b = IpLocationBackend()
        result = b.locate()
        assert result["ok"] is False
        assert result["error"]["code"] == "E_HTTP_FAILED"

    def test_locate_missing_fields(self, monkeypatch):
        """部分字段缺失时仍返回 ok（None 填充）。"""
        fake = {"lat": 30.0, "lon": 120.0}
        _patch_httpx_get(monkeypatch, fake)
        b = IpLocationBackend()
        result = b.locate()
        assert result["ok"] is True
        assert result["lat"] == 30.0
        assert result["city"] is None
        assert result["country"] is None

    def test_locate_httpx_unavailable(self, monkeypatch):
        """httpx 未安装时降级为 E_BACKEND_UNAVAILABLE。"""
        monkeypatch.setitem(sys.modules, "httpx", None)
        b = IpLocationBackend()
        result = b.locate()
        assert result["ok"] is False
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"
        assert "httpx" in result["error"]["message"]

    def test_locate_json_decode_error(self, monkeypatch):
        """响应 JSON 解析失败映射为 E_PARSE_FAILED。"""

        class _BadResp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> Any:
                raise ValueError("bad json")

        import httpx

        monkeypatch.setattr(httpx, "get", lambda url, **kw: _BadResp())
        b = IpLocationBackend()
        result = b.locate()
        assert result["ok"] is False
        assert result["error"]["code"] == "E_PARSE_FAILED"


# ---------------------------------------------------------------------------
# FakeOpenMeteoBackend
# ---------------------------------------------------------------------------
class TestFakeOpenMeteoBackend:
    def test_get_weather_invalid_lat_string(self):
        """lat 为非数字字符串（ValueError）→ E_INVALID_ARG。"""
        b = FakeOpenMeteoBackend()
        result = b.get_weather(lat="abc", lon=116.4)  # type: ignore[arg-type]
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_ARG"
        assert "abc" in result["error"]["message"]

    def test_get_weather_none_lat(self):
        """lat 为 None（TypeError）→ E_INVALID_ARG。"""
        b = FakeOpenMeteoBackend()
        result = b.get_weather(lat=None, lon=116.4)  # type: ignore[arg-type]
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_ARG"

    def test_get_weather_success_echoes_coords_and_city(self):
        """成功路径：回显归一化 lat/lon 与 city，hourly 为 24 条。"""
        b = FakeOpenMeteoBackend()
        result = b.get_weather(lat=39.9042, lon=116.4074, city="北京")
        assert result["ok"] is True
        assert result["fake"] is True
        assert result["lat"] == 39.9042
        assert result["lon"] == 116.4074
        assert result["city"] == "北京"
        assert len(result["hourly"]) == 24


# ---------------------------------------------------------------------------
# FakeGeocodingBackend
# ---------------------------------------------------------------------------
class TestFakeGeocodingBackend:
    def test_search_empty_keyword(self):
        """空白关键词 → E_INVALID_ARG。"""
        b = FakeGeocodingBackend()
        for bad in ("", "   "):
            result = b.search(bad)
            assert result["ok"] is False
            assert result["error"]["code"] == "E_INVALID_ARG"

    def test_search_non_string_keyword(self):
        """非字符串关键词 → E_INVALID_ARG。"""
        b = FakeGeocodingBackend()
        result = b.search(None)  # type: ignore[arg-type]
        assert result["ok"] is False
        assert result["error"]["code"] == "E_INVALID_ARG"

    def test_search_unknown_city(self):
        """未收录城市 → E_CITY_NOT_FOUND。"""
        b = FakeGeocodingBackend()
        result = b.search("亚特兰蒂斯")
        assert result["ok"] is False
        assert result["error"]["code"] == "E_CITY_NOT_FOUND"
        assert "亚特兰蒂斯" in result["error"]["message"]

    def test_search_known_city(self):
        """收录城市 → ok + 标准化结果。"""
        b = FakeGeocodingBackend()
        result = b.search("北京")
        assert result["ok"] is True
        assert result["count"] == 1
        assert result["results"][0]["name"] == "北京"
        assert result["results"][0]["lat"] == 39.9042


# ---------------------------------------------------------------------------
# FakeIpLocationBackend
# ---------------------------------------------------------------------------
class TestFakeIpLocationBackend:
    def test_locate_success_default(self):
        """默认返回预设 Beijing 位置。"""
        b = FakeIpLocationBackend()
        result = b.locate()
        assert result["ok"] is True
        assert result["lat"] == 39.9042
        assert result["lon"] == 116.4074
        assert result["city"] == "Beijing"
        assert result["fake"] is True

    def test_locate_failure_when_should_fail(self):
        """should_fail=True 时返回 E_IP_LOCATION_FAILED。"""
        b = FakeIpLocationBackend(should_fail=True)
        result = b.locate()
        assert result["ok"] is False
        assert result["error"]["code"] == "E_IP_LOCATION_FAILED"
