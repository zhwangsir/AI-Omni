"""天气数据缓存：30 分钟 TTL + 命中时间戳。

- 缓存键为 ``(lat, lon)``（小数位归一化到 4 位，避免微小漂移导致 miss）
- TTL 默认 1800 秒；过期后强制刷新
- 后端返回 ``ok:false`` 时**不**写入缓存（下次仍尝试拉取）
- 命中返回的数据附加 ``cached_at`` / ``cached=True`` 标记

``_rewind_now`` 为测试钩子，模拟时间前进验证 TTL 过期。
"""

from __future__ import annotations

import time
from typing import Any, Callable

__all__ = ["WeatherCache"]


_DEFAULT_TTL = 1800  # 30 分钟
_COORD_PRECISION = 4  # 经纬度归一化到 4 位小数


class WeatherCache:
    """进程内天气缓存：按 (lat, lon) 索引，TTL 过期自动失效。

    线程安全：当前 M15 不要求跨线程并发访问；CLI 子进程模式天然隔离。
    如未来引入长驻进程多线程，应在外层加锁。
    """

    def __init__(self, ttl_seconds: int = _DEFAULT_TTL) -> None:
        """构造缓存。

        :param ttl_seconds: TTL 秒数，默认 1800（30 分钟）
        """
        self._ttl = int(ttl_seconds)
        # key: (lat_rounded, lon_rounded) -> {"data": dict, "cached_at": float}
        self._store: dict[tuple[float, float], dict[str, Any]] = {}
        # 测试用时间偏移（秒）；正数 = 把"当前时间"向前推进
        self._time_offset: float = 0.0

    def get(
        self,
        lat: float,
        lon: float,
        fetcher: Callable[[float, float], dict[str, Any]],
    ) -> dict[str, Any]:
        """取天气数据；未命中或过期时调用 ``fetcher(lat, lon)`` 拉取并缓存。

        :param lat: 纬度
        :param lon: 经度
        :param fetcher: 拉取函数，返回标准化天气 dict（含 ok 字段）
        :return: 天气数据 dict（命中时附加 cached_at / cached=True）
        """
        key = self._key(lat, lon)
        entry = self._store.get(key)
        now = self._now()
        if entry is not None and (now - entry["cached_at"]) < self._ttl:
            data = dict(entry["data"])
            data["cached"] = True
            data["cached_at"] = entry["cached_at"]
            return data
        # miss / expired → 拉取
        data = fetcher(float(lat), float(lon))
        if data.get("ok"):
            self._store[key] = {"data": dict(data), "cached_at": now}
            data["cached"] = False
            data["cached_at"] = now
        return data

    def invalidate(self, lat: float, lon: float) -> None:
        """清除指定位置的缓存。"""
        self._store.pop(self._key(lat, lon), None)

    def invalidate_all(self) -> None:
        """清空全部缓存。"""
        self._store.clear()

    def status(self) -> dict[str, Any]:
        """返回缓存状态摘要。"""
        locations = [
            {"lat": k[0], "lon": k[1], "cached_at": v["cached_at"]}
            for k, v in self._store.items()
        ]
        return {
            "entries": len(self._store),
            "locations": locations,
            "ttl_seconds": self._ttl,
        }

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _key(lat: float, lon: float) -> tuple[float, float]:
        """经纬度归一化到 4 位小数，避免微小漂移导致缓存 miss。"""
        return (round(float(lat), _COORD_PRECISION), round(float(lon), _COORD_PRECISION))

    def _now(self) -> float:
        """取当前时间（含测试偏移）。"""
        return time.time() + self._time_offset

    def _rewind_now(self, seconds: float) -> None:
        """测试钩子：把"当前时间"向前推进 ``seconds`` 秒。"""
        self._time_offset += float(seconds)
