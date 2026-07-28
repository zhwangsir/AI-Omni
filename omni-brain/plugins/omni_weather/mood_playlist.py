"""情绪 → 歌单标签推荐（纯函数）。

根据 ``weather_mood.Mood.music_tags`` 推荐歌单标签。
**不直接 import omni_music**（项目隔离纪律 AGENTS.md §四.3）；
通过事件总线 ``publish("weather.mood_changed", {mood, music_tags, ...})`` 通知 omni_music 订阅。
"""

from __future__ import annotations

__all__ = ["MOOD_TO_TAGS", "DEFAULT_TAGS", "recommend_playlist_tags"]


# 默认标签（未知 mood / 兜底）
DEFAULT_TAGS: list[str] = ["chill", "ambient"]

# mood → 推荐歌单标签（与 weather_mood.Mood.music_tags 一致，但独立维护便于扩展）
MOOD_TO_TAGS: dict[str, list[str]] = {
    "sunny": ["pop", "upbeat", "sunny", "indie"],
    "calm": ["chill", "calm", "acoustic", "lofi"],
    "melancholy": ["melancholy", "sad", "mellow", "rainy", "piano"],
    "dreamy": ["dreamy", "ambient", "snow", "ethereal"],
    "mysterious": ["ambient", "mysterious", "fog", "dark"],
    "dramatic": ["dramatic", "intense", "epic", "storm", "orchestral"],
}


def recommend_playlist_tags(mood: str) -> list[str]:
    """按情绪推荐歌单标签。

    :param mood: 情绪名（如 ``sunny`` / ``melancholy``）
    :return: 标签字符串列表；未知 mood 返回 :data:`DEFAULT_TAGS`
    """
    tags = MOOD_TO_TAGS.get(mood)
    if not tags:
        return list(DEFAULT_TAGS)
    return list(tags)
