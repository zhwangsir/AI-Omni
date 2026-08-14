"""omni_wechat 错误响应构造函数测试。"""

from __future__ import annotations

from omni_wechat.errors import error_response, success_response


class TestErrorResponse:
    def test_basic(self) -> None:
        r = error_response("E_TEST", "something failed")
        assert r["ok"] is False
        assert r["error"]["code"] == "E_TEST"
        assert r["error"]["message"] == "something failed"

    def test_extra_fields(self) -> None:
        r = error_response("E_TEST", "fail", status_code=500, ret=-2)
        assert r["error"]["status_code"] == 500
        assert r["error"]["ret"] == -2

    def test_no_extra_fields(self) -> None:
        r = error_response("E_A", "msg")
        assert set(r["error"].keys()) == {"code", "message"}


class TestSuccessResponse:
    def test_empty(self) -> None:
        r = success_response()
        assert r == {"ok": True}

    def test_with_data(self) -> None:
        r = success_response(message_id="abc", to="user@im.wechat")
        assert r["ok"] is True
        assert r["message_id"] == "abc"
        assert r["to"] == "user@im.wechat"

    def test_no_error_key(self) -> None:
        r = success_response(data="value")
        assert "error" not in r
