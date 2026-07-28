"""NeteaseMusicSource：网易云音乐源实现（M17.5）。

实现 :class:`MusicSource` 抽象基类的 6 个方法，对接网易云音乐 web API：

- ``/api/cloudsearch/pc`` 搜索
- ``/api/song/enhance/player/url/v1`` 获取播放 URL
- ``/api/song/lyric`` 获取歌词
- ``/api/v3/song/detail`` 获取歌曲详情
- ``/api/login/qrcode/unikey`` + ``/api/login/qrcode/client/login`` 扫码登录

合规说明（D17.4）：**仅个人学习用途，不破解付费内容**。

- 仅免费/试听曲目；VIP 曲目 :meth:`get_song_url` 返回 None，不绕过付费墙
- ``httpx`` 惰性导入（CLAUDE.md §三），``ImportError`` 时降级返回空/None，不拖垮插件
- 测试全部使用 fake http_client（依赖注入），不发真实网络请求
- 网易云接口变更风险：所有 HTTP 调用捕获异常，返回空/None，不让插件崩溃
"""

from __future__ import annotations

import json
import logging
from typing import Any

from omni_music.models import MusicSourceEnum, Song
from omni_music.sources.base import MusicSource

logger = logging.getLogger(__name__)

# 音质 quality → 网易云 level 映射
_QUALITY_LEVEL_MAP: dict[str, str] = {
    "standard": "standard",
    "higher": "higher",
    "exhigh": "exhigh",
    "lossless": "lossless",
    "hires": "hires",
}

# 扫码登录 code → 状态字符串映射
_LOGIN_CODE_MAP: dict[int, str] = {
    801: "waiting",
    802: "scanned",
    803: "confirmed",
    800: "expired",
}


class NeteaseMusicSource(MusicSource):
    """网易云音乐源。

    通过网易云 web API 提供搜索/播放 URL/歌词/详情/扫码登录能力。

    :ivar cookies: 持久化 cookie（从 CookieStore 加载）
    :ivar call_counts: 各方法调用计数（便于测试断言）
    """

    source: MusicSourceEnum = MusicSourceEnum.NETEASE

    def __init__(
        self,
        cookies: dict[str, str] | None = None,
        http_client: Any = None,
        base_url: str = "https://music.163.com",
    ) -> None:
        """构造网易云音乐源。

        :param cookies: 从 CookieStore 加载的持久化 cookie；None 视为空
        :param http_client: HTTP 客户端（测试注入 fake）；None 时惰性创建 ``httpx.Client``
        :param base_url: 网易云 API 基址
        """
        self._cookies: dict[str, str] = dict(cookies) if cookies else {}
        self._http: Any = http_client
        self._base_url: str = base_url
        self.call_counts: dict[str, int] = {
            "search": 0,
            "get_song_url": 0,
            "get_lyrics": 0,
            "get_song_detail": 0,
            "login_qr": 0,
            "check_login_status": 0,
        }

    def _get_http(self) -> Any:
        """返回 HTTP 客户端；``http_client`` 为 None 时惰性创建 ``httpx.Client``。

        :raises RuntimeError: ``httpx`` 未安装时抛出（调用方按需捕获或上抛）
        """
        if self._http is not None:
            return self._http
        try:
            from httpx import Client
        except ImportError as exc:
            raise RuntimeError(f"httpx 未安装: {exc}")
        self._http = Client()
        return self._http

    def _parse_song(self, raw: dict[str, Any]) -> Song:
        """把网易云 API 返回的歌曲 dict 映射为 :class:`Song`。

        :param raw: 网易云 API 的单曲 dict（含 id/name/ar/al/dt 字段）
        :return: :class:`Song` 实例
        """
        ar_list = raw.get("ar") or []
        artists = [ar.get("name", "") for ar in ar_list if ar.get("name")]
        al = raw.get("al") or {}
        return Song(
            id=str(raw.get("id", "")),
            name=raw.get("name", ""),
            source=MusicSourceEnum.NETEASE,
            artists=artists,
            album=al.get("name"),
            duration_s=(raw.get("dt") or 0) // 1000,
            cover_url=al.get("picUrl"),
        )

    def search(self, keyword: str, limit: int = 20) -> list[Song]:
        """按关键词搜索歌曲。

        :param keyword: 搜索关键词（空字符串返回 []）
        :param limit: 返回上限
        :return: 匹配的 :class:`Song` 列表；异常时返回 []
        """
        self.call_counts["search"] += 1
        if not keyword:
            return []
        try:
            http = self._get_http()
            resp = http.post(
                f"{self._base_url}/api/cloudsearch/pc",
                data={"s": keyword, "type": 1, "limit": limit},
                cookies=self._cookies,
            )
            resp.raise_for_status()
            data = resp.json()
        except RuntimeError:
            # httpx 未安装：降级返回空列表
            return []
        except Exception as exc:  # noqa: BLE001 - 接口变更/网络异常统一兜底
            logger.warning("网易云搜索失败: %s", exc)
            return []
        songs_data = (data.get("result") or {}).get("songs") or []
        return [self._parse_song(s) for s in songs_data]

    def get_song_url(self, song_id: str, quality: str = "standard") -> str | None:
        """获取可播放 URL。

        :param song_id: 歌曲 ID
        :param quality: 音质（standard/higher/exhigh/lossless/hires）
        :return: 可播放 URL；VIP 无权限或异常时返回 None
        """
        self.call_counts["get_song_url"] += 1
        level = _QUALITY_LEVEL_MAP.get(quality, "standard")
        try:
            http = self._get_http()
            resp = http.post(
                f"{self._base_url}/api/song/enhance/player/url/v1",
                data={"ids": json.dumps([song_id]), "level": level},
                cookies=self._cookies,
            )
            resp.raise_for_status()
            data = resp.json()
        except RuntimeError:
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("网易云获取播放URL失败: %s", exc)
            return None
        data_list = data.get("data") or []
        if not data_list:
            return None
        url = data_list[0].get("url")
        # VIP 曲目 url 为 null —— 不破解，直接返回 None
        return url if isinstance(url, str) and url else None

    def get_lyrics(self, song_id: str) -> str | None:
        """获取歌词文本（LRC 格式）。

        :param song_id: 歌曲 ID
        :return: LRC 歌词字符串；无歌词或异常时返回 None
        """
        self.call_counts["get_lyrics"] += 1
        try:
            http = self._get_http()
            resp = http.post(
                f"{self._base_url}/api/song/lyric",
                data={"id": song_id},
                cookies=self._cookies,
            )
            resp.raise_for_status()
            data = resp.json()
        except RuntimeError:
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("网易云获取歌词失败: %s", exc)
            return None
        lrc = data.get("lrc") or {}
        lyric = lrc.get("lyric")
        return lyric if isinstance(lyric, str) and lyric else None

    def get_song_detail(self, song_id: str) -> Song | None:
        """获取歌曲详情。

        :param song_id: 歌曲 ID
        :return: :class:`Song` 实例；不存在或异常时返回 None
        """
        self.call_counts["get_song_detail"] += 1
        try:
            http = self._get_http()
            resp = http.post(
                f"{self._base_url}/api/v3/song/detail",
                data={"c": json.dumps([{"id": song_id}])},
                cookies=self._cookies,
            )
            resp.raise_for_status()
            data = resp.json()
        except RuntimeError:
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("网易云获取详情失败: %s", exc)
            return None
        songs = data.get("songs") or []
        if not songs:
            return None
        return self._parse_song(songs[0])

    def login_qr(self) -> dict[str, str]:
        """发起扫码登录，返回二维码 key 与 URL。

        :return: dict 含 ``key``（轮询用）与 ``qr_url``（二维码图片 URL）
        :raises RuntimeError: ``httpx`` 未安装或网络异常时抛出（上层捕获转 E_BACKEND_UNAVAILABLE）
        """
        self.call_counts["login_qr"] += 1
        # _get_http 在 try 外调用：httpx 缺失时直接抛 RuntimeError("httpx 未安装")
        http = self._get_http()
        try:
            resp = http.post(
                f"{self._base_url}/api/login/qrcode/unikey",
                data={},
                cookies=self._cookies,
            )
            resp.raise_for_status()
            unikey = (resp.json() or {}).get("unikey", "")
            resp2 = http.post(
                f"{self._base_url}/api/login/qrcode/client/login",
                data={"key": unikey},
                cookies=self._cookies,
            )
            resp2.raise_for_status()
            qr_url = (resp2.json() or {}).get("url", "")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"login_qr 失败: {exc}")
        return {"key": unikey, "qr_url": qr_url}

    def check_login_status(self, key: str) -> str:
        """轮询扫码登录状态。

        :param key: :meth:`login_qr` 返回的 key
        :return: ``waiting`` / ``scanned`` / ``confirmed`` / ``expired``；异常时返回 ``waiting``
        """
        self.call_counts["check_login_status"] += 1
        try:
            http = self._get_http()
            resp = http.post(
                f"{self._base_url}/api/login/qrcode/client/login",
                data={"key": key},
                cookies=self._cookies,
            )
            resp.raise_for_status()
            data = resp.json()
        except RuntimeError:
            # httpx 未安装：返回 waiting（不丢失流程，由 QRLoginFlow timeout 兜底）
            return "waiting"
        except Exception as exc:  # noqa: BLE001
            logger.warning("网易云查询登录状态失败: %s", exc)
            return "waiting"
        code = data.get("code")
        return _LOGIN_CODE_MAP.get(code, "waiting")

    def get_cookies_on_confirmed(self) -> dict[str, str] | None:
        """confirmed 时返回当前 cookie 供 :class:`QRLoginFlow` 保存。

        :return: cookie dict（无 cookie 时返回空 dict）
        """
        return dict(self._cookies) if self._cookies else {}
