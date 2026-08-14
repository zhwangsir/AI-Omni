"""omni_weather CLI 测试：子命令派发 + JSON 输出 + 退出码。

fake HTTP 全程 monkeypatch；config 路径指向 tmp_path 隔离。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from omni_weather import cli, tools


class _FakeResp:
    def __init__(self, data: Any, status: int = 200) -> None:
        self._data = data
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._data


def _fake_weather_payload(temp: float = 22.0, code: int = 0) -> dict[str, Any]:
    return {
        "current": {
            "temperature_2m": temp,
            "relative_humidity_2m": 60,
            "wind_speed_10m": 2.0,
            "weather_code": code,
            "apparent_temperature": temp,
        },
        "hourly": {
            "time": ["2026-07-27T00:00"] * 24,
            "temperature_2m": [temp] * 24,
            "weather_code": [code] * 24,
            "precipitation_probability": [10] * 24,
        },
    }


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    """重置 runtime + 把 config 路径指向 tmp_path。"""
    monkeypatch.setenv("AI_OMNI_WEATHER_CONFIG", str(tmp_path / "config.json"))
    tools._reset_runtime()
    yield


@pytest.fixture
def patch_httpx(monkeypatch):
    import httpx

    def fake_get(url: str, **kwargs: Any) -> _FakeResp:
        if "geocoding-api" in url:
            return _FakeResp(
                {
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
            )
        if "ip-api" in url:
            return _FakeResp(
                {
                    "status": "success",
                    "lat": 39.9042,
                    "lon": 116.4074,
                    "city": "Beijing",
                    "regionName": "Beijing",
                    "country": "China",
                    "query": "1.2.3.4",
                }
            )
        return _FakeResp(_fake_weather_payload())

    monkeypatch.setattr(httpx, "get", fake_get)


class TestCliStatus:
    def test_status_no_location(self, patch_httpx, capsys):
        """status 无位置时返回 ok（location=null）。"""
        rc = cli.main(["status", "--fake"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert rc == 0
        assert data["ok"] is True
        assert data["data"]["location"] is None

    def test_status_with_location(self, patch_httpx, capsys):
        """status 已配置位置时返回 location。"""
        tools._runtime.location = {"city": "北京", "lat": 39.9, "lon": 116.4}
        rc = cli.main(["status", "--fake"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert rc == 0
        assert data["data"]["location"]["city"] == "北京"


class TestCliGet:
    def test_get_returns_weather(self, patch_httpx, capsys):
        tools._runtime.location = {"city": "北京", "lat": 39.9, "lon": 116.4}
        rc = cli.main(["get", "--fake"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert rc == 0
        assert data["ok"] is True
        assert data["data"]["mood"]["mood"] == "sunny"


class TestCliForecast:
    def test_forecast_returns_24h(self, patch_httpx, capsys):
        tools._runtime.location = {"city": "北京", "lat": 39.9, "lon": 116.4}
        rc = cli.main(["forecast", "--fake"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert rc == 0
        assert len(data["data"]["hourly"]) == 24


class TestCliSetLocation:
    def test_set_location_persists(self, patch_httpx, tmp_path, capsys):
        rc = cli.main(["set-location", "北京", "--fake"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert rc == 0
        assert data["data"]["city"] == "北京"
        cfg = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert cfg["city"] == "北京"


class TestCliSearch:
    def test_search_returns_results(self, patch_httpx, capsys):
        rc = cli.main(["search", "北京", "--fake"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert rc == 0
        assert data["data"]["results"][0]["name"] == "北京"

    def test_search_missing_keyword_returns_json_invalid_params(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(["search", "--fake"])
        assert exc.value.code == 1
        data = json.loads(capsys.readouterr().out)
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_PARAMS"

    def test_set_location_missing_city_returns_json_invalid_params(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(["set-location", "--fake"])
        assert exc.value.code == 1
        data = json.loads(capsys.readouterr().out)
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_PARAMS"


class TestCliRefresh:
    def test_refresh_ok(self, patch_httpx, capsys):
        tools._runtime.location = {"city": "北京", "lat": 39.9, "lon": 116.4}
        rc = cli.main(["refresh", "--fake"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert rc == 0
        assert "refreshed_at" in data["data"]


class TestCliCall:
    def test_call_status(self, patch_httpx, capsys):
        """call 通用入口可调用 weather_status。"""
        rc = cli.main(["call", "weather_status", "--args", "{}", "--fake"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert rc == 0
        assert data["ok"] is True

    def test_call_with_args_json(self, patch_httpx, capsys):
        """call 接受 --args JSON 字符串。"""
        tools._runtime.location = {"city": "北京", "lat": 39.9, "lon": 116.4}
        rc = cli.main(["call", "weather_search_city", "--args", '{"keyword":"北京"}', "--fake"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert rc == 0
        assert data["data"]["results"][0]["name"] == "北京"

    def test_call_unknown_tool(self, capsys):
        """未知工具 → ok:false + 退出码 1。"""
        rc = cli.main(["call", "weather_nonexistent", "--fake"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert rc == 1
        assert data["ok"] is False

    def test_call_invalid_args_json(self, capsys):
        """非法 JSON → ok:false。"""
        rc = cli.main(["call", "weather_status", "--args", "{not json", "--fake"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert rc == 1
        assert data["ok"] is False
