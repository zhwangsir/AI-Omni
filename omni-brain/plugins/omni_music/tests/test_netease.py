"""NeteaseMusicSource 测试（M17.5）。

覆盖：
- search / get_song_url / get_lyrics / get_song_detail 成功与失败路径
- login_qr / check_login_status 状态机
- httpx 惰性导入与缺失降级
- cookie 透传、调用计数、音质映射、source 字段

测试全部使用 FakeHttpClient，不发真实网络请求（CLAUDE.md §三 测试零依赖）。
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from omni_music.models import MusicSourceEnum, Song
from omni_music.sources.netease import NeteaseMusicSource


class _FakeResp:
    """fake HTTP 响应：持有预设 JSON 数据。"""

    def __init__(self, data: Any) -> None:
        self._data = data

    def json(self) -> Any:
        return self._data

    def raise_for_status(self) -> None:
        return None


class FakeHttpClient:
    """fake HTTP client：按 URL 子串匹配返回预设响应，记录所有调用。

    用法::

        fake = FakeHttpClient(responses={"cloudsearch": {...}})
        fake = FakeHttpClient(raise_on_call=ConnectionError("boom"))
    """

    def __init__(
        self,
        responses: dict[str, Any] | None = None,
        *,
        raise_on_call: BaseException | None = None,
    ) -> None:
        self._responses = responses or {}
        self._raise_on_call = raise_on_call
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def post(self, url: str, **kw: Any) -> _FakeResp:
        self.calls.append(("post", url, kw))
        if self._raise_on_call is not None:
            raise self._raise_on_call
        return self._match(url)

    def get(self, url: str, **kw: Any) -> _FakeResp:
        self.calls.append(("get", url, kw))
        if self._raise_on_call is not None:
            raise self._raise_on_call
        return self._match(url)

    def _match(self, url: str) -> _FakeResp:
        for pattern, resp in self._responses.items():
            if pattern in url:
                return _FakeResp(resp)
        return _FakeResp({})


# ---- 固定测试数据（模拟网易云 API 返回结构）----

_NETEASE_SEARCH_RESPONSE = {
    "result": {
        "songs": [
            {
                "id": 28815230,
                "name": "晴天",
                "ar": [{"name": "周杰伦"}],
                "al": {"name": "叶惠美", "picUrl": "https://p1.music.126.net/cover.jpg"},
                "dt": 269000,
            },
            {
                "id": 185809,
                "name": "稻香",
                "ar": [{"name": "周杰伦"}, {"name": "方文山"}],
                "al": {"name": "魔杰座", "picUrl": "https://p1.music.126.net/cover2.jpg"},
                "dt": 223000,
            },
        ]
    }
}

_NETEASE_SONG_URL_RESPONSE = {"data": [{"url": "http://m10.music.126.net/play.mp3"}]}
_NETEASE_SONG_URL_VIP_RESPONSE = {"data": [{"url": None}]}
_NETEASE_LYRICS_RESPONSE = {"lrc": {"lyric": "[00:00]故事的小黄花\n[00:10]从出生那年就飘着"}}
_NETEASE_NO_LYRICS_RESPONSE = {"lrc": {"lyric": None}}
_NETEASE_SONG_DETAIL_RESPONSE = {
    "songs": [
        {
            "id": 28815230,
            "name": "晴天",
            "ar": [{"name": "周杰伦"}],
            "al": {"name": "叶惠美", "picUrl": "https://p1.music.126.net/cover.jpg"},
            "dt": 269000,
        }
    ]
}
_NETEASE_SONG_NOT_FOUND_RESPONSE = {"songs": []}
_NETEASE_UNIKEY_RESPONSE = {"unikey": "test_unikey_abc123"}
_NETEASE_QR_URL_RESPONSE = {"url": "https://music.163.com/qr/test_unikey_abc123"}


class TestNeteaseSearch:
    def test_search_returns_songs(self) -> None:
        """search 成功返回 Song 列表，字段映射正确。"""
        fake = FakeHttpClient(responses={"cloudsearch": _NETEASE_SEARCH_RESPONSE})
        source = NeteaseMusicSource(http_client=fake)
        results = source.search("晴天", limit=10)
        assert len(results) == 2
        song = results[0]
        assert isinstance(song, Song)
        assert song.id == "28815230"
        assert song.name == "晴天"
        assert song.artists == ["周杰伦"]
        assert song.album == "叶惠美"
        assert song.duration_s == 269
        assert song.cover_url == "https://p1.music.126.net/cover.jpg"
        # 第二首多艺人场景
        assert results[1].artists == ["周杰伦", "方文山"]
        assert results[1].duration_s == 223

    def test_search_empty_keyword_returns_empty(self) -> None:
        """空 keyword 返回 []，不发请求。"""
        fake = FakeHttpClient()
        source = NeteaseMusicSource(http_client=fake)
        assert source.search("", limit=10) == []
        assert len(fake.calls) == 0

    def test_search_http_error_returns_empty(self) -> None:
        """search 接口异常返回 []。"""
        fake = FakeHttpClient(raise_on_call=ConnectionError("network down"))
        source = NeteaseMusicSource(http_client=fake)
        assert source.search("晴天") == []

    def test_search_empty_result(self) -> None:
        """search 返回空结果集时返回 []。"""
        fake = FakeHttpClient(responses={"cloudsearch": {"result": {"songs": []}}})
        source = NeteaseMusicSource(http_client=fake)
        assert source.search("不存在的歌") == []


class TestNeteaseGetSongUrl:
    def test_get_song_url_returns_url(self) -> None:
        """get_song_url 成功返回 URL。"""
        fake = FakeHttpClient(responses={"player/url/v1": _NETEASE_SONG_URL_RESPONSE})
        source = NeteaseMusicSource(http_client=fake)
        url = source.get_song_url("28815230")
        assert url == "http://m10.music.126.net/play.mp3"

    def test_get_song_url_vip_returns_none(self) -> None:
        """VIP 曲目 url 为 null 时返回 None（不破解）。"""
        fake = FakeHttpClient(responses={"player/url/v1": _NETEASE_SONG_URL_VIP_RESPONSE})
        source = NeteaseMusicSource(http_client=fake)
        assert source.get_song_url("vip_song_id") is None

    def test_get_song_url_http_error_returns_none(self) -> None:
        """get_song_url 异常返回 None。"""
        fake = FakeHttpClient(raise_on_call=ConnectionError("timeout"))
        source = NeteaseMusicSource(http_client=fake)
        assert source.get_song_url("28815230") is None

    def test_get_song_url_empty_data_returns_none(self) -> None:
        """data 为空列表时返回 None。"""
        fake = FakeHttpClient(responses={"player/url/v1": {"data": []}})
        source = NeteaseMusicSource(http_client=fake)
        assert source.get_song_url("28815230") is None

    def test_get_song_url_quality_maps_to_level(self) -> None:
        """quality 参数映射到 level 字段（断言 fake 收到 level=exhigh）。"""
        fake = FakeHttpClient(responses={"player/url/v1": _NETEASE_SONG_URL_RESPONSE})
        source = NeteaseMusicSource(http_client=fake)
        source.get_song_url("28815230", quality="exhigh")
        assert len(fake.calls) == 1
        _, _, kw = fake.calls[0]
        assert kw["data"]["level"] == "exhigh"

    def test_get_song_url_unknown_quality_defaults_standard(self) -> None:
        """未知 quality 默认 standard。"""
        fake = FakeHttpClient(responses={"player/url/v1": _NETEASE_SONG_URL_RESPONSE})
        source = NeteaseMusicSource(http_client=fake)
        source.get_song_url("28815230", quality="unknown_quality")
        _, _, kw = fake.calls[0]
        assert kw["data"]["level"] == "standard"


class TestNeteaseGetLyrics:
    def test_get_lyrics_returns_lrc(self) -> None:
        """get_lyrics 成功返回 LRC 文本。"""
        fake = FakeHttpClient(responses={"song/lyric": _NETEASE_LYRICS_RESPONSE})
        source = NeteaseMusicSource(http_client=fake)
        lyrics = source.get_lyrics("28815230")
        assert isinstance(lyrics, str)
        assert "[00:00]" in lyrics

    def test_get_lyrics_none_returns_none(self) -> None:
        """无歌词（lyric 为 null）返回 None。"""
        fake = FakeHttpClient(responses={"song/lyric": _NETEASE_NO_LYRICS_RESPONSE})
        source = NeteaseMusicSource(http_client=fake)
        assert source.get_lyrics("28815230") is None

    def test_get_lyrics_http_error_returns_none(self) -> None:
        """get_lyrics 异常返回 None。"""
        fake = FakeHttpClient(raise_on_call=ConnectionError("timeout"))
        source = NeteaseMusicSource(http_client=fake)
        assert source.get_lyrics("28815230") is None


class TestNeteaseGetSongDetail:
    def test_get_song_detail_returns_song(self) -> None:
        """get_song_detail 成功返回 Song。"""
        fake = FakeHttpClient(responses={"song/detail": _NETEASE_SONG_DETAIL_RESPONSE})
        source = NeteaseMusicSource(http_client=fake)
        detail = source.get_song_detail("28815230")
        assert detail is not None
        assert isinstance(detail, Song)
        assert detail.id == "28815230"
        assert detail.name == "晴天"
        assert detail.artists == ["周杰伦"]
        assert detail.album == "叶惠美"

    def test_get_song_detail_not_found_returns_none(self) -> None:
        """歌曲不存在返回 None。"""
        fake = FakeHttpClient(responses={"song/detail": _NETEASE_SONG_NOT_FOUND_RESPONSE})
        source = NeteaseMusicSource(http_client=fake)
        assert source.get_song_detail("ghost_id") is None

    def test_get_song_detail_http_error_returns_none(self) -> None:
        """get_song_detail 异常返回 None。"""
        fake = FakeHttpClient(raise_on_call=ConnectionError("timeout"))
        source = NeteaseMusicSource(http_client=fake)
        assert source.get_song_detail("28815230") is None


class TestNeteaseLoginQR:
    def test_login_qr_returns_key_and_url(self) -> None:
        """login_qr 返回 key + qr_url，均非空。"""
        fake = FakeHttpClient(responses={
            "qrcode/unikey": _NETEASE_UNIKEY_RESPONSE,
            "qrcode/client/login": _NETEASE_QR_URL_RESPONSE,
        })
        source = NeteaseMusicSource(http_client=fake)
        result = source.login_qr()
        assert isinstance(result, dict)
        assert result["key"] == "test_unikey_abc123"
        assert result["qr_url"] == "https://music.163.com/qr/test_unikey_abc123"

    def test_login_qr_makes_two_requests(self) -> None:
        """login_qr 发起 unikey + client/login 两次请求。"""
        fake = FakeHttpClient(responses={
            "qrcode/unikey": _NETEASE_UNIKEY_RESPONSE,
            "qrcode/client/login": _NETEASE_QR_URL_RESPONSE,
        })
        source = NeteaseMusicSource(http_client=fake)
        source.login_qr()
        assert len(fake.calls) == 2
        assert "unikey" in fake.calls[0][1]
        assert "client/login" in fake.calls[1][1]

    def test_login_qr_http_error_raises(self) -> None:
        """login_qr 网络异常时抛 RuntimeError（上层转 E_BACKEND_UNAVAILABLE）。"""
        fake = FakeHttpClient(raise_on_call=ConnectionError("timeout"))
        source = NeteaseMusicSource(http_client=fake)
        with pytest.raises(RuntimeError, match="login_qr 失败"):
            source.login_qr()


class TestNeteaseCheckLoginStatus:
    @pytest.mark.parametrize(
        "code,expected",
        [
            (801, "waiting"),
            (802, "scanned"),
            (803, "confirmed"),
            (800, "expired"),
        ],
    )
    def test_check_login_status_code_mapping(self, code: int, expected: str) -> None:
        """check_login_status 按 code 映射状态。"""
        fake = FakeHttpClient(responses={"qrcode/client/login": {"code": code}})
        source = NeteaseMusicSource(http_client=fake)
        assert source.check_login_status("any_key") == expected

    def test_check_login_status_unknown_code_returns_waiting(self) -> None:
        """未知 code 返回 waiting（保持轮询）。"""
        fake = FakeHttpClient(responses={"qrcode/client/login": {"code": 999}})
        source = NeteaseMusicSource(http_client=fake)
        assert source.check_login_status("any_key") == "waiting"

    def test_check_login_status_http_error_returns_waiting(self) -> None:
        """check_login_status 异常返回 waiting（不丢失流程，由 timeout 兜底）。"""
        fake = FakeHttpClient(raise_on_call=ConnectionError("timeout"))
        source = NeteaseMusicSource(http_client=fake)
        assert source.check_login_status("any_key") == "waiting"


class TestNeteaseCookies:
    def test_get_cookies_on_confirmed_returns_dict(self) -> None:
        """get_cookies_on_confirmed 返回 dict（含传入 cookie）。"""
        source = NeteaseMusicSource(cookies={"MUSIC_U": "token"})
        result = source.get_cookies_on_confirmed()
        assert isinstance(result, dict)
        assert result == {"MUSIC_U": "token"}

    def test_get_cookies_on_confirmed_empty_returns_empty_dict(self) -> None:
        """无 cookie 时返回空 dict（非 None）。"""
        source = NeteaseMusicSource()
        result = source.get_cookies_on_confirmed()
        assert result == {}

    def test_cookies_passed_to_requests(self) -> None:
        """构造时传入的 cookie 透传到 HTTP 请求。"""
        fake = FakeHttpClient(responses={"cloudsearch": _NETEASE_SEARCH_RESPONSE})
        cookies = {"MUSIC_U": "test_token_123"}
        source = NeteaseMusicSource(cookies=cookies, http_client=fake)
        source.search("晴天")
        assert len(fake.calls) == 1
        _, _, kw = fake.calls[0]
        assert kw["cookies"] == cookies


class TestNeteaseHttpxMissing:
    """httpx 缺失时各方法降级行为（CLAUDE.md §三 可缺省）。"""

    def test_search_httpx_missing_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """httpx 缺失时 search 返回 []。"""
        monkeypatch.setitem(sys.modules, "httpx", None)
        source = NeteaseMusicSource(http_client=None)
        assert source.search("晴天") == []

    def test_get_song_url_httpx_missing_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """httpx 缺失时 get_song_url 返回 None。"""
        monkeypatch.setitem(sys.modules, "httpx", None)
        source = NeteaseMusicSource(http_client=None)
        assert source.get_song_url("123") is None

    def test_get_lyrics_httpx_missing_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """httpx 缺失时 get_lyrics 返回 None。"""
        monkeypatch.setitem(sys.modules, "httpx", None)
        source = NeteaseMusicSource(http_client=None)
        assert source.get_lyrics("123") is None

    def test_get_song_detail_httpx_missing_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """httpx 缺失时 get_song_detail 返回 None。"""
        monkeypatch.setitem(sys.modules, "httpx", None)
        source = NeteaseMusicSource(http_client=None)
        assert source.get_song_detail("123") is None

    def test_login_qr_httpx_missing_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """httpx 缺失时 login_qr 抛 RuntimeError（上层捕获转 E_BACKEND_UNAVAILABLE）。"""
        monkeypatch.setitem(sys.modules, "httpx", None)
        source = NeteaseMusicSource(http_client=None)
        with pytest.raises(RuntimeError, match="httpx 未安装"):
            source.login_qr()

    def test_check_login_status_httpx_missing_returns_waiting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """httpx 缺失时 check_login_status 返回 waiting。"""
        monkeypatch.setitem(sys.modules, "httpx", None)
        source = NeteaseMusicSource(http_client=None)
        assert source.check_login_status("key") == "waiting"


class TestNeteaseSourceAttribute:
    def test_source_is_netease(self) -> None:
        """source 字段为 MusicSourceEnum.NETEASE。"""
        source = NeteaseMusicSource()
        assert source.source is MusicSourceEnum.NETEASE

    def test_search_song_source_is_netease(self) -> None:
        """search 返回的 Song.source 为 NETEASE。"""
        fake = FakeHttpClient(responses={"cloudsearch": _NETEASE_SEARCH_RESPONSE})
        source = NeteaseMusicSource(http_client=fake)
        results = source.search("晴天")
        assert len(results) > 0
        for song in results:
            assert song.source is MusicSourceEnum.NETEASE


class TestNeteaseCallCounts:
    def test_search_call_count_increments(self) -> None:
        """search 调用计数正确递增。"""
        fake = FakeHttpClient(responses={"cloudsearch": _NETEASE_SEARCH_RESPONSE})
        source = NeteaseMusicSource(http_client=fake)
        assert source.call_counts["search"] == 0
        source.search("晴天")
        source.search("稻香")
        assert source.call_counts["search"] == 2

    def test_get_song_url_call_count_increments(self) -> None:
        """get_song_url 调用计数正确递增。"""
        fake = FakeHttpClient(responses={"player/url/v1": _NETEASE_SONG_URL_RESPONSE})
        source = NeteaseMusicSource(http_client=fake)
        source.get_song_url("123")
        source.get_song_url("456")
        source.get_song_url("789")
        assert source.call_counts["get_song_url"] == 3

    def test_login_qr_call_count_increments(self) -> None:
        """login_qr 调用计数正确递增。"""
        fake = FakeHttpClient(responses={
            "qrcode/unikey": _NETEASE_UNIKEY_RESPONSE,
            "qrcode/client/login": _NETEASE_QR_URL_RESPONSE,
        })
        source = NeteaseMusicSource(http_client=fake)
        source.login_qr()
        source.login_qr()
        assert source.call_counts["login_qr"] == 2

    def test_check_login_status_call_count_increments(self) -> None:
        """check_login_status 调用计数正确递增。"""
        fake = FakeHttpClient(responses={"qrcode/client/login": {"code": 801}})
        source = NeteaseMusicSource(http_client=fake)
        source.check_login_status("k1")
        source.check_login_status("k2")
        source.check_login_status("k3")
        source.check_login_status("k4")
        assert source.call_counts["check_login_status"] == 4
