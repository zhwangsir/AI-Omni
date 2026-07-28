"""omni_music auth 包：Cookie 加密存储 + 扫码登录流程。

- :class:`CookieStore`：AES-256-GCM 加密落盘（M17.3）
- :class:`FakeCookieStore`：内存版 fake
- :class:`QRLoginFlow`：扫码登录协调器（M17.4）
- :class:`FakeQRLoginFlow`：测试用 fake 流程
"""

from __future__ import annotations

from omni_music.auth.cookie_store import CookieStore, FakeCookieStore
from omni_music.auth.qr_login import FakeQRLoginFlow, QRLoginFlow

__all__ = [
    "CookieStore",
    "FakeCookieStore",
    "QRLoginFlow",
    "FakeQRLoginFlow",
]
