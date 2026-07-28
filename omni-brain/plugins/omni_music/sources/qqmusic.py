"""QQ音乐源实现（M17.7）。

通过 QQ 音乐公开 ``/cgi-bin/musicu.fcg`` 接口提供搜索 / 播放 URL / 歌词 /
详情 / 扫码登录能力，继承 :class:`MusicSource` 抽象基类。

合规说明（D17.4）：
- 本模块仅用于**个人学习用途**，仅消费免费/试听接口；
- VIP / 付费内容一律返回 ``None``，**不破解、不绕过 DRM、不录制**；
- 不携带任何反向工程或加密破解逻辑。

重型依赖惰性导入（CLAUDE.md §三）：``httpx`` 在方法内 import，模块顶层
禁止 import httpx；``ImportError`` 时各方法降级返回空值，login_qr 抛
RuntimeError 由上层捕获。测试通过依赖注入 ``http_client`` 实现零网络。
"""

from __future__ import annotations

from typing import Any

from omni_music.models import MusicSourceEnum, Song
from omni_music.sources.base import MusicSource

# ---------------------------------------------------------------------------
# 常量映射
# ---------------------------------------------------------------------------

#: quality 字符串 → QQ音乐 quality_code（与 ``musicu.fcg`` ``cmd=play`` 对齐）
QUALITY_CODE_MAP: dict[str, int] = {
    "standard": 10,   # 标准音质
    "exhigh": 24,     # HQ 高品
    "lossless": 29,    # SQ 无损
    "hires": 30,      # Hi-Res
}

#: 扫码登录 code → 状态字符串
LOGIN_CODE_TO_STATUS: dict[int, str] = {
    0: "waiting",
    1: "scanned",
    2: "confirmed",
    -1: "expired",
}

#: 专辑封面 URL 模板（album.mid 拼接）
COVER_URL_TEMPLATE: str = (
    "https://y.gtimg.cn/music/photo_new/T002R300x300M000{mid}.jpg"
)

#: 默认接口 base URL
DEFAULT_BASE_URL: str = "https://u.y.qq.com"

#: 统一接口路径
API_PATH: str = "/cgi-bin/musicu.fcg"


class QQMusicSource(MusicSource):
    """QQ音乐源（D17.4 合规：仅免费/试听，不破解付费内容）。

    通过依赖注入 ``http_client`` 解耦网络层，便于测试零依赖。
    所有 VIP / 付费曲目返回 ``None``；仅供个人学习用途。

    用法::

        src = QQMusicSource()
        songs = src.search("晴天", limit=10)
        url = src.get_song_url(songs[0].id)  # VIP 曲目可能返回 None

    测试用法（注入 fake）::

        fake = FakeHttpClient([{"data": {"url": "http://x/y.mp3"}}])
        src = QQMusicSource(http_client=fake)
        assert src.get_song_url("001abc") == "http://x/y.mp3"
    """

    #: 类属性：本源对应的 MusicSourceEnum
    source: MusicSourceEnum = MusicSourceEnum.QQMUSIC

    def __init__(
        self,
        cookies: dict | None = None,
        http_client: Any = None,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        """构造 QQ音乐源实例。

        :param cookies: 持久化 cookies（扫码登录确认后注入）；可选
        :param http_client: HTTP 客户端，duck-typed 需实现
            ``get(url, params=, cookies=)`` 并返回带 ``.json()`` 的响应。
            ``None`` 时惰性 import httpx；httpx 不可用时各方法降级。
        :param base_url: 接口 base URL，默认 ``https://u.y.qq.com``
        """
        self._cookies: dict[str, str] = dict(cookies) if cookies else {}
        self._http_client: Any = http_client
        self._base_url: str = base_url.rstrip("/")
        #: 调用计数器（测试断言用），每次发请求累加
        self.call_count: int = 0

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        """惰性获取 HTTP 客户端。

        优先返回构造时注入的 ``http_client``；否则惰性 ``import httpx``
        并构造 ``httpx.Client``。``httpx`` 缺失时返回 ``None``，由
        :meth:`_request` 降级处理。

        :return: HTTP 客户端实例或 ``None``
        """
        if self._http_client is not None:
            return self._http_client
        try:
            import httpx  # type: ignore[import-not-found]
        except ImportError:
            return None
        client = httpx.Client(timeout=10.0, follow_redirects=True)
        # 缓存以便后续复用
        self._http_client = client
        return client

    def _request(self, params: dict) -> dict | None:
        """统一请求封装；任何异常返回 ``None``。

        :param params: 请求 query 参数
        :return: 解析后的 JSON dict；失败返回 ``None``
        """
        self.call_count += 1
        try:
            client = self._get_client()
            if client is None:
                return None
            url = f"{self._base_url}{API_PATH}"
            resp = client.get(
                url,
                params=params,
                cookies=self._cookies or None,
            )
            return resp.json()
        except Exception:
            return None

    @staticmethod
    def _parse_song(item: dict) -> Song:
        """把 QQ音乐响应中的 song item 映射为 :class:`Song`。

        :param item: 单个歌曲 dict（``mid`` / ``name`` / ``singer`` / ``album`` / ``interval``）
        :return: :class:`Song` 实例，``source`` 固定为 ``QQMUSIC``
        """
        mid = str(item.get("mid") or item.get("songmid") or "")
        name = str(item.get("name") or item.get("songname") or "")
        singers = item.get("singer") or []
        artists = [str(s.get("name", "")) for s in singers if s.get("name")]
        album = item.get("album") or {}
        album_name = album.get("name")
        interval = item.get("interval") or 0
        cover_mid = album.get("mid") or ""
        cover_url = (
            COVER_URL_TEMPLATE.format(mid=cover_mid) if cover_mid else None
        )
        return Song(
            id=mid,
            name=name,
            artists=artists,
            album=album_name,
            duration_s=int(interval) if interval else 0,
            cover_url=cover_url,
            source=MusicSourceEnum.QQMUSIC,
        )

    # ------------------------------------------------------------------
    # 抽象方法实现
    # ------------------------------------------------------------------

    def search(self, keyword: str, limit: int = 20) -> list[Song]:
        """按关键词搜索歌曲。

        :param keyword: 搜索关键词（歌曲名/歌手名/专辑名）；空字符串直接返回 ``[]``
        :param limit: 返回上限
        :return: :class:`Song` 列表；接口异常或 httpx 缺失返回 ``[]``
        """
        if not keyword:
            return []
        params = {
            "cmd": "search",
            "keyword": keyword,
            "page": 1,
            "limit": limit,
        }
        data = self._request(params)
        if not data:
            return []
        try:
            song_list = data["data"]["song"]["list"]
        except (KeyError, TypeError):
            return []
        return [self._parse_song(item) for item in song_list]

    def get_song_url(self, song_id: str, quality: str = "standard") -> str | None:
        """获取可播放 URL。

        VIP 无权限或返回空字符串时返回 ``None``（合规：不破解付费内容）。

        :param song_id: 歌曲 mid
        :param quality: 音质，``standard`` / ``exhigh`` / ``lossless`` / ``hires``
        :return: 可播放 URL 字符串；不可用返回 ``None``
        """
        quality_code = QUALITY_CODE_MAP.get(quality, QUALITY_CODE_MAP["standard"])
        params = {
            "cmd": "play",
            "songmid": song_id,
            "quality": quality_code,
        }
        data = self._request(params)
        if not data:
            return None
        try:
            url = data["data"]["url"]
        except (KeyError, TypeError):
            return None
        if not url:
            return None
        return str(url)

    def get_lyrics(self, song_id: str) -> str | None:
        """获取歌词文本。

        :param song_id: 歌曲 mid
        :return: 歌词字符串（LRC 或纯文本）；无歌词或异常返回 ``None``
        """
        params = {"cmd": "lyric", "songmid": song_id}
        data = self._request(params)
        if not data:
            return None
        try:
            lyric = data["data"]["lyric"]
        except (KeyError, TypeError):
            return None
        if not lyric:
            return None
        return str(lyric)

    def get_song_detail(self, song_id: str) -> Song | None:
        """获取歌曲详情。

        :param song_id: 歌曲 mid
        :return: :class:`Song` 实例；不存在或异常返回 ``None``
        """
        params = {"cmd": "songinfo", "songmid": song_id}
        data = self._request(params)
        if not data:
            return None
        try:
            info = data["data"]["info"]
        except (KeyError, TypeError):
            return None
        if not info:
            return None
        return self._parse_song(info)

    def login_qr(self) -> dict[str, str]:
        """发起扫码登录，返回二维码 key 与 URL。

        :return: dict 含 ``key``（轮询用）与 ``qr_url``（二维码图片 URL）
        :raises RuntimeError: httpx 不可用或响应缺字段时抛出（由上层捕获）
        """
        params = {"cmd": "qq_login_qr"}
        data = self._request(params)
        if not data:
            raise RuntimeError(
                "QQ音乐登录二维码获取失败：httpx 不可用或网络异常"
            )
        try:
            inner = data["data"]
            key = inner["key"]
            qr_url = inner["qr_url"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                f"QQ音乐登录响应缺少 key/qr_url 字段: {exc}"
            ) from exc
        return {"key": str(key), "qr_url": str(qr_url)}

    def check_login_status(self, key: str) -> str:
        """轮询扫码登录状态。

        code 映射：``0`` → waiting, ``1`` → scanned, ``2`` → confirmed,
        ``-1`` → expired。

        :param key: :meth:`login_qr` 返回的 key
        :return: 状态字符串（``waiting`` / ``scanned`` / ``confirmed`` / ``expired``）；
            接口异常时返回 ``waiting``（不阻塞轮询循环）
        """
        params = {"cmd": "qq_login_check", "key": key}
        data = self._request(params)
        if not data:
            return "waiting"
        try:
            code = int(data["data"]["code"])
        except (KeyError, TypeError, ValueError):
            return "waiting"
        return LOGIN_CODE_TO_STATUS.get(code, "waiting")

    def get_cookies_on_confirmed(self) -> dict[str, str] | None:
        """扫码登录 confirmed 后返回 session cookies。

        本实现返回构造时注入的 cookies 副本；未注入 cookies 时返回 ``None``。

        :return: cookies dict 的副本；无 cookies 返回 ``None``
        """
        if not self._cookies:
            return None
        return dict(self._cookies)
