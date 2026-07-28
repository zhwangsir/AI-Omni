"""omni_weather 缓存测试：30 分钟 TTL + 启动刷新。

覆盖：
- 命中：cached_at 时间戳正确
- 过期：30 分钟后强制刷新
- 不同 (lat, lon) 不混用缓存
- 手动 invalidate
- 后端失败不污染旧缓存
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from omni_weather.cache import WeatherCache


def _fake_weather(temp: float, code: int = 0) -> dict[str, Any]:
    """构造一份预制天气数据。"""
    return {
        "ok": True,
        "current": {
            "temperature": temp,
            "humidity": 60,
            "wind_speed": 2.0,
            "weather_code": code,
            "apparent_temperature": temp,
        },
        "hourly": [],
        "city": "测试",
        "raw": {},
    }


class TestWeatherCache:
    def test_miss_triggers_fetch(self):
        """缓存未命中时调用 fetcher 拉取。"""
        calls: list[tuple[float, float]] = []

        def fetcher(lat: float, lon: float) -> dict[str, Any]:
            calls.append((lat, lon))
            return _fake_weather(20.0)

        cache = WeatherCache(ttl_seconds=1800)
        result = cache.get(39.9, 116.4, fetcher)
        assert result["ok"] is True
        assert result["current"]["temperature"] == 20.0
        assert "cached_at" in result
        assert len(calls) == 1

    def test_hit_avoids_fetch(self):
        """缓存命中时不调用 fetcher。"""
        calls: list[tuple[float, float]] = []

        def fetcher(lat: float, lon: float) -> dict[str, Any]:
            calls.append((lat, lon))
            return _fake_weather(20.0)

        cache = WeatherCache(ttl_seconds=1800)
        cache.get(39.9, 116.4, fetcher)
        # 第二次命中
        result = cache.get(39.9, 116.4, fetcher)
        assert result["ok"] is True
        assert result["current"]["temperature"] == 20.0
        assert result.get("cached")
        assert len(calls) == 1

    def test_expired_forces_refresh(self):
        """TTL 过期后强制刷新。"""
        calls: list[int] = []

        def fetcher(lat: float, lon: float) -> dict[str, Any]:
            calls.append(1)
            return _fake_weather(20.0 + len(calls))

        cache = WeatherCache(ttl_seconds=1800)
        cache.get(39.9, 116.4, fetcher)
        # 模拟时间前进 31 分钟
        cache._rewind_now(31 * 60)  # type: ignore[attr-defined]
        result = cache.get(39.9, 116.4, fetcher)
        assert result["current"]["temperature"] == 22.0
        assert len(calls) == 2

    def test_different_location_does_not_share_cache(self):
        """不同 (lat, lon) 不混用缓存。"""
        calls: list[tuple[float, float]] = []

        def fetcher(lat: float, lon: float) -> dict[str, Any]:
            calls.append((lat, lon))
            return _fake_weather(lat)

        cache = WeatherCache(ttl_seconds=1800)
        cache.get(39.9, 116.4, fetcher)
        cache.get(31.2, 121.5, fetcher)
        assert len(calls) == 2
        assert (39.9, 116.4) in calls
        assert (31.2, 121.5) in calls

    def test_invalidate_clears_entry(self):
        """invalidate 清除指定位置的缓存。"""
        calls: list[int] = []

        def fetcher(lat: float, lon: float) -> dict[str, Any]:
            calls.append(1)
            return _fake_weather(20.0)

        cache = WeatherCache(ttl_seconds=1800)
        cache.get(39.9, 116.4, fetcher)
        cache.invalidate(39.9, 116.4)
        cache.get(39.9, 116.4, fetcher)
        assert len(calls) == 2

    def test_invalidate_all_clears_everything(self):
        """invalidate_all 清空全部缓存。"""
        calls: list[int] = []

        def fetcher(lat: float, lon: float) -> dict[str, Any]:
            calls.append(1)
            return _fake_weather(20.0)

        cache = WeatherCache(ttl_seconds=1800)
        cache.get(39.9, 116.4, fetcher)
        cache.get(31.2, 121.5, fetcher)
        cache.invalidate_all()
        cache.get(39.9, 116.4, fetcher)
        assert len(calls) == 3

    def test_fetcher_failure_does_not_pollute_cache(self):
        """fetcher 返回 ok:false 时缓存保持空（下次仍尝试拉取）。"""
        calls: list[int] = []
        attempt = {"n": 0}

        def fetcher(lat: float, lon: float) -> dict[str, Any]:
            calls.append(1)
            attempt["n"] += 1
            if attempt["n"] == 1:
                return {"ok": False, "error": {"code": "E_HTTP_FAILED", "message": "down"}}
            return _fake_weather(25.0)

        cache = WeatherCache(ttl_seconds=1800)
        r1 = cache.get(39.9, 116.4, fetcher)
        assert r1["ok"] is False
        # 失败结果不应被缓存
        r2 = cache.get(39.9, 116.4, fetcher)
        assert r2["ok"] is True
        assert r2["current"]["temperature"] == 25.0
        assert len(calls) == 2

    def test_cached_at_timestamp_present(self):
        """命中缓存时返回 cached_at（ISO8601 字符串或数值）。"""
        def fetcher(lat: float, lon: float) -> dict[str, Any]:
            return _fake_weather(20.0)

        cache = WeatherCache(ttl_seconds=1800)
        cache.get(39.9, 116.4, fetcher)
        result = cache.get(39.9, 116.4, fetcher)
        assert result["cached_at"] is not None
        assert result["cached"] is True

    def test_status_reports_cache_state(self):
        """status 返回缓存条数 / 位置列表 / 最后更新时间。"""
        def fetcher(lat: float, lon: float) -> dict[str, Any]:
            return _fake_weather(20.0)

        cache = WeatherCache(ttl_seconds=1800)
        cache.get(39.9, 116.4, fetcher)
        cache.get(31.2, 121.5, fetcher)
        status = cache.status()
        assert status["entries"] == 2
        assert len(status["locations"]) == 2
        assert status["ttl_seconds"] == 1800

    def test_location_rounding_avoids_drift(self):
        """缓存键对经纬度做小数位归一化，避免微小漂移导致 miss。"""
        calls: list[int] = []

        def fetcher(lat: float, lon: float) -> dict[str, Any]:
            calls.append(1)
            return _fake_weather(lat)

        cache = WeatherCache(ttl_seconds=1800)
        cache.get(39.9042, 116.4074, fetcher)
        # 第 5 位小数变化应命中
        cache.get(39.90421, 116.40739, fetcher)
        assert len(calls) == 1

    def test_custom_ttl(self):
        """支持自定义 TTL（如 60s 短缓存）。"""
        def fetcher(lat: float, lon: float) -> dict[str, Any]:
            return _fake_weather(20.0)

        cache = WeatherCache(ttl_seconds=60)
        cache.get(0.0, 0.0, fetcher)
        assert cache.status()["ttl_seconds"] == 60
