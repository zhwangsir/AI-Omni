"""omni_weather 情绪歌单推荐测试。

不直接 import omni_music（项目隔离纪律）；仅验证纯函数
``recommend_playlist_tags(mood)`` 返回合法标签列表。
"""

from __future__ import annotations

import pytest

from omni_weather.mood_playlist import (
    DEFAULT_TAGS,
    MOOD_TO_TAGS,
    recommend_playlist_tags,
)


class TestRecommendPlaylistTags:
    def test_sunny_returns_upbeat_tags(self):
        """sunny → 含欢快标签（如 pop / upbeat）。"""
        tags = recommend_playlist_tags("sunny")
        assert isinstance(tags, list)
        assert len(tags) >= 1
        assert any(t in tags for t in ("pop", "upbeat", "sunny"))

    def test_melancholy_returns_mellow_tags(self):
        """melancholy → 含忧郁标签（如 melancholy / sad / mellow）。"""
        tags = recommend_playlist_tags("melancholy")
        assert any(t in tags for t in ("melancholy", "sad", "mellow", "rainy"))

    def test_dreamy_returns_dreamy_tags(self):
        """dreamy → 含梦幻标签（如 dreamy / ambient）。"""
        tags = recommend_playlist_tags("dreamy")
        assert any(t in tags for t in ("dreamy", "ambient", "snow"))

    def test_mysterious_returns_ambient_tags(self):
        """mysterious → 含神秘/环境标签。"""
        tags = recommend_playlist_tags("mysterious")
        assert any(t in tags for t in ("ambient", "mysterious", "fog"))

    def test_dramatic_returns_intense_tags(self):
        """dramatic → 含戏剧/激烈标签。"""
        tags = recommend_playlist_tags("dramatic")
        assert any(t in tags for t in ("dramatic", "intense", "epic", "storm"))

    def test_calm_returns_chill_tags(self):
        """calm → 含平静标签。"""
        tags = recommend_playlist_tags("calm")
        assert any(t in tags for t in ("chill", "calm", "acoustic"))

    def test_unknown_mood_returns_default(self):
        """未知 mood → 返回 DEFAULT_TAGS（不抛错）。"""
        tags = recommend_playlist_tags("not_a_mood")
        assert tags == DEFAULT_TAGS
        assert len(tags) >= 1

    def test_returns_unique_tags(self):
        """返回的标签无重复。"""
        for mood in MOOD_TO_TAGS:
            tags = recommend_playlist_tags(mood)
            assert len(tags) == len(set(tags)), f"{mood} 有重复标签"

    def test_tags_are_strings(self):
        """每个标签是字符串。"""
        for mood in MOOD_TO_TAGS:
            tags = recommend_playlist_tags(mood)
            for t in tags:
                assert isinstance(t, str)
                assert t
