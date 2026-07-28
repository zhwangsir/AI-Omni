"""Open-Meteo Geocoding API 客户端：城市名 → 经纬度。

文档：``https://geocoding-api.open-meteo.com/v1/search``

httpx 惰性导入；空字符串返回 ``E_INVALID_ARG``；
HTTP 错误映射为 ``E_HTTP_FAILED``。
"""

from __future__ import annotations

from typing import Any

__all__ = ["GeocodingBackend"]


_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


class GeocodingBackend:
    """Geocoding 客户端：城市名搜索。"""

    def search(self, name: str, limit: int = 5) -> dict[str, Any]:
        """按城市名搜索，返回标准化 results 列表。

        :param name: 城市名（非空字符串）
        :param limit: 返回上限，默认 5
        :return: ``{"ok": True, "results": [...], "count": N}`` 或错误 dict
        """
        if not isinstance(name, str) or not name.strip():
            return {
                "ok": False,
                "error": {"code": "E_INVALID_ARG", "message": "name 不能为空"},
            }
        params = {
            "name": name.strip(),
            "count": max(1, min(limit, 50)),
            "language": "zh",
            "format": "json",
        }
        data = self._http_get(_GEOCODING_URL, params)
        if not data.get("ok"):
            return data
        raw = data["data"]
        results_raw = raw.get("results", []) or []
        results = [
            {
                "name": r.get("name"),
                "lat": r.get("latitude"),
                "lon": r.get("longitude"),
                "country": r.get("country"),
                "region": r.get("admin1"),
                "timezone": r.get("timezone"),
                "population": r.get("population"),
            }
            for r in results_raw
        ]
        return {"ok": True, "results": results, "count": len(results), "raw": raw}

    # ------------------------------------------------------------------
    def _http_get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """惰性 import httpx，发起 GET 请求。"""
        try:
            import httpx  # 惰性导入
        except ImportError as exc:
            return {
                "ok": False,
                "error": {"code": "E_BACKEND_UNAVAILABLE", "message": f"httpx 不可用: {exc}"},
            }
        try:
            resp = httpx.get(url, params=params, timeout=10)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": {"code": "E_HTTP_FAILED", "message": str(exc)},
            }
        try:
            return {"ok": True, "data": resp.json()}
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": {"code": "E_PARSE_FAILED", "message": str(exc)},
            }
