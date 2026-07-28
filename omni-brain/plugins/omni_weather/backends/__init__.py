"""omni_weather backends 子包：Open-Meteo / Geocoding / IP 定位。

后端统一返回 dict：
- 成功 ``{"ok": True, ...}``
- 失败 ``{"ok": False, "error": {"code": "E_XXX", "message": "..."}}``

httpx 惰性导入（函数内 import），``ImportError`` 时返回 ``E_BACKEND_UNAVAILABLE``；
测试全用 fake HTTP（monkeypatch httpx.get），不访问真实网络。
"""
