"""QRLoginFlow：扫码登录通用协调流程（M17.4）。

协调 :class:`MusicSource` 的 ``login_qr`` / ``check_login_status`` 与
:class:`CookieStore` 的 ``save``：

1. ``start()`` → 调用 ``source.login_qr()`` 得到 ``{key, qr_url}``
2. 调用方展示 qr_url 二维码给用户扫码
3. ``poll()`` → 调用 ``source.check_login_status(key)`` 返回状态字符串
4. 状态变为 ``confirmed`` 时，从 source 取出 cookie 调用 ``store.save()``
5. 状态变为 ``expired`` 或超时则不保存

防死循环：默认超时 180s（可通过 ``timeout_s`` 调整）。

合规说明（D17.4）：仅协调用户本人扫码登录流程，不携带任何破解付费内容的逻辑。
仅个人学习用途。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from omni_music.auth.cookie_store import CookieStore
from omni_music.models import MusicSourceEnum
from omni_music.sources.base import MusicSource

logger = logging.getLogger(__name__)

# 默认轮询间隔（秒）
_DEFAULT_POLL_INTERVAL_S = 2.0

# 默认超时（秒）—— 防死循环
_DEFAULT_TIMEOUT_S = 180.0

# 终态集合
_TERMINAL_STATES: frozenset[str] = frozenset({"confirmed", "expired", "timeout"})


class QRLoginFlow:
    """扫码登录协调器：协调 MusicSource + CookieStore 完成扫码登录全流程。

    :ivar source: 音乐源实例（需实现 login_qr / check_login_status）
    :ivar store: Cookie 存储器
    :ivar poll_interval_s: 轮询间隔（秒）
    :ivar timeout_s: 总超时（秒）
    """

    def __init__(
        self,
        source: MusicSource,
        store: CookieStore,
        poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        """构造扫码登录流程。

        :param source: 音乐源实例
        :param store: Cookie 存储器
        :param poll_interval_s: 轮询间隔秒数
        :param timeout_s: 总超时秒数
        """
        self.source: MusicSource = source
        self.store: CookieStore = store
        self.poll_interval_s: float = poll_interval_s
        self.timeout_s: float = timeout_s
        # start 后填充
        self._key: str | None = None
        self._qr_url: str | None = None
        self._started_at: float | None = None
        self._final_status: str | None = None
        self._cookies_saved: bool = False

    def start(self) -> dict[str, str]:
        """发起扫码登录，返回 ``{key, qr_url}``。

        :return: dict 含 ``key``（轮询用）与 ``qr_url``（二维码图片 URL）
        """
        result = self.source.login_qr()
        self._key = result.get("key", "")
        self._qr_url = result.get("qr_url", "")
        self._started_at = time.monotonic()
        self._final_status = None
        self._cookies_saved = False
        return {"key": self._key, "qr_url": self._qr_url}

    def poll(self) -> str:
        """轮询一次登录状态。

        confirmed 时自动保存 cookie（仅首次）；expired/timeout 不保存。
        未 start 时返回 ``timeout``。

        :return: 状态字符串 ``waiting`` / ``scanned`` / ``confirmed`` / ``expired`` / ``timeout``
        """
        if self._key is None:
            return "timeout"
        # 超时检查
        elapsed = time.monotonic() - (self._started_at or 0)
        if elapsed >= self.timeout_s:
            self._final_status = "timeout"
            return "timeout"
        status = self.source.check_login_status(self._key)
        if status == "confirmed" and not self._cookies_saved:
            self._save_cookies()
            self._cookies_saved = True
        if status in _TERMINAL_STATES:
            self._final_status = status
        return status

    def _save_cookies(self) -> None:
        """从 source 取出 cookie 并保存到 store。

        子类可覆盖此方法定制 cookie 获取方式（如 FakeQRLoginFlow 走 fake 路径）。
        默认实现尝试调用 ``source.get_cookies_on_confirmed()``，若无此方法则保存空 dict。
        """
        cookies: dict[str, str] | None = None
        getter = getattr(self.source, "get_cookies_on_confirmed", None)
        if callable(getter):
            try:
                cookies = getter()
            except Exception as exc:  # noqa: BLE001
                logger.warning("获取 cookie 失败: %s", exc)
        if cookies is None:
            cookies = {}
        source_name = self._source_name()
        self.store.save(source_name, cookies)

    def _source_name(self) -> str:
        """返回用于 CookieStore 索引的 source 名（``source.source.value``）。"""
        return self.source.source.value

    def run_until_done(self) -> dict[str, Any]:
        """阻塞轮询直到 confirmed/expired/timeout。

        :return: dict 含 ``status`` / ``key`` / ``qr_url``
        """
        if self._key is None:
            self.start()
        assert self._key is not None
        while True:
            status = self.poll()
            if status in _TERMINAL_STATES:
                break
            # sleep interval（sleep(0) 让出调度，不阻塞）
            time.sleep(self.poll_interval_s)
        return {
            "status": self._final_status or status,
            "key": self._key or "",
            "qr_url": self._qr_url or "",
        }


class FakeQRLoginFlow(QRLoginFlow):
    """测试用 fake 扫码登录流程。

    与 :class:`QRLoginFlow` 行为一致，但默认 ``poll_interval_s=0`` 与 ``timeout_s=10``，
    便于测试快速跑完状态机。子类化而非独立实现，确保与真实流程行为一致。
    """

    def __init__(
        self,
        source: MusicSource,
        store: CookieStore,
        poll_interval_s: float = 0.0,
        timeout_s: float = 10.0,
    ) -> None:
        """构造 fake 流程，默认无 sleep 与 10s 超时。"""
        super().__init__(
            source=source,
            store=store,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )
