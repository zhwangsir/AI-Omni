"""QQ音乐源（QQMusicSource）TDD 测试（M17.7）。

测试先行（red → green）。所有用例注入 FakeHttpClient 返回固定 JSON，
不发真实网络请求、不下载模型、不依赖音频硬件。

覆盖：
- search 字段映射 / 空 keyword / 异常路径
- get_song_url 成功 / VIP 无权限 / 异常
- get_lyrics 成功 / 无歌词
- get_song_detail 成功 / 不存在
- login_qr 返回 key + qr_url
- check_login_status code 映射（0/1/2/-1 参数化）
- get_cookies_on_confirmed 返回 dict
- httpx 缺失时降级返回 []（monkeypatch sys.modules）
- quality → quality_code 映射（4 档参数化）
- Song.source == MusicSourceEnum.QQMUSIC
- cookie 持久化并在请求中携带
- 调用计数器递增
- 惰性导入 httpx 成功路径（stub 模块覆盖 httpx.Client 分支）

合规说明（D17.4）：仅个人学习用途，不破解付费内容；VIP 曲目返回 None。
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from omni_music.models import MusicSourceEnum, Song
from omni_music.sources.qqmusic import QQMusicSource


# ---------------------------------------------------------------------------
# Fake HTTP 基础设施
# ---------------------------------------------------------------------------


class _FakeResponse:
    """模拟 httpx.Response：只暴露 .json() 与 .status_code。"""

    def __init__(self, json_data: Any) -> None:
        self._json = json_data
        self.status_code = 200

    def json(self) -> Any:
        return self._json


class FakeHttpClient:
    """按预置响应队列返回的 HTTP 客户端。

    每次调用 ``get`` 记录 url/params/cookies 到 ``calls``，
    便于断言请求参数（如 quality_code 映射）。
    """

    def __init__(self, responses: list[Any] | None = None) -> None:
        """预置响应队列；元素可为 dict（json body）或 Exception 实例（raise）。"""
        self._responses: list[Any] = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def get(
        self,
        url: str,
        params: dict | None = None,
        cookies: dict | None = None,
    ) -> _FakeResponse:
        """记录本次调用并返回队列中下一个响应；若响应为 Exception 则抛出。"""
        self.calls.append(
            {
                "url": url,
                "params": dict(params or {}),
                "cookies": cookies,
            }
        )
        if not self._responses:
            raise RuntimeError("FakeHttpClient: 响应队列已耗尽")
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return _FakeResponse(resp)

    @property
    def last_call(self) -> dict[str, Any] | None:
        """最后一次调用的 url/params/cookies。"""
        return self.calls[-1] if self.calls else None


# ---------------------------------------------------------------------------
# 测试用固定响应数据
# ---------------------------------------------------------------------------


SEARCH_RESPONSE_OK: dict = {
    "data": {
        "song": {
            "list": [
                {
                    "mid": "001abc",
                    "name": "晴天",
                    "singer": [{"name": "周杰伦"}, {"name": "蔡依林"}],
                    "album": {"name": "叶惠美", "mid": "002xyz"},
                    "interval": 269,
                },
                {
                    "mid": "003def",
                    "name": "七里香",
                    "singer": [{"name": "周杰伦"}],
                    "album": {"name": "七里香", "mid": "004uvw"},
                    "interval": 299,
                },
            ]
        }
    }
}

SONG_DETAIL_RESPONSE_OK: dict = {
    "data": {
        "info": {
            "mid": "001abc",
            "name": "晴天",
            "singer": [{"name": "周杰伦"}],
            "album": {"name": "叶惠美", "mid": "002xyz"},
            "interval": 269,
        }
    }
}

COVER_URL_FOR = "https://y.gtimg.cn/music/photo_new/T002R300x300M000{mid}.jpg"


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_returns_songs_with_field_mapping(self) -> None:
        """search 成功返回 Song 列表，字段正确映射（mid→id/singer[].name→artists/album.name/interval→duration_s）。"""
        client = FakeHttpClient([SEARCH_RESPONSE_OK])
        src = QQMusicSource(http_client=client)
        results = src.search("晴天", limit=5)
        assert len(results) == 2
        first = results[0]
        assert isinstance(first, Song)
        # mid → id
        assert first.id == "001abc"
        # name → name
        assert first.name == "晴天"
        # singer[].name → artists
        assert first.artists == ["周杰伦", "蔡依林"]
        # album.name → album
        assert first.album == "叶惠美"
        # interval → duration_s
        assert first.duration_s == 269
        # album.mid → 拼封面 URL
        assert first.cover_url == COVER_URL_FOR.format(mid="002xyz")
        # source 枚举
        assert first.source is MusicSourceEnum.QQMUSIC

    def test_search_empty_keyword_returns_empty(self) -> None:
        """空 keyword 直接返回 []，不发起请求。"""
        client = FakeHttpClient([])
        src = QQMusicSource(http_client=client)
        assert src.search("", limit=5) == []
        # 队列未被消费
        assert len(client.calls) == 0

    def test_search_api_exception_returns_empty(self) -> None:
        """接口异常（FakeHttpClient 抛 RuntimeError）时 search 返回 []。"""
        client = FakeHttpClient([RuntimeError("network down")])
        src = QQMusicSource(http_client=client)
        assert src.search("周杰伦", limit=5) == []

    def test_search_malformed_response_returns_empty(self) -> None:
        """响应缺少 data.song.list 字段时返回 []。"""
        client = FakeHttpClient([{"unexpected": "shape"}])
        src = QQMusicSource(http_client=client)
        assert src.search("周杰伦", limit=5) == []

    def test_search_increments_call_count(self) -> None:
        """每次 search 调用累加 call_count（即便失败也累加）。"""
        client = FakeHttpClient([SEARCH_RESPONSE_OK, RuntimeError("boom")])
        src = QQMusicSource(http_client=client)
        assert src.call_count == 0
        src.search("晴天", limit=5)
        assert src.call_count == 1
        src.search("七里香", limit=5)
        assert src.call_count == 2


# ---------------------------------------------------------------------------
# get_song_url
# ---------------------------------------------------------------------------


class TestGetSongUrl:
    def test_get_song_url_success(self) -> None:
        """成功返回可播放 URL 字符串。"""
        client = FakeHttpClient([{"data": {"url": "http://example.com/play.mp3"}}])
        src = QQMusicSource(http_client=client)
        url = src.get_song_url("001abc", quality="standard")
        assert url == "http://example.com/play.mp3"

    def test_get_song_url_missing_url_field_returns_none(self) -> None:
        """响应缺少 data.url 字段（KeyError）时返回 None。"""
        client = FakeHttpClient([{"data": {}}])
        src = QQMusicSource(http_client=client)
        assert src.get_song_url("001abc") is None

    def test_get_song_url_data_not_dict_returns_none(self) -> None:
        """data 不是 dict（TypeError）时返回 None。"""
        client = FakeHttpClient([{"data": None}])
        src = QQMusicSource(http_client=client)
        assert src.get_song_url("001abc") is None

    def test_get_song_url_vip_no_permission_returns_none(self) -> None:
        """VIP 无权限时 url 字段为空字符串，返回 None（合规：不破解）。"""
        client = FakeHttpClient([{"data": {"url": ""}}])
        src = QQMusicSource(http_client=client)
        assert src.get_song_url("vip_song", quality="lossless") is None

    def test_get_song_url_exception_returns_none(self) -> None:
        """接口异常时返回 None。"""
        client = FakeHttpClient([RuntimeError("network error")])
        src = QQMusicSource(http_client=client)
        assert src.get_song_url("001abc") is None

    @pytest.mark.parametrize(
        "quality,expected_code",
        [
            ("standard", 10),
            ("exhigh", 24),
            ("lossless", 29),
            ("hires", 30),
        ],
    )
    def test_get_song_url_quality_mapping(
        self, quality: str, expected_code: int
    ) -> None:
        """quality 字符串映射到 QQ音乐 quality_code（standard→10/exhigh→24/lossless→29/hires→30）。"""
        client = FakeHttpClient([{"data": {"url": "http://x/y.mp3"}}])
        src = QQMusicSource(http_client=client)
        src.get_song_url("001abc", quality=quality)
        assert client.last_call is not None
        assert client.last_call["params"]["quality"] == expected_code

    def test_get_song_url_unknown_quality_falls_back_to_standard(self) -> None:
        """未知 quality 字符串回退为 standard（code 10）。"""
        client = FakeHttpClient([{"data": {"url": "http://x/y.mp3"}}])
        src = QQMusicSource(http_client=client)
        src.get_song_url("001abc", quality="unknown_quality")
        assert client.last_call["params"]["quality"] == 10


# ---------------------------------------------------------------------------
# get_lyrics
# ---------------------------------------------------------------------------


class TestGetLyrics:
    def test_get_lyrics_success(self) -> None:
        """成功返回歌词文本。"""
        client = FakeHttpClient([{"data": {"lyric": "[00:00]故事的小黄花"}}])
        src = QQMusicSource(http_client=client)
        lyric = src.get_lyrics("001abc")
        assert lyric == "[00:00]故事的小黄花"

    def test_get_lyrics_empty_returns_none(self) -> None:
        """lyric 字段为空字符串时返回 None。"""
        client = FakeHttpClient([{"data": {"lyric": ""}}])
        src = QQMusicSource(http_client=client)
        assert src.get_lyrics("001abc") is None

    def test_get_lyrics_exception_returns_none(self) -> None:
        """接口异常时返回 None。"""
        client = FakeHttpClient([RuntimeError("net err")])
        src = QQMusicSource(http_client=client)
        assert src.get_lyrics("001abc") is None

    def test_get_lyrics_missing_lyric_field_returns_none(self) -> None:
        """响应缺少 data.lyric 字段（KeyError）时返回 None。"""
        client = FakeHttpClient([{"data": {}}])
        src = QQMusicSource(http_client=client)
        assert src.get_lyrics("001abc") is None

    def test_get_lyrics_data_not_dict_returns_none(self) -> None:
        """data 不是 dict（TypeError）时返回 None。"""
        client = FakeHttpClient([{"data": None}])
        src = QQMusicSource(http_client=client)
        assert src.get_lyrics("001abc") is None


# ---------------------------------------------------------------------------
# get_song_detail
# ---------------------------------------------------------------------------


class TestGetSongDetail:
    def test_get_song_detail_success(self) -> None:
        """成功返回 Song 详情。"""
        client = FakeHttpClient([SONG_DETAIL_RESPONSE_OK])
        src = QQMusicSource(http_client=client)
        song = src.get_song_detail("001abc")
        assert song is not None
        assert isinstance(song, Song)
        assert song.id == "001abc"
        assert song.name == "晴天"
        assert song.artists == ["周杰伦"]
        assert song.album == "叶惠美"
        assert song.duration_s == 269
        assert song.source is MusicSourceEnum.QQMUSIC

    def test_get_song_detail_not_found_returns_none(self) -> None:
        """info 为 None 时返回 None。"""
        client = FakeHttpClient([{"data": {"info": None}}])
        src = QQMusicSource(http_client=client)
        assert src.get_song_detail("ghost") is None

    def test_get_song_detail_exception_returns_none(self) -> None:
        """接口异常时返回 None。"""
        client = FakeHttpClient([RuntimeError("boom")])
        src = QQMusicSource(http_client=client)
        assert src.get_song_detail("001abc") is None

    def test_get_song_detail_missing_info_field_returns_none(self) -> None:
        """响应缺少 data.info 字段（KeyError）时返回 None。"""
        client = FakeHttpClient([{"data": {}}])
        src = QQMusicSource(http_client=client)
        assert src.get_song_detail("001abc") is None

    def test_get_song_detail_data_not_dict_returns_none(self) -> None:
        """data 不是 dict（TypeError）时返回 None。"""
        client = FakeHttpClient([{"data": None}])
        src = QQMusicSource(http_client=client)
        assert src.get_song_detail("001abc") is None


# ---------------------------------------------------------------------------
# login_qr / check_login_status / get_cookies_on_confirmed
# ---------------------------------------------------------------------------


class TestLoginQR:
    def test_login_qr_returns_key_and_qr_url(self) -> None:
        """login_qr 返回 dict 含 key 与 qr_url。"""
        client = FakeHttpClient(
            [{"data": {"key": "qr_key_1", "qr_url": "https://qq.com/qr.png"}}]
        )
        src = QQMusicSource(http_client=client)
        result = src.login_qr()
        assert result == {"key": "qr_key_1", "qr_url": "https://qq.com/qr.png"}

    def test_login_qr_missing_httpx_raises_runtime_error(self) -> None:
        """无 http_client 且 httpx 不可用时，login_qr 抛 RuntimeError（由上层捕获）。"""
        # 用一个永远返回 None 的 _get_client 替身，模拟 httpx 缺失
        src = QQMusicSource(http_client=None)
        # 强制 _get_client 返回 None（模拟 httpx ImportError）
        src._http_client = None  # type: ignore[assignment]
        # monkeypatch _get_client 直接返回 None
        src._get_client = lambda: None  # type: ignore[assignment]
        with pytest.raises(RuntimeError):
            src.login_qr()

    def test_login_qr_malformed_response_raises_runtime_error(self) -> None:
        """响应缺字段时抛 RuntimeError（不静默返回伪数据）。"""
        client = FakeHttpClient([{"data": {}}])  # 缺 key/qr_url
        src = QQMusicSource(http_client=client)
        with pytest.raises(RuntimeError):
            src.login_qr()


class TestCheckLoginStatus:
    @pytest.mark.parametrize(
        "code,expected",
        [
            (0, "waiting"),
            (1, "scanned"),
            (2, "confirmed"),
            (-1, "expired"),
        ],
    )
    def test_check_login_status_code_mapping(
        self, code: int, expected: str
    ) -> None:
        """code → status 映射：0→waiting / 1→scanned / 2→confirmed / -1→expired。"""
        client = FakeHttpClient([{"data": {"code": code}}])
        src = QQMusicSource(http_client=client)
        assert src.check_login_status("any_key") == expected

    def test_check_login_status_unknown_code_falls_back_to_waiting(self) -> None:
        """未知 code 回退为 waiting。"""
        client = FakeHttpClient([{"data": {"code": 999}}])
        src = QQMusicSource(http_client=client)
        assert src.check_login_status("any_key") == "waiting"

    def test_check_login_status_exception_returns_waiting(self) -> None:
        """接口异常时返回 waiting（不阻塞轮询循环）。"""
        client = FakeHttpClient([RuntimeError("net")])
        src = QQMusicSource(http_client=client)
        assert src.check_login_status("any_key") == "waiting"

    def test_check_login_status_missing_code_field_returns_waiting(self) -> None:
        """响应缺少 data.code 字段（KeyError）时返回 waiting。"""
        client = FakeHttpClient([{"data": {}}])
        src = QQMusicSource(http_client=client)
        assert src.check_login_status("any_key") == "waiting"

    def test_check_login_status_code_not_int_returns_waiting(self) -> None:
        """code 字段非整型（ValueError）时返回 waiting。"""
        client = FakeHttpClient([{"data": {"code": "not_a_number"}}])
        src = QQMusicSource(http_client=client)
        assert src.check_login_status("any_key") == "waiting"

    def test_check_login_status_data_not_dict_returns_waiting(self) -> None:
        """data 不是 dict（TypeError）时返回 waiting。"""
        client = FakeHttpClient([{"data": None}])
        src = QQMusicSource(http_client=client)
        assert src.check_login_status("any_key") == "waiting"


class TestGetCookiesOnConfirmed:
    def test_returns_cookies_when_injected(self) -> None:
        """构造时注入 cookies，confirmed 时返回该 dict 的副本。"""
        cookies = {"uin": "12345", "qqmusic_key": "abc"}
        src = QQMusicSource(cookies=cookies, http_client=FakeHttpClient([]))
        result = src.get_cookies_on_confirmed()
        assert result == cookies
        # 返回副本，修改不影响内部状态
        result["uin"] = "modified"
        assert src.get_cookies_on_confirmed()["uin"] == "12345"

    def test_returns_none_when_no_cookies(self) -> None:
        """未注入 cookies 时返回 None。"""
        src = QQMusicSource(http_client=FakeHttpClient([]))
        assert src.get_cookies_on_confirmed() is None


# ---------------------------------------------------------------------------
# 合规 / 惰性导入 / Cookie 携带 / 计数器
# ---------------------------------------------------------------------------


class TestSourceEnumAndCompliance:
    def test_source_attribute_is_qqmusic(self) -> None:
        """类属性 source == MusicSourceEnum.QQMUSIC。"""
        src = QQMusicSource(http_client=FakeHttpClient([]))
        assert src.source is MusicSourceEnum.QQMUSIC

    def test_song_source_field_is_qqmusic(self) -> None:
        """search 返回的 Song.source 字段为 QQMUSIC。"""
        client = FakeHttpClient([SEARCH_RESPONSE_OK])
        src = QQMusicSource(http_client=client)
        results = src.search("晴天", limit=5)
        assert results
        assert all(s.source is MusicSourceEnum.QQMUSIC for s in results)


class TestCookiePropagation:
    def test_cookies_passed_to_request(self) -> None:
        """构造时注入 cookies 后，请求 get 调用应携带该 cookies。"""
        cookies = {"uin": "1", "key": "k"}
        client = FakeHttpClient([SEARCH_RESPONSE_OK])
        src = QQMusicSource(cookies=cookies, http_client=client)
        src.search("晴天", limit=5)
        assert client.last_call is not None
        assert client.last_call["cookies"] == cookies

    def test_no_cookies_passes_none(self) -> None:
        """未注入 cookies 时请求 cookies 参数为 None。"""
        client = FakeHttpClient([SEARCH_RESPONSE_OK])
        src = QQMusicSource(http_client=client)
        src.search("晴天", limit=5)
        assert client.last_call is not None
        assert client.last_call["cookies"] is None


class TestCallCounter:
    def test_counter_increments_across_methods(self) -> None:
        """call_count 在跨方法调用时累加。"""
        client = FakeHttpClient(
            [
                SEARCH_RESPONSE_OK,
                {"data": {"url": "http://x/y.mp3"}},
                {"data": {"lyric": "lrc"}},
            ]
        )
        src = QQMusicSource(http_client=client)
        assert src.call_count == 0
        src.search("晴天", limit=5)
        src.get_song_url("001abc")
        src.get_lyrics("001abc")
        assert src.call_count == 3


class TestHttpxMissingFallback:
    def test_search_returns_empty_when_httpx_missing(self, monkeypatch) -> None:
        """httpx 不可用时 search 返回 []，不抛 ImportError（CLAUDE.md §三 降级要求）。"""
        # sys.modules["httpx"] = None 会让 `import httpx` 抛 ImportError
        monkeypatch.setitem(sys.modules, "httpx", None)
        src = QQMusicSource(http_client=None)
        assert src.search("周杰伦", limit=5) == []

    def test_get_song_url_returns_none_when_httpx_missing(self, monkeypatch) -> None:
        """httpx 不可用时 get_song_url 返回 None。"""
        monkeypatch.setitem(sys.modules, "httpx", None)
        src = QQMusicSource(http_client=None)
        assert src.get_song_url("001abc") is None

    def test_get_lyrics_returns_none_when_httpx_missing(self, monkeypatch) -> None:
        """httpx 不可用时 get_lyrics 返回 None。"""
        monkeypatch.setitem(sys.modules, "httpx", None)
        src = QQMusicSource(http_client=None)
        assert src.get_lyrics("001abc") is None

    def test_get_song_detail_returns_none_when_httpx_missing(self, monkeypatch) -> None:
        """httpx 不可用时 get_song_detail 返回 None。"""
        monkeypatch.setitem(sys.modules, "httpx", None)
        src = QQMusicSource(http_client=None)
        assert src.get_song_detail("001abc") is None


class TestLazyImportHttpxHappyPath:
    def test_lazy_import_creates_httpx_client_once(self, monkeypatch) -> None:
        """http_client=None 且 httpx 可用时，惰性创建 httpx.Client 并复用。"""

        class _FakeClient:
            def __init__(self, timeout: float | None = None, follow_redirects: bool = False) -> None:
                self.timeout = timeout
                self.follow_redirects = follow_redirects

            def get(self, url, params=None, cookies=None) -> _FakeResponse:
                return _FakeResponse(SEARCH_RESPONSE_OK)

        fake_mod = types.ModuleType("httpx")
        fake_mod.Client = _FakeClient  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "httpx", fake_mod)

        src = QQMusicSource(http_client=None)
        client1 = src._get_client()
        assert isinstance(client1, _FakeClient)
        # 复用：第二次调用返回同一实例
        client2 = src._get_client()
        assert client2 is client1
        # 实际请求能跑通
        results = src.search("晴天", limit=5)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# close() / 上下文管理器（M32.24：自有客户端连接池释放）
# ---------------------------------------------------------------------------


def _make_closable_client_cls() -> type:
    """构造带 close()/closed 标记的 fake httpx.Client 类（每测例独立类，隔离 instances）。"""

    class _ClosableFakeClient:
        """模拟 httpx.Client：接受 timeout/follow_redirects，记录 close 调用。"""

        instances: list["_ClosableFakeClient"] = []

        def __init__(
            self, timeout: float | None = None, follow_redirects: bool = False
        ) -> None:
            self.timeout = timeout
            self.follow_redirects = follow_redirects
            self.closed = False
            type(self).instances.append(self)

        def get(self, url, params=None, cookies=None) -> _FakeResponse:
            return _FakeResponse(SEARCH_RESPONSE_OK)

        def close(self) -> None:
            self.closed = True

    return _ClosableFakeClient


def _install_fake_httpx(monkeypatch, client_cls: type) -> None:
    """向 sys.modules 注入 fake httpx 模块（其 Client 为 client_cls）。"""
    fake_mod = types.ModuleType("httpx")
    fake_mod.Client = client_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "httpx", fake_mod)


class TestClose:
    def test_close_closes_owned_client(self, monkeypatch) -> None:
        """未注入 client 时惰性创建的 httpx.Client 为自有，close() 应关闭它。"""
        client_cls = _make_closable_client_cls()
        _install_fake_httpx(monkeypatch, client_cls)
        src = QQMusicSource(http_client=None)
        client = src._get_client()
        src.close()
        assert client.closed is True
        # close 后内部引用清空
        assert src._http_client is None

    def test_close_does_not_close_injected_client(self) -> None:
        """注入的外部 client 非自有，close() 不得调用其 close()（调用方管理生命周期）。"""
        client = FakeHttpClient([])
        # 给注入的 fake 加 close 追踪
        close_calls: list[bool] = []
        client.close = lambda: close_calls.append(True)  # type: ignore[attr-defined]
        src = QQMusicSource(http_client=client)
        src.close()
        assert close_calls == []
        # 注入的 client 引用保持不动
        assert src._http_client is client

    def test_close_idempotent_and_reusable(self, monkeypatch) -> None:
        """close() 幂等（多次调用不报错）；close 后 _get_client() 可重新创建新 client。"""
        client_cls = _make_closable_client_cls()
        _install_fake_httpx(monkeypatch, client_cls)
        src = QQMusicSource(http_client=None)
        first = src._get_client()
        src.close()
        src.close()  # 第二次不报错
        assert first.closed is True
        # 重新创建：返回新实例且未关闭
        second = src._get_client()
        assert second is not first
        assert isinstance(second, client_cls)
        assert second.closed is False

    def test_context_manager_closes(self, monkeypatch) -> None:
        """with 语句退出时自动 close 自有客户端。"""
        client_cls = _make_closable_client_cls()
        _install_fake_httpx(monkeypatch, client_cls)
        with QQMusicSource(http_client=None) as src:
            client = src._get_client()
            assert client.closed is False
        assert client.closed is True
        assert src._http_client is None


class TestCustomBaseUrl:
    def test_custom_base_url_used_in_request(self) -> None:
        """自定义 base_url 拼接到请求 URL。"""
        client = FakeHttpClient([SEARCH_RESPONSE_OK])
        src = QQMusicSource(
            http_client=client, base_url="https://example.qq.com"
        )
        src.search("晴天", limit=5)
        assert client.last_call is not None
        assert client.last_call["url"] == "https://example.qq.com/cgi-bin/musicu.fcg"
