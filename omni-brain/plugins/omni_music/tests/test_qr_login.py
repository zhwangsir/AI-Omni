"""omni_music QRLoginFlow + FakeQRLoginFlow 测试（M17.4）。

覆盖：
- FakeQRLoginFlow 状态机：start → poll（waiting→scanned→confirmed）
- confirmed 时保存 cookie 到 CookieStore
- expired / timeout 不保存 cookie
- 防死循环：默认超时 180s
- start 返回 {key, qr_url}
- 真实 QRLoginFlow 协调 MusicSource + CookieStore
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from omni_music.auth.cookie_store import FakeCookieStore
from omni_music.auth.qr_login import FakeQRLoginFlow, QRLoginFlow
from omni_music.models import MusicSourceEnum
from omni_music.sources.base import FakeMusicSource


class TestFakeQRLoginFlow:
    def test_start_returns_key_and_qr_url(self) -> None:
        """start 返回 dict 含 key 与 qr_url。"""
        flow = FakeQRLoginFlow(source=FakeMusicSource(), store=FakeCookieStore())
        result = flow.start()
        assert "key" in result and result["key"]
        assert "qr_url" in result and result["qr_url"]

    def test_poll_returns_status_str(self) -> None:
        """poll 返回状态字符串（waiting/scanned/confirmed/expired）。"""
        flow = FakeQRLoginFlow(source=FakeMusicSource(), store=FakeCookieStore())
        flow.start()
        status = flow.poll()
        assert status in ("waiting", "scanned", "confirmed", "expired")

    def test_poll_transitions_to_confirmed(self) -> None:
        """FakeQRLoginFlow 经多次 poll 到达 confirmed。"""
        flow = FakeQRLoginFlow(source=FakeMusicSource(), store=FakeCookieStore())
        flow.start()
        # waiting → scanned → confirmed
        statuses = [flow.poll() for _ in range(3)]
        assert statuses[0] == "waiting"
        assert statuses[1] == "scanned"
        assert statuses[2] == "confirmed"

    def test_confirmed_saves_cookies(self) -> None:
        """confirmed 时把 cookie 写入 CookieStore。"""
        store = FakeCookieStore()
        source = FakeMusicSource()
        # 预置 fake source 在 confirmed 时返回的 cookie
        source.fake_cookies_on_confirmed = {"MUSIC_U": "token_abc"}
        flow = FakeQRLoginFlow(source=source, store=store)
        flow.start()
        for _ in range(3):
            flow.poll()
        # confirmed 后 cookie 应已保存
        loaded = store.load("netease")
        assert loaded is not None
        assert loaded.get("MUSIC_U") == "token_abc"

    def test_expired_does_not_save(self) -> None:
        """expired 时不保存 cookie。"""
        store = FakeCookieStore()
        source = FakeMusicSource()
        source.fake_login_status_sequence = ["waiting", "expired"]
        flow = FakeQRLoginFlow(source=source, store=store)
        flow.start()
        flow.poll()
        status = flow.poll()
        assert status == "expired"
        assert store.load("netease") is None

    def test_poll_after_confirmed_idempotent(self) -> None:
        """confirmed 后再 poll 保持 confirmed（不重复保存）。"""
        store = FakeCookieStore()
        source = FakeMusicSource()
        source.fake_cookies_on_confirmed = {"k": "v"}
        flow = FakeQRLoginFlow(source=source, store=store)
        flow.start()
        for _ in range(3):
            flow.poll()
        save_count_before = source.fake_cookies_save_count
        flow.poll()
        flow.poll()
        # save_count 不应继续增长
        assert source.fake_cookies_save_count == save_count_before


class TestQRLoginFlowRunUntilDone:
    def test_run_until_confirmed(self) -> None:
        """run_until_done 自动轮询到 confirmed，返回最终状态。"""
        store = FakeCookieStore()
        source = FakeMusicSource()
        source.fake_cookies_on_confirmed = {"MUSIC_U": "tok"}
        flow = FakeQRLoginFlow(source=source, store=store, poll_interval_s=0)
        result = flow.run_until_done()
        assert result["status"] == "confirmed"
        assert store.load("netease") == {"MUSIC_U": "tok"}

    def test_run_until_expired(self) -> None:
        """run_until_done 收到 expired 时停止并返回 expired。"""
        store = FakeCookieStore()
        source = FakeMusicSource()
        source.fake_login_status_sequence = ["waiting", "scanned", "expired"]
        flow = FakeQRLoginFlow(source=source, store=store, poll_interval_s=0)
        result = flow.run_until_done()
        assert result["status"] == "expired"
        assert store.load("netease") is None

    def test_run_until_timeout(self) -> None:
        """超时时返回 timeout，不保存 cookie。"""
        store = FakeCookieStore()
        source = FakeMusicSource()
        # 永远返回 waiting 的 source
        source.fake_login_status_sequence = ["waiting"] * 1000
        flow = FakeQRLoginFlow(
            source=source,
            store=store,
            poll_interval_s=0,
            timeout_s=0.05,  # 50ms 超时
        )
        result = flow.run_until_done()
        assert result["status"] == "timeout"
        assert store.load("netease") is None

    def test_run_until_done_returns_key_and_qr_url(self) -> None:
        """run_until_done 返回结果携带 key 与 qr_url。"""
        flow = FakeQRLoginFlow(
            source=FakeMusicSource(),
            store=FakeCookieStore(),
            poll_interval_s=0,
        )
        result = flow.run_until_done()
        assert "key" in result
        assert "qr_url" in result


class TestQRLoginFlowRealWithFakeSource:
    """真实 QRLoginFlow（非 Fake 子类）+ FakeMusicSource + FakeCookieStore 的协调测试。"""

    def test_real_flow_confirmed_saves_cookie(self) -> None:
        """真实 QRLoginFlow 协调 FakeMusicSource 走完整流程。"""
        store = FakeCookieStore()
        source = FakeMusicSource()
        source.fake_cookies_on_confirmed = {"MUSIC_U": "real_token"}
        flow = QRLoginFlow(source=source, store=store, poll_interval_s=0, timeout_s=5)
        start_result = flow.start()
        assert start_result["key"]
        # 轮询直到 confirmed（FakeMusicSource 内置 waiting→scanned→confirmed）
        statuses: list[str] = []
        for _ in range(5):
            status = flow.poll()
            statuses.append(status)
            if status in ("confirmed", "expired", "timeout"):
                break
        assert "confirmed" in statuses
        assert store.load("netease") == {"MUSIC_U": "real_token"}

    def test_real_flow_uses_source_name_for_store_key(self) -> None:
        """CookieStore 保存时按 source.name 索引（不同源互不干扰）。"""
        # 构造一个 qqmusic fake source
        store = FakeCookieStore()

        class _QQFakeSource(FakeMusicSource):
            source = MusicSourceEnum.QQMUSIC

        source = _QQFakeSource()
        source.fake_cookies_on_confirmed = {"qq_token": "x"}
        flow = QRLoginFlow(source=source, store=store, poll_interval_s=0, timeout_s=5)
        flow.start()
        for _ in range(5):
            if flow.poll() == "confirmed":
                break
        # 应保存到 qqmusic 槽，不是 netease
        assert store.load("qqmusic") == {"qq_token": "x"}
        assert store.load("netease") is None
