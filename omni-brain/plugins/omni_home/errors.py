"""omni_home 插件的异常体系。

所有可被调用方预期的错误都继承自 :class:`HomeError`，
tools/CLI 层统一捕获并映射为 ``{"ok": false, "error": {...}}`` 响应。
"""


class HomeError(Exception):
    """智能家居插件所有可预期错误的基类。"""


class HomeConnectionError(HomeError):
    """无法连接 Home Assistant（网络失败 / 超时 / 服务不可达）时抛出。"""


class HomeAuthError(HomeError):
    """认证失败（401/403，token 缺失或失效）时抛出。"""
