"""IP 定位后端：无城市配置时降级使用。

使用 ip-api.com 免费 API：``http://ip-api.com/json/``

httpx 惰性导入；``status=fail`` 映射为 ``E_LOCATE_FAILED``；
HTTP 错误映射为 ``E_HTTP_FAILED``。
"""

from __future__ import annotations

from typing import Any

__all__ = ["IpLocationBackend"]


_IP_API_URL = "http://ip-api.com/json/"


class IpLocationBackend:
    """IP 定位客户端：根据当前出口 IP 推断地理位置。"""

    def locate(self) -> dict[str, Any]:
        """获取当前位置（基于出口 IP）。

        :return: ``{"ok": True, "lat", "lon", "city", "region", "country", "ip"}`` 或错误
        """
        params = {
            "fields": "status,lat,lon,city,regionName,country,query",
        }
        data = self._http_get(_IP_API_URL, params)
        if not data.get("ok"):
            return data
        raw = data["data"]
        if raw.get("status") == "fail":
            return {
                "ok": False,
                "error": {
                    "code": "E_LOCATE_FAILED",
                    "message": raw.get("message", "IP 定位失败"),
                },
            }
        return {
            "ok": True,
            "lat": raw.get("lat"),
            "lon": raw.get("lon"),
            "city": raw.get("city"),
            "region": raw.get("regionName"),
            "country": raw.get("country"),
            "ip": raw.get("query"),
            "raw": raw,
        }

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
